# Diagnostic Tools

These scripts are manual diagnostics, not part of unittest discovery.

Generate a matrix of KML variants from a local KML file:

```powershell
python tools/generate_geolibre_import_diagnostics.py --input-kml <input.kml>
```

The default output is the ignored `diagnostics/geolibre_import_matrix/`
directory. Input and generated KML may contain sensitive location data and
must not be committed.

Run the GeoLibre plugin performance and behavior harness with a JSON array of
GeoLibre feature objects:

```powershell
node tools/plugin_performance_harness.mjs <features.json>
```

An alternate plugin JavaScript file can be supplied as the second argument.