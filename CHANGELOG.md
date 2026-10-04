# Changelog

---

## [Unreleased]

### Changed
- All record types now retain usable location information when dates/times are missing, unreadable, or unresolved during daylight-saving transitions. Matching KML and GeoJSON events are labeled `date/time unavailable` without invented timeline times; warnings and the TXT log report the untimed records and daylight-saving conflicts. Import date/time filters remain strict and exclude records whose times cannot be confirmed within the selected range.

## [2.0.0-beta.1] - 2026-10-03

### Changed
- Default Location Accuracy is now 0: missing or zero accuracy produces a visible point without an accuracy circle in KML and GeoJSON, explicitly identified as unknown rather than exact; positive accuracy values and configurable positive defaults retain their circles
- The application is now labeled 2.0.0-beta.1 for the first 2.0 beta; Windows executable metadata uses numeric version 2.0.0.1, while bundled viewer and plugin versions remain independent
- Settings and Colors retain tooltip-only labels with a small hover-help reminder at the top of each tab; Nearby Cell Site Radius help explicitly explains its CSL-only effect and separation from event geometry
- Timestamp and missing-data documentation now describes named source timezones, year-first date-order choices, fractional-second handling, and configured accuracy defaults; viewer guidance explicitly identifies network-backed basemap behavior
- Startup information and usage guidance now describe the bundled GeoLibre workflow, import filtering and cell-site joins, static auxiliary datasets, missing-data outcomes, and current viewer troubleshooting
- User-facing terminology now uses Cell Site, Cell Site/Sector, and Distance from Cell Site throughout the application, notices, templates, KML/GeoJSON descriptions, viewer, and generation logs; existing internal identifiers and legacy input headers remain compatible

### Fixed
- The main program window now appears behind the startup disclaimer, which remains modal until dismissed
- TXT generation logs now record the source timestamp interpretation and selected output display timezone separately
- Numeric Excel serial timestamps now use Excel's 1900 date system without a one-day shift
- Import date/time filters now use the selected display timezone, or the source timezone when display is set to No Change

## [1.3.0-beta.1] - 2026-09-21

### Added
- Current-record-set markers with unlimited manual entry, CSV/XLS/XLSX import, row-specific validation warnings, individual colors, and a downloadable coordinate-only template
- Separate static marker datasets in KML and GeoJSON with dataset-wide and individual controls, always-visible enabled labels, and coordinate details in GeoLibre
- Static, independently toggleable reference-cell-site layers for cell-site-based KML and GeoJSON outputs, including unique record cell sites or radius-filtered CSL neighbors, configurable dot color, and a 25-mile default radius
- Optional separate cell site list import for Cell Site/Sector and Distance from Cell Site records, with mapped two-column lookup keys, authoritative cell site fields, previews, match accounting, and TXT-log provenance
- Paired GeoJSON output with the same event identity, temporal metadata, geometry, and display colors as KML
- Stable `osloc_*` dataset, event, component, timezone, and epoch metadata for interoperable viewers
- GeoLibre viewer plugin with event filtering, timeline playback, map labels, details, and focused navigation
- Process and Open in Viewer action with bundled GeoLibre Desktop, automatic plugin provisioning, and same-named project files
- Open Viewer action for loading one or more existing KML or GeoJSON files without generating new outputs
- Prominent Load GeoJSON action in the viewer panel for reopening validated OS-LOC exports
- Project-scoped simplified GeoLibre chrome with automatic startup data framing
- GeoLibre filter fields automatically suggest the first and last corrected record date/time
- GeoLibre About & Licenses details with bundled plugin and viewer license notices
- Application Licenses & Third-Party Notices dialog with the full GeoLibre MIT notice
- Preliminary-review metadata in both KML documents and GeoJSON collections
- Pinned runtime and Windows build dependencies with packaged third-party license files
- Clicking a GeoLibre event record now focuses its map geometry and opens its details
- Automated coverage for import-wizard behavior, temporal KML metadata, geometry preservation, and KML/GeoJSON parity

### Changed
- Reference-site event cards, KML balloons, and GeoLibre details now identify contributing CSL spreadsheet rows (or original-record rows without a CSL), omit unavailable Site IDs, and replace generic static timing text with row provenance
- Cell-site-based import labels now distinguish cell site coordinates from Location Point coordinates; mapped-equivalent CSL duplicates are collapsed, while referenced conflicts report their keys, rows, and differing fields
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
- GeoLibre now frames newly loaded data while leaving every record disabled
- GeoLibre hidden-layer filters no longer trigger repeated MapLibre Diagnostics errors
- GeoLibre datasets now start hidden, and the first Show All action immediately displays the selected-color evidence layers
- GeoLibre now waits for newly requested datasets and suppresses late-ready generic host layers without requiring Hide All / Show All
- Generated viewer projects keep the OS-LOC side panel expanded during GeoLibre project restoration
- Hidden KML anchor points remain hidden without suppressing intentionally visible location points
- GeoJSON timeline filters use bounded epoch comparisons instead of event-ID lists
- Google Earth event names no longer append geometry labels such as Shaded Area to the primary event title
- Google Earth Places entries suppress truncated description previews while retaining complete balloon details
- GeoLibre date/time fields no longer jump or clear while a value is typed manually
- Valid geometry with an unparseable timestamp now emits a summarized warning and is recorded as untimed in the generation log

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
- Distance from Cell Site now visualizes as a band with configurable inner and outer thickness
- KML descriptions include band area in square miles
- Settings tab reorganized into labeled sections with visual separators

### Fixed
- Templates changed from CSV to XLSX to prevent Excel from dropping seconds on some timestamps
- Fixed AM/PM timestamp handling (12 PM, 12 AM edge cases)
- Fixed Google Earth timeline animation using correct KML TimeSpan elements
- Other minor fixes

## [1.0] - 2025-11-02

### Initial Release
- Cell Site/Sector data visualization with directional wedges
- Distance from Cell Site data visualization with arcs
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
