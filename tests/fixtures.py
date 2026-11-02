"""Synthetic test pictures: no real photos are ever used.

Each picture is a distinct generated pattern written as BMP, converted with
macOS `sips`, then given EXIF with exiftool.
"""
import os
import random
import struct
import subprocess


def bmp(path, w, h, seed):
    """Photo-like synthetic picture: smooth blobs, waves and grain.

    Flat shapes confuse feature-print models; textured content behaves much
    more like a real photo when resized or recompressed.
    """
    import math
    rnd = random.Random(seed)
    blobs = [(rnd.uniform(0, w), rnd.uniform(0, h), rnd.uniform(w / 10, w / 3),
              (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))) for _ in range(12)]
    fx, fy, ph = rnd.uniform(2, 9), rnd.uniform(2, 9), rnd.uniform(0, 6.28)
    row_pad = (4 - (w * 3) % 4) % 4
    pixels = bytearray()
    for y in range(h - 1, -1, -1):
        for x in range(w):
            r = g = b = 0.0
            wsum = 0.0
            for bx, by, rad, col in blobs:
                d2 = ((x - bx) ** 2 + (y - by) ** 2) / (rad * rad)
                k = math.exp(-d2)
                r += col[0] * k; g += col[1] * k; b += col[2] * k; wsum += k
            base = 128 + 60 * math.sin(fx * x / w * 6.28 + ph) * math.cos(fy * y / h * 6.28)
            if wsum > 0:
                r, g, b = r / wsum, g / wsum, b / wsum
            mix = min(1.0, wsum)
            c = [int(max(0, min(255, base * (1 - mix) + v * mix + rnd.uniform(-12, 12)))) for v in (r, g, b)]
            pixels += bytes((c[2], c[1], c[0]))
        pixels += b"\x00" * row_pad
    header = b"BM" + struct.pack("<IHHI", 54 + len(pixels), 0, 0, 54)
    dib = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
    with open(path, "wb") as f:
        f.write(header + dib + pixels)


def jpeg(path, seed, w=320, h=240, exif=None, fmt="jpeg"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".bmp"
    bmp(tmp, w, h, seed)
    subprocess.run(["sips", "-s", "format", fmt, tmp, "--out", path], capture_output=True, check=True)
    os.remove(tmp)
    if exif:
        set_exif(path, exif)
    return path


def set_exif(path, tags):
    args = ["exiftool", "-q", "-overwrite_original"] + ["-%s=%s" % (k, v) for k, v in tags.items()] + [path]
    subprocess.run(args, capture_output=True, check=True)


def rotate(src, dst, degrees=90):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    subprocess.run(["sips", "-r", str(degrees), src, "--out", dst], capture_output=True, check=True)


def resize(src, dst, longest=160):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    subprocess.run(["sips", "-Z", str(longest), src, "--out", dst], capture_output=True, check=True)
    subprocess.run(["exiftool", "-q", "-overwrite_original", "-all=", dst], capture_output=True)


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def photo(path, seed, longest=1600, exif=None):
    """A larger picture (generated small, scaled up): Vision feature prints
    are only meaningful on images of a realistic size."""
    small = jpeg(path + ".small.jpg", seed, w=320, h=240)
    subprocess.run(["sips", "-Z", str(longest), small, "--out", path], capture_output=True, check=True)
    os.remove(small)
    if exif:
        set_exif(path, exif)
    return path


def damage_header(src, dst):
    """Zero the APPn segments (EXIF etc.) after SOI, as when the start of a
    file was overwritten but the image tables and data survived."""
    with open(src, "rb") as f:
        b = bytearray(f.read())
    p = 2
    while p + 4 < len(b) and b[p] == 0xFF and 0xE0 <= b[p + 1] <= 0xEF:
        p += 2 + ((b[p + 2] << 8) | b[p + 3])
    for k in range(2, p):
        b[k] = 0
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as f:
        f.write(bytes(b))
