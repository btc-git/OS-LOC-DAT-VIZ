# Changelog

---

## [1.1] - 2025-02-28

### Added
- Distance from Tower now visualizes as a band with configurable inner and outer thickness
- KML descriptions include band area in square miles
- Settings tab reorganized into labeled sections with visual separators

### Fixed
- Templates changed from CSV to XLSX to prevent Excel from dropping seconds on some timestamps
- Fixed AM/PM timestamp handling (12 PM, 12 AM edge cases)

---

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
