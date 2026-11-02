# The standard layout and naming rules

## Folders

| key | English | Turkish | holds |
|---|---|---|---|
| photos | Photos | Foto | pictures and RAW files |
| videos | Videos | Video | videos (+ .thm/.moi sidecars) |
| undated | Undated | Tarihsiz | no usable date |
| screenshots | Screenshots | Ekran Goruntuleri | screenshots, scanned documents (per year) |
| data | Data | Data | documents, archives, programs, anything not media |
| logs | Logs | Kayitlar | Operations-Log.csv / Islem-Kaydi.csv and older logs |
| duplicates | Duplicates | Cop | byte-identical extra copies (keep old relative path) |
| similar | Similar | Benzerler | other versions set aside by `similar` |
| corrupt | Corrupt | Bozuk | files that do not decode |
| recovered | Recovered | Kurtarilan | rebuilt pictures |
| missing | Missing | Olmayanlar | default extract destination suffix |

Year folders contain only `YYYY-MM`, `Screenshots` and `Undated` (plus any
album or category folder the user protects through `albums`).
Folder and log names use initial capitals only (Foto, Kayitlar, Tasima-Kaydi.csv).

## Dates, in order of trust

Photos: `DateTimeOriginal` → (RAW only) `CreateDate` → date in the file name
(`2012-05-18 15.22.35`, `IMG_20190514_154753`, `20171215_133054`) → year/month in
a folder name (`2011`, `2011-03-05 Alps`) → undated.

Videos: `CreationDate` (Apple, local with zone) → `ContentCreateDate` →
`DateTimeOriginal` → `CreateDate` → `MediaCreateDate`. For JVC `.MOD` files the
date comes from the matching `.MOI`.

`CreateDate` in QuickTime files is UTC by specification but local time on many
cameras; it is used as written unless `quicktime_utc` is true. An existing name
that differs from the computed one only by whole hours is kept (time-zone
handling of an earlier run), so re-running never churns names.

Rejected: years before `min_year` (1950) or after next year, month 0/13,
`0000:00:00`. Such files count as undated and the report says why.

## Names

| known | name | folder |
|---|---|---|
| full moment | `YYYYMMDD_HHMMSS_<sha4>.ext` | `YYYY/YYYY-MM` |
| day (from name) | `YYYYMMDD_<sha6>.ext` | `YYYY/YYYY-MM` |
| month (from folder) | `YYYYMM_<sha6>.ext` | `YYYY/YYYY-MM` |
| year (from folder) | `YYYY_<sha6>.ext` | `YYYY/Undated` |
| nothing | `undated_<sha6>.ext` (TR `tarihsiz_`) | `Photos/Undated` |

- `<sha4>` is the start of the file's SHA-256; on a clash the next 2 characters
  are added. Extensions are lower-case.
- Typed names are kept (`Diploma.jpg`, `Start Deutsch 1 Zeugnis.jpg`); camera and
  generic names are replaced (IMG_1234, DSC09595, uuid names, Fotoğraf0832,
  "vural 030", WhatsApp/iCloud copies, " (1)" / " kopya" suffixes). Add patterns
  with `generic_name_patterns`.
- Sidecars take the main file's new stem: `.aae .xmp .thm .moi .pgi .lrv`.
- Documents keep their names in `Data/`; a clash gets `_<sha4>`.

## Screenshots

A PNG without camera model in a typical screen resolution, or a name containing
"Screenshot"/"Ekran Resmi"/"Bildschirmfoto", goes to `YYYY/Screenshots/` when
`separate_screenshots` is true. A file that already sits in the right year's
Screenshots or month folder keeps that placement: earlier classifications
(by a person or by Vision text/face checks) are respected.

## Idempotency

Running `standardize` on an organized folder must give (almost) zero moves. Files
already named `<date>_<hash>` in the standard folders are trusted without
re-reading them (`trust_existing_names`), which makes re-runs fast.
