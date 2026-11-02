"""Merge one standard-layout folder into another (same relative places).

A file whose identical copy already sits at the destination is not moved: it
is reported as a duplicate so the user can trash it. A different file with the
same name gets a dated suffix instead of overwriting. The source's logs are
moved into the destination's log folder with the source name as prefix.
"""
import datetime
import os

from .common import OpLog, is_system, managed_dirs, move_file, names, sha256, tree_prune, walk


def plan(source, dest, cfg):
    n = names(cfg)
    skip = managed_dirs(cfg) - {n["data"]}
    files, skipped = walk(source, skip_top=skip)
    moves, duplicates, renamed, system = [], [], [], []
    taken = set()
    for r, s, _ in files:
        if is_system(os.path.basename(r), s):
            system.append(r)
            continue
        dst = r
        full_dst = os.path.join(dest, dst)
        if os.path.lexists(full_dst) or dst.lower() in taken:
            if os.path.isfile(full_dst) and os.path.getsize(full_dst) == s and \
                    sha256(full_dst) == sha256(os.path.join(source, r)):
                duplicates.append({"path": r, "same_as": full_dst})
                continue
            day = datetime.date.fromtimestamp(os.path.getmtime(os.path.join(source, r))).isoformat()
            stem, ext = os.path.splitext(r)
            dst = "%s (%s)%s" % (stem, day, ext)
            i = 2
            while os.path.lexists(os.path.join(dest, dst)) or dst.lower() in taken:
                dst = "%s (%s-%d)%s" % (stem, day, i, ext)
                i += 1
            renamed.append({"path": r, "to": dst})
        taken.add(dst.lower())
        moves.append({"from": r, "to": dst})
    logs_dir = os.path.join(source, n["logs"])
    logs = sorted(os.listdir(logs_dir)) if os.path.isdir(logs_dir) else []
    return {"source": os.path.abspath(source), "dest": os.path.abspath(dest),
            "counts": {"files": len(files), "moves": len(moves), "duplicates": len(duplicates),
                       "renamed": len(renamed), "system": len(system)},
            "moves": moves, "duplicates": duplicates, "renamed": renamed,
            "logs": [l for l in logs if l != ".DS_Store"], "skipped": skipped}


def apply(p, cfg):
    n = names(cfg)
    src, dest = p["source"], p["dest"]
    log = OpLog(dest, cfg, "merge")
    done = 0
    how = None
    for m in p["moves"]:
        how = move_file(os.path.join(src, m["from"]), os.path.join(dest, m["to"]))
        log.add(how, os.path.join(os.path.basename(src), m["from"]), m["to"], "",
                "merged from " + src)
        done += 1
    prefix = os.path.basename(src.rstrip(os.sep)) + "-"
    for l in p["logs"]:
        a = os.path.join(src, n["logs"], l)
        b = os.path.join(dest, n["logs"], prefix + l)
        if os.path.exists(a) and not os.path.exists(b):
            move_file(a, b)
    path = log.flush()
    if how != "copied":
        tree_prune(src)
    return {"moved" if how != "copied" else "copied": done, "log": path,
            "duplicates_left_in_source": len(p["duplicates"])}
