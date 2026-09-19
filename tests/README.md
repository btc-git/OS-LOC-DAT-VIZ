# Test Suite

Run the automated tests from the repository root:

```powershell
python -m unittest discover -s tests -v
```

The `test_*.py` modules cover KML temporal metadata and geometry, paired
GeoJSON output, and the import wizard UI. Tests use Qt's offscreen platform
and do not require opening the desktop application.

Manual data-generation and performance utilities live in `tools/`. Generated
diagnostic outputs belong in the ignored `diagnostics/` directory.