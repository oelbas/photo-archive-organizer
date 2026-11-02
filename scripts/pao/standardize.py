"""Bring a person's folder into the standard layout, inside the same root:

  <Photos>/YYYY/YYYY-MM/YYYYMMDD_HHMMSS_hash4.ext   dated photos (and RAW)
  <Photos>/YYYY/<Screenshots>/...                   screenshots (optional)
  <Photos>/YYYY/YYYY-MM/YYYYMM_hash6.ext            month known, time not
  <Photos>/YYYY/<Undated>/YYYY_hash6.ext            only the year is known
  <Photos>/<Undated>/undated_hash6.ext              no date at all
  <Videos>/... same pattern
  <Data>/                                           documents and other files
  <Duplicates>/<old relative path>                  byte-identical extra copies

Sidecars (.aae .xmp .thm .moi ...) follow their main file's new name. Names a
person typed are kept. Albums listed in the config are left alone. The run is
idempotent: files already at their target are not touched.
"""
import collections
import datetime
import os
import re

from .common import (OpLog, ext_of, exif_read, is_system, kind_of, managed_dirs, move_file,
                     names, nfc, sha256, stem_of, tree_prune, valid_date, walk)

GENERIC = [
    r"img[_-]?\d+", r"img[_-]\d{8}[_-]wa\d+", r"img[_-]\d{8}[_-]\d{6}(_\d+)?", r"vid[_-]?\d{8}[_-]?\d{6}",
    r"dsc[fn_]?\d+", r"_mg_\d+", r"mvi_\d+", r"p\d{7}", r"pxl_\d{8}_\d+(\..*)?", r"cimg\d+",
    r"\d{8}_\d{6}(_\w+)?", r"\d{4}-\d\d-\d\d \d\d\.\d\d\.\d\d", r"\d+", r"\d+ \d+", r"\d+_\d+_\d+_[no]",
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    r"(fotoğraf|fotograf|görüntü|goruntu|photo|image|picture|resim|bild)[ _-]?\d*(_\d+)?",
    r"(screenshot|ekran resmi|ekran görüntüsü|bildschirmfoto|screen shot).*",
    r"s\d{5,}", r"mov\d+", r"prg\d+", r"\w+( \d+)? \d{3}", r"wp_\d+_\d+",
    r"(img|dsc|photo)\d+_\d+", r"\d{6}_\d+", r"aa\d{6}_\d+", r"[a-z]{2,4}\d{4,}",
    r"(undated|tarihsiz)_[0-9a-f]+", r"\d{4}(\d\d)?_[0-9a-f]{6,}",
]
STANDARD_NAME = re.compile(r"^(\d{8}_\d{6}|\d{8}|\d{6}|\d{4}|undated|tarihsiz)_(?P<hash>[0-9a-f]{4,64})\.[A-Za-z0-9]+$")
COPY_SUFFIX = re.compile(r"( \(\d+\)| copy( \d+)?| kopya(sı)?( \d+)?|-\d)$", re.I)
NAME_DATES = [
    (re.compile(r"(?<!\d)(20\d\d|19\d\d)[-_.]?(\d\d)[-_.]?(\d\d)[ _T-]?(\d\d)[.:_-]?(\d\d)[.:_-]?(\d\d)(?!\d)"), "full"),
    (re.compile(r"(?<!\d)(20\d\d|19\d\d)[-_.]?(\d\d)[-_.]?(\d\d)(?!\d)"), "day"),
]
SCREEN_SIZES = {(640, 960), (640, 1136), (750, 1334), (1242, 2208), (1125, 2436), (828, 1792),
                (1242, 2688), (1170, 2532), (1284, 2778), (1179, 2556), (1290, 2796),
                (1080, 1920), (1080, 2340), (1440, 2960), (1536, 2048), (2048, 2732),
                (1668, 2388), (1620, 2160), (768, 1024), (2880, 1800), (2560, 1600),
                (1440, 900), (1920, 1080), (2560, 1440)}


def is_generic(stem, cfg):
    s = COPY_SUFFIX.sub("", nfc(stem)).strip().lower()
    pats = GENERIC + list(cfg.get("generic_name_patterns") or [])
    return any(re.fullmatch(p, s, re.I) for p in pats)


def date_from_name(stem, cfg):
    for rx, kind in NAME_DATES:
        m = rx.search(stem)
        if not m:
            continue
        g = m.groups()
        if kind == "full":
            d = valid_date("%s:%s:%s %s:%s:%s" % g, cfg)
            if d:
                return d, "full"
        else:
            d = valid_date("%s:%s:%s 00:00:00" % g, cfg)
            if d:
                return d, "day"
    return None, None


