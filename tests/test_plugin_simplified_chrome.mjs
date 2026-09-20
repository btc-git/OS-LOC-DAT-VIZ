/*
 * Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
 * Licensed under the GNU General Public License v3.0 - see LICENSE for details
 */

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const pluginPath = path.join(repositoryRoot, "GeoLibre-Plugin", "dist", "index.js");
const manifestPath = path.join(repositoryRoot, "GeoLibre-Plugin", "plugin.json");
const stylePath = path.join(repositoryRoot, "GeoLibre-Plugin", "dist", "style.css");

const toolbarClasses = new Set();
const toolbar = {
    classList: {
        add(value) { toolbarClasses.add(value); },
        remove(value) { toolbarClasses.delete(value); },
    },
};
const pluginButton = {
    getAttribute(name) {
        return name === "aria-label" ? "OS-LOC-DAT-VIZ" : null;
    },
    closest(selector) {
        return selector === "header" ? toolbar : null;
    },
};

let observerDisconnects = 0;
globalThis.document = {
    body: {},
    querySelectorAll(selector) {
        assert.equal(selector, "header button");
        return [pluginButton];
    },
};
globalThis.MutationObserver = class {
    observe(target, options) {
        assert.equal(target, globalThis.document.body);
        assert.deepEqual(options, { childList: true, subtree: true });
    }

    disconnect() {
        observerDisconnects += 1;
    }
};

const pluginSource = fs.readFileSync(pluginPath, "utf8");
const pluginModule = await import(
    `data:text/javascript;base64,${Buffer.from(pluginSource).toString("base64")}`
);
const plugin = pluginModule.default;
const {
    eventDisplayMinute,
    eventMatchesDateTimeBounds,
    normalizeDateTimeFilterValue,
} = pluginModule;
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
assert.equal(plugin.version, manifest.version);
assert.equal(plugin.restoresPanelCollapseState, true);

assert.equal(
    normalizeDateTimeFilterValue("2024-01-15", false),
    "2024-01-15T00:00",
);
assert.equal(
    normalizeDateTimeFilterValue("2024-01-15", true),
    "2024-01-15T23:59",
);
assert.equal(
    normalizeDateTimeFilterValue("2024-01-15T14:30", true),
    "2024-01-15T14:30",
);
assert.equal(normalizeDateTimeFilterValue("2024-02-30T14:30"), null);
assert.equal(normalizeDateTimeFilterValue("2024-01-15T24:00"), null);

const localEvent = {
    startMs: Date.parse("2024-01-15T19:30:59Z"),
    endMs: Date.parse("2024-01-15T19:31:59Z"),
    localStart: "2024-01-15T14:30:59-05:00",
    timezone: "America/New_York",
};
assert.equal(eventDisplayMinute(localEvent), "2024-01-15T14:30");
assert(eventMatchesDateTimeBounds(
    localEvent,
    "2024-01-15T14:30",
    "2024-01-15T14:30",
));
assert(!eventMatchesDateTimeBounds(
    localEvent,
    "2024-01-15T14:31",
    "",
));
assert.equal(
    eventDisplayMinute({
        startMs: Date.parse("2024-01-15T19:30:00Z"),
        endMs: Date.parse("2024-01-15T19:31:00Z"),
        timezone: "America/New_York",
    }),
    "2024-01-15T14:30",
);
assert.equal(
    eventDisplayMinute({
        startMs: Date.parse("2024-01-15T19:30:00Z"),
        endMs: Date.parse("2024-01-15T19:31:00Z"),
        timezone: "Fixed UTC -05:00",
    }),
    "2024-01-15T14:30",
);

let panelOpenCalls = 0;
const app = {
    getMap() { return null; },
    registerRightPanel() { return () => { }; },
    registerToolbarMenu() { return () => { }; },
    openRightPanel() { panelOpenCalls += 1; },
    closeRightPanel() { },
    closeFloatingPanel() { },
};
const simplifiedClass = "osloc-simplified-viewer-toolbar";

plugin.applyProjectState(app, { simplifiedViewer: true });
plugin.activate(app);
assert(toolbarClasses.has(simplifiedClass));
assert.equal(panelOpenCalls, 1);

plugin.applyProjectState(app, { simplifiedViewer: false });
assert(!toolbarClasses.has(simplifiedClass));
assert.equal(observerDisconnects, 1);

plugin.applyProjectState(app, { simplifiedViewer: true });
assert.equal(panelOpenCalls, 2);
plugin.deactivate(app);
assert(!toolbarClasses.has(simplifiedClass));
assert.equal(observerDisconnects, 2);

const styleSource = fs.readFileSync(stylePath, "utf8");
assert(styleSource.includes(`header.${simplifiedClass} button`));
assert(styleSource.includes(`button[aria-label="OS-LOC-DAT-VIZ"]`));
assert(pluginSource.includes('input.type = "datetime-local"'));
assert(pluginSource.includes('input.step = "60"'));
assert(styleSource.includes('input[type="datetime-local"]'));

console.log("Simplified viewer chrome and date/time filter contracts passed.");