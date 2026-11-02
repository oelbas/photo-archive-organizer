# Changelog

## 0.1.0 — 2026-11-02
First public version.
- compare / extract with count check, same-volume move or cross-volume copy+verify
- standardize: year/month layout, date sources (EXIF, ContentCreateDate, file and
  folder names), typed names kept, sidecars, screenshots, albums, idempotent re-runs,
  respect for earlier classifications, time-zone tolerant names
- similar: scan-data, EXIF identity, rotation-aware Vision, RAW policy, review list
- merge with collision handling, verify-aside, Finder trash
- check / recover damaged JPEGs (segment-chain rebuild)
- env (NTFS/exFAT/APFS/network, iCloud placeholders, Photos libraries), mirror-check,
  devices, case-rename
- English and Turkish folder names; synthetic-image test suite
