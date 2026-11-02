"""Check which images decode, and try to rebuild JPEGs whose header was
overwritten while the image data survived.

A camera JPEG is SOI + APP1(EXIF, with a small thumbnail) + DQT/SOF/DHT/SOS +
data. When only the start is damaged, starting a new file at one of the later
quantisation tables (DQT) often brings the full-size picture back. Every
candidate is decoded and the largest one that decodes wins. Results go to
<Recovered>/ next to the originals; originals are never modified.
"""
import os
import subprocess
import tempfile

from .common import OpLog, names, walk, kind_of, move_file
from .similar import VISION_BIN, vision_available


def decode(paths):
    """{path: (ok, width, height, gray_fraction)} using the bundled Swift tool."""
    if not paths:
        return {}
    if not vision_available():
        raise SystemExit("tools/vision/pao-vision is not built. Run tools/vision/build.sh (macOS).")
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8") as f:
        f.write("\n".join(paths) + "\n")
        lst = f.name
    try:
        out = subprocess.run([VISION_BIN, "decode", lst], capture_output=True, text=True).stdout
    finally:
        os.unlink(lst)
    res = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 4:
            ok = parts[0] == "OK"
            w, h = (int(v) for v in parts[1].split("x")) if "x" in parts[1] else (0, 0)
            res[parts[3]] = (ok, w, h, float(parts[2] or 0))
    return res


def check(root, cfg, gray_limit=0.25):
    files, _ = walk(root)
    imgs = [os.path.join(root, r) for r, s, _ in files if kind_of(r) == "photo" and s > 0]
    d = decode(imgs)
    bad = [p for p in imgs if not d.get(p, (False,))[0]]
    partial = [p for p in imgs if d.get(p, (False,))[0] and d[p][3] >= gray_limit]
    return {"root": os.path.abspath(root), "checked": len(imgs),
            "corrupt": [os.path.relpath(p, root) for p in bad],
            "partly_gray": [os.path.relpath(p, root) for p in partial]}


SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
TABLES = {0xC4, 0xDB, 0xDD, 0xCC} | SOF


def chain(data, pos, limit=40):
    """Segment offsets of a well-formed run starting at pos that reaches a scan
    (SOS) after a frame (SOF) and at least one table, else None."""
    seen_sof = seen_table = False
    p, offsets = pos, []
    for _ in range(limit):
        if p + 4 > len(data) or data[p] != 0xFF:
            return None
        m = data[p + 1]
        offsets.append(p)
        if m == 0xDA:
            return offsets if (seen_sof and seen_table) else None
        if not (m in TABLES or 0xE0 <= m <= 0xEF or m == 0xFE):
            return None
        length = (data[p + 2] << 8) | data[p + 3]
        if length < 2:
            return None
        seen_sof |= m in SOF
        seen_table |= m in (0xC4, 0xDB)
        p += 2 + length
    return None


def candidates(data):
    """Offsets where an intact segment chain (tables, frame, scan) begins.

    Cameras usually write DQT before SOF; some encoders write SOF/DHT first, so
    any table or frame marker can start the surviving part. An EXIF thumbnail
    has its own small chain; decoding decides which chain is the full picture.
    """
    out, covered = [], set()
    i = data.find(b"\xff", 2)
    while i != -1 and i < len(data) - 4:
        if i not in covered and data[i + 1] in TABLES:
            c = chain(data, i)
            if c:
                out.append(i)
                covered.update(c)
        i = data.find(b"\xff", i + 1)
    return out


def rebuild(path, workdir):
    """Return (best_bytes, width, height, how) or None."""
    with open(path, "rb") as f:
        data = f.read()
    tries = []
    if not data.rstrip(b"\x00").endswith(b"\xff\xd9"):
        tries.append(("added end marker", data.rstrip(b"\x00") + b"\xff\xd9"))
    for pos in candidates(data):
        body = data[pos:]
        tries.append(("rebuilt from offset %d" % pos, b"\xff\xd8" + body))
    files = []
    for k, (how, b) in enumerate(tries):
        t = os.path.join(workdir, "try_%d.jpg" % k)
        with open(t, "wb") as f:
            f.write(b)
        files.append((t, how, b))
    res = decode([t for t, _, _ in files])
    best = None
    for t, how, b in files:
        ok, w, h, gray = res.get(t, (False, 0, 0, 1))
        if ok and gray < 0.9:
            score = (w * h, -gray)
            if not best or score > best[0]:
                best = (score, b, w, h, how, gray)
    if not best:
        return None
    return best[1], best[2], best[3], best[4], best[5]


def recover(root, rel_paths, cfg, apply=False):
    n = names(cfg)
    log = OpLog(root, cfg, "recover")
    out = []
    with tempfile.TemporaryDirectory() as td:
        for rel in rel_paths:
            src = os.path.join(root, rel)
            r = rebuild(src, td)
            if not r:
                out.append({"path": rel, "result": "not recoverable"})
                continue
            b, w, h, how, gray = r
            dst = os.path.join(root, n["recovered"], rel)
            item = {"path": rel, "result": "recovered", "size": "%dx%d" % (w, h), "how": how,
                    "gray_fraction": round(gray, 3), "to": os.path.relpath(dst, root)}
            if apply:
                if os.path.lexists(dst):
                    item["result"] = "skipped: target exists"
                else:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(dst, "wb") as f:
                        f.write(b)
                    log.add("recovered", rel, item["to"], "", how)
            out.append(item)
    return {"items": out, "log": log.flush() if apply else None,
            "recovered": sum(1 for i in out if i["result"] == "recovered")}
