"""End-to-end tests on generated pictures. Run: python3 -m unittest discover tests -v

Needs macOS (sips), exiftool, and for the Vision tests tools/vision/pao-vision.
"""
import csv
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, HERE)

import fixtures as fx  # noqa: E402
from pao import common, compare, merge, recover, similar, standardize  # noqa: E402

HAVE_TOOLS = shutil.which("sips") and shutil.which("exiftool")


def files_under(root):
    out = []
    for r, s, _ in common.walk(root)[0]:
        if not common.is_system(os.path.basename(r), s):
            out.append(r)
    return sorted(out)


@unittest.skipUnless(HAVE_TOOLS, "needs macOS sips and exiftool")
class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pao-test-")
        self.cfg = common.load_config(os.path.join(self.tmp, "none.json"))
        self.cfg.update(common.DEFAULT_CONFIG)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def p(self, *parts):
        return os.path.join(self.tmp, *parts)


class CompareTests(Base):
    def test_missing_found_by_content_not_name(self):
        fx.jpeg(self.p("ref", "Photos", "2015", "20150101_120000_aaaa.jpg"), 1)
        fx.jpeg(self.p("ref", "Photos", "x.jpg"), 2)
        shutil.copy(self.p("ref", "Photos", "2015", "20150101_120000_aaaa.jpg"), self.p("src_a.jpg"))
        os.makedirs(self.p("src", "phone"))
        shutil.move(self.p("src_a.jpg"), self.p("src", "phone", "IMG_0001.JPG"))  # same content, new name
        fx.jpeg(self.p("src", "phone", "IMG_0002.JPG"), 3)                       # new picture
        fx.write(self.p("src", "phone", ".DS_Store"), b"junk")
        plan = compare.compare(self.p("ref"), self.p("src"))
        c = plan["counts"]
        self.assertEqual((c["total"], c["present"], c["missing"], c["skipped"]), (3, 1, 1, 1))
        self.assertEqual(plan["missing"][0]["path"], os.path.join("phone", "IMG_0002.JPG"))

    def test_extract_keeps_structure_and_logs(self):
        fx.jpeg(self.p("ref", "a.jpg"), 1)
        fx.jpeg(self.p("src", "deep", "er", "b.jpg"), 2)
        plan = compare.compare(self.p("ref"), self.p("src"))
        dry = compare.extract(plan, self.p("out"), self.cfg, apply=False)
        self.assertEqual(dry["done"], 0)
        self.assertTrue(os.path.exists(self.p("src", "deep", "er", "b.jpg")))
        r = compare.extract(plan, self.p("out"), self.cfg, apply=True)
        self.assertEqual(r["done"], 1)
        self.assertTrue(os.path.exists(self.p("out", "deep", "er", "b.jpg")))
        self.assertFalse(os.path.exists(self.p("src", "deep", "er", "b.jpg")))
        self.assertTrue(os.path.exists(r["log"]))


