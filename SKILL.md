---
name: photo-archive-organizer
description: Safely organize, compare, deduplicate and merge photo and video archives on external disks (NTFS, exFAT, APFS) or local folders, without ever looking at the pictures. Use this skill whenever the user wants to sort photos into year/month folders, rename them by capture date, compare two photo folders or disks and pull out the files that exist in only one, find duplicate or near-duplicate photos (rotated, resized, re-saved, RAW+JPEG), merge a backup or an old phone/computer dump into an organized archive, recover corrupt JPEGs, check that two backups are identical, split a mixed family archive by device/owner, or clean up Cop/Duplicates/Similar folders — even if they only say things like "yedekte olup arşivde olmayanları çıkar", "fotoğrafları yıl ay düzenine sok", "benzerleri ayıkla", "bu diskteki kopyaları bul", "masaüstündeki yedeği arşive kat" or "are these two backups the same?".
---

# Photo archive organizer

Family photo archives are irreplaceable, usually spread over several disks, and
full of copies that are almost-but-not-quite identical. This skill turns that
mess into one predictable layout while guaranteeing that nothing is lost and
every step can be undone.

All heavy lifting is done by `scripts/pao.py` (Python 3.8+, standard library)
plus `exiftool`. Apple Vision is used through the bundled `tools/vision/pao-vision`
helper (macOS) for picture similarity and decode checks.

Talk to the user in their language (Turkish users: Turkish). Keep technical
words out of the reply unless the user uses them.

## Non-negotiable rules (and why)

1. **Never look at the user's pictures.** Not as thumbnails, grids or crops.
   Family photos are private; decisions come from numbers only (hashes, EXIF,
   Vision distances, decode results). When numbers cannot decide, list the files
   and let the user look.
2. **Nothing is deleted on suspicion.** Extra copies go to `Duplicates/` (TR:
   `Cop/`), other versions to `Similar/` (TR: `Benzerler/`). Trashing happens
   only after `verify-aside` confirms every pair still exists, only with the
   user's explicit go-ahead, and only to the Finder Trash (recoverable).
3. **Only mounted disks count.** "The original is on the other disk" is not
   evidence unless that disk is mounted and the file was found there. iCloud
   placeholders and unmounted network shares do not count either.
4. **Plan first, then apply.** Every changing command writes a plan; read the
   summary to the user, then `apply`. Never chain plan+apply silently for large
   or unfamiliar folders.
5. **Every change is logged** in `<root>/Logs/Operations-Log.csv` (TR:
   `Kayitlar/Islem-Kaydi.csv`) with old path, new path, hash and reason.
6. **Count everything.** After a compare/extract the numbers must add up
   (`total = present + missing + skipped`). Report the equation; if it does not
   hold, stop.
7. **Do exactly the scope asked.** "Only check", "don't move yet", "başka işlem
   yapma" mean exactly that. Offer next steps, don't take them.
8. **Across volumes, copy + verify; the source stays.** Removing the source is a
   separate decision for the user.

## First steps in any session

```bash
python3 scripts/pao.py env "<folder>" --scan     # filesystem, free space, quirks, iCloud, protected libraries
```
- Read the `quirks` and `warnings` aloud in plain words if they matter (NTFS
  case renames, iCloud placeholders, Photos library skipped).
- If `vision_tool` is not built: `sh tools/vision/build.sh` (macOS, needs Xcode
  command line tools). Without it, similarity uses hashes and EXIF only.
- If the user has a config (`~/.config/photo-archive-organizer/config.json`)
  it is picked up automatically. Turkish users usually want `"language": "tr"`;
  ask once, then remember. See `config.example.json` for every option.
- Paths run from this skill's directory; quote paths (they contain spaces and
  Turkish characters).

## Workflows

Pick the one that matches the request. Details, edge cases and report
templates are in `references/workflows.md` — read the relevant section before
running a workflow for the first time in a session.

| User wants | Commands |
|---|---|
| What is on SOURCE that REFERENCE lacks; pull it out | `compare REF SRC` → report → `extract PLAN --dest DIR --apply` |
| Year/month layout + standard names inside a folder | `standardize ROOT` → report → `apply PLAN` |
| Other versions of pictures that already exist | `similar TARGET --reference REF` → report → `apply PLAN` |
| Fold an organized folder into another | `merge SRC DEST` → report → `apply PLAN` |
| Clean `Duplicates/` / `Similar/` | `verify-aside ROOT` → ask → `trash PATH --yes` |
| Broken pictures | `check ROOT` → `recover ROOT --apply` |
| Are two backups the same? | `mirror-check A B [--deep]` |
| Whose photos are these? | `devices ROOT` → ask the user which device is whose |
| Folder name differs only in case (MOM → Mom) | `case-rename PATH NewName --apply` |

