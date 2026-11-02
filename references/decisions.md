# Judgment calls

These are the situations where a careful person had to decide. Defaults are
what worked; always tell the user what was decided and why.

## "Is this really the same picture?"

| evidence | meaning | action |
|---|---|---|
| same SHA-256 | the same file | duplicate → `Duplicates/` |
| same JPEG scan data | same pixels, metadata differs (rotation tag, EXIF edit) | similar |
| same capture second + sub-second + model (+serial/file number), compatible dimensions | same shot, re-saved/rotated | similar |
| Vision ≤ 0.15, both images ≥ 500 px | looks the same | similar |
| Vision 0.15–0.25 | maybe | list for the user, never move |
| same second, no sub-second, different dimensions | burst or edit | review |

Lossless rotation (jpegtran, Photos) changes the bytes but keeps EXIF identity;
Vision is not rotation-invariant, so `pao-vision` also compares 90/180/270°.

When keeping one of several versions, keep the one already in the organized
archive; inside one folder keep the largest image.

## Folder name vs. metadata

- Two independent devices give the same EXIF date → EXIF wins (e.g. folder
  `21_12_2012`, JVC camera and iPhone both say 2011-12).
- Camera clock obviously wrong (2097, 0000, 1970 on a 2015 phone) → undated; if
  the folder name gives a year, use it as an estimate (`YYYY_hash`).
- Video `CreateDate` may be the end of recording or the export time; prefer
  `CreationDate`/`ContentCreateDate`.

## File types

- **RAW + JPEG**: default keep. Many users decide "JPEGs are enough" for
  events shot in RAW+JPEG; only then use `raw_policy: similar` and confirm each
  RAW has a JPEG twin by EXIF identity (date + sub-second + file number + serial).
- **AAE** (iPhone edit notes) and **XMP** (Lightroom notes): worthless without
  their photo or RAW. Orphans are listed; delete only on request.
- **THM/MOI/PGI**: camera sidecars; follow the video.
- **DVD folders (VIDEO_TS, VOB)**: keep the folder intact as an album.
- **Live Photo videos**: keep next to the photo's month; same stem when possible.
- **Documents/scans inside photo folders** (CVs, diplomas): to `Data/` or
  Screenshots; keep typed names.

## People

- A dump may contain another person's files (a spouse's CVs, a child's phone). Extract first,
  run `devices`, ask. Documents with a name in them are strong hints; faces are
  never used.
- Device rules belong in `device_owners` ("iPhone 11 → Anna"), but the user can
  override them per batch; follow the latest instruction.

## Deleting

- Exact duplicates whose pair is verified → may be trashed after the user agrees.
- Similar versions → trashed only after the user saw the counts/evidence.
- Emptying the Trash is the user's act. If the user explicitly asks you to empty
  it and Finder fails with "in use" on an external volume, the volume's
  `.Trashes/<uid>` content can be removed — say clearly that this is permanent.
- Never remove a source on another volume as part of a copy.

## Names

- Case-only renames on NTFS/APFS need a temporary name.
- Two documents with the same name and different content: keep both; the
  incoming one gets ` (YYYY-MM-DD)`.
