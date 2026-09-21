# OS-LOC-DAT-VIZ Viewer Plugin

This directory contains the installable GeoLibre viewer plugin used with
OS-LOC-DAT-VIZ KML and GeoJSON exports.

The viewer provides a prominent **Load GeoJSON** action for previous
OS-LOC-DAT-VIZ exports and supports inclusive local date/time filtering to the
minute, timeline playback, map labels, event details, and focused navigation.
Additional GeoJSON exports can be loaded by repeating the action. KML remains
available through GeoLibre drag and drop. Static reference-site record sets
remain independently toggleable and visible during timeline playback and
date/time filtering. Their event cards and details show the contributing CSL
spreadsheet rows, or original-record rows when no CSL was used.
The panel's **About & licenses** section identifies the GPL-licensed plugin and
the bundled GeoLibre 3.0.0 viewer under its MIT License.

- `plugin.json` defines the plugin package and version.
- `dist/index.js` and `dist/style.css` are the maintained, readable runtime
  source required by GeoLibre.
- `GeoLibre-Plugin.zip` is a generated local package and is intentionally
  ignored. Rebuild it from `plugin.json` and `dist/` when preparing a plugin
  release.

The plugin is covered by the repository's GNU GPL v3.0 license.