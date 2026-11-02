"""Find files in SOURCE that have no byte-identical copy in REFERENCE.

Names are ignored on purpose: organized folders rename files, so only content
counts. Size is the first filter, a head+tail fingerprint the second, and a
full SHA-256 decides. Every source file ends in exactly one bucket, so
present + missing + skipped == total is checked before anything is reported.
"""
import collections
import os

from .common import OpLog, is_system, move_file, quick_key, sha256, walk, names


def compare(reference, source, progress=None):
    ref_files, ref_skipped = walk(reference)
    src_files, src_skipped = walk(source)
    ref_sizes = collections.Counter(s for _, s, _ in ref_files)
    src_sizes = {s for _, s, _ in src_files}

    def full(root, rel):
        return os.path.join(root, rel)

    # quick keys only where sizes overlap
    ref_q = {r: quick_key(full(reference, r), s) for r, s, _ in ref_files if s in src_sizes}
    src_q = {r: quick_key(full(source, r), s) for r, s, _ in src_files if s in ref_sizes}
    common = ({(s, ref_q[r]) for r, s, _ in ref_files if r in ref_q}
              & {(s, src_q[r]) for r, s, _ in src_files if r in src_q})
    ref_hash = {}
    for r, s, _ in ref_files:
        if r in ref_q and (s, ref_q[r]) in common:
            ref_hash.setdefault(sha256(full(reference, r)), r)
    present, missing, skipped = [], [], []
    for i, (r, s, _) in enumerate(src_files):
        name = os.path.basename(r)
        if is_system(name, s):
            skipped.append({"path": r, "size": s, "why": "system or empty file"})
            continue
        h = None
        if r in src_q and (s, src_q[r]) in common:
            h = sha256(full(source, r))
        if h and h in ref_hash:
            present.append({"path": r, "size": s, "sha256": h, "copy_in_reference": ref_hash[h]})
        else:
            missing.append({"path": r, "size": s, "sha256": h})
        if progress and i % 1000 == 0:
            progress(i, len(src_files))
    total = len(src_files)
    assert len(present) + len(missing) + len(skipped) == total
    return {
        "reference": os.path.abspath(reference),
        "source": os.path.abspath(source),
        "counts": {"total": total, "present": len(present), "missing": len(missing),
                   "skipped": len(skipped),
                   "missing_bytes": sum(m["size"] for m in missing),
                   "reference_files": len(ref_files)},
        "unreadable_or_protected": {"reference": ref_skipped, "source": src_skipped},
        "present": present,
        "missing": missing,
        "skipped": skipped,
    }


def extract(plan, dest, cfg, apply=False, copy=False):
    """Move (same volume) or copy+verify (other volume) the missing files to
    DEST, keeping their relative folders and names."""
    source = plan["source"]
    todo = []
    for m in plan["missing"]:
        src = os.path.join(source, m["path"])
        dst = os.path.join(dest, m["path"])
        todo.append((src, dst, m))
    clashes = [d for _, d, _ in todo if os.path.lexists(d)]
    result = {"planned": len(todo), "clashes": clashes, "done": 0, "mode": None}
    if not apply or clashes:
        return result
    log = OpLog(dest, cfg, "extract")
    for src, dst, m in todo:
        if copy:
            import shutil
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            how = "copied"
            if m.get("sha256") and sha256(dst) != m["sha256"]:
                raise OSError("copy verification failed: %s" % src)
        else:
            how = move_file(src, dst)
        result["mode"] = how
        log.add(how, src, dst, m.get("sha256") or "", "not in reference " + plan["reference"])
        result["done"] += 1
    result["log"] = log.flush()
    return result
