# m4a → FLAC Converter

Recursively finds all `.m4a` files in a folder and converts them to lossless `.flac`, placing every output file flat in a single output directory.

## Requirements

- Python 3.6+
- [ffmpeg](https://ffmpeg.org/download.html) installed and available on your `PATH`

## Usage

```bash
python convert_m4a_to_flac.py <source_dir> <output_dir>
```

**Example:**

```bash
python convert_m4a_to_flac.py "C:\Music" "C:\Music-FLAC"
```

## Options

| Flag | Description |
|---|---|
| `--delete-source` | Delete each `.m4a` file after successful conversion |
| `--dry-run` | Preview what would happen without converting anything |

**Examples:**

```bash
# Preview only
python convert_m4a_to_flac.py "C:\Music" "C:\Music-FLAC" --dry-run

# Convert and delete originals
python convert_m4a_to_flac.py "C:\Music" "C:\Music-FLAC" --delete-source
```

## Behaviour

- Searches `source_dir` **recursively** for `.m4a` files
- All `.flac` files are written **flat** into `output_dir` (no subfolders)
- Files with the same name are **overwritten**
- Leading track number prefixes are stripped from output filenames:
  `01 - Songname.m4a` → `Songname.flac`
- Audio is converted **losslessly** using the FLAC codec at compression level 8
- All metadata tags are copied from the source file
