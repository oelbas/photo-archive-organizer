# Workflows

Contents
1. Compare and extract (X vs X-E backups)
2. Standardize a folder
3. Set aside similar versions
4. Clean Duplicates / Similar
5. Merge into the archive
6. Check and recover broken pictures
7. Verify a second backup
8. Split by owner / device
9. Session hand-off

All commands: `python3 scripts/pao.py [--config FILE] [--lang tr] <command> ...`
Plans are saved under `~/.cache/photo-archive-organizer/plans/` unless `--out`
is given. Read the plan summary to the user before applying.

---

## 1. Compare and extract

**When:** "SOURCE'ta olup REFERENCE'ta olmayanları ayrı klasöre çıkar", a phone
dump vs. the organized folder, a desktop copy vs. the disk.

```bash
pao.py compare "<REFERENCE organized>" "<SOURCE dump>"          # read-only
pao.py extract <plan.json> --dest "<disk root>/<Source>-Missing"   # dry run
pao.py extract <plan.json> --dest "..." --apply
```
- Names are ignored; only content counts (size → head/tail fingerprint → SHA-256).
- Same volume: files are **moved** (instant, no extra space). The user usually
  wants them gone from the source ("kendi klasöründe kalmasın"). Use `--copy`
  only if they want the source untouched.
- Other volume: **copied and verified**; the source stays. Ask about removing it
  later.
- Put the destination where the user said (disk root vs. inside a folder);
  keep relative paths so the origin (Acer/, Iphone8/ ...) stays visible.

Report template:
```
Total in SOURCE: 18,835
  identical copy exists in REFERENCE: 17,175  (left in place)
  not in REFERENCE → moved to <dest>:  1,637  (24.8 GB)
  system files / empty (left):            23
Equation holds: 17,175 + 1,637 + 23 = 18,835
Where they come from: table by top folder and by file type
Log: <dest>/Logs/Operations-Log.csv
```
Then point out obvious patterns (e.g. "908 CR2 = two identical sets of 454",
"AAE edit notes without photos") and offer the next steps.

## 2. Standardize a folder

**When:** "yıl ay düzenine sok", "standartlarımıza göre düzenle", after an extract.

```bash
pao.py standardize "<root>"          # plan; nothing changes
pao.py apply <plan.json>
```
Before applying, tell the user:
- how many files move, how many are already in place (re-running on an
  organized folder should give ~0 moves),
- distribution per year/Undated/Data/Duplicates,
- anything odd: impossible dates ignored, folder/EXIF conflicts, orphan sidecars,
  typed names kept.

Albums (wedding, trips the user wants intact) go into the config `albums` list
first. Exact duplicates inside the folder go to `Duplicates/<old path>`; their
pair is in the log.

## 3. Set aside similar versions

**When:** after extracting a dump, the files are "not byte-identical" but may be
rotated / resized / WhatsApp / iCloud copies of archive pictures.

```bash
pao.py similar "<side folder>" --reference "<archive person folder>"
pao.py apply <plan.json>      # moves them into <side folder>/Similar/<path>
```
- Evidence order: `scan` (same pixels, metadata differs) > `exif` (same capture
  moment + camera, compatible dimensions) > `vision` (≤ similar_threshold) >
  `raw` (RAW with JPEG twin; moved only when raw_policy = similar).
- `review` entries are never moved: list them with distances, the user decides.
- To find versions *inside* one folder, pass the folder itself as reference.
- Vision matches on small images (< vision_min_side px) are review-only.
- Undated rotated copies can slip through; say so when reporting.

## 4. Clean Duplicates / Similar

```bash
pao.py verify-aside "<root>"         # every file's pair must still exist
pao.py trash "<root>/Duplicates" --yes   # only after the user says so
```
If anything is reported missing, do not trash; explain which pair vanished.
Files the user already deleted themselves are fine — mention them.

## 5. Merge into the archive

**When:** the side folder is standardized and cleaned; "ilgili yerlere taşı".

```bash
pao.py merge "<side folder>" "<archive person folder>"
pao.py apply <plan.json>
```
- Identical file already at the destination → not moved, listed as duplicate.
- Same name, different content → dated suffix, never overwrite. Tell the user.
- The side folder's logs move to the archive's log folder with a prefix.
- Afterwards suggest `mirror-check` against the second backup.

## 6. Check and recover broken pictures

```bash
pao.py check "<root>"                         # corrupt + partly gray
pao.py recover "<root>"                       # dry run on the corrupt list
pao.py recover "<root>" --apply               # writes <root>/Recovered/<path>
```
- Recovered files are new files; originals are untouched. The user confirms
  they open, then the originals can be moved to `Corrupt/` (TR `Bozuk/`).
- Unrecoverable files: keep them in `Corrupt/` with the note that other tools
  (PhotoRec, specialised JPEG repair) may help later.
- Partly gray pictures (truncated) are listed, not "fixed".

## 7. Verify a second backup

```bash
pao.py mirror-check "<disk A>/<Person>" "<disk B>/<Person>"         # paths + sizes
pao.py mirror-check ... --deep                                       # + SHA-256 (slow)
```
Differences in log files only are normal; say so.

## 8. Split by owner / device

```bash
pao.py devices "<folder>"
```
Show models with counts, years and source folders; ask the user whose each
device is, write the answer into `device_owners` in the config, then move the
chosen groups (compare/extract or merge into the owner's folder). Never guess
ownership from faces or content.

## 9. Session hand-off

When the user unplugs a disk or stops: record in the user's notes/memory
- which disk/folder, what was done (counts), where logs are,
- what is waiting for a decision,
- the exact next command.
Start the next session by re-running `env` and reading that note.
