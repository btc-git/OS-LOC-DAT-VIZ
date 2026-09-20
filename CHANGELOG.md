# Changelog

---

## [Unreleased]

### Added
- Paired GeoJSON output with the same event identity, temporal metadata, geometry, and display colors as KML
- Stable `osloc_*` dataset, event, component, timezone, and epoch metadata for interoperable viewers
- GeoLibre viewer plugin with event filtering, timeline playback, map labels, details, and focused navigation
- Save & Open Viewer action with bundled GeoLibre Desktop, automatic plugin provisioning, and same-named project files
- Open Viewer action for loading one or more existing KML or GeoJSON files without generating new outputs
- Project-scoped simplified GeoLibre chrome with automatic Show All and data framing
- GeoLibre filter fields automatically suggest the first and last corrected record date/time
- GeoLibre About & Licenses details with bundled plugin and viewer license notices
- Application Licenses & Third-Party Notices dialog with the full GeoLibre MIT notice
- Automated coverage for import-wizard behavior, temporal KML metadata, geometry preservation, and KML/GeoJSON parity

### Changed
- KML now uses shared document styles, a flattened dataset folder, compact anchor metadata, and safe MultiGeometry consolidation to reduce import overhead
- Source/evidence coordinates preserve supplied precision while derived geometry remains deterministically formatted
- KML and GeoJSON event titles now use the same corrected local `MM/DD/YYYY, h:mm:ss AM/PM` format
- GeoLibre map labels now always include the full year and match event-card and popup titles
- GeoLibre labels global, record-set, and individual framing actions as Focus All, Focus Set, and Zoom to Event
- GeoLibre presents generated description tables as one readable detail field per line
- GeoLibre includes inclusive From/Through date-and-time pickers with minute precision and Apply and All Times controls
- Active GeoLibre date/time ranges limit map evidence, event lists, counts, Focus bounds, and the timeline slider range
- Removed the one-minute backward and forward buttons from the GeoLibre timeline

### Fixed
- Generated viewer projects keep the OS-LOC side panel expanded during GeoLibre project restoration
- Hidden KML anchor points remain hidden without suppressing intentionally visible location points
- GeoJSON timeline filters use bounded epoch comparisons instead of event-ID lists
- Google Earth event names no longer append geometry labels such as Shaded Area to the primary event title
- Google Earth Places entries suppress truncated description previews while retaining complete balloon details
- GeoLibre date/time fields no longer jump or clear while a value is typed manually

## [1.2] - 2026-09-10

### Added
- Automatic column-mapping wizard for non-template CSV, XLS, and XLSX records
- Combined or separate date/time column mapping with source previews
- Optional inclusive date/time range filtering with whole-day defaults, exact-time mode, pre-import result checks, and audit-log counts
- Named timezone conversion with historical daylight-saving rules
- Configurable fixed UTC offsets and slash-date order
- Same-named TXT generation logs containing hashes, settings, mappings, row outcomes, and warnings

### Changed
- Standard template files continue directly while non-template files open the mapping wizard automatically
- Explicit timezone information in source records takes precedence over selected fallback settings
- Missing azimuth mappings are accepted and produce 360-degree visualizations
- Disclaimer and usage guidance now describe source transformations and independent verification requirements

### Fixed
- Explicit timezone offsets are converted to UTC before KML timestamps receive the `Z` suffix
- Ambiguous or nonexistent daylight-saving transition times are omitted and reported instead of producing untimed geometry
- Invalid coordinate rows are counted and reported instead of being skipped silently
- Invalid accuracy values produce visible point-only output instead of an assumed radius
- Distance-band inner radii are clamped at zero
- Unparsed timestamp labels are XML-escaped before KML insertion
- Misleading runtime references to coverage circles and areas were replaced with visualization terminology

## [1.1] - 2026-02-28

### Added
- Distance from Tower now visualizes as a band with configurable inner and outer thickness
- KML descriptions include band area in square miles
- Settings tab reorganized into labeled sections with visual separators

### Fixed
- Templates changed from CSV to XLSX to prevent Excel from dropping seconds on some timestamps
- Fixed AM/PM timestamp handling (12 PM, 12 AM edge cases)
- Fixed Google Earth timeline animation using correct KML TimeSpan elements
- Other minor fixes

## [1.0] - 2025-11-02

### Initial Release
- Tower/Sector data visualization with directional wedges
- Distance from Tower data visualization with arcs
- Location Point data visualization with accuracy circles
- Drag-and-drop file input (CSV and XLSX)
- Customizable colors for all data types
- Time animation support for Google Earth timeline playback
- Configurable sector width, leg length, and shaded area length
- Custom KML label field
- Missing data handling with status warnings
- Built-in sample templates
- Standalone Windows executable via PyInstaller
- GPL v3.0 license