def date_from_folders(rel, cfg):
    """Year (and month) a person wrote into folder names: '2011', '2011-03-05 Alps'."""
    parts = rel.split(os.sep)[:-1]
    for part in reversed(parts):
        m = re.match(r"^(19\d\d|20\d\d)(?:[-_. ](\d\d))?", part)
        if m and cfg.get("min_year", 1950) <= int(m.group(1)) <= datetime.date.today().year + 1:
            mo = m.group(2)
            if mo and 1 <= int(mo) <= 12:
                return m.group(1), mo
            return m.group(1), None
    return None, None


def looks_like_screenshot(rel, x):
    stem = stem_of(rel).lower()
    if re.search(r"screenshot|screen shot|ekran resmi|ekran görüntüsü|bildschirmfoto", stem):
        return True
    if ext_of(rel) == ".png" and not x.get("Model"):
        w, h = x.get("ImageWidth"), x.get("ImageHeight")
        if w and h and (min(w, h), max(w, h)) in SCREEN_SIZES:
            return True
    return False


def keeper_rank(rel, cfg):
    n = names(cfg)
    low = rel.lower()
    return (
        0 if (low.startswith(n["photos"].lower() + os.sep) or low.startswith(n["videos"].lower() + os.sep)) else 1,
        1 if COPY_SUFFIX.search(stem_of(rel)) else 0,
        1 if re.search(r"icloud|whatsapp|kopya|copy|backup|yedek", low) else 0,
        len(rel), rel,
    )


MONTH_DIR = re.compile(r"^(\d{4})-(\d\d)$")


def respect_existing_folder(rel, target_dir, top, n):
    """Keep a classification made earlier (by a person or another tool) when the
    file already sits in the right year: screenshot vs. month folder, or an
    undated/screenshot folder when only the year is known. Wrong years or wrong
    months are still corrected, and a newly known month wins over 'undated'."""
    cur = rel.split(os.sep)[:-1]
    tgt = target_dir.split(os.sep)
    if len(cur) != 3 or len(tgt) != 3 or cur[0] != top or tgt[0] != top or cur[1] != tgt[1]:
        return target_dir
    csub, tsub = cur[2], tgt[2]
    if csub == tsub:
        return target_dir
    cm, tm = MONTH_DIR.match(csub), MONTH_DIR.match(tsub)
    if cm and tm:
        return target_dir                      # wrong month: fix it
    if csub == n["undated"] and tm:
        return target_dir                      # month now known: move in
    if (cm and cm.group(1) == cur[1]) or csub in (n["screenshots"], n["undated"]):
        return os.sep.join(cur)                # earlier classification stands
    return target_dir