class StandardizeTests(Base):
    def build(self):
        root = self.p("person")
        fx.jpeg(self.p("person", "phone", "IMG_1234.JPG"), 1,
                exif={"DateTimeOriginal": "2015:03:15 10:10:10", "Model": "iPhone 6"})
        fx.write(self.p("person", "phone", "IMG_1234.AAE"), b"<plist>edit</plist>")
        shutil.copy(self.p("person", "phone", "IMG_1234.JPG"), self.p("person", "phone", "IMG_1234 (1).JPG"))
        fx.jpeg(self.p("person", "misc", "IMG_9999.JPG"), 2)                      # no date
        fx.jpeg(self.p("person", "misc", "Diploma.jpg"), 3)                       # typed name, no date
        fx.jpeg(self.p("person", "1997", "S7300927.JPG"), 4)                      # year only from folder
        fx.jpeg(self.p("person", "cam", "S2010013.JPG"), 5,
                exif={"DateTimeOriginal": "2097:05:25 12:42:14"})                  # broken clock
        fx.jpeg(self.p("person", "misc", "2012-05-18 15.22.35.jpg"), 6)           # date in name
        fx.write(self.p("person", "docs", "CV.pdf"), b"%PDF-1.4 cv")
        fx.write(self.p("person", "docs", "orphan.AAE"), b"<plist>x</plist>")
        return root

    def test_layout(self):
        root = self.build()
        plan = standardize.plan(root, self.cfg)
        res = standardize.apply(plan, self.cfg)
        got = files_under(root)
        h = common.sha256(os.path.join(root, [f for f in got if f.startswith("Photos/2015/2015-03/") and f.endswith(".jpg")][0]))
        self.assertIn("Photos/2015/2015-03/20150315_101010_%s.jpg" % h[:4], got)
        self.assertIn("Photos/2015/2015-03/20150315_101010_%s.aae" % h[:4], got)        # sidecar follows
        self.assertIn(os.path.join("Duplicates", "phone", "IMG_1234 (1).JPG"), got)       # exact copy aside
        self.assertTrue(any(f.startswith("Photos/Undated/undated_") for f in got))
        self.assertIn("Photos/Undated/Diploma.jpg", got)                                  # typed name kept
        self.assertTrue(any(f.startswith("Photos/1997/Undated/1997_") for f in got))
        self.assertTrue(any(f.startswith("Photos/2012/2012-05/20120518_152235_") for f in got))
        self.assertFalse(any("2097" in f for f in got))                                   # clock ignored
        self.assertIn("Data/CV.pdf", got)
        self.assertIn("Photos/Undated/orphan.AAE", got)
        self.assertEqual(plan["counts"]["orphan_sidecars"], 1)
        self.assertFalse(os.path.exists(os.path.join(root, "phone")))                    # emptied dirs pruned
        with open(res["log"], encoding="utf-8") as f:
            log = list(csv.DictReader(f))
        self.assertEqual(len(log), plan["counts"]["moves"])

    def test_idempotent(self):
        root = self.build()
        standardize.apply(standardize.plan(root, self.cfg), self.cfg)
        again = standardize.plan(root, self.cfg)
        self.assertEqual(again["counts"]["moves"], 0, again["moves"][:3])

    def test_turkish_names(self):
        self.cfg["language"] = "tr"
        root = self.build()
        standardize.apply(standardize.plan(root, self.cfg), self.cfg)
        got = files_under(root)
        self.assertTrue(any(f.startswith("Foto/2015/2015-03/") for f in got))
        self.assertTrue(any(f.startswith("Foto/Tarihsiz/tarihsiz_") for f in got))
        self.assertTrue(any(f.startswith("Cop/") for f in got))
        self.assertTrue(any(f.startswith("Kayitlar/") for f in got))

    def test_albums_untouched(self):
        root = self.build()
        fx.jpeg(self.p("person", "Wedding", "IMG_5000.JPG"), 9,
                exif={"DateTimeOriginal": "2017:12:15 13:00:00"})
        self.cfg["albums"] = ["Wedding"]
        standardize.apply(standardize.plan(root, self.cfg), self.cfg)
        self.assertTrue(os.path.exists(self.p("person", "Wedding", "IMG_5000.JPG")))


class SimilarTests(Base):
    def test_metadata_only_and_exif_versions(self):
        tags = {"DateTimeOriginal": "2018:06:02 09:13:12", "SubSecTimeOriginal": "50", "Model": "SLT-A58",
                "SerialNumber": "123"}
        keep = fx.jpeg(self.p("ref", "Photos", "2018", "2018-06", "keep.jpg"), 11, exif=tags)
        # metadata-only difference: same pixels, other orientation tag
        shutil.copy(keep, self.p("t_meta.jpg"))
        fx.set_exif(self.p("t_meta.jpg"), {"Orientation#": "6", "Software": "x"})
        os.makedirs(self.p("tgt", "a"))
        shutil.move(self.p("t_meta.jpg"), self.p("tgt", "a", "meta.jpg"))
        # rotated and re-encoded with the same EXIF identity
        fx.rotate(keep, self.p("tgt", "a", "rot.jpg"))
        fx.set_exif(self.p("tgt", "a", "rot.jpg"), tags)
        # unrelated picture with a different moment
        fx.jpeg(self.p("tgt", "a", "other.jpg"), 99, exif={"DateTimeOriginal": "2018:06:02 09:20:00",
                                                           "Model": "SLT-A58"})
        plan = similar.find(self.p("tgt"), [self.p("ref")], self.cfg, use_vision=False)
        ev = {s["path"]: s["evidence"] for s in plan["similar"]}
        self.assertEqual(ev.get(os.path.join("a", "meta.jpg")), "scan")
        self.assertEqual(ev.get(os.path.join("a", "rot.jpg")), "exif")
        self.assertNotIn(os.path.join("a", "other.jpg"), ev)
        res = similar.apply(plan, self.cfg)
        self.assertEqual(res["moved"], 2)
        self.assertTrue(os.path.exists(self.p("tgt", "Similar", "a", "rot.jpg")))
        self.assertTrue(os.path.exists(self.p("tgt", "a", "other.jpg")))

    @unittest.skipUnless(similar.vision_available(), "pao-vision not built")
    def test_vision_finds_resized_copy_without_exif(self):
        keep = fx.photo(self.p("ref", "big.jpg"), 21, 1600)
        fx.resize(keep, self.p("tgt", "smaller.jpg"), 800)
        fx.rotate(self.p("tgt", "smaller.jpg"), self.p("tgt", "turned.jpg"), 90)
        fx.photo(self.p("tgt", "different.jpg"), 77, 1600)
        fx.resize(keep, self.p("tgt", "tiny.jpg"), 200)
        plan = similar.find(self.p("tgt"), [self.p("ref")], self.cfg, use_vision=True)
        found = {s["path"] for s in plan["similar"]}
        review = {s["path"] for s in plan["review"]}
        self.assertIn("smaller.jpg", found)
        self.assertIn("turned.jpg", found)          # rotation-aware comparison
        self.assertNotIn("different.jpg", found)
        self.assertNotIn("tiny.jpg", found)         # too small to trust: review at most
        self.assertTrue("tiny.jpg" in review or "tiny.jpg" not in found)

    def test_raw_policy(self):
        tags = {"DateTimeOriginal": "2017:12:15 13:00:22", "Model": "Canon EOS 6D", "FileNumber": "1005364"}
        fx.jpeg(self.p("ref", "a.jpg"), 31, exif=tags)
        raw = fx.jpeg(self.p("tgt", "IMG_5364.tif"), 31, exif=tags, fmt="tiff")
        os.rename(raw, self.p("tgt", "IMG_5364.CR2"))   # stand-in RAW: kind is decided by extension
        plan = similar.find(self.p("tgt"), [self.p("ref")], self.cfg, use_vision=False)
        self.assertEqual(len(plan["review"]), 1)       # raw_policy=keep -> listed, not moved
        self.cfg["raw_policy"] = "similar"
        plan = similar.find(self.p("tgt"), [self.p("ref")], self.cfg, use_vision=False)
        self.assertEqual(plan["similar"][0]["evidence"], "raw")


