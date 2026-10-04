# Open Source Location Data Visualizer

### Development Transparency
This application was developed with AI assistance and has undergone human review and testing. The program itself does not use AI. As with any AI-assisted software, additional scrutiny and verification are recommended before critical use.

---

A standalone desktop application for **quick triage and initial visualization** of location data. This tool converts data containing cell site/sector, distance from cell site, and location point information into paired KML and GeoJSON files for preliminary analysis.

⚠️ **IMPORTANT: This is for initial review only. All findings must be analyzed and verified.**

<a href="https://github.com/btc-git/OS-LOC-DAT-VIZ/releases/latest/download/OS-LocationDataVisualizer.exe" style="text-decoration:none;font-weight:bold;font-size:1.1em;">
⬇️ Download the latest stable OS-LocationDataVisualizer.exe
</a>
<br>

Development preview builds are marked **Pre-release** on the
[GitHub Releases page](https://github.com/btc-git/OS-LOC-DAT-VIZ/releases).
They do not replace the stable download above.

## Features

### 🎯 **Data Type Support**

- **Cell Site/Sector Data**: Creates directional wedges with azimuth (does not depict coverage)
- **Distance from Cell Site Data**: Generates distance-based band visualization with configurable inner/outer band thickness
- **Location Point Data**: Displays points with accuracy radius circles

### 🎨 **Customizable Visualization**

- Adjustable sector width, leg length, and shaded area length
- Configurable distance band (inner/outer) for Distance from Cell Site data
- Color-coded data types with customizable colors
- Static reference-site dots with a selectable color and a configurable nearby-CSL radius
- Unlimited static markers with individual colors, map labels, and details
- Configurable unit support (Meters, Feet, Miles, Kilometers)
- Time animation support for chronological display

### **Output & Interoperability**

- Paired KML and GeoJSON exports with matching event and dataset metadata
- Independently toggleable, untimed reference-cell-site record set for cell-site-based outputs
- Separate static Markers record set with whole-set and individual marker controls
- KML output for Google Earth Pro and compatible GIS software
- GeoJSON output optimized for GeoLibre/MapLibre workflows
- Included [GeoLibre viewer plugin](GeoLibre-Plugin/README.md) for filtering, timeline playback, labels, and event details
- Direct **Process**, **Process and Open in Viewer**, and **Open Viewer** actions using the included GeoLibre Desktop 3.0.0 portable viewer
- Same-named TXT generation log with source/output hashes, settings, row outcomes, and warnings

### 🖥️ **User-Friendly Interface**

- Drag-and-drop CSV, XLS, and XLSX input
- Built-in sample XLSX templates for proper formatting
- Manual marker entry plus CSV/XLS/XLSX marker-list drag and drop
- Automatic column-mapping wizard for files that do not match a standard template
- Optional separate cell site list joined by mapped site/node and sector/cell IDs as the authoritative cell-site-coordinate source
- Optional inclusive date/time range filtering during import
- Named timezone and fixed UTC-offset handling
- Human-readable TXT generation log with hashes, settings, row outcomes, and warnings

## Application Screenshot

<div align="center">
  <img src="screenshot.PNG" alt="Application Interface" width="350">
</div>

## How to Use

1. Drag and drop a CSV or Excel file into the program, or use the Browse for File button.
2. A file using the application’s standard template headers is recognized automatically.
3. For other files, the column-mapping wizard opens automatically. Select the worksheet and header row, choose the record type, review the suggested mappings, and optionally limit the import to an inclusive date/time range.
4. Review the timezone, slash/dash date order, units, and visualization settings. Optionally add or import current-record-set markers on the **Markers** tab.
5. Click **Process** to create the KML, GeoJSON, and TXT generation log, or **Process and Open in Viewer** to create them and immediately open the GeoJSON in the included viewer. Use **Open Viewer** to review existing KML or GeoJSON files without generating new outputs.
6. Review warnings and row outcomes in the TXT log. All visualizations remain preliminary and require independent expert review.

Each generation writes a `.kml`, `.geojson`, and `.txt` file with the same base name. The log records source and output SHA-256 hashes, import mappings, timestamp interpretation, visualization settings, row outcomes, and warnings without copying source-record contents.

**Process and Open in Viewer** also creates a same-named `.geolibre` companion beside the outputs. This small viewer project does not duplicate the source records: it references the GeoJSON and stores its path, display name, dataset identifier, map extent, and viewer/plugin settings so GeoLibre can reopen it with the OS-LOC interface and frame its events automatically. Keep the `.geolibre` file with its GeoJSON; moving or renaming the GeoJSON can break the reference. The project may be deleted without affecting the KML, GeoJSON, or TXT files if convenient reopening is not needed. **Open Viewer** starts a clean, plugin-enabled session. Use the prominent **Load GeoJSON** button beneath the viewer-panel title for previous OS-LOC exports; repeat it to add more record sets. KML files remain available through GeoLibre drag and drop. On first use, the application verifies and extracts its pinned GeoLibre portable bundle and installs the included OS-LOC viewer plugin in GeoLibre's per-user plugin directory. Because GeoLibre enforces one running instance per Windows session, close any other GeoLibre window before starting the included viewer.

For original carrier records that do not match a template, the import wizard opens automatically. It supports CSV, XLS, and XLSX files; worksheet and header-row selection; record-type selection; explicit column mapping; and optional inclusive date/time range filtering. Date selections include the complete start and end days by default; select **Use exact times** for narrower boundaries. **Check Matching Rows** reports both timestamp matches and rows with valid mapped coordinates before import. The filter uses the selected display timezone when one is chosen; **No Change** keeps filtering in the source timezone. Boundaries and source records are converted to UTC for comparison. Timestamps that cannot be parsed or uniquely resolved are excluded, and all filter counts and boundaries are recorded in the TXT generation log. Its live preview shows the first 25 source rows with each original column header and the application field currently mapped to it. Azimuth may be left unmapped when it is unavailable; the application will use a 360-degree visualization. Imported records are normalized in memory and the original file is not modified.

Cell Site/Sector and Distance from Cell Site imports can optionally use a separate cell site list. Enable **Use a separate cell site list**, drop or browse to the CSL, select its worksheet and header row, then map a two-part lookup: the original record's site/node ID and sector/cell ID to the corresponding CSL columns. Map CSL cell site latitude, cell site longitude, and optionally sector azimuth. While enabled, the corresponding original-record mappings are disabled and ignored; timestamp, lookup IDs, and Distance from cell site still come from the original records. An unmatched lookup leaves the cell site fields blank. Repeated lookup keys with equivalent mapped cell site values are collapsed automatically. Conflicting duplicates stop the import only when the original records reference that key; the message identifies its site/node ID, sector/cell ID, CSL rows, and differing mapped fields. The TXT generation log records the CSL filename and hash, mappings, source policy, duplicate counts, and match outcomes without recording lookup-key values.

Cell-site-based outputs also contain a separate **Reference Cell Sites** record set that can be toggled independently. Without a CSL, it contains each unique cell site coordinate used by the records. With a CSL, it contains the used cell sites plus unique CSL cell sites within the configured radius of any used cell site; the default radius is 25 miles. Sectors sharing one coordinate are combined into one dot. Reference dots show every contributing CSL spreadsheet row, the mapped site ID when available, and the source coordinates. If no CSL is used, they show the contributing original-record rows instead. They use the color selected under **Reference Cell Site Dots** and remain visible during timeline playback and date filtering.

The **Markers** tab accepts unlimited manual points or a dropped/browsed CSV, XLS, or XLSX marker list. Each valid row needs `Label`, `Latitude`, `Longitude`, and `Color`; colors may be familiar names such as `red`, `green`, `yellow`, `orange`, `blue`, `purple`, or `black`, or a `#RRGGBB` value. Invalid imported rows are skipped with row-specific status warnings. Markers are exported as a separate untimed record set, remain visible during timeline playback, and provide both whole-set and individual controls in GeoLibre. An enabled marker always shows its label, and its details include the label and source coordinates. Markers belong only to the current source record set: selecting or importing another source clears them, and they are not retained between application sessions.

A small note at the top of Settings and Colors reminds you to hover over labels
for more information. Hover over those labels to see their tooltips.
**Nearby Cell Site Radius (miles)** applies only when using a separate cell
site list: it selects nearby static reference dots, not coverage or event
geometry. Without a CSL, the radius has no effect.

### Data Format Reference

**For Cell Site/Sector Data:**
- `Timestamp`, `Latitude`, `Longitude`, `Azimuth`

**For Distance from Cell Site Data:**
- `Timestamp`, `Latitude`, `Longitude`, `Azimuth`, `Distance`

**For Location Point Data:**
- `Timestamp`, `Latitude`, `Longitude`, `Accuracy` (optional)

**For Marker Lists:**
- `Label`, `Latitude`, `Longitude`, `Color`

The templates use one combined `Timestamp` column, which is recommended. Input files may instead use separate `Date` and `Time` columns, including common variants such as `Conn. Date` and `Conn. Time (UTC)`. Common combined fields such as `Start DateTime`, `StartTime`, `Record Open Date/Time`, and `Msg Send Date` are also recognized.

### Supported Timestamp Formats

The application supports **18+ timestamp formats**, including:

**Common Formats:**
- ISO: `2025-01-15T14:30:00`, `2025-01-15 14:30`, `2025/02/11 11:06:07`
- US (4-digit year): `01/15/2025 2:30 PM`, `01/15/2025 2:30`, `08/01/2015 22:14:13`
- US (2-digit year): `07/30/24 13:00:20` (auto-converts: 00–30 → 2000–2030, 31–99 → 1931–1999)
- European: `15.01.2025 14:30:00`, `15.01.2025 14:30`
- Time-only: `14:30:00`, `2:30 PM` (uses today's date)

**Advanced Formats:**
- Excel serial dates: `45696.7637037037`
- With timezone: `2025-02-11 11:06:07.557 EST`, `2019/05/03 18:36:04 (GMT -4)`, `2025-01-15T14:30:00Z` (converted to UTC for KML)
- Without timezone: Uses the selected source timezone, either a named timezone or a fixed UTC offset (UTC by default); an explicit offset in a record takes precedence
- Fixed offsets are shown with familiar North American abbreviations where useful; the numeric UTC offset is authoritative because abbreviations can be ambiguous
- Slash or dash dates use the selected Month-Day-Year or Day-Month-Year order; year-first dates use Year-Month-Day unless Year-Day-Month is selected. Review the wizard's suggested date order before import
- Named timezones apply historical daylight-saving rules. When a local time happens twice or is skipped during a clock change, usable location information is kept without a date/time in both KML and GeoJSON. The app reports source-row numbers rather than guessing a time; an explicit UTC offset can resolve the uncertainty
- Fractional seconds in text timestamps are discarded. Time-only entries use today's date; verify that this matches the source records before use

**Missing-data outcomes:** Missing azimuth uses a 360-degree visualization; missing distance omits the distance band; missing Location Point accuracy uses the configured default (initially 0). With a zero default, missing accuracy produces a visible point without an accuracy circle in both KML and GeoJSON. Supplied zero accuracy also produces a point without a circle: zero means unknown accuracy, not an exact location. Positive supplied accuracy still produces a circle; a positive configured default is a visualization assumption, not measured accuracy. Invalid accuracy produces a point without an accuracy circle. These defaults and omissions are summarized in warnings and the TXT log and must be independently verified. Exported records remain initially hidden until enabled in the viewer.

**Missing or unreadable dates and times:** All record types retain usable location information when the date/time is missing, unreadable, or uncertain. These records are labeled `date/time unavailable` and have no timeline time. Warnings and the TXT log count records exported without timeline metadata, including a separate count for daylight-saving conflicts. Timestamp mapping is optional when no import date/time filter is enabled; for separate columns, map both Date and Time or leave both unmapped. An active import date/time range requires timestamp mapping and excludes records with unresolved times because the app cannot confirm that they fall within the selected range. Invalid coordinates are still skipped.

---

## Open Source & Contributing

This is an open source project. Found a bug or have a suggestion? [Open an issue or suggest a feature here.](https://github.com/btc-git/OS-LOC-DAT-VIZ/issues)


## Installation & Distribution

### For End Users

Download the standalone executable `OS-LocationDataVisualizer.exe` - no Python installation required.

### For Developers

**Source Development Requirements:**

- Python 3.11+
- Node.js for the GeoLibre plugin contract test

Reproducible Windows release builds require Python 3.11.3 and the complete
`requirements-build.txt` lock. See `requirements.txt` for runtime versions and
`THIRD_PARTY_NOTICES.md` for the dependency inventory.

**Setup & Installation:**

1. Clone the repository
2. Install dependencies:
   ```bash
   python -m pip install -r requirements.txt
   ```
3. Run from source:
   ```bash
   python app.py
   ```

**Run Tests:**

```bash
python -m unittest discover -s tests -v
node tests/test_plugin_simplified_chrome.mjs
node --check tools/plugin_performance_harness.mjs
```

**Building the Executable:**

1. Use Python 3.11.3.
2. Install the complete pinned build environment:
   ```bash
   python -m pip install -r requirements-build.txt
   ```
3. Build the executable:
   ```bash
   python -m PyInstaller --clean app.spec
   ```
4. Find the executable in the `dist/` directory (the file will be named `OS-LocationDataVisualizer.exe`)

Always build through `app.spec`; it packages the icon, version metadata,
timezone and XLS support, bundled GeoLibre viewer and plugin, and license files.

## Privacy & Security

Location-data processing and export run locally; the application does not upload source or output files. Marker entry is coordinate-only: the application does not send addresses to an online geocoding service. Generated KML, GeoJSON, TXT, and GeoLibre project files can contain sensitive information and should be handled together. The GeoLibre project does not duplicate source records, but it contains the GeoJSON's absolute path, dataset name or identifier, and map extent. The included viewer loads its default basemap from OpenFreeMap, which requires a network connection and discloses ordinary tile-request metadata such as IP address and viewed map area to that service. Opening project links or exported files in other applications is subject to those applications' behavior.

## Troubleshooting

- **Slow KML viewing:** Try the paired GeoJSON in the included GeoLibre viewer using **Process and Open in Viewer**, or **Open Viewer** followed by **Load GeoJSON**. GeoJSON is optimized for this viewer workflow and may provide smoother interaction; performance still depends on dataset size, geometry, and hardware. Limit the imported date/time range or process smaller subsets if generation or viewing remains slow.
- **Data loaded but nothing visible:** GeoLibre starts records hidden. Enable individual events or use **Show All** for the record set, check any active **From/Through** filter, then use **Focus Set**. Reference-site dots and markers have separate controls.
- **Viewer will not start:** Close other GeoLibre windows before starting the included viewer; only one instance can run per Windows session. Review the status console or error dialog for remaining launch problems.
- **Missing records or unexpected times:** Review source/display timezones, date order, timestamp mappings, coordinates, cell-site-list matches, and import filters. Check summarized warnings and TXT-log row outcomes. All record types retain usable locations without a date/time when timestamps are missing, unreadable, or uncertain, including daylight-saving conflicts. Active import date/time filters exclude these records because their times cannot be confirmed as matching the range.

Processing and export are local. External viewers, map services, and opened links have their own network and privacy behavior; do not assume they are offline.

## Important Disclaimers

At startup, the main program window appears behind the **Important Disclaimers & Usage Information** dialog. Click **Close** or the dialog's window close button to dismiss the information and use the program. The dialog appears on every startup and can be reopened with the information button.

- **This tool is in continuous development and may contain errors.**
- **This tool is designed for quick preliminary review and visualization. All outputs require verification.**
- **NO COVERAGE ESTIMATIONS**: All shaded areas, wedges, and circles are visual representations only - NOT coverage depictions
- Distance from cell site measurements, sector areas, and location accuracy should all be independently validated
- This tool does not replace professional forensic analysis or expert work

## Sample Data Templates

The application includes built-in templates for each source data type plus marker lists. Click the "📁 Templates" button in the application to download properly formatted XLSX files with sample data and correct column headers.

---
## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

---
Copyright (c) 2025-2026 CrimLawTech LLC
**Version 2.0.0-beta.1**
_Open Source Location Data Visualization Tool_
