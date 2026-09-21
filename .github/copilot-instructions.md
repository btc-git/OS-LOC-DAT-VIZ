# Open Source Location Data Visualizer - AI Coding Guide

## Purpose

This PyQt6 desktop application converts CSV/XLS/XLSX location records into
paired KML and GeoJSON visualizations plus a TXT generation log. It is a
preliminary triage tool: all source interpretation and generated geometry
require independent expert verification.

Use [README.md](../README.md) for user and developer documentation,
[tests/README.md](../tests/README.md) for automated tests, and
[tools/README.md](../tools/README.md) for manual diagnostics. Do not duplicate
those documents here.

## Ownership Boundaries

- `app.py` configures and starts Qt. Every startup must show
  `DisclaimerDialog` through `MainWindow`.
- `main_window.py` owns UI state, `QSettings`, file selection, worker
  orchestration, paired output writes, and audit logs.
- `import_wizard.py` owns custom CSV/Excel loading, column mapping, timezone
  choices, date filtering, and optional cell-site-list joins.
- `kml_generator.py` owns parsing, geographic calculations, KML/GeoJSON
  generation, shared metadata, row outcomes, and worker signals.
- `geolibre_launcher.py` owns bundled-viewer verification, extraction, plugin
  provisioning, project files, and process launch.
- `GeoLibre-Plugin/dist/` is the readable runtime plugin source. Its generated
  ZIP is intentionally ignored.

Keep changes inside the owning module unless a contract genuinely crosses a
boundary. Never update Qt widgets directly from the worker thread.

## Required Behavior

- Keep generation in `KMLGenerator` (`QThread`). Communicate through
  `progress`, `finished`, `error`, and `status_message` signals.
- Generate matching KML and GeoJSON together. The UI also writes a same-stem
  TXT audit log; `Process and Open in Viewer` additionally writes a GeoLibre
  project.
- Preserve the preliminary-review notice in KML document metadata and GeoJSON
  collection metadata.
- Preserve source coordinate text precision. Format only derived geometry
  vertices and endpoints to six decimal places.
- Keep KML/GeoJSON dataset, event, component, temporal, style, and source-row
  metadata in parity. KML uses standard 2.2 elements, not `gx:` extensions.
- Missing azimuth produces a 360-degree visualization. Missing distance omits
  the distance band. Missing location accuracy uses the configured default.
  Emit summarized warnings for these outcomes.
- Valid geometry with an unparseable timestamp remains untimed and emits a
  warning. Missing Location Point timestamps and DST-ambiguous/nonexistent
  local times are omitted and reported.
- Reference sites and user markers are separate, static auxiliary datasets.
  Markers belong only to the currently selected source record set.
- Escape user-controlled KML/XML text with the existing XML helpers. Continue
  using structured JSON serialization for GeoJSON.

## Data And File Safety

- Use `pathlib.Path` for paths.
- Never commit source records or generated KML, KMZ, GeoJSON, TXT, GeoLibre,
  diagnostic, build, or executable output. Respect `.gitignore`; keep local
  sensitive diagnostics under `diagnostics/`.
- Do not place real location records in tests. Use synthetic identifiers and
  coordinates.
- Do not add source-record values to logs beyond the existing bounded row
  references, filenames, mappings, counts, settings, and hashes.
- The bundled GeoLibre archive is intentionally tracked. If it changes, update
  and verify the pinned SHA-256 in `GeoLibre-Viewer/README.md` and
  `geolibre_launcher.py`.

## Implementation Conventions

- Use modern PyQt6 signal connections: `widget.signal.connect(slot)`.
- Route worker feedback through `status_message`; route main-thread UI feedback
  through `add_status_message()` and dialogs.
- Reuse normalized, case-insensitive column helpers rather than direct
  case-sensitive header assumptions.
- Maintain explicit source and display timezone semantics. Explicit offsets in
  records take precedence over configured source timezone choices.
- Use named timezones for historical DST behavior and fixed offsets only when
  the user selected one.
- Keep application version declarations synchronized in `version.py`,
  `version_info.txt`, `CHANGELOG.md`, and the README footer. GeoLibre viewer and
  plugin versions are independent.
- Update nearby regression tests whenever output metadata, parsing, geometry,
  UI labels, or viewer contracts change.

## Verify Changes

Install and run from the repository root:

```powershell
python -m pip install -r requirements.txt
python app.py
```

Run the automated checks:

```powershell
python -m unittest discover -s tests -v
node tests/test_plugin_simplified_chrome.mjs
node --check tools/plugin_performance_harness.mjs
```

For a reproducible Windows release build, use Python 3.11.3, install the
complete build lock, and build only through the tracked spec:

```powershell
python -m pip install -r requirements-build.txt
python -m PyInstaller --clean app.spec
```

The spec packages the icon, Windows version metadata, timezone data, XLS
support, GeoLibre viewer archive, plugin, and required license files. Do not
replace it with a reduced one-line PyInstaller command in documentation.