The usual order for an unknown dump (old phone, laptop copy, "X-E" backup):
`compare` against the organized archive → `extract` missing files into a
side folder → `standardize` that side folder → `similar` against the archive →
user trashes `Similar/` → `merge` into the archive → `mirror-check` with the
second backup disk.

## The standard layout

```
<Person>/
  Photos/YYYY/YYYY-MM/YYYYMMDD_HHMMSS_ab12.jpg     capture date from metadata
  Photos/YYYY/YYYY-MM/YYYYMMDD_ab12cd.jpg          only the day is known (name)
  Photos/YYYY/YYYY-MM/YYYYMM_ab12cd.jpg            only the month is known (folder)
  Photos/YYYY/Screenshots/...                      screenshots and documents
  Photos/YYYY/Undated/YYYY_ab12cd.jpg              only the year is known
  Photos/Undated/undated_ab12cd.jpg                no date at all
  Videos/... same pattern
  Data/                                            documents, programs, other files
  Logs/                                            operation logs
```
Turkish names: Foto, Video, Tarihsiz, Ekran Goruntuleri, Data, Kayitlar, Cop,
Benzerler, Bozuk, Kurtarilan. The hash is the start of the file's SHA-256, so
names are stable and unique. Typed names ("Diploma.jpg", "Lise Arkadaşları.JPG")
are kept. Sidecars (.aae .xmp .thm .moi) take their main file's new name. Albums
listed in the config stay untouched. Full rules: `references/standard.md`.

## Deciding things the tools cannot

These come up again and again; the defaults below match what careful users
chose, but they are the user's decisions — ask when unsure.
`references/decisions.md` has the reasoning and more cases.

- **Folder date vs. EXIF date** disagree (folder `21_12_2012`, EXIF 2011): if two
  different devices agree, trust EXIF; tell the user.
- **Impossible dates** (0000, 2097): ignored, file treated as undated.
- **RAW files with a JPEG twin**: kept by default (`raw_policy: keep`); offer
  removal when the user says JPEGs are enough.
- **Orphan .AAE/.XMP** (their photo is gone): useless edit notes; list them, the
  user decides.
- **Rotated copies**: lossless rotation changes the hash but not EXIF identity;
  `similar` catches them via capture moment or rotation-aware Vision.
- **Same name, different content** while merging: never overwrite; a dated
  suffix is added. Tell the user which files got it.
- **Another person's files** in a dump: extract to a separate folder first,
  run `devices`, and ask whose devices they are before merging.

## Reporting

After every step give a short report: what was checked, the counts (with the
equation), where things went, what is waiting for the user's decision. Use a
small table for distributions. Mention the log file. Give time estimates before
long runs (hashing an HDD: ~80–120 MB/s; Vision: ~10–20 pictures/s) and answer
"ne durumda?" with the current phase and rough remaining time.

When a session ends mid-work, write what is done and what is open to the
user's notes/memory so the next session can continue ("nerede kaldık?").

## Filesystem notes

`env` tells you which apply; the essentials:
- **NTFS (Paragon/Tuxera/macFUSE)**: walk with listdir (the scripts do);
  case-only renames via a temporary name (`case-rename`); Finder may refuse to
  empty the Trash ("in use") — emptying the volume's `.Trashes` by hand is only
  done when the user asks.
- **Unicode**: macOS/NTFS may store names decomposed (NFD). Compare names after
  NFC normalization (the scripts do) — "Düğün" may otherwise not match.
- **Local disk**: never enter `*.photoslibrary`; iCloud placeholders are not on
  disk; Desktop/Documents may need a permission prompt.
More in `references/filesystems.md`.

## Files in this skill

- `scripts/pao.py` — the command line (run `-h` on any command)
- `scripts/pao/*.py` — compare, standardize, similar, merge, recover, env
- `tools/vision/` — Swift source + build script for the Vision helper
- `references/workflows.md` — step-by-step playbooks and report templates
- `references/standard.md` — naming and layout rules in full
- `references/decisions.md` — judgment calls and their reasons
- `references/filesystems.md` — NTFS / exFAT / APFS / network / iCloud details
- `config.example.json` — all options with comments
- `tests/` — synthetic-image test suite (`python3 -m unittest discover tests`)
