# Open Source Location Data Visualizer — AI Coding Agent Guide

## Project Overview
Desktop triage tool for converting CSV/Excel location data into Google Earth KML visualizations. **All outputs are preliminary and require expert review.** Users can customize visualizations (sector widths, leg lengths, colors, time animation) and export to Google Earth.

## Architecture & Key Files

**Entry Points & Threading:**
- `app.py`: Creates Qt application, sets Windows taskbar identity (`SetCurrentProcessExplicitAppUserModelID`), creates MainWindow, shows disclaimer
- `main_window.py` (1003 lines): Central GUI hub managing all UI state, settings persistence, file validation, thread orchestration
- `kml_generator.py` (QThread subclass): Background worker thread for KML generation—never blocks UI; emits `progress`, `finished`, `error`, `status_message` signals

**UI & Input:**
- `widgets.py`: Custom `DragDropWidget` frame with drag-enter feedback (`dragActive` property for styling)
- `dialogs.py`: `DisclaimerDialog` (shown on every startup, non-negotiable legal requirement); also references `LicenseDialog` from `license_dialog.py`

## Data Processing Pipeline

1. **File Input** → `handle_file_selection(file_path)`: Loads CSV (pandas) or Excel (openpyxl), reads first row to detect data type
2. **Type Detection** → Column header matching with case-insensitive, flexible name aliases:
   - **Tower/Sector**: Has Latitude, Longitude, Timestamp, Azimuth (NO Distance) → creates sector wedges
   - **Distance from Tower**: Has Latitude, Longitude, Timestamp, Azimuth, Distance → creates sector + distance arc
   - **Location Point**: Has Latitude, Longitude, Timestamp, optionally Accuracy → creates accuracy circles
3. **Validation** → Button disabled if type unclear; shows status messages with emoji indicators (✅, ⚠️, ❌, 📊, 📄)
4. **KML Generation** → Threaded via `KMLGenerator.run()`:
   - Calls type-specific generator (`generate_cell_tower_kml()`, `generate_timing_advance_kml()`, `generate_gps_kml()`)
   - Converts lat/lon to KML (6 decimal places), calculates geographic points via `destination_point()`
   - Wraps visualizations in timestamped folders with optional time animation (`<gx:TimeSpan>`)
5. **Output** → KML string written to file via `on_generation_finished()`; launches Google Earth with result

## Project-Specific Patterns

### Legal & Disclaimers
- **Always** show `DisclaimerDialog` on startup—required by project governance
- All KML documents include preliminary/triage language in descriptions
- License (GPL v3.0) enforced via LICENSE file; project header in all source files

### Missing Data Handling (Never Fail Silently)
- **Missing Azimuth** → Create 360° circle instead of wedge; emit ⚠️ status message with count
- **Missing Distance** → Skip distance visualization for that row; emit ⚠️ status message
- **Missing Accuracy (Location Point)** → Use configurable default (100 meters); emit ⚠️ status message with default value
- All edge cases logged via `status_message` signal to UI console

### Settings Persistence & State
- Settings stored in `QSettings("OpenSource", "LocationDataVisualizer")`
- Configurable per-session: leg length (0.5–20 mi), sector width (30–360°), shaded area length (0.1–10 mi), default accuracy, colors, time animation duration
- Custom KML label field (`custom_label_input`) for user-provided document names

### Status Console & User Feedback
- Use `add_status_message(msg)` for all user-visible feedback (errors, warnings, progress)
- Prefix with emoji: ✅ success, ⚠️ warning, 📊 data type, 📄 file type, 📁 templates
- Messages timestamped and scrollable in status QTextEdit

