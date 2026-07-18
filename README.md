# CrystalAtlas

CrystalAtlas is a configurable Windows desktop application for collating crystallisation drop images into annotated plate layouts and recording crystal positions.

## Development Note

*CrystalAtlas was conceived, designed, and directed by **Jordon James**. OpenAI's ChatGPT was used as a software development assistant to help generate code, troubleshoot issues, refine features, and improve documentation throughout development. All design decisions, feature selection, testing, validation, and final approval of the software were carried out by the project author. The author accepts full responsibility for the functionality and content of this project.*

## Features

- 24-well, 48-well, 96-well and 384-well plate presets
- Fully custom row, column and drop layouts
- Built-in and user-defined filename parsing presets
- Persistent named filename presets that can be created, updated and deleted
- Automatic grouping of images by plate, well and drop
- High-resolution plate montage generation without cropping source images
- Missing, duplicate and invalid-image reporting
- Interactive Crystal Locator with zoom, pan and crystal notes
- Adjustable crystal marker diameter and colour
- Previous/Next image navigation and keyboard arrow shortcuts
- CSV export of crystal coordinates

## Filename presets

CrystalAtlas uses regular expressions with named groups. A pattern must provide either:

- `plate`, `well`, and `drop`; or
- `plate`, `row`, `column`, and `drop`.

The `plate` group is optional when a default plate name is configured.

Examples:

```text
Plate1_A1_D1.jpg
A1_D1.jpg
```

Custom expressions can be named and saved from the **Filenames** tab.

## Plate formats

The **Grid / Drops** tab includes:

- 24-well: 4 × 6
- 48-well: 6 × 8
- 96-well: 8 × 12
- 384-well: 16 × 24
- Custom

Drop count and arrangement remain independently configurable.

## Running from source

```bash
python CrystalAtlas.py
```

## Building the Windows executable

1. Install Python 3.11 or newer.
2. Download or clone this repository.
3. Double-click `Build_CrystalAtlas_EXE.bat`.
4. Find the executable at `dist/CrystalAtlas.exe`.

## Outputs

Generated plate images are named:

```text
<plate>_CrystalAtlas.png
```

Validation information is written to:

```text
CrystalAtlas_Report.csv
```

Crystal selections are written to:

```text
Crystal_Locations.csv
```

## Licence

Released under the MIT License.
