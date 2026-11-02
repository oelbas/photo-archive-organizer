# Filesystems and locations

`pao.py env <path>` reports the family and the quirks below.

## NTFS on macOS (Paragon `ufsd_NTFS`, Tuxera, macFUSE ntfs-3g)
- `os.walk`, `find` (bfs) and `scandir` can report folders as files or miss them.
  All scripts walk with `listdir` + `lstat`.
- Case-insensitive: `MOM → Mom` in Finder silently reverts. Use a temporary
  name (`case-rename`).
- Names may be stored in decomposed Unicode (NFD). Normalize to NFC before
  comparing ("Düğün", "adsız klasör").
- Finder "Empty Trash" can fail with error -8076 ("in use"). The items live in
  `/Volumes/<disk>/.Trashes/<uid>/`.
- A folder can turn into a 0-byte file after an interrupted move or unsafe eject.
  There is nothing to read on macOS; check the disk on Windows (chkdsk) or with
  the driver's repair tool, compare with other backups first.
- Spinning disks: ~80–120 MB/s; hashing 100 GB takes 15–25 minutes.

## exFAT / FAT32
- Case-insensitive, no ownership, 2-second timestamps on FAT.
- `._*` AppleDouble files appear for every file written from a Mac; they are
  system files and are skipped.
- FAT32 cannot hold files > 4 GB (long videos).

## APFS / HFS+ (local or external Mac disks)
- Usually case-insensitive; still use `case-rename`.
- Fast; hashing is CPU-bound.

## Local folders
- Never enter `*.photoslibrary` (Photos.app owns it). Export from Photos instead.
- Desktop/Documents may be iCloud Drive: files flagged dataless are not on disk.
  Reading them triggers a download; they are not "originals here" until
  downloaded. `env --scan` counts them.
- macOS may ask for Desktop/Documents/Downloads permission the first time.
- Check free space before copying (`env` shows it; `extract` refuses when short).

## Network shares (SMB/AFP/NFS)
- Slow and may disconnect: always copy + verify, never rely on rename across
  shares; keep batches small.
- Files on an unmounted share do not count as originals.

## Trash
- `pao.py trash` uses Finder (recoverable). Each volume has its own Trash.
- Batches of 50; on AppleEvent timeout (-1712) items are retried one by one.