### UI Theme & Styling
- **Dark theme**: `apply_dark_theme()` sets stylesheet for all widgets (backgrounds #1e1e1e, text #ffffff)
- **Color pickers**: Linked to KML output (leg color, shaded area color, distance/TA color, GPS circle color) via QColorDialog
- **Icons**: Generated programmatically—`create_pushpin_icon()` draws WiFi arcs for taskbar/window; no PNG/ICO files required (except app icon)

### File Handling
- **Always** use `Path` from `pathlib` for cross-platform compatibility (Windows/Unix)
- Drag-drop widget validates `.csv` and `.xlsx` extensions before accepting
- CSV detection via `pd.read_csv()`, Excel via `pd.read_excel(..., engine='openpyxl')`

### Threading & Signals
- KML generation **must** run in `QThread` background worker (not main thread)
- Emit progress (0–100), finished (KML string), error (exception str), status_message (UI updates) via Qt signals
- Main window connects slots: `progress_bar.setValue()`, `on_generation_finished()`, `on_generation_error()`, `add_status_message()`
- Never call UI updates directly from worker thread

### Geographic Calculations
- `destination_point(lat, lon, azimuth_deg, distance_miles)`: Returns new (lat, lon) using spherical haversine math
  - Earth radius: 3960 miles; handles edge case when distance < 1e-9
  - Used for: sector wedge arcs, directional legs, distance circles, accuracy rings
- Azimuths: 0° = North, 90° = East, 180° = South, 270° = West
- Distance conversions handled in `convert_gps_accuracy_to_miles()` and `convert_ta_distance_to_miles()` (Meters/Feet/Miles/Kilometers)

### Timestamp Parsing
- `parse_timestamp_to_kml(timestamp_str)`: Handles 18+ flexible formats (pre-processing + regex patterns)
  - **Supported formats** (all tested and working):
    - **ISO**: `2025-01-15T14:30:00`, `2025-01-15 14:30`, `2025-01-15`, `2025/02/11 11:06:07`
    - **US 4-digit**: `01/15/2025 2:30 PM`, `01/15/2025 2:30`, `01/15/2025`
    - **US 2-digit**: `07/30/24 13:00:20`, `07/30/24 13:00`, `07/30/24` (auto-converts: 00–30 → 2000–2030, 31–99 → 1931–1999)
    - **European**: `15.01.2025 14:30:00`, `15.01.2025 14:30`, `15.01.2025`
    - **Time-only**: `14:30:00`, `2:30 PM` (uses today's date)
    - **Excel serial**: `45696.7637037037` (converts with Excel epoch, handles 1900 leap year bug)
    - **With timezone**: `2019/05/03 18:36:04 (GMT -4)`, `2025-02-11 11:06:07.557 EST` (auto-strips timezone and milliseconds)
  - **Pre-processing steps**:
    1. Try Excel serial conversion first (numeric values 1–50000)
    2. Strip timezone in parentheses `(GMT±X)`, `(UTC±X)` via regex
    3. Strip timezone abbreviations (EST, UTC, GMT, etc.) from end
    4. Strip milliseconds/microseconds (`.557` → removed)
  - **Return value**: Tuple `(KML ISO format YYYY-MM-DDTHH:MM:SSZ, display label)`
  - **Edge cases**:
    - Time-only entries use today's date; display shows only time
    - Unparseable entries return `(None, original_string)` (never fail silently, logged via status_message)
    - 2-digit years auto-convert: ≤30 → 2000–2030, >30 → 1931–1999
    - AM/PM parsing: 12:30 PM → 12:30, 1:30 PM → 13:30, 12:30 AM → 00:30
- Duration-based animation: `create_time_element()` calculates end time by adding `duration_minutes` setting

## Data Type Detection Example
```python
# Tower/Sector: Required columns (case-insensitive, flexible naming)
#   ['Latitude'|'lat', 'Longitude'|'lon'|'long', 'Timestamp'|'Time'|'DateTime', 'Azimuth'|'bearing'|'direction']
#   Generates: Shaded sector wedge, center label, directional legs

# Distance from Tower: Tower/Sector columns PLUS Distance
#   + ['Distance'|'range'|'distance (m)'|'distance (meters)']
#   Generates: Sector + distance arc (combines visualization)
#   Can handle missing azimuth (→ 360° circle) or missing distance (→ wedge only)

# Location Point: Minimal required
#   ['Latitude'|'lat', 'Longitude'|'lon'|'long', 'Timestamp'|'Time'|'DateTime']
#   + optionally ['GPS Accuracy'|'Accuracy'|'accuracy']
#   Generates: Accuracy circle at each point (default 100m if missing)
```

## Build & Test Workflows

**Development:**
```bash
pip install -r requirements.txt
python app.py  # Runs with disclaimer dialog
```

**Build Executable:**
```powershell
# Option 1: Use app.spec (includes icon config)
pyinstaller app.spec

# Option 2: Full command-line
pyinstaller --onefile --windowed --name "OS-LocationDataVisualizer" --icon=wifi_icon.ico --exclude-module=matplotlib --exclude-module=scipy --exclude-module=numba --noupx app.py
```
Output: `dist/OS-LocationDataVisualizer.exe` (self-contained, ~50MB)

**Testing:**
- Use `download_template()` method to generate sample CSV files with proper headers
- Create test files with missing columns/rows to validate error handling
- Verify status messages appear for each edge case (missing azimuth, distance, accuracy)
- Test timestamp parsing with samples from README (ISO, US, European formats)

## Integration Points

**KML Structure:**
- Root: `<Document>` with `<gx:AnimatedUpdate>` for time layer support
- Folders group related placemarks (each timestamp/entry is a folder with circle/wedge + label placemark)
- Coordinate format: `lon,lat,0` (6 decimal places ≈ 0.1m precision)
- Colors: AABBGGRR format (alpha, then BGR); transparency via `4d` prefix (opacity ≈ 30%)
- Time animation: `<gx:TimeSpan><begin>2025-01-15T14:30:00Z</begin><end>2025-01-15T15:00:00Z</end></gx:TimeSpan>`

**Windows Integration:**
- Taskbar grouping: `SetCurrentProcessExplicitAppUserModelID('opensource.locationvisualizer.1.0')`
- Explorer integration: `subprocess.Popen(['explorer', '/select,', file_path])`

**User Workflows:**
1. Click 📁 Templates → select Tower/Sector/Distance/Location Point → CSV file downloads
2. User edits CSV with their data
3. Drag-drop or Browse → app auto-detects type → shows in status console
4. Adjust visualization settings (colors, sector width, leg length) in tabs
5. Click "Generate KML File" → progress bar, background thread → save dialog → opens in Google Earth
6. Status console shows warnings for missing data (⚠️)

## Code Style & Conventions

- **PyQt6 signals/slots**: Use modern syntax `widget.signal.connect(slot_method)`, not SIGNAL()/SLOT()
- **F-strings**: All string formatting (`f"Value: {var}"`)
- **Path handling**: `from pathlib import Path`, use `.suffix`, `.stem`, `/` operator
- **Pandas column access**: Case-insensitive matching via `get_column_value(row, ['Name1', 'name2', 'NAME3'])` utility
- **Settings access**: `self.settings.value(key, default)` and `self.settings.setValue(key, value)`
- **Docstrings**: Include for geographic/math functions; geo functions document Earth radius and units
- **No external assets**: Icons programmatically created (WiFi arcs in `create_pushpin_icon()`); app icon from `wifi_icon.ico`
- **Exception handling**: Emit `error` signal in threads; use `QMessageBox` for user-facing errors in main thread

---

**Last Updated:** November 2025 | Based on v1.0 codebase analysis