class MergeTests(Base):
    def test_merge_collisions(self):
        fx.jpeg(self.p("dst", "Photos", "2015", "2015-01", "a.jpg"), 1)
        fx.jpeg(self.p("dst", "Data", "cv.pdf"), 2)
        shutil.copytree(self.p("dst", "Photos"), self.p("src", "Photos"))          # identical file
        fx.jpeg(self.p("src", "Data", "cv.pdf"), 3)                                # same name, other content
        fx.jpeg(self.p("src", "Photos", "2011", "2011-12", "b.jpg"), 4)            # new
        fx.write(self.p("src", "Logs", "Operations-Log.csv"), b"time\n")
        plan = merge.plan(self.p("src"), self.p("dst"), self.cfg)
        self.assertEqual(plan["counts"]["duplicates"], 1)
        self.assertEqual(plan["counts"]["renamed"], 1)
        merge.apply(plan, self.cfg)
        got = files_under(self.p("dst"))
        self.assertIn("Photos/2011/2011-12/b.jpg", got)
        self.assertTrue(any(f.startswith("Data/cv (") for f in got))
        self.assertIn("Logs/src-Operations-Log.csv", got)
        self.assertTrue(os.path.exists(self.p("src", "Photos", "2015", "2015-01", "a.jpg")))  # dup left for user


@unittest.skipUnless(similar.vision_available(), "pao-vision not built")
class RecoverTests(Base):
    def test_rebuild_damaged_header(self):
        good = fx.jpeg(self.p("x", "good.jpg"), 41, w=400, h=300,
                       exif={"DateTimeOriginal": "2020:01:01 10:00:00", "Model": "Cam"})
        fx.damage_header(good, self.p("x", "bad.jpg"))
        chk = recover.check(self.p("x"), self.cfg)
        self.assertIn("bad.jpg", chk["corrupt"])
        res = recover.recover(self.p("x"), ["bad.jpg"], self.cfg, apply=True)
        self.assertEqual(res["recovered"], 1, res)
        out = self.p("x", "Recovered", "bad.jpg")
        d = recover.decode([out])[out]
        self.assertTrue(d[0])
        self.assertEqual((d[1], d[2]), (400, 300))


    def test_picks_full_image_not_thumbnail(self):
        good = fx.jpeg(self.p("x", "good.jpg"), 42, w=480, h=360,
                       exif={"DateTimeOriginal": "2020:01:01 10:00:00", "Model": "Cam"})
        thumb = fx.jpeg(self.p("t", "thumb.jpg"), 42, w=160, h=120)
        import subprocess
        subprocess.run(["exiftool", "-q", "-overwrite_original", "-ThumbnailImage<=" + thumb, good],
                       capture_output=True, check=True)
        with open(good, "rb") as f:
            b = bytearray(f.read())
        for k in range(2, 40):          # wipe the start of the EXIF header only
            b[k] = 0
        with open(self.p("x", "bad.jpg"), "wb") as f:
            f.write(bytes(b))
        res = recover.recover(self.p("x"), ["bad.jpg"], self.cfg, apply=False)
        self.assertEqual(res["items"][0]["result"], "recovered", res)
        self.assertEqual(res["items"][0]["size"], "480x360")


