#!/usr/bin/env python3
"""photo-archive-organizer command line.

Every command that changes files works in two steps:
  1. it writes a plan (JSON) and prints a summary  -> nothing is touched
  2. `pao.py apply PLAN.json` carries the plan out  -> every change is logged
Trashing always needs --yes and goes to the Finder Trash.

Run `pao.py <command> -h` for the options of each command.
"""
import argparse
import collections
import csv
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pao import common, compare, env, merge, recover, similar, standardize  # noqa: E402

PLAN_DIR = os.path.expanduser("~/.cache/photo-archive-organizer/plans")


def save_plan(kind, data, out=None):
    data["kind"] = kind
    data["created"] = datetime.datetime.now().isoformat(timespec="seconds")
    path = out or os.path.join(PLAN_DIR, "%s-%s.json" % (kind, datetime.datetime.now().strftime("%Y%m%d-%H%M%S")))
    common.write_json(path, data)
    return path


def show(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def cmd_env(a, cfg):
    info = env.describe(a.path, scan=a.scan)
    info["free"] = common.fmt_gb(info.pop("free_bytes"))
    info["total"] = common.fmt_gb(info.pop("total_bytes"))
    info["vision_tool"] = "built" if similar.vision_available() else "not built (tools/vision/build.sh)"
    info["exiftool"] = "found" if common.have("exiftool") else "MISSING"
    info["config"] = cfg.get("_source", "defaults")
    info["language"] = cfg.get("language")
    show(info)


def cmd_compare(a, cfg):
    p = compare.compare(a.reference, a.source,
                        progress=lambda i, n: sys.stderr.write("hashing %d/%d\n" % (i, n)))
    path = save_plan("compare", p, a.out)
    c = p["counts"]
    show({"plan": path, "counts": c, "missing_size": common.fmt_gb(c["missing_bytes"]),
          "check": "%d = %d present + %d missing + %d skipped" % (c["total"], c["present"], c["missing"], c["skipped"]),
          "missing_by_top_folder": dict(collections.Counter(m["path"].split(os.sep)[0] for m in p["missing"]).most_common(20)),
          "missing_by_extension": dict(collections.Counter(os.path.splitext(m["path"])[1].lower() for m in p["missing"]).most_common(20)),
          "skipped": p["skipped"][:30]})


def cmd_extract(a, cfg):
    p = common.read_json(a.plan)
    if p.get("kind") != "compare":
        raise SystemExit("extract needs a compare plan")
    dest = a.dest or os.path.join(os.path.dirname(p["source"]),
                                  os.path.basename(p["source"]) + "-" + common.names(cfg)["missing"])
    need = sum(m["size"] for m in p["missing"])
    cross = not common.same_device(p["source"], dest)
    if cross and not env.free_space_ok(dest if os.path.exists(dest) else os.path.dirname(dest), need):
        raise SystemExit("not enough free space at %s for %s" % (dest, common.fmt_gb(need)))
    r = compare.extract(p, dest, cfg, apply=a.apply, copy=a.copy)
    r.update({"dest": dest, "files": len(p["missing"]), "size": common.fmt_gb(need),
              "how": "copy + verify (other volume; originals stay)" if (cross or a.copy) else "move (same volume)"})
    if not a.apply:
        r["next"] = "add --apply to carry this out"
    show(r)


def cmd_standardize(a, cfg):
    p = standardize.plan(a.root, cfg)
    path = save_plan("standardize", p, a.out)
    show({"plan": path, "counts": p["counts"], "by_destination": p["by_destination"],
          "sample": p["moves"][:15], "orphan_sidecars": p["orphan_sidecars"][:20],
          "next": "review, then: pao.py apply %s" % path})


def cmd_similar(a, cfg):
    p = similar.find(a.target, a.reference or [a.target], cfg, use_vision=not a.no_vision)
    path = save_plan("similar", p, a.out)
    show({"plan": path, "vision": p["vision"], "counts": p["counts"], "sample": p["similar"][:15],
          "review_not_moved": p["review"][:30], "next": "review, then: pao.py apply %s" % path})


def cmd_merge(a, cfg):
    p = merge.plan(a.source, a.dest, cfg)
    path = save_plan("merge", p, a.out)
    show({"plan": path, "counts": p["counts"], "renamed": p["renamed"][:30],
          "duplicates_already_in_dest": p["duplicates"][:30], "logs": p["logs"],
          "next": "review, then: pao.py apply %s" % path})


def cmd_apply(a, cfg):
    p = common.read_json(a.plan)
    kind = p.get("kind")
    if kind == "standardize":
        missing = [m["from"] for m in p["moves"] if not os.path.exists(os.path.join(p["root"], m["from"]))]
        if missing:
            raise SystemExit("plan is stale, %d files changed since planning (e.g. %s); plan again"
                             % (len(missing), missing[0]))
        show(standardize.apply(p, cfg))
    elif kind == "similar":
        show(similar.apply(p, cfg))
    elif kind == "merge":
        show(merge.apply(p, cfg))
    else:
        raise SystemExit("cannot apply a '%s' plan (compare plans are applied with extract)" % kind)


def cmd_verify_aside(a, cfg):
    """Confirm every file in <Duplicates>/ and <Similar>/ still has its pair."""
    n = common.names(cfg)
    root = a.root
    pairs = {}
    logdir = os.path.join(root, n["logs"])
    for lf in (os.listdir(logdir) if os.path.isdir(logdir) else []):
        if not lf.endswith(".csv"):
            continue
        with open(os.path.join(logdir, lf), encoding="utf-8") as f:
            for row in csv.DictReader(f):
                new, note = row.get("new_path") or "", row.get("note") or ""
                if "copy of " in note:
                    pairs[new] = ("dup", note.split("copy of ", 1)[1], row.get("sha256"))
                elif "pair: " in note:
                    pairs[new] = ("sim", note.split("pair: ", 1)[1], None)
    final = {}
    for lf in (os.listdir(logdir) if os.path.isdir(logdir) else []):
        if lf.endswith(".csv"):
            with open(os.path.join(logdir, lf), encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    final[row.get("old_path")] = row.get("new_path")
    ok, problems = [], []
    for folder in (n["duplicates"], n["similar"]):
        base = os.path.join(root, folder)
        if not os.path.isdir(base):
            continue
        files, _ = common.walk(base)
        for r, s, _ in files:
            if common.is_system(os.path.basename(r), s):
                continue
            rel = os.path.join(folder, r)
            info = pairs.get(rel)
            if not info:
                problems.append({"file": rel, "problem": "no log entry"})
                continue
            kind, pair, h = info
            pair_now = final.get(pair, pair)
            pp = pair_now if os.path.isabs(pair_now) else os.path.join(root, pair_now)
            if not os.path.exists(pp):
                problems.append({"file": rel, "problem": "pair missing: " + pair_now})
            elif kind == "dup" and h and common.sha256(pp) != common.sha256(os.path.join(root, rel)):
                problems.append({"file": rel, "problem": "pair content differs: " + pair_now})
            else:
                ok.append(rel)
    show({"verified": len(ok), "problems": problems,
          "safe_to_trash": [os.path.join(root, d) for d in (n["duplicates"], n["similar"])
                            if os.path.isdir(os.path.join(root, d))] if not problems else []})


def cmd_trash(a, cfg):
    targets = [os.path.abspath(p) for p in a.paths]
    exist = [p for p in targets if os.path.lexists(p)]
    if not a.yes:
        show({"would_trash": exist, "missing": [p for p in targets if p not in exist],
              "next": "add --yes to move these to the Finder Trash"})
        return
    done, failed = common.trash(exist)
    show({"trashed": len(done), "failed": failed,
          "note": "recoverable from the Trash until it is emptied"})


def cmd_check(a, cfg):
    show(recover.check(a.root, cfg))


def cmd_recover(a, cfg):
    rels = a.files or recover.check(a.root, cfg)["corrupt"]
    show(recover.recover(a.root, rels, cfg, apply=a.apply))


def cmd_mirror(a, cfg):
    fa, _ = common.walk(a.a)
    fb, _ = common.walk(a.b)
    da = {r: s for r, s, _ in fa if not common.is_system(os.path.basename(r), s)}
    db = {r: s for r, s, _ in fb if not common.is_system(os.path.basename(r), s)}
    only_a = sorted(set(da) - set(db))
    only_b = sorted(set(db) - set(da))
    size_diff = sorted(r for r in set(da) & set(db) if da[r] != db[r])
    content_diff = []
    if a.deep:
        for r in sorted(set(da) & set(db)):
            if da[r] == db[r] and common.sha256(os.path.join(a.a, r)) != common.sha256(os.path.join(a.b, r)):
                content_diff.append(r)
    show({"a": len(da), "b": len(db), "only_in_a": only_a[:50], "only_in_a_count": len(only_a),
          "only_in_b": only_b[:50], "only_in_b_count": len(only_b), "size_differs": size_diff[:50],
          "content_differs": content_diff[:50] if a.deep else "not checked (add --deep)",
          "identical": not (only_a or only_b or size_diff or content_diff)})


def cmd_devices(a, cfg):
    files, _ = common.walk(a.root)
    paths = [os.path.join(a.root, r) for r, s, _ in files if common.kind_of(r) in ("photo", "raw", "video")]
    meta = common.exif_read(paths)
    owners = cfg.get("device_owners") or {}
    stats = collections.defaultdict(lambda: {"files": 0, "years": collections.Counter(), "folders": collections.Counter()})
    for p in paths:
        x = meta[p]
        model = str(x.get("Model") or "(no camera info)")
        d = common.valid_date(x.get("DateTimeOriginal"), cfg) or common.valid_date(x.get("CreateDate"), cfg)
        s = stats[model]
        s["files"] += 1
        s["years"][d[:4] if d else "undated"] += 1
        s["folders"][os.path.relpath(p, a.root).split(os.sep)[0]] += 1
    show([{"model": m, "owner": owners.get(m, "?"), "files": s["files"],
           "years": dict(sorted(s["years"].items())), "top_folders": dict(s["folders"].most_common(5))}
          for m, s in sorted(stats.items(), key=lambda t: -t[1]["files"])])


def cmd_case_rename(a, cfg):
    new = os.path.join(os.path.dirname(os.path.abspath(a.path)), a.new_name)
    if not a.apply:
        show({"would_rename": a.path, "to": new, "next": "add --apply"})
        return
    show({"renamed_to": common.case_rename(os.path.abspath(a.path), a.new_name)})


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pao.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="config JSON (default ~/.config/photo-archive-organizer/config.json)")
    ap.add_argument("--lang", choices=["en", "tr"], help="override folder-name language")
    sp = ap.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("env", help="filesystem, free space, quirks, iCloud placeholders")
    s.add_argument("path"); s.add_argument("--scan", action="store_true"); s.set_defaults(f=cmd_env)

    s = sp.add_parser("compare", help="files in SOURCE with no identical copy in REFERENCE")
    s.add_argument("reference"); s.add_argument("source"); s.add_argument("--out"); s.set_defaults(f=cmd_compare)

    s = sp.add_parser("extract", help="move/copy the missing files of a compare plan")
    s.add_argument("plan"); s.add_argument("--dest"); s.add_argument("--copy", action="store_true",
                                                                      help="copy even on the same volume")
    s.add_argument("--apply", action="store_true"); s.set_defaults(f=cmd_extract)

    s = sp.add_parser("standardize", help="plan the year/month layout inside ROOT")
    s.add_argument("root"); s.add_argument("--out"); s.set_defaults(f=cmd_standardize)

    s = sp.add_parser("similar", help="plan setting aside other versions of pictures that exist elsewhere")
    s.add_argument("target"); s.add_argument("--reference", action="append",
                                             help="folder holding the keepers (repeatable; default: TARGET itself)")
    s.add_argument("--no-vision", action="store_true"); s.add_argument("--out"); s.set_defaults(f=cmd_similar)

    s = sp.add_parser("merge", help="plan merging standard folder SOURCE into DEST")
    s.add_argument("source"); s.add_argument("dest"); s.add_argument("--out"); s.set_defaults(f=cmd_merge)

    s = sp.add_parser("apply", help="carry out a standardize/similar/merge plan")
    s.add_argument("plan"); s.set_defaults(f=cmd_apply)

    s = sp.add_parser("verify-aside", help="check Duplicates/Similar files still have their pairs")
    s.add_argument("root"); s.set_defaults(f=cmd_verify_aside)

    s = sp.add_parser("trash", help="move paths to the Finder Trash (needs --yes)")
    s.add_argument("paths", nargs="+"); s.add_argument("--yes", action="store_true"); s.set_defaults(f=cmd_trash)

    s = sp.add_parser("check", help="which images fail to decode or are partly gray")
    s.add_argument("root"); s.set_defaults(f=cmd_check)

    s = sp.add_parser("recover", help="try to rebuild damaged JPEGs into <Recovered>/")
    s.add_argument("root"); s.add_argument("files", nargs="*"); s.add_argument("--apply", action="store_true")
    s.set_defaults(f=cmd_recover)

    s = sp.add_parser("mirror-check", help="are two copies of a folder the same?")
    s.add_argument("a"); s.add_argument("b"); s.add_argument("--deep", action="store_true"); s.set_defaults(f=cmd_mirror)

    s = sp.add_parser("devices", help="camera models, years and folders (helps split owners)")
    s.add_argument("root"); s.set_defaults(f=cmd_devices)

    s = sp.add_parser("case-rename", help="rename when only letter case changes")
    s.add_argument("path"); s.add_argument("new_name"); s.add_argument("--apply", action="store_true")
    s.set_defaults(f=cmd_case_rename)

    a = ap.parse_args(argv)
    cfg = common.load_config(a.config)
    if a.lang:
        cfg["language"] = a.lang
    a.f(a, cfg)


if __name__ == "__main__":
    main()
