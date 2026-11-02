"""Find files in TARGET that are another version of a picture already in REFERENCE
(or elsewhere in TARGET): rotated, re-saved, resized, metadata-edited copies and
RAW files whose JPEG exists.

Evidence, strongest first:
  scan     identical JPEG image data (only metadata differs)
  exif     same capture second + sub-second + camera model (+ serial/file number
           when both have them) and the same or swapped dimensions
  vision   Apple Vision feature-print distance <= similar_threshold
           (rotation-aware: the query is also compared at 90/180/270 degrees)
  raw      RAW file whose JPEG twin (same EXIF identity) exists

Distances between similar_threshold and review_threshold are listed for the
user, never moved. Nobody looks at the pictures: only numbers are compared.
"""
import collections
import os
import subprocess
import tempfile

from .common import (OpLog, exif_read, is_system, jpeg_scan_hash, kind_of, managed_dirs,
                     move_file, names, tree_prune, valid_date, walk)

HERE = os.path.dirname(os.path.abspath(__file__))
VISION_BIN = os.path.join(HERE, "..", "..", "tools", "vision", "pao-vision")


def vision_available():
    return os.path.isfile(VISION_BIN) and os.access(VISION_BIN, os.X_OK)


def identity(x, cfg):
    d = (valid_date(x.get("DateTimeOriginal"), cfg) or valid_date(x.get("CreationDate"), cfg)
         or valid_date(x.get("ContentCreateDate"), cfg)
         or valid_date(x.get("CreateDate"), cfg))
    if not d:
        return None
    return (d, str(x.get("SubSecTimeOriginal") or ""), str(x.get("Model") or ""))


def dims_compatible(a, b):
    wa, ha, wb, hb = a.get("ImageWidth"), a.get("ImageHeight"), b.get("ImageWidth"), b.get("ImageHeight")
    if not (wa and ha and wb and hb):
        return True
    return {wa, ha} == {wb, hb} or abs(wa / float(ha) - wb / float(hb)) < 0.02 or abs(wa / float(ha) - hb / float(wb)) < 0.02


def strong_ids_agree(a, b):
    for k in ("SerialNumber", "FileNumber"):
        if a.get(k) and b.get(k) and str(a[k]) != str(b[k]):
            return False
    return True


def run_vision(queries, refs, rotate=True):
    if not queries or not refs:
        return {}
    with tempfile.TemporaryDirectory() as td:
        q, r, o = (os.path.join(td, n) for n in ("q.txt", "r.txt", "o.tsv"))
        for path, items in ((q, queries), (r, refs)):
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(items) + "\n")
        cmd = [VISION_BIN, "fp", q, r, o] + (["--rotate"] if rotate else [])
        subprocess.run(cmd, capture_output=True, text=True)
        out = {}
        if os.path.exists(o):
            with open(o, encoding="utf-8") as f:
                lines = f.read().splitlines()
            for line in lines:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 3 and parts[2]:
                    out[parts[0]] = (float(parts[1]), parts[2])
        return out