def same_moment_name(rel, base, precision):
    """If the file already carries a <date>_<time>_<hash> name that differs from
    the computed one only by whole hours (time-zone handling), keep it."""
    if precision != "full":
        return None
    m = re.match(r"^(\d{8})_(\d{6})_[0-9a-f]{4,64}\.[A-Za-z0-9]+$", os.path.basename(rel))
    b = re.match(r"^(\d{8})_(\d{6})$", base)
    if not m or not b or m.group(1) + m.group(2) == b.group(1) + b.group(2):
        return None
    try:
        t1 = datetime.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        t2 = datetime.datetime.strptime(b.group(1) + b.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    diff = abs((t1 - t2).total_seconds())
    off = diff % 1800
    if diff <= 14 * 3600 + 2 and (off <= 2 or off >= 1798):
        return os.path.basename(rel)
    return None


def plan(root, cfg):
    n = names(cfg)
    albums = set(cfg.get("albums") or [])
    files, skipped = walk(root, skip_top=managed_dirs(cfg) | albums,
                          skip_any={a for a in albums if os.sep not in a})
    system = [(r, s) for r, s, _ in files if is_system(os.path.basename(r), s)]
    files = [(r, s) for r, s, _ in files if not is_system(os.path.basename(r), s)]
    absf = {r: os.path.join(root, r) for r, _ in files}
    meta = exif_read([absf[r] for r, _ in files
                      if kind_of(r) in ("photo", "raw", "video", "sidecar")],
                     quicktime_utc=cfg.get("quicktime_utc", False))
    sizes = collections.Counter(s for _, s in files)
    size_of = dict(files)
    trust = cfg.get("trust_existing_names", True)

    class LazySha(dict):
        """Hash on demand. A file already named <date>_<hash> under the
        standard folders is trusted when trust_existing_names is on, so an
        organized archive is not re-read in full."""

        def __missing__(self, r):
            m = STANDARD_NAME.match(os.path.basename(r))
            top = r.split(os.sep)[0]
            if trust and m and top in (n["photos"], n["videos"]) and sizes[size_of[r]] == 1:
                h = m.group("hash").lower()
                val = h + "?" * (64 - len(h))
            else:
                val = sha256(absf[r])
            self[r] = val
            return val

    sha = LazySha()

    def real(r):
        if "?" in sha[r]:
            sha[r] = sha256(absf[r])
        return sha[r]

    # 1. exact duplicates -> Duplicates/<old path>
    groups = collections.defaultdict(list)
    for r, _ in files:
        if sizes[size_of[r]] == 1 and kind_of(r) != "sidecar":
            continue  # a unique size cannot have an exact duplicate
        key = (sha[r],) if kind_of(r) != "sidecar" else (sha[r], os.path.basename(r).lower())
        groups[key].append(r)
    dup_of = {}
    for v in groups.values():
        v.sort(key=lambda r: keeper_rank(r, cfg))
        for r in v[1:]:
            dup_of[r] = v[0]

    used = set()      # (dir_lower, name_lower) already claimed

    def claim(d, name):
        key = (d.lower(), name.lower())
        if key in used:
            return False
        used.add(key)
        return True

    def hashed(base, r, d, n0):
        known = sha[r].rstrip("?")
        if len(known) < 64:  # trusted name: keep its hash length, it may have been bumped before
            nm = "%s_%s%s" % (base, known, ext_of(r))
            if claim(d, nm):
                return nm
            sha[r] = sha256(absf[r])  # clash: fall back to the real hash
        for k in (n0, n0 + 2, 8, 12, 64):
            nm = "%s_%s%s" % (base, sha[r][:k], ext_of(r))
            if claim(d, nm):
                return nm
        raise RuntimeError("cannot name " + r)

    targets, reasons = {}, {}
    main_files = [r for r, _ in files if r not in dup_of and kind_of(r) != "sidecar"]
    hl, hu = int(cfg.get("hash_len", 4)), int(cfg.get("hash_len_undated", 6))

    for r in sorted(main_files, key=lambda r: (os.path.dirname(r) != "", r)):
        k = kind_of(r)
        x = meta.get(absf[r], {})
        top = n["videos"] if k == "video" else n["photos"]
        if k in ("photo", "raw", "video"):
            if k == "video":
                # CreationDate / ContentCreateDate hold the capture moment in local time;
                # CreateDate is often the export/re-encode time for edited videos
                d = (valid_date(x.get("CreationDate"), cfg) or valid_date(x.get("ContentCreateDate"), cfg)
                     or valid_date(x.get("DateTimeOriginal"), cfg)
                     or valid_date(x.get("CreateDate"), cfg) or valid_date(x.get("MediaCreateDate"), cfg))
                if not d and ext_of(r) == ".mod":
                    moi = os.path.splitext(absf[r])[0]
                    for e in (".MOI", ".moi"):
                        if os.path.exists(moi + e):
                            d = valid_date(exif_read([moi + e]).get(moi + e, {}).get("DateTimeOriginal"), cfg)
            else:
                d = valid_date(x.get("DateTimeOriginal"), cfg) or (
                    valid_date(x.get("CreateDate"), cfg) if k == "raw" else None)
            src = "metadata"
            precision = "full" if d else None
            if not d:
                d, precision = date_from_name(stem_of(r), cfg)
                src = "file name"
            year = month = None
            if d:
                year, month = d[:4], d[5:7]
            else:
                year, month = date_from_folders(r, cfg)
                src, precision = "folder name", ("month" if month else ("year" if year else None))
            keep_name = cfg.get("keep_descriptive_names", True) and not is_generic(stem_of(r), cfg)
            shot = cfg.get("separate_screenshots", True) and k == "photo" and looks_like_screenshot(r, x)
            if precision == "full":
                dd = os.path.join(top, year, n["screenshots"] if shot else "%s-%s" % (year, month))
                base = d[:10].replace(":", "") + "_" + d[11:19].replace(":", "")
                note = "date from " + src
            elif precision == "day":
                dd = os.path.join(top, year, "%s-%s" % (year, month))
                base = d[:10].replace(":", "")
                note = "day from file name"
            elif precision == "month":
                dd = os.path.join(top, year, "%s-%s" % (year, month))
                base = year + month
                note = "month estimated from folder name"
            elif precision == "year":
                dd = os.path.join(top, year, n["undated"])
                base = year
                note = "year estimated from folder name"
            else:
                dd = os.path.join(top, n["undated"])
                base = n["undated_prefix"]
                note = "no date"
            dd = respect_existing_folder(r, dd, top, n)
            tz_name = same_moment_name(r, base, precision)
            if tz_name and claim(dd, tz_name):
                nm = tz_name
                note += "; existing name kept (same moment, other time zone)"
            elif keep_name:
                nm = os.path.basename(r)
                if not claim(dd, nm):
                    nm = "%s_%s%s" % (stem_of(r), real(r)[:hl], os.path.splitext(r)[1])
                    claim(dd, nm)
                note += "; typed name kept"
            else:
                nm = hashed(base, r, dd, hl if precision == "full" else hu)
            targets[r] = os.path.join(dd, nm)
            reasons[r] = note
        else:
            dd = n["data"]
            nm = os.path.basename(r)
            if not claim(dd, nm):
                nm = "%s_%s%s" % (stem_of(r), real(r)[:hl], os.path.splitext(r)[1])
                claim(dd, nm)
            targets[r] = os.path.join(dd, nm)
            reasons[r] = "document/other, name kept"

    # sidecars follow their partner (same folder, same stem)
    by_stem = collections.defaultdict(list)
    for r in main_files:
        by_stem[(os.path.dirname(r), stem_of(r).lower())].append(r)
    orphans = []
    for r, _ in files:
        if r in dup_of or kind_of(r) != "sidecar":
            continue
        partners = by_stem.get((os.path.dirname(r), stem_of(r).lower()), [])
        if partners:
            p = sorted(partners, key=lambda q: kind_of(q) != "photo")[0]
            t = os.path.splitext(targets[p])[0] + os.path.splitext(r)[1].lower()
            if not claim(os.path.dirname(t), os.path.basename(t)):
                t = os.path.splitext(targets[p])[0] + "_" + real(r)[:hl] + ext_of(r)
                claim(os.path.dirname(t), os.path.basename(t))
            targets[r] = t
            reasons[r] = "sidecar of " + os.path.basename(targets[p])
        else:
            dd = os.path.join(n["photos"], n["undated"])
            folder_mods = [targets[q] for q in main_files if os.path.dirname(q) == os.path.dirname(r)
                           and kind_of(q) == "video"]
            if folder_mods and ext_of(r) in (".pgi", ".moi", ".thm"):
                dd = os.path.dirname(folder_mods[0])
            nm = os.path.basename(r)
            if not claim(dd, nm):
                nm = "%s_%s%s" % (stem_of(r), real(r)[:hl], ext_of(r))
                claim(dd, nm)
            targets[r] = os.path.join(dd, nm)
            reasons[r] = "orphan sidecar (its photo is not here), name kept"
            orphans.append(r)

    for r, keeper in dup_of.items():
        t = os.path.join(n["duplicates"], r)
        targets[r] = t
        reasons[r] = "byte-identical copy of " + keeper

    moves = [(r, t) for r, t in targets.items() if os.path.normcase(r) != os.path.normcase(t) or r != t]
    unchanged = [r for r, t in targets.items() if r == t]
    tcount = collections.Counter(t.lower() for t in targets.values())
    clash = [t for t, c in tcount.items() if c > 1]
    assert not clash, clash[:5]
    summary = collections.Counter()
    for r, t in targets.items():
        parts = t.split(os.sep)
        summary["/".join(parts[:2]) if parts[0] in (n["photos"], n["videos"]) else parts[0]] += 1
    return {
        "root": os.path.abspath(root),
        "counts": {"files": len(files), "moves": len(moves), "unchanged": len(unchanged),
                   "duplicates": len(dup_of), "orphan_sidecars": len(orphans),
                   "system_files_left": len(system)},
        "by_destination": dict(sorted(summary.items())),
        "moves": [{"from": r, "to": t, "sha256": sha[r] if "?" not in sha[r] else sha256(absf[r]),
                   "why": reasons[r]} for r, t in sorted(moves)],
        "orphan_sidecars": orphans,
        "skipped": skipped,
    }


def apply(p, cfg):
    root = p["root"]
    log = OpLog(root, cfg, "standardize")
    # two-phase via temporary names so swaps and case-only renames never collide
    staged = []
    for m in p["moves"]:
        src = os.path.join(root, m["from"])
        tmp = src + ".__pao_stage"
        os.rename(src, tmp)
        staged.append((tmp, m))
    for tmp, m in staged:
        dst = os.path.join(root, m["to"])
        if os.path.lexists(dst):
            raise FileExistsError(dst)
        move_file(tmp, dst)
        log.add("moved+renamed", m["from"], m["to"], m["sha256"], m["why"])
    path = log.flush()
    removed = tree_prune(root)
    return {"moved": len(staged), "log": path, "empty_folders_removed": len(removed)}
