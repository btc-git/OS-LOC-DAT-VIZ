# Test Suite

Run the automated tests from the repository root:

```powershell
python -m unittest discover -s tests -v
node tests/test_plugin_simplified_chrome.mjs
node --check tools/plugin_performance_harness.mjs
```

The `test_*.py` modules cover KML temporal metadata and geometry, paired
GeoJSON output, the GeoLibre launch workflow, the import wizard UI, and the
startup disclaimer's visibility and dismissal behavior. The
Node.js contract test covers project-scoped simplified viewer chrome. Tests use
Qt's offscreen platform and do not require opening the desktop application.

Source/output safety regressions cover real CSV import precision and leading-zero
IDs, ordinary-coordinate geometry parity, load-bound hashes, CSL joins, marker
file versions, sibling overwrite cancellation, staged-save failures, replacement
rollback, and explicit backup retention when recovery fails.

Terminology regressions check Cell Site/Sector and Distance from Cell Site labels in the
UI, notices, templates, generation logs, KML/GeoJSON names and descriptions, and
viewer event types. Internal export identifiers and legacy coordinate headers
remain compatible; both site-named and legacy headers are tested.

Manual data-generation and performance utilities live in `tools/`. Generated
diagnostic outputs belong in the ignored `diagnostics/` directory.