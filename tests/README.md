# Test Suite

Run the automated tests from the repository root:

```powershell
python -m unittest discover -s tests -v
node tests/test_plugin_simplified_chrome.mjs
```

The `test_*.py` modules cover KML temporal metadata and geometry, paired
GeoJSON output, the GeoLibre launch workflow, and the import wizard UI. The
Node.js contract test covers project-scoped simplified viewer chrome. Tests use
Qt's offscreen platform and do not require opening the desktop application.

Manual data-generation and performance utilities live in `tools/`. Generated
diagnostic outputs belong in the ignored `diagnostics/` directory.