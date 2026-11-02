"""Describe where a folder lives so the right rules apply.

NTFS through a third-party driver, exFAT/FAT, APFS/HFS+ and network shares
behave differently (case handling, walking, trash, speed). The report also
flags iCloud placeholders and Photos libraries before anything is touched.
"""
import os
import re
import shutil
import subprocess
import sys

from .common import PROTECTED_SUFFIXES, SF_DATALESS, have, walk

QUIRKS = {
    "ntfs": [
        "case-only renames need a temporary name (use case-rename)",
        "walk with listdir+lstat; os.walk/find can misreport folders",
        "Finder 'empty trash' may fail with 'in use'; the volume's .Trashes can be emptied only on user request",
        "usually a spinning disk: expect ~80-120 MB/s when hashing",
    ],
    "exfat": [
        "case-only renames need a temporary name",
        "no permissions/ownership; timestamps have 2-second resolution on FAT",
    ],
    "apfs": ["case-insensitive by default: case-only renames still go through a temporary name"],
    "hfs": ["case-insensitive by default"],
    "network": ["slow and may disconnect: copy+verify, never rely on rename across shares",
                "files on the share do not count as originals unless the share is mounted"],
}


def mount_info(path):
    path = os.path.realpath(path)
    best = ("/", "unknown", "")
    try:
        out = subprocess.run(["mount"], capture_output=True, text=True).stdout
    except OSError:
        out = ""
    for line in out.splitlines():
        m = re.match(r"^(.*?) on (.*?) \(([^,)]+)(.*)\)$", line)
        if not m:
            continue
        dev, mp, fstype, rest = m.groups()
        if (path == mp or path.startswith(mp.rstrip("/") + "/")) and len(mp) >= len(best[0]):
            best = (mp, fstype, dev + " " + rest)
    return best


def family(fstype):
    f = fstype.lower()
    if "ntfs" in f:
        return "ntfs"
    if "exfat" in f or "msdos" in f or "fat" in f:
        return "exfat"
    if "apfs" in f:
        return "apfs"
    if "hfs" in f:
        return "hfs"
    if f in ("smbfs", "afpfs", "nfs", "webdav"):
        return "network"
    return f or "unknown"


def describe(path, scan=False):
    mp, fstype, extra = mount_info(path)
    fam = family(fstype)
    du = shutil.disk_usage(path)
    home = os.path.expanduser("~")
    real = os.path.realpath(path)
    info = {
        "path": real,
        "mount_point": mp,
        "filesystem": fstype,
        "family": fam,
        "location": "external" if mp.startswith("/Volumes/") else "local",
        "free_bytes": du.free,
        "total_bytes": du.total,
        "quirks": QUIRKS.get(fam, []),
        "warnings": [],
    }
    if info["location"] == "local":
        if real.startswith(os.path.join(home, "Library")):
            info["warnings"].append("inside ~/Library: application data, do not reorganize")
        for sub in ("Desktop", "Documents"):
            if real.startswith(os.path.join(home, sub)):
                info["warnings"].append(
                    "%s may be synced by iCloud Drive: placeholder files are not on disk" % sub)
        if "Mobile Documents" in real:
            info["warnings"].append("iCloud Drive folder: files may be cloud-only placeholders")
    if sys.platform == "darwin" and not have("osascript"):
        info["warnings"].append("osascript missing: Finder trash unavailable")
    if scan:
        files, skipped = walk(path)
        dataless = [r for r, _, fl in files if fl & SF_DATALESS]
        info["file_count"] = len(files)
        info["total_size"] = sum(s for _, s, _ in files)
        info["icloud_placeholders"] = len(dataless)
        info["icloud_placeholder_examples"] = dataless[:10]
        info["protected"] = [r for r, why in skipped if "protected" in why]
        if dataless:
            info["warnings"].append(
                "%d files are iCloud placeholders: reading them downloads them; "
                "they are not originals on this disk until downloaded" % len(dataless))
        if info["protected"]:
            info["warnings"].append("photo library packages found and skipped: %s"
                                    % ", ".join(info["protected"][:5]))
    return info


def free_space_ok(dest, need_bytes, margin=1.1):
    return shutil.disk_usage(dest).free >= need_bytes * margin
