# OS-LOC-DAT-VIZ Viewer Plugin

This directory contains the installable GeoLibre viewer plugin used with
OS-LOC-DAT-VIZ KML and GeoJSON exports.

The viewer supports inclusive local date/time filtering to the minute, filtered
timeline playback, map labels, event details, and focused navigation.
The panel's **About & licenses** section identifies the GPL-licensed plugin and
the bundled GeoLibre 3.0.0 viewer under its MIT License.

- `plugin.json` defines the plugin package and version.
- `dist/index.js` and `dist/style.css` are the maintained, readable runtime
  source required by GeoLibre.
- `GeoLibre-Plugin.zip` is a generated local package and is intentionally
  ignored. Rebuild it from `plugin.json` and `dist/` when preparing a plugin
  release.

The plugin is covered by the repository's GNU GPL v3.0 license.