"""Shared helpers: config, folder names, safe directory walking, hashing,
metadata reading, the operations log, moving and trashing.

Everything here is standard-library Python 3.8+ so the skill runs on a stock
macOS install. exiftool is the only hard external dependency.
"""
import csv
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata

# ---------------------------------------------------------------- config

DEFAULT_CONFIG = {
    # "en" or "tr": picks the default folder names below.
    "language": "en",
    # Per-key overrides of the folder names, e.g. {"photos": "Pictures"}.
    "folder_names": {},
    # Hash characters appended to dated names; undated names use the longer one.
    "hash_len": 4,
    "hash_len_undated": 6,
    # Keep names a person typed ("Diploma.jpg") instead of renaming them.
    "keep_descriptive_names": True,
    # Extra regexes (case-insensitive, full match on the stem) treated as
    # camera/generic names that may be renamed.
    "generic_name_patterns": [],
    # Earliest plausible capture year; anything outside [min_year, now+1] is a
    # broken camera clock (0000, 2097 ...) and is ignored.
    "min_year": 1950,
    # Vision feature-print distance: <= similar_threshold counts as the same
    # picture, up to review_threshold is listed for the user but never moved.
    "similar_threshold": 0.15,
    "review_threshold": 0.25,
    # Vision matches on images whose longest side is below this are only
    # listed for review: feature prints are unreliable on thumbnails.
    "vision_min_side": 500,
    # RAW files whose JPEG twin exists: "keep" or "similar" (offer for trash).
    "raw_policy": "keep",
    # Treat QuickTime CreateDate as UTC and convert to local time. Off by
    # default: many cameras store local time there.
    "quicktime_utc": False,
    # Files already named <date>_<hash> by this tool are trusted instead of
    # re-reading them completely (much faster on large, already organized
    # folders). Exact-duplicate detection still hashes same-size files.
    "trust_existing_names": True,
    # Put screenshots in <year>/<screenshots>/ instead of month folders.
    "separate_screenshots": True,
    # Folder names (relative to the processed root, or bare names) that are
    # albums and must stay as they are.
    "albums": [],
    # Camera model -> owner, used only for reports, e.g. {"iPhone 11": "Anna"}.
    "device_owners": {},
    # Named roots so the user can say "Anna on the backup disk".
    "roots": {},
}

FOLDER_NAMES = {
    "en": {
        "photos": "Photos", "videos": "Videos", "undated": "Undated",
        "screenshots": "Screenshots", "data": "Data", "logs": "Logs",
        "duplicates": "Duplicates", "similar": "Similar", "corrupt": "Corrupt",
        "recovered": "Recovered", "missing": "Missing",
        "undated_prefix": "undated",
    },
    "tr": {
        "photos": "Foto", "videos": "Video", "undated": "Tarihsiz",
        "screenshots": "Ekran Goruntuleri", "data": "Data", "logs": "Kayitlar",
        "duplicates": "Cop", "similar": "Benzerler", "corrupt": "Bozuk",
        "recovered": "Kurtarilan", "missing": "Olmayanlar",
        "undated_prefix": "tarihsiz",
    },
}

CONFIG_LOCATIONS = [
    os.environ.get("PAO_CONFIG", ""),
    os.path.expanduser("~/.config/photo-archive-organizer/config.json"),
]


def load_config(path=None):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    for p in ([path] if path else []) + CONFIG_LOCATIONS:
        if p and os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                user = json.load(f)
            for k, v in user.items():
                if k.startswith("_"):
                    continue
                cfg[k] = v
            cfg["_source"] = p
            break
    return cfg


def names(cfg):
    n = dict(FOLDER_NAMES.get(cfg.get("language", "en"), FOLDER_NAMES["en"]))
    n.update(cfg.get("folder_names") or {})
    return n


def managed_dirs(cfg):
    """Top-level folders the tool writes into and must never re-process."""
    n = names(cfg)
    return {n[k] for k in ("logs", "duplicates", "similar", "corrupt", "recovered", "data")}


# ---------------------------------------------------------------- files

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".tif", ".tiff",
             ".bmp", ".webp"}
RAW_EXT = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf",
           ".pef", ".srw"}
VIDEO_EXT = {".mov", ".mp4", ".m4v", ".3gp", ".avi", ".mpg", ".mpeg", ".mod",
             ".mts", ".m2ts", ".wmv", ".mkv", ".vob", ".tod"}
SIDECAR_EXT = {".aae", ".xmp", ".thm", ".moi", ".pgi", ".lrv"}
SYSTEM_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", ".localized", "Icon\r",
                "ehthumbs.db"}
PROTECTED_SUFFIXES = (".photoslibrary", ".aplibrary", ".migratedphotolibrary",
                      ".photolibrary")

SF_DATALESS = 0x40000000  # macOS: file content lives only in iCloud


def nfc(s):
    return unicodedata.normalize("NFC", s)


def ext_of(p):
    return os.path.splitext(p)[1].lower()


def stem_of(p):
    return os.path.splitext(os.path.basename(p))[0]


def kind_of(p):
    e = ext_of(p)
    if e in PHOTO_EXT:
        return "photo"
    if e in RAW_EXT:
        return "raw"
    if e in VIDEO_EXT:
        return "video"
    if e in SIDECAR_EXT:
        return "sidecar"
    return "other"


def is_system(name, size=None):
    return name in SYSTEM_NAMES or name.startswith("._") or size == 0


def walk(root, skip_top=(), skip_any=()):
    """Return [(relpath, size, flags)] for every regular file under root.

    os.walk/find misreport directories on NTFS volumes mounted through
    third-party drivers, so this walks with listdir + lstat only. Photo library
    packages are never entered: their insides belong to Photos.app.
    Symlinks are reported as skipped instead of followed.
    """
    out, skipped = [], []
    stack = [""]
    skip_top = {nfc(x) for x in skip_top}
    skip_any = {nfc(x) for x in skip_any}
    while stack:
        rel = stack.pop()
        full = os.path.join(root, rel) if rel else root
        try:
            entries = os.listdir(full)
        except OSError as e:
            skipped.append((rel, "unreadable: %s" % e))
            continue
        for name in entries:
            r = os.path.join(rel, name) if rel else name
            p = os.path.join(root, r)
            try:
                st = os.lstat(p)
            except OSError as e:
                skipped.append((r, "unreadable: %s" % e))
                continue
            if os.path.islink(p):
                skipped.append((r, "symlink"))
            elif os.path.isdir(p):
                if name.lower().endswith(PROTECTED_SUFFIXES):
                    skipped.append((r, "photo library package (protected)"))
                elif (not rel and nfc(name) in skip_top) or nfc(name) in skip_any \
                        or nfc(r) in skip_any:
                    continue
                else:
                    stack.append(r)
            else:
                out.append((r, st.st_size, getattr(st, "st_flags", 0)))
    out.sort()
    return out, skipped


def sha256(path, chunk=8 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def quick_key(path, size):
    """Head+tail fingerprint: cheap filter before reading a whole file."""
    with open(path, "rb") as f:
        head = f.read(65536)
        tail = b""
        if size > 131072:
            f.seek(-65536, 2)
            tail = f.read()
    return hashlib.sha1(head + tail).hexdigest()


def jpeg_scan_hash(path):
    """Hash of the compressed image data (from the last SOS marker).

    Two JPEGs with equal scan hashes show the same pixels even when their
    metadata (orientation tag, EXIF edits) differs.
    """
    try:
        with open(path, "rb") as f:
            b = f.read()
    except OSError:
        return None
    i = b.rfind(b"\xff\xda")
    return hashlib.sha256(b[i:]).hexdigest() if i > 0 else None


def tree_prune(root, keep_root=True):
    """Remove empty directories (a lone .DS_Store counts as empty)."""
    removed = []

    def rec(p):
        try:
            entries = os.listdir(p)
        except OSError:
            return False
        has = False
        for e in entries:
            q = os.path.join(p, e)
            if os.path.isdir(q) and not os.path.islink(q):
                if rec(q):
                    has = True
            elif e != ".DS_Store":
                has = True
        if not has and not (keep_root and p == root):
            for e in os.listdir(p):
                os.remove(os.path.join(p, e))
            os.rmdir(p)
            removed.append(os.path.relpath(p, root))
        return has

    if os.path.isdir(root):
        rec(root)
    return removed


# ---------------------------------------------------------------- metadata

DATE_TAGS = ["DateTimeOriginal", "SubSecTimeOriginal", "CreateDate", "CreationDate", "ContentCreateDate",
             "MediaCreateDate", "Model", "Make", "SerialNumber", "FileNumber",
             "ImageWidth", "ImageHeight", "Orientation", "Duration", "MIMEType",
             "Software"]


def have(cmd):
    return shutil.which(cmd) is not None


def exif_read(paths, tags=DATE_TAGS, quicktime_utc=False):
    """Read tags for many files with one exiftool process. Returns {path: dict}.

    quicktime_utc=False keeps QuickTime CreateDate as written. The spec says
    UTC, but many cameras write local time; Apple files carry CreationDate with
    a zone, which is preferred anyway.
    """
    if not paths:
        return {}
    if not have("exiftool"):
        raise SystemExit("exiftool not found. Install it from https://exiftool.org "
                         "(macOS .pkg) and run again.")
    res = {}
    for i in range(0, len(paths), 2000):
        batch = paths[i:i + 2000]
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt",
                                         encoding="utf-8") as lf:
            lf.write("\n".join(batch))
            listfile = lf.name
        try:
            cmd = ["exiftool", "-q", "-q", "-j", "-n", "-api",
                   "QuickTimeUTC=%d" % (1 if quicktime_utc else 0),
                   "-charset", "filename=utf8", "-@", listfile]
            cmd += ["-" + t for t in tags]
            raw = subprocess.run(cmd, capture_output=True).stdout
        finally:
            os.unlink(listfile)
        text = raw.decode("utf-8", "replace").replace("\x00", "")
        try:
            data = json.loads(text) if text.strip() else []
        except ValueError:
            data = []
        for x in data:
            res[nfc(x.get("SourceFile", ""))] = x
    return {p: res.get(nfc(p), {}) for p in paths}


_DATE_RE = re.compile(r"^(\d{4}):(\d\d):(\d\d)[ T](\d\d):(\d\d):(\d\d)")


def valid_date(value, cfg):
    """Return 'YYYY:MM:DD HH:MM:SS' or None for missing/absurd dates."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh, mi, ss = int(m.group(4)), int(m.group(5)), int(m.group(6))
    if not (cfg.get("min_year", 1950) <= y <= datetime.date.today().year + 1):
        return None
    if not (1 <= mo <= 12 and 1 <= d <= 31 and hh < 24 and mi < 60 and ss < 61):
        return None
    return "%04d:%02d:%02d %02d:%02d:%02d" % (y, mo, d, hh, mi, ss)


# ---------------------------------------------------------------- log

LOG_FIELDS = ["time", "command", "action", "old_path", "new_path", "sha256", "note"]


class OpLog:
    """Append-only CSV inside <root>/<logs>/ so every change can be reversed."""

    def __init__(self, root, cfg, command):
        self.dir = os.path.join(root, names(cfg)["logs"])
        self.path = os.path.join(self.dir, "Operations-Log.csv" if cfg.get("language") != "tr"
                                 else "Islem-Kaydi.csv")
        self.command = command
        self.rows = []

    def add(self, action, old, new, sha="", note=""):
        self.rows.append([datetime.datetime.now().isoformat(timespec="seconds"),
                          self.command, action, old, new, sha, note])

    def flush(self):
        if not self.rows:
            return None
        os.makedirs(self.dir, exist_ok=True)
        new = not os.path.exists(self.path)
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(LOG_FIELDS)
            w.writerows(self.rows)
        self.rows = []
        return self.path


# ---------------------------------------------------------------- moving

def same_device(a, b):
    def dev(p):
        while not os.path.exists(p):
            p = os.path.dirname(p)
        return os.stat(p).st_dev
    return dev(a) == dev(b)


def move_file(src, dst, verify_copy=True):
    """Move within a volume (rename) or copy+verify across volumes.

    Across volumes the source is left in place: removing it is the user's call.
    Returns 'moved' or 'copied'. Never overwrites.
    """
    if os.path.lexists(dst):
        raise FileExistsError(dst)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if same_device(src, os.path.dirname(dst)):
        os.rename(src, dst)
        if not os.path.exists(dst) or os.path.exists(src):
            raise OSError("rename did not complete: %s" % src)
        return "moved"
    shutil.copy2(src, dst)
    if verify_copy and sha256(src) != sha256(dst):
        os.remove(dst)
        raise OSError("copy verification failed: %s" % src)
    return "copied"


def case_rename(path, new_name):
    """Rename even when only letter case changes (NTFS/APFS are case-insensitive)."""
    parent = os.path.dirname(path)
    dst = os.path.join(parent, new_name)
    if os.path.basename(path) == new_name:
        return dst
    if os.path.lexists(dst) and os.path.basename(path).lower() != new_name.lower():
        raise FileExistsError(dst)
    tmp = path + ".__pao_tmp"
    os.rename(path, tmp)
    os.rename(tmp, dst)
    return dst


def trash(paths, timeout=900):
    """Move paths to the Finder Trash (recoverable until the Trash is emptied).

    Batches of 50; on an AppleEvent timeout each item is retried alone with a
    longer timeout. Returns (trashed, failed).
    """
    paths = [p for p in paths if os.path.lexists(p)]
    if sys.platform != "darwin":
        raise SystemExit("trash is implemented for macOS Finder only; "
                         "move the listed files to the trash by hand.")
    done, failed = [], []

    def run(batch, t):
        items = ", ".join('POSIX file "%s" as alias' % p.replace("\\", "\\\\").replace('"', '\\"')
                          for p in batch)
        r = subprocess.run(["osascript", "-e", "with timeout of %d seconds" % t, "-e",
                            'tell application "Finder" to delete {%s}' % items, "-e",
                            "end timeout"], capture_output=True, text=True)
        return r.returncode == 0, r.stderr.strip()

    for i in range(0, len(paths), 50):
        batch = paths[i:i + 50]
        ok, _ = run(batch, timeout)
        if not ok:
            for p in batch:
                if os.path.lexists(p):
                    ok1, err = run([p], timeout * 2)
                    if not ok1 and os.path.lexists(p):
                        failed.append((p, err))
        done += [p for p in batch if not os.path.lexists(p)]
    return done, failed


def fmt_gb(n):
    return "%.2f GB" % (n / 1e9)


def write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