def find(target, references, cfg, use_vision=True):
    n = names(cfg)
    skip = managed_dirs(cfg)
    tfiles, _ = walk(target, skip_top=skip)
    tabs = [os.path.join(target, r) for r, s, _ in tfiles
            if not is_system(os.path.basename(r), s) and kind_of(r) in ("photo", "raw", "video")]
    rabs = []
    for ref in references:
        rf, _ = walk(ref, skip_top=skip if os.path.abspath(ref) == os.path.abspath(target) else ())
        rabs += [os.path.join(ref, r) for r, s, _ in rf
                 if not is_system(os.path.basename(r), s) and kind_of(r) in ("photo", "raw", "video")]
    tset = set(tabs)
    rabs = [p for p in rabs if p not in tset]
    meta = exif_read(tabs + rabs)

    ref_by_id = collections.defaultdict(list)
    for p in rabs:
        i = identity(meta[p], cfg)
        if i:
            ref_by_id[i].append(p)
    ref_scan = {}
    for p in rabs:
        if p.lower().endswith((".jpg", ".jpeg")):
            h = jpeg_scan_hash(p)
            if h:
                ref_scan.setdefault(h, p)

    found, review = {}, {}
    # inside-target versions: group target files by identity, keep the best one
    tgt_by_id = collections.defaultdict(list)
    for p in tabs:
        i = identity(meta[p], cfg)
        if i:
            tgt_by_id[i].append(p)

    for p in tabs:
        x = meta[p]
        k = kind_of(p)
        if p.lower().endswith((".jpg", ".jpeg")):
            h = jpeg_scan_hash(p)
            if h and h in ref_scan:
                found[p] = (ref_scan[h], "scan", "same image data, only metadata differs")
                continue
        i = identity(x, cfg)
        if i and i in ref_by_id:
            cands = [q for q in ref_by_id[i] if strong_ids_agree(x, meta[q])]
            same_kind = [q for q in cands if kind_of(q) == k and dims_compatible(x, meta[q])]
            if k == "raw":
                jp = [q for q in cands if kind_of(q) == "photo"]
                if jp:
                    if cfg.get("raw_policy", "keep") == "similar":
                        found[p] = (jp[0], "raw", "RAW whose JPEG exists")
                    else:
                        review[p] = (jp[0], "raw", "RAW whose JPEG exists (raw_policy=keep)")
                    continue
            if same_kind:
                found[p] = (same_kind[0], "exif", "same capture moment and camera")
                continue
        if k == "raw" and i and i in tgt_by_id:
            jp = [q for q in tgt_by_id[i] if kind_of(q) == "photo" and strong_ids_agree(x, meta[q])]
            if jp:
                (found if cfg.get("raw_policy", "keep") == "similar" else review)[p] = (
                    jp[0], "raw", "RAW whose JPEG is in the same folder")

    # versions inside TARGET itself (when TARGET is also listed as a reference):
    # keep the largest image of each capture moment, set the others aside
    if any(os.path.abspath(r) == os.path.abspath(target) for r in references):
        for i, group in tgt_by_id.items():
            for k in ("photo", "video"):
                g = [p for p in group if kind_of(p) == k and p not in found]
                if len(g) < 2:
                    continue
                g.sort(key=lambda p: (-(meta[p].get("ImageWidth") or 0) * (meta[p].get("ImageHeight") or 0),
                                      -os.path.getsize(p), p))
                best = g[0]
                for p in g[1:]:
                    if dims_compatible(meta[p], meta[best]) and strong_ids_agree(meta[p], meta[best]):
                        found[p] = (best, "exif", "another version inside the same folder")

    if use_vision and vision_available():
        qs = [p for p in tabs if p not in found and kind_of(p) == "photo"]
        refs = [p for p in rabs if kind_of(p) == "photo"]
        dist = run_vision(qs, refs)
        st, rt = float(cfg.get("similar_threshold", 0.15)), float(cfg.get("review_threshold", 0.25))
        min_side = int(cfg.get("vision_min_side", 500))

        def big_enough(path):
            w, h = meta.get(path, {}).get("ImageWidth"), meta.get(path, {}).get("ImageHeight")
            return bool(w and h and max(w, h) >= min_side)

        for p, (d, q) in dist.items():
            if d <= st and not (big_enough(p) and big_enough(q)):
                review[p] = (q, "vision", "looks the same (distance %.3f) but the image is too small "
                             "for a reliable comparison" % d)
            elif d <= st:
                found[p] = (q, "vision", "looks the same (distance %.3f)" % d)
            elif d <= rt:
                review[p] = (q, "vision", "possibly the same (distance %.3f)" % d)

    def rel(p):
        return os.path.relpath(p, target)

    return {
        "target": os.path.abspath(target),
        "references": [os.path.abspath(r) for r in references],
        "vision": "used" if use_vision and vision_available() else "not available",
        "counts": {"checked": len(tabs), "similar": len(found), "review": len(review),
                   "by_evidence": dict(collections.Counter(v[1] for v in found.values()))},
        "similar": [{"path": rel(p), "pair": q, "evidence": e, "why": w}
                    for p, (q, e, w) in sorted(found.items())],
        "review": [{"path": rel(p), "pair": q, "evidence": e, "why": w}
                   for p, (q, e, w) in sorted(review.items())],
    }


def apply(p, cfg):
    """Set the similar files aside in TARGET/<Similar>/<relative path>."""
    target = p["target"]
    n = names(cfg)
    log = OpLog(target, cfg, "similar")
    moved = 0
    for s in p["similar"]:
        if not os.path.exists(s["pair"]):
            continue  # pair vanished: keep the file
        src = os.path.join(target, s["path"])
        dst = os.path.join(target, n["similar"], s["path"])
        move_file(src, dst)
        log.add("set aside", s["path"], os.path.join(n["similar"], s["path"]), "",
                "%s; pair: %s" % (s["why"], s["pair"]))
        moved += 1
    path = log.flush()
    tree_prune(target)
    return {"moved": moved, "log": path}