class HelperTests(Base):
    def test_case_rename(self):
        os.makedirs(self.p("MOM"))
        common.case_rename(self.p("MOM"), "Mom")
        self.assertIn("Mom", os.listdir(self.tmp))

    def test_valid_date(self):
        self.assertIsNone(common.valid_date("0000:00:00 00:00:00", self.cfg))
        self.assertIsNone(common.valid_date("2097:05:25 12:42:14", self.cfg))
        self.assertEqual(common.valid_date("2011:12:21 13:25:38+02:00", self.cfg), "2011:12:21 13:25:38")

    def test_generic_names(self):
        g = lambda s: standardize.is_generic(s, self.cfg)
        for s in ["IMG_1234", "IMG_1234 (1)", "DSC09595", "Fotoğraf0832", "538bbd82-bff2-449c-abc1-6769c079c668",
                  "vural 030", "20171215_133054_c517", "tarihsiz_e60e4e", "photo1"]:
            self.assertTrue(g(s), s)
        for s in ["Diploma", "Lise Arkadaşları", "Start Deutsch 1 Zeugnis", "Bewerbung"]:
            self.assertFalse(g(s), s)


if __name__ == "__main__":
    unittest.main()


class CliFlowTests(Base):
    """The whole chain through the command line, as Claude runs it."""

    def run_cli(self, *args):
        import json
        import subprocess
        cfgp = self.p("cfg.json")
        with open(cfgp, "w") as f:
            json.dump({"language": "tr"}, f)
        r = subprocess.run([sys.executable, os.path.join(HERE, "..", "scripts", "pao.py"), "--config", cfgp]
                           + list(args), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_backup_to_archive(self):
        tags = {"DateTimeOriginal": "2016:05:26 10:00:00", "Model": "iPad"}
        a = fx.jpeg(self.p("arsiv", "Foto", "2016", "2016-05", "20160526_100000_aaaa.jpg"), 1, exif=tags)
        shutil.copy(a, self.p("same.jpg"))
        os.makedirs(self.p("yedek", "Ipad"))
        shutil.move(self.p("same.jpg"), self.p("yedek", "Ipad", "IMG_0820.JPG"))
        fx.jpeg(self.p("yedek", "Ipad", "IMG_0900.JPG"), 2,
                exif={"DateTimeOriginal": "2016:06:01 09:00:00", "Model": "iPad"})
        fx.rotate(a, self.p("yedek", "Ipad", "IMG_0820 (1).JPG"))
        fx.set_exif(self.p("yedek", "Ipad", "IMG_0820 (1).JPG"), tags)
        c = self.run_cli("compare", self.p("arsiv"), self.p("yedek"), "--out", self.p("c.json"))
        self.assertEqual(c["counts"]["present"], 1)
        self.assertEqual(c["counts"]["missing"], 2)
        e = self.run_cli("extract", self.p("c.json"), "--dest", self.p("Olmayanlar"), "--apply")
        self.assertEqual(e["done"], 2)
        s = self.run_cli("standardize", self.p("Olmayanlar"), "--out", self.p("s.json"))
        self.run_cli("apply", self.p("s.json"))
        sim = self.run_cli("similar", self.p("Olmayanlar"), "--reference", self.p("arsiv"),
                           "--no-vision", "--out", self.p("m.json"))
        self.assertEqual(sim["counts"]["similar"], 1)
        self.run_cli("apply", self.p("m.json"))
        v = self.run_cli("verify-aside", self.p("Olmayanlar"))
        self.assertEqual(v["verified"], 1)
        self.assertEqual(v["problems"], [])
        t = self.run_cli("trash", *v["safe_to_trash"])            # dry run only, no --yes
        self.assertEqual(len(t["would_trash"]), 1)
        shutil.rmtree(v["safe_to_trash"][0])                       # stand-in for the user's Trash
        mg = self.run_cli("merge", self.p("Olmayanlar"), self.p("arsiv"), "--out", self.p("g.json"))
        self.assertEqual(mg["counts"]["moves"], 1)
        self.run_cli("apply", self.p("g.json"))
        got = files_under(self.p("arsiv"))
        self.assertTrue(any(f.startswith("Foto/2016/2016-06/20160601_090000_") for f in got))
        self.assertTrue(any(f.startswith("Kayitlar/") for f in got))
