# Tennessee Coordinate Converter

Tennessee Coordinate Converter is a desktop and command-line application for
converting between coordinate systems commonly used in Tennessee. Carter
coordinates are one supported format alongside geographic, Tennessee State
Plane, and UTM coordinates.

The project is being prepared as an open-source repository at
[alwunder/tn-coordinate-converter](https://github.com/alwunder/tn-coordinate-converter).

## Features

- Convert a single coordinate in the Tkinter desktop interface.
- Batch-convert CSV and JSON files from the desktop interface or command line.
- Convert Carter coordinates to and from NAD27 without an external lookup
  table.
- Read complete or partial legacy Carter quadrant calls and represent the most
  specific supplied subdivision by its center point.
- Transform geographic and projected coordinates with `pyproj`.
- Display converted locations in the NGMDB MapView on supported Windows
  systems.
- Use the standalone Carter conversion module without third-party
  dependencies.

## Supported coordinate formats

| Format | Command-line name | Units |
| --- | --- | --- |
| Carter Coordinates | `CARTER` | U.S. survey feet from section lines |
| Latitude/Longitude (NAD27) | `GEOGRAPHIC_NAD27` | Decimal degrees |
| Latitude/Longitude (NAD83) | `GEOGRAPHIC_NAD83` | Decimal degrees |
| Latitude/Longitude (WGS84) | `GEOGRAPHIC_WGS84` | Decimal degrees |
| Tennessee State Plane, NAD27 | `TNSPC_NAD27` | U.S. survey feet |
| Tennessee State Plane, NAD83 | `TNSPC_NAD83` | Meters |
| Tennessee State Plane, NAD83 | `TNSPC_NAD83_FTUS` | U.S. survey feet |
| UTM Zone 15N, NAD27/NAD83 | `UTM15_NAD27`, `UTM15_NAD83` | Meters |
| UTM Zone 16N, NAD27/NAD83 | `UTM16_NAD27`, `UTM16_NAD83` | Meters |
| UTM Zone 17N, NAD27/NAD83 | `UTM17_NAD27`, `UTM17_NAD83` | Meters |

## Requirements

- Python 3.10 or newer
- Python 3.12 is selected for the reproducible deployment lock and plan
- Tkinter for the desktop interface (included with standard Windows Python
  installations)
- `pyproj` for geographic and projected transformations
- On Windows, `pywebview`, Python.NET, and the Microsoft Edge WebView2 Runtime
  for the optional NGMDB map window

Coordinate conversion works without internet access. The NGMDB map requires
access to `https://ngmdb.usgs.gov`.

## Install from source

Clone the repository and create an isolated environment:

```powershell
git clone https://github.com/alwunder/tn-coordinate-converter.git
Set-Location .\tn-coordinate-converter
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[map]"
```

The `map` extra installs the Windows map-window dependencies. For conversion
without MapView, install with `python -m pip install -e .` instead.

Start the desktop application:

```powershell
tn-coordinate-converter-gui
```

The source file can also be run directly:

```powershell
python .\tn_coord_converter_gui.py
```

## Single conversions

The desktop application contains three tabs:

- **Single Conversion** converts one location at a time.
- **Batch Conversion** processes every record in a CSV or JSON file.
- **About** displays this guide.

For Carter input, provide section, township, range, north-south footage and
reference line, and east-west footage and reference line. For example:

```text
Section:       11
Township:      2S
Range:         47E
N-S Distance:  1750
From N-S Line: FSL
E-W Distance:  1900
From E-W Line: FWL
```

The approximate NAD27 result is:

```text
Latitude:   36.3714736806
Longitude: -85.5935471530
```

Legacy Bulletin 62 quadrant calls are also accepted in place of the four
footage fields. Enter the calls from the smallest subdivision to the largest,
as originally printed. Because a quadrant call identifies an area rather than
an exact well point, the converter uses the center of the most specific
subdivision supplied:

- One call is the largest quadrant.
- Two calls are the middle and largest quadrants.
- Three calls are the smallest, middle, and largest quadrants.

```text
Section:    11
Township:   A
Range:      54E
Quadrants:  NE NE SE
```

After a successful single conversion, **Copy X**, **Copy Y**, and **Copy X,Y**
copy result coordinates to the clipboard. Select **Invert** to change the
combined button to **Copy Y,X**. Longitude is X and latitude is Y.
For a Carter target, the copied X/Y pair is the accompanying Tennessee State
Plane NAD27 coordinate.

Partial Carter coordinates are valid when township and range are known. A
township/range-only record resolves to the center of its 5-minute quadrangle;
adding a section resolves to the center of that section. Outputs set
`carter_complete` to `false` and include `location_method` and `location_note`
so these approximate centers are not mistaken for precisely located points.

For geographic input, enter longitude and latitude in decimal degrees. For a
projected source, enter easting/X and northing/Y in the units listed above.

When Carter coordinates are the target, the result includes the containing
section, township, range, and footage from the nearest section lines.

## Batch conversion

The batch interface and command line accept `.csv` and `.json` inputs. The
output filename extension selects CSV or JSON output. Existing input fields
are retained and converted values are appended.

### Carter CSV

```csv
section,township,range,ns_feet,fsl_fnl,ew_feet,fwl_fel
11,2S,47E,1750,FSL,1900,FWL
15,2S,48E,1500,FSL,1950,FEL
```

Accepted Carter columns include:

| Value | Accepted columns |
| --- | --- |
| Section (optional) | `section` |
| Township | `township` |
| Range | `range` or `range_` |
| N-S footage | `ns_feet` or `north_south_feet` |
| N-S line | `fsl_fnl` or `ns_line` |
| E-W footage | `ew_feet` or `east_west_feet` |
| E-W line | `fwl_fel` or `ew_line` |

For a legacy Carter record, use `quadrants` (also accepted: `quadrant`,
`quarter_calls`, or `quarter_quadrants`) instead of all four footage fields.
Township and range are the minimum fields; section and quadrants may be left
blank for poorly located records.

```csv
section,township,range,quadrants
"",A,54E,""
11,A,54E,""
11,A,54E,SE
11,A,54E,"NE SE"
11,A,54E,"NE NE SE"
```

### Geographic or projected CSV

Geographic input may use `lat` and `lon`, `latitude` and `longitude`,
`y_lat27` and `x_lon27`, or `y_lat83` and `x_lon83`.

```csv
latitude,longitude
36.3714736806,-85.5935471530
```

Projected input may use `x` and `y`, or `easting` and `northing`. Select the
source format explicitly because those column names do not identify a CRS.

```csv
x,y
2119668.814,720797.189
```

### JSON

Coordinate pairs in JSON output consistently place the X-like value before the
Y-like value: `lon` before `lat` for geographic coordinates and `x` before `y`
for projected coordinates.

JSON input may be a list of records:

```json
[
  {
    "section": 11,
    "township": "2S",
    "range": "47E",
    "ns_feet": 1750,
    "fsl_fnl": "FSL",
    "ew_feet": 1900,
    "fwl_fel": "FWL"
  }
]
```

An object containing a `records` list is also accepted.

### Command line

Carter CSV to NAD27 latitude/longitude:

```powershell
tn-coordinate-converter `
  --input .\sample_carter_input.csv `
  --output .\sample_carter_output.csv `
  --source-format CARTER `
  --target-format GEOGRAPHIC_NAD27 `
  --no-gui
```

NAD27 JSON to Carter coordinates:

```powershell
tn-coordinate-converter `
  --input .\sample_latlon_input.json `
  --output .\sample_latlon_output.json `
  --source-format GEOGRAPHIC_NAD27 `
  --target-format CARTER `
  --no-gui
```

Use `--source-format AUTO` when the first record has recognizable Carter or
NAD27 latitude/longitude fields. The target format is always required.

## Use as a Python module

`tn_coord_converter_module.py` contains the Carter/NAD27 calculations and has no
third-party dependencies.

```python
from tn_coord_converter_module import carter_to_nad27, nad27_to_carter

coordinate = carter_to_nad27(
  section=11,
  township="2S",
  range_="47E",
  ns_feet=1750,
  ns_line="FSL",
  ew_feet=1900,
  ew_line="FWL",
)

carter = nad27_to_carter(
  nad27_lat=coordinate.nad27_lat,
  nad27_lon=coordinate.nad27_lon,
)
```

The standalone module uses the Clarke 1866 ellipsoid associated with NAD27
and reports ground distances in U.S. survey feet.

## MapView

After a successful desktop conversion, select **View on map** to open or
update the NGMDB MapView window. Install the `map` extra and verify that the
Microsoft Edge WebView2 Evergreen Runtime is installed if the map does not
open. Conversion remains available when MapView is unavailable.

Map errors are written to the temporary file
`tn_coord_converter_mapview.mapview-error.log`.

## Development

Install development and map dependencies:

```powershell
python -m pip install -e ".[dev,map]"
python -m pytest
python -m ruff check .
```

The repository intentionally excludes generated executables, build output,
IDE settings, caches, and historical source material.

## Deployment planning

The intended deployment workflow is
[alwunder/python-deployment-builder](https://github.com/alwunder/python-deployment-builder):

```powershell
pdbuilder assess .
pdbuilder plan . --online
```

As of August 19, 2026, Python Deployment Builder supports assessment and
planning. Its generation and runtime-validation milestones are not yet
implemented, so these commands prepare deployment evidence and policy but do
not build an end-user installer.

## Project layout

| Path | Purpose |
| --- | --- |
| `tn_coord_converter_gui.py` | Desktop interface, batch processing, and CLI |
| `tn_coord_converter_module.py` | Standalone Carter/NAD27 calculations |
| `tn_coord_converter_version.py` | Release and product metadata |
| `ngmdb_mapview_window.py` | NGMDB MapView integration |
| `tests/` | Automated conversion and CLI tests |
| `sample_carter_input.csv` | Example Carter batch input |
| `sample_carter_quadrant_input.csv` | Example legacy Carter quadrant input |
| `sample_latlon_input.json` | Example NAD27 batch input |

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow and
[SECURITY.md](SECURITY.md) for responsible vulnerability reporting.

## License

This project is dedicated to the public domain under the
[CC0 1.0 Universal license](LICENSE).
