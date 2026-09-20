/*
 * Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
 * Licensed under the GNU General Public License v3.0 - see LICENSE for details
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { performance } from "node:perf_hooks";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDir, "..");
const [featuresArgument, pluginArgument] = process.argv.slice(2);
const pluginPath = path.resolve(
    pluginArgument || path.join(repositoryRoot, "GeoLibre-Plugin", "dist", "index.js")
);
const featureDataPath = featuresArgument ? path.resolve(featuresArgument) : "";
const tmpModule = path.join(os.tmpdir(), `osloc_plugin_diag_runtime_${process.pid}.mjs`);

function fail(message) {
    throw new Error(message);
}

function assert(condition, message) {
    if (!condition) fail(message);
}

function loadFeatures() {
    if (!featureDataPath) {
        fail("Usage: node tools/plugin_performance_harness.mjs <features.json> [plugin.js]");
    }
    if (!fs.existsSync(featureDataPath)) {
        fail(`Missing feature file: ${featureDataPath}`);
    }
    const payload = JSON.parse(fs.readFileSync(featureDataPath, "utf8"));
    if (Array.isArray(payload)) return payload;
    if (payload?.type === "FeatureCollection" && Array.isArray(payload.features)) {
        return payload.features;
    }
    fail("Feature file must be a GeoJSON FeatureCollection or an array of features");
}

function eventKeyFromProps(p) {
    const datasetId = String(p?.osloc_dataset_id || p?.osloc_export_id || "legacy");
    const eventId = String(p?.osloc_event_id || "");
    return eventId ? `${datasetId}::${eventId}` : "";
}

function makeEventLayerScenario(features) {
    const byEvent = new Map();
    for (const feature of features) {
        const key = eventKeyFromProps(feature.properties || {});
        if (!key) continue;
        if (!byEvent.has(key)) byEvent.set(key, []);
        byEvent.get(key).push(feature);
    }

    const storeLayers = [];
    const storeFeatures = new Map();
    const styleLayers = [];

    for (const [key, group] of byEvent.entries()) {
        const layerId = `store_${key.replace(/[:]/g, "_")}`;
        storeLayers.push({ id: layerId, name: layerId, type: "kml" });
        storeFeatures.set(layerId, group);
        styleLayers.push({
            id: `native_${layerId}`,
            source: `src_${layerId}`,
            "source-layer": layerId,
            type: "line",
            layout: {},
        });
    }

    return { name: "event", storeLayers, storeFeatures, styleLayers };
}

function makeComponentLayerScenario(features) {
    const storeLayers = [];
    const storeFeatures = new Map();
    const styleLayers = [];
    let i = 0;

    for (const feature of features) {
        const props = feature.properties || {};
        const key = eventKeyFromProps(props);
        if (!key) continue;

        const component = String(props.osloc_component_type || "component");
        const layerId = `store_${key.replace(/[:]/g, "_")}_${component}_${i++}`;

        storeLayers.push({ id: layerId, name: layerId, type: "kml" });
        storeFeatures.set(layerId, [feature]);
        styleLayers.push({
            id: `native_${layerId}`,
            source: `src_${layerId}`,
            "source-layer": layerId,
            type: component === "center_point" ? "symbol" : "line",
            layout: {},
        });
    }

    return { name: "component", storeLayers, storeFeatures, styleLayers };
}

function makeConsolidatedEventScenario(features) {
    const byEvent = new Map();
    for (const feature of features) {
        const key = eventKeyFromProps(feature.properties || {});
        if (!key) continue;
        if (!byEvent.has(key)) byEvent.set(key, []);
        byEvent.get(key).push(feature);
    }

    const storeLayers = [];
    const storeFeatures = new Map();
    const styleLayers = [];

    for (const [key, group] of byEvent.entries()) {
        const layerId = `store_${key.replace(/[:]/g, "_")}`;
        const props = { ...(group[0]?.properties || {}) };

        // Consolidated KML may expose one feature per event while still carrying
        // event identity and a representative component type.
        const pointLike = group.find(f => f?.geometry?.type === "Point") || group[0];
        const synthetic = {
            type: "Feature",
            properties: {
                ...props,
                osloc_component_type: props.osloc_component_type || "tower_sector",
            },
            geometry: pointLike?.geometry || { type: "Point", coordinates: [0, 0] },
        };

        storeLayers.push({ id: layerId, name: layerId, type: "kml" });
        storeFeatures.set(layerId, [synthetic]);
        styleLayers.push({
            id: `native_${layerId}`,
            source: `src_${layerId}`,
            "source-layer": layerId,
            type: "symbol",
            layout: {},
        });
    }

    return { name: "consolidated", storeLayers, storeFeatures, styleLayers };
}

function makeGeojsonSharedLayerScenario(features) {
    const layerId = "store_geojson_shared";
    const storeLayers = [{ id: layerId, name: layerId, type: "geojson" }];
    const geojsonFeatures = features
        .filter(feature => eventKeyFromProps(feature.properties || {}))
        .map((feature, index) => {
            const x = -77.61 + (index % 100) * 0.000001;
            const y = 43.15 + (index % 100) * 0.000001;
            let geometry = feature.geometry;
            if (!Array.isArray(geometry?.coordinates)) {
                if (geometry?.type === "Polygon") {
                    geometry = {
                        type: "Polygon",
                        coordinates: [[
                            [x, y], [x + 0.0001, y],
                            [x + 0.0001, y + 0.0001], [x, y],
                        ]],
                    };
                } else if (geometry?.type === "LineString") {
                    geometry = {
                        type: "LineString",
                        coordinates: [[x, y], [x + 0.0001, y + 0.0001]],
                    };
                } else if (geometry?.type === "Point") {
                    geometry = { type: "Point", coordinates: [x, y] };
                }
            }
            return {
                ...feature,
                geometry,
                properties: {
                    ...(feature.properties || {}),
                    osloc_event_key: eventKeyFromProps(feature.properties || {}),
                    osloc_start_epoch_ms: Date.parse(feature.properties?.osloc_start_time),
                    osloc_end_epoch_ms: Date.parse(feature.properties?.osloc_end_time),
                    osloc_style_leg_color: "ff000000",
                    osloc_style_shaded_color: "7d00ffff",
                    osloc_style_band_color: "7d0099ff",
                    osloc_style_gps_line_color: "ff00ff00",
                    osloc_style_gps_fill_color: "4d00ff00",
                    osloc_style_reported_distance_color: "ff000000",
                    osloc_style_distance_center_color: "ff0000ff",
                },
            };
        });
    const storeFeatures = new Map([[layerId, geojsonFeatures]]);

    const styleLayers = [
        {
            id: "native_shared_fill",
            source: `src_${layerId}`,
            "source-layer": layerId,
            type: "fill",
            filter: ["==", ["geometry-type"], "Polygon"],
            layout: {},
        },
        {
            id: "native_shared_line",
            source: `src_${layerId}`,
            "source-layer": layerId,
            type: "line",
            filter: ["==", ["geometry-type"], "LineString"],
            layout: {},
        },
        {
            id: "native_shared_symbol",
            source: `src_${layerId}`,
            "source-layer": layerId,
            type: "symbol",
            filter: ["==", ["geometry-type"], "Point"],
            layout: {},
        },
    ];

    return { name: "geojson-shared", storeLayers, storeFeatures, styleLayers };
}

function buildEventStoreIndex(storeLayers, storeFeatures) {
    const events = [];
    const eventStore = new Map();

    for (const layer of storeLayers) {
        const features = storeFeatures.get(layer.id) || [];
        for (const feature of features) {
            const key = eventKeyFromProps(feature.properties || {});
            if (!key) continue;
            if (!eventStore.has(key)) {
                eventStore.set(key, new Map());
            }
            eventStore.get(key).set(layer.id, { id: layer.id, name: layer.name || layer.id });
        }
    }

    for (const key of [...eventStore.keys()].sort()) {
        events.push({ key, storeLayers: eventStore.get(key) });
    }

    return { events, eventStore };
}

function legacyComparisonCount(events, styleLayers, uniqueNameCount) {
    let checks = 0;

    for (const event of events) {
        for (const store of event.storeLayers.values()) {
            const idNeedle = String(store.id).toLowerCase();
            const nameNeedle = String(store.name || "").toLowerCase();

            let matched = false;
            for (const sl of styleLayers) {
                checks++;
                const values = [sl.id, sl.source, sl["source-layer"]]
                    .filter(Boolean)
                    .map(v => String(v).toLowerCase());
                if (values.includes(idNeedle)) matched = true;
            }

            if (!matched && idNeedle.length >= 5) {
                for (const sl of styleLayers) {
                    checks++;
                    const hay = [sl.id, sl.source, sl["source-layer"]]
                        .filter(Boolean)
                        .join(" ")
                        .toLowerCase();
                    if (hay.includes(idNeedle)) matched = true;
                }
            }

            if (!matched && nameNeedle && uniqueNameCount.get(nameNeedle) === 1) {
                for (const sl of styleLayers) {
                    checks++;
                    const hay = [sl.id, sl.source, sl["source-layer"]]
                        .filter(Boolean)
                        .join(" ")
                        .toLowerCase();
                    if (hay.includes(nameNeedle)) matched = true;
                }
            }
        }
    }

    return checks;
}

function optimizedComparisonCount(storeLayers, styleLayers) {
    const byExact = new Map();
    let buildChecks = 0;

    for (const sl of styleLayers) {
        const values = [sl.id, sl.source, sl["source-layer"]]
            .filter(Boolean)
            .map(v => String(v).toLowerCase());

        for (const value of values) {
            if (!byExact.has(value)) byExact.set(value, []);
            byExact.get(value).push(sl);
            buildChecks++;
        }
    }

    let queryChecks = 0;
    for (const layer of storeLayers) {
        const idNeedle = String(layer.id).toLowerCase();
        const candidates = byExact.get(idNeedle) || [];
        queryChecks += Math.max(1, candidates.length);
    }

    return buildChecks + queryChecks;
}

function makeDocumentMock(stats) {
    class ElementMock {
        constructor(tag) {
            this.tagName = tag;
            this.children = [];
            this.parentNode = null;
            this.dataset = {};
            this.classList = { toggle() { } };
            this.textContent = "";
            this.innerHTML = "";
            this.value = "";
            this.checked = false;
            this.indeterminate = false;
            this.className = "";
            this.listeners = {};
        }
        appendChild(el) {
            this.children.push(el);
            if (el && typeof el === "object") el.parentNode = this;
            if (el?.className && String(el.className) === "osloc-v028__event") {
                stats.domEventRows++;
            }
            return el;
        }
        append(...items) {
            for (const item of items) this.appendChild(item);
        }
        setAttribute() { }
        addEventListener(type, listener) {
            stats.domListeners++;
            (this.listeners[type] ||= []).push(listener);
        }
        closest(selector) {
            const role = /^\[data-role='([^']+)'\]$/.exec(selector)?.[1];
            let current = this;
            while (current) {
                if (role && current.dataset?.role === role) return current;
                current = current.parentNode;
            }
            return null;
        }
        dispatchEvent(event) {
            for (const listener of this.listeners[event.type] || []) listener.call(this, event);
        }
        querySelector() { return null; }
        querySelectorAll(selector) {
            if (selector !== "tr") return [];
            return [...String(this.innerHTML || "").matchAll(/<tr[^>]*>([\s\S]*?)<\/tr>/gi)]
                .map(rowMatch => ({
                    querySelectorAll(cellSelector) {
                        if (cellSelector !== "th, td") return [];
                        return [...rowMatch[1].matchAll(/<t[hd][^>]*>([\s\S]*?)<\/t[hd]>/gi)]
                            .map(cellMatch => ({
                                textContent: cellMatch[1].replace(/<[^>]+>/g, ""),
                            }));
                    },
                }));
        }
        remove() { }
        get innerText() { return String(this.innerHTML || "").replace(/<[^>]+>/g, ""); }
    }

    return {
        createElement(tag) {
            stats.domCreates++;
            return new ElementMock(tag);
        },
        createDocumentFragment() {
            stats.domCreates++;
            return new ElementMock("fragment");
        },
    };
}

function buildRuntime(diag, scenario) {
    const op = {
        listLayersCalls: 0,
        getLayerFeaturesCalls: 0,
        setLayoutPropertyCalls: 0,
        setPaintPropertyCalls: 0,
        setFilterCalls: 0,
        moveLayerCalls: 0,
        labelSetDataCalls: 0,
        labelFeatureCountLast: 0,
        fitBoundsCalls: 0,
        openFloatingPanelCalls: 0,
        domCreates: 0,
        domListeners: 0,
        domEventRows: 0,
    };

    const styleById = new Map(scenario.styleLayers.map(layer => [layer.id, layer]));
    const sourceById = new Map();
    const filterByLayerId = new Map(
        scenario.styleLayers.map(layer => [layer.id, layer.filter ?? null])
    );
    const clickListeners = [];

    const map = {
        getStyle() { return { layers: scenario.styleLayers }; },
        querySourceFeatures(sourceId, options) {
            const sid = String(sourceId || "").replace(/^src_/, "");
            const sourceLayer = options?.sourceLayer ? String(options.sourceLayer) : sid;
            return scenario.storeFeatures.get(sourceLayer) || [];
        },
        setLayoutProperty(id, property, value) {
            op.setLayoutPropertyCalls++;
            const layer = styleById.get(id);
            if (!layer) return;
            if (!layer.layout) layer.layout = {};
            layer.layout[property] = value;
        },
        setFilter(id, filter) {
            op.setFilterCalls++;
            filterByLayerId.set(id, filter ?? null);
            const layer = styleById.get(id);
            if (layer) {
                layer.filter = filter ?? null;
            }
        },
        getFilter(id) {
            return filterByLayerId.get(id) ?? null;
        },
        setPaintProperty(id, property, value) {
            op.setPaintPropertyCalls++;
            const layer = styleById.get(id);
            if (!layer) return;
            if (!layer.paint) layer.paint = {};
            layer.paint[property] = value;
        },
        moveLayer() { op.moveLayerCalls++; },
        getLayer(id) { return styleById.get(id) || null; },
        addLayer(layer) {
            styleById.set(layer.id, layer);
            scenario.styleLayers.push(layer);
        },
        removeLayer(id) {
            styleById.delete(id);
            scenario.styleLayers = scenario.styleLayers.filter(layer => layer.id !== id);
        },
        addSource(id, source) {
            sourceById.set(id, {
                ...source,
                setData(payload) {
                    op.labelSetDataCalls++;
                    op.labelFeatureCountLast = payload?.features?.length || 0;
                }
            });
        },
        getSource(id) { return sourceById.get(id) || null; },
        removeSource(id) { sourceById.delete(id); },
        getContainer() { return null; },
        queryRenderedFeatures(_pointOrBox, options) {
            const targetLayers = options?.layers;
            if (Array.isArray(targetLayers) && targetLayers.length === 1) {
                const target = String(targetLayers[0]);
                const layer = styleById.get(target);
                if (layer) {
                    const sourceLayer = String(layer["source-layer"] || "");
                    if (sourceLayer && scenario.storeFeatures.has(sourceLayer)) {
                        return scenario.storeFeatures.get(sourceLayer) || [];
                    }
                }
            }
            const firstEvent = diag.state.events[0];
            if (!firstEvent || !firstEvent.features?.length) return [];
            const base = firstEvent.features[0];
            return [{ ...base, properties: { ...(base.properties || {}), __oslocEventKey: firstEvent.key } }];
        },
        on(name, fn) {
            if (name === "click") clickListeners.push(fn);
        },
        off() { }
    };

    const app = {
        listLayers() { op.listLayersCalls++; return scenario.storeLayers; },
        getLayerFeatures(id) {
            op.getLayerFeaturesCalls++;
            return scenario.storeFeatures.get(id) || [];
        },
        getMap() { return map; },
        registerRightPanel() { return { dispose() { } }; },
        registerToolbarMenu() { return { dispose() { } }; },
        openRightPanel() { },
        closeRightPanel() { },
        openFloatingPanel() { op.openFloatingPanelCalls++; },
        closeFloatingPanel() { },
        fitBounds() { op.fitBoundsCalls++; }
    };

    globalThis.document = makeDocumentMock(op);
    globalThis.requestAnimationFrame = (cb) => {
        cb(performance.now());
        return 1;
    };
    globalThis.cancelAnimationFrame = () => { };

    diag.state.app = app;
    diag.state.container = null;
    diag.state.datasets = [];
    diag.state.events = [];
    diag.state.eventKeysKnownLastScan = new Set();
    diag.state.enabledEventKeys = new Set();
    diag.state.collapsedDatasets = new Set();
    diag.state.mode = "overview";
    diag.state.currentMs = null;
    diag.state.playing = false;
    diag.state.scrubbing = false;
    diag.state.durationOverrideMs = null;
    diag.state.labelsEnabled = true;
    diag.state.dateFilterStart = "";
    diag.state.dateFilterEnd = "";
    diag.state.dateFilterAuto = true;
    diag.state.nativeIdsByEventKey = new Map();
    diag.state.nativeOwnerByLayerId = new Map();
    diag.state.nativeMappingKindByLayerId = new Map();
    diag.state.ambiguousNativeIds = new Set();
    diag.state.hiddenAnchorCircleLayerIds = new Set();
    diag.state.hiddenAnchorSymbolLayerIds = new Set();
    diag.state.hiddenAnchorOriginalIconSizes = new Map();
    diag.state.mappingStats = {
        nativeMapped: 0,
        nativeMetadata: 0,
        fallbackMapped: 0,
        ambiguousRenderLayers: 0,
        ambiguousSourceGroups: 0,
        sharedFilteredLayers: 0,
        unmappedEvents: 0,
        suppressedHiddenAnchorLayers: 0
    };
    diag.state.sharedNativeLayerBaseFilter = new Map();
    diag.state.sharedNativeLayerEventKeys = new Map();
    diag.state.sharedNativeLayerAppliedSignature = new Map();
    diag.state.sharedNativeLayerVisibilityById = new Map();
    diag.state.sharedNativeLayerSupportsEpochs = new Map();
    diag.state.geojsonSourceGroups = new Map();
    diag.state.pluginEvidenceLayerIds = new Set();
    diag.state.suppressedHostLayerIds = new Set();
    diag.state.hostLayerOriginalVisibility = new Map();
    diag.state.hostLayerOriginalFilter = new Map();
    diag.state.selectedEventKey = null;
    diag.state.lastScanReason = "";
    diag.state.enabledEventsVersion = 0;
    diag.state.timelineBoundaries = [];
    diag.state.labelsLastEmpty = true;
    diag.state.labelLayersVisible = false;

    return { op, app, map, clickListeners };
}

async function loadDiagModule() {
    if (!fs.existsSync(pluginPath)) {
        fail(`Missing plugin file: ${pluginPath}`);
    }
    const src = fs.readFileSync(pluginPath, "utf8") +
        "\nexport const __diag = { state, scanAll, applyVisibility, applyDateFilter, eventDisplayMinute, eventDateTimeBounds, eventMatchesDateFilter, makeDateFilterControl, makeAboutSection, rebuildNativeIndex, reconcileGeojsonRendering, focusEvents, activateEvent, detailDescriptionForFeature, parseDescription, formatMainEventLabel, formatMapTimeLabel, scheduleFullScan, updateMapLabels, updateDynamicUI, renderEventList, renderPanel, renderPanelSafe, shouldShow, timelineRange, eventFromMapFeature, collectOslocLayerDiagnostics };\n";
    fs.writeFileSync(tmpModule, src, "utf8");
    try {
        const moduleUrl = `${pathToFileURL(tmpModule).href}?v=${Date.now()}`;
        const mod = await import(moduleUrl);
        return mod.__diag;
    } finally {
        fs.rmSync(tmpModule, { force: true });
    }
}

function runScanTiming(diag, scenario) {
    const runtime = buildRuntime(diag, scenario);
    const t0 = performance.now();
    const found = diag.scanAll(`harness-${scenario.name}`);
    const t1 = performance.now();
    return {
        runtime,
        found,
        ms: +(t1 - t0).toFixed(3)
    };
}

function withImmediateTimers(fn) {
    const oldSetTimeout = globalThis.setTimeout;
    const oldClearTimeout = globalThis.clearTimeout;
    const oldSetInterval = globalThis.setInterval;
    const oldClearInterval = globalThis.clearInterval;

    globalThis.setTimeout = (cb) => { cb(); return 1; };
    globalThis.clearTimeout = () => { };
    globalThis.setInterval = (cb) => { cb(); return 1; };
    globalThis.clearInterval = () => { };

    try {
        return fn();
    } finally {
        globalThis.setTimeout = oldSetTimeout;
        globalThis.clearTimeout = oldClearTimeout;
        globalThis.setInterval = oldSetInterval;
        globalThis.clearInterval = oldClearInterval;
    }
}

function uniqueNameCount(storeLayers) {
    const m = new Map();
    for (const layer of storeLayers) {
        const name = String(layer.name || "").toLowerCase();
        if (!name) continue;
        m.set(name, (m.get(name) || 0) + 1);
    }
    return m;
}

function runComplexityComparison(features) {
    const scenarios = [
        makeEventLayerScenario(features),
        makeComponentLayerScenario(features),
    ];

    const results = [];
    for (const scenario of scenarios) {
        const { events } = buildEventStoreIndex(scenario.storeLayers, scenario.storeFeatures);
        const names = uniqueNameCount(scenario.storeLayers);

        const t0 = performance.now();
        const oldChecks = legacyComparisonCount(events, scenario.styleLayers, names);
        const t1 = performance.now();

        const t2 = performance.now();
        const newChecks = optimizedComparisonCount(scenario.storeLayers, scenario.styleLayers);
        const t3 = performance.now();

        results.push({
            scenario: scenario.name,
            oldChecks,
            newChecks,
            reduction: +(oldChecks / Math.max(1, newChecks)).toFixed(2),
            oldMs: +(t1 - t0).toFixed(3),
            newMs: +(t3 - t2).toFixed(3),
            storeLayers: scenario.storeLayers.length,
            styleLayers: scenario.styleLayers.length,
            events: events.length,
        });
    }

    return results;
}

function opSnapshot(op) {
    return {
        setLayoutPropertyCalls: op.setLayoutPropertyCalls,
        setPaintPropertyCalls: op.setPaintPropertyCalls,
        setFilterCalls: op.setFilterCalls,
        moveLayerCalls: op.moveLayerCalls,
        labelSetDataCalls: op.labelSetDataCalls,
        domCreates: op.domCreates,
        domListeners: op.domListeners,
        domEventRows: op.domEventRows,
    };
}

function opDelta(before, after, elapsedMs) {
    return {
        elapsedMs: +elapsedMs.toFixed(3),
        setLayoutPropertyCalls: after.setLayoutPropertyCalls - before.setLayoutPropertyCalls,
        setPaintPropertyCalls: after.setPaintPropertyCalls - before.setPaintPropertyCalls,
        setFilterCalls: after.setFilterCalls - before.setFilterCalls,
        moveLayerCalls: after.moveLayerCalls - before.moveLayerCalls,
        labelSetDataCalls: after.labelSetDataCalls - before.labelSetDataCalls,
        domCreates: after.domCreates - before.domCreates,
        domListeners: after.domListeners - before.domListeners,
        domEventRows: after.domEventRows - before.domEventRows,
    };
}

function measure(runtime, fn) {
    const before = opSnapshot(runtime.op);
    const t0 = performance.now();
    fn();
    const t1 = performance.now();
    const after = opSnapshot(runtime.op);
    return opDelta(before, after, t1 - t0);
}

function runLifecycleMetrics(diag, scenario) {
    const runtime = buildRuntime(diag, scenario);

    const t0 = performance.now();
    const found = diag.scanAll(`harness-${scenario.name}`);
    const t1 = performance.now();
    assert(found > 0, "scanAll should discover events");

    const initialTotals = opSnapshot(runtime.op);
    const initialHiddenStateInitialization = {
        elapsedMs: +(t1 - t0).toFixed(3),
        ...initialTotals,
    };

    const secondIdenticalHideAll = measure(runtime, () => {
        diag.state.mode = "overview";
        diag.state.enabledEventKeys.clear();
        diag.applyVisibility(true);
    });

    const showAll = measure(runtime, () => {
        diag.state.mode = "overview";
        diag.state.enabledEventKeys = new Set(diag.state.events.map(e => e.key));
        diag.applyVisibility(true);
    });

    const hideAllAfterShowAll = measure(runtime, () => {
        diag.state.mode = "overview";
        diag.state.enabledEventKeys.clear();
        diag.applyVisibility(true);
    });

    const range = diag.timelineRange();
    assert(range && Number.isFinite(range.min) && Number.isFinite(range.max), "Timeline range should be available");

    diag.state.enabledEventKeys = new Set(diag.state.events.map(e => e.key));
    diag.state.mode = "timeline";
    diag.state.currentMs = range.min;
    diag.applyVisibility(true);

    const oneTimelineStep = measure(runtime, () => {
        diag.state.currentMs = Math.min(range.max, range.min + 60000);
        diag.applyVisibility(false);
    });

    const repeatedIdenticalTimelineState = measure(runtime, () => {
        diag.applyVisibility(false);
    });
    assert(repeatedIdenticalTimelineState.setLayoutPropertyCalls === 0, "Unchanged timeline frame must not touch layout");
    assert(repeatedIdenticalTimelineState.setFilterCalls === 0, "Unchanged timeline frame must not rebuild filters");
    assert(repeatedIdenticalTimelineState.labelSetDataCalls === 0, "Unchanged timeline frame must not rebuild labels");
    assert(repeatedIdenticalTimelineState.domEventRows === 0, "Unchanged timeline frame must not rebuild event rows");

    const labelsWhenHidden = measure(runtime, () => {
        diag.state.enabledEventKeys.clear();
        diag.state.mode = "overview";
        diag.state.labelsEnabled = false;
        diag.updateMapLabels();
    });

    const labelsSmallVisibleSubset = measure(runtime, () => {
        diag.state.labelsEnabled = true;
        diag.state.mode = "overview";
        diag.state.enabledEventKeys = new Set(
            diag.state.events.slice(0, 25).map(e => e.key)
        );
        diag.applyVisibility(true);
        diag.updateMapLabels();
    });

    const panelOpenEventListCreation = measure(runtime, () => {
        diag.state.container = globalThis.document.createElement("div");
        diag.renderPanel();
    });

    const firstEvent = diag.state.events[0];
    const resolved = diag.eventFromMapFeature({
        properties: {
            osloc_dataset_id: firstEvent.datasetId,
            osloc_event_id: firstEvent.id,
        }
    });
    assert(resolved?.key === firstEvent.key, "Click feature resolution should still locate matching event");

    return {
        found,
        initialHiddenStateInitialization,
        secondIdenticalHideAll,
        showAll,
        hideAllAfterShowAll,
        oneTimelineStep,
        repeatedIdenticalTimelineState,
        labelsWhenHidden,
        labelsSmallVisibleSubset,
        panelOpenEventListCreation,
        finalTotals: opSnapshot(runtime.op),
        labelFeatureCountLast: runtime.op.labelFeatureCountLast,
    };
}

function runScanGateChecks(diag, scenario) {
    const { op, app } = buildRuntime(diag, scenario);

    return withImmediateTimers(() => {
        diag.scheduleFullScan("panel-open", 3);
        const firstScanFeatureCalls = op.getLayerFeaturesCalls;
        assert(firstScanFeatureCalls > 0, "Initial panel-open scan should run");

        diag.scheduleFullScan("panel-reopen", 3);
        const secondScanFeatureCalls = op.getLayerFeaturesCalls;
        assert(secondScanFeatureCalls === firstScanFeatureCalls, "Unchanged signature should skip redundant scan");

        const newLayer = {
            id: "store_new_dataset_layer",
            name: "store_new_dataset_layer",
            type: "kml"
        };

        const baseFeature = scenario.storeFeatures.values().next().value?.[0];
        const newFeature = {
            ...(baseFeature || {}),
            properties: {
                ...(baseFeature?.properties || {}),
                osloc_dataset_id: "dataset_new",
                osloc_dataset_name: "dataset_new",
                osloc_event_id: "event_new_0001",
                osloc_component_type: "center_point",
            },
            geometry: { type: "Point" }
        };

        scenario.storeLayers = [...scenario.storeLayers, newLayer];
        scenario.storeFeatures.set(newLayer.id, [newFeature]);

        app.listLayers = () => scenario.storeLayers;

        diag.scheduleFullScan("layer-list-change", 3);
        const thirdScanFeatureCalls = op.getLayerFeaturesCalls;
        assert(thirdScanFeatureCalls > secondScanFeatureCalls, "Changed signature should trigger rescan");

        const discovered = diag.state.events.some(e => e.datasetId === "dataset_new" && e.id === "event_new_0001");
        assert(discovered, "Newly imported dataset should be discovered after signature change");

        return {
            firstScanFeatureCalls,
            secondScanFeatureCalls,
            thirdScanFeatureCalls,
            discovered
        };
    });
}

function runConsolidatedRecognitionCheck(diag, features) {
    const scenario = makeConsolidatedEventScenario(features);
    buildRuntime(diag, scenario);
    const found = diag.scanAll("harness-consolidated-recognition");
    assert(found > 0, "Consolidated scenario should discover events");

    const firstEvent = diag.state.events[0];
    assert(firstEvent, "Consolidated scenario should have at least one event");

    const resolved = diag.eventFromMapFeature({
        properties: {
            osloc_dataset_id: firstEvent.datasetId,
            osloc_event_id: firstEvent.id,
        }
    });

    assert(resolved?.key === firstEvent.key, "Consolidated feature click should resolve to event");

    return {
        found,
        clickResolved: resolved?.key === firstEvent.key,
        placemarkLikeFeaturesPerEvent: 1,
    };
}

function runShuffledFeatureOrderingCheck(diag, features) {
    const shuffled = [...features].reverse();
    const scenario = makeEventLayerScenario(shuffled);
    buildRuntime(diag, scenario);
    const found = diag.scanAll("harness-shuffled-order");
    const expectedEvents = new Set(
        shuffled.map(feature => eventKeyFromProps(feature.properties || {})).filter(Boolean)
    ).size;

    assert(found === expectedEvents, "Shuffled feature ordering must not change event discovery counts");

    const firstEvent = diag.state.events[0];
    assert(firstEvent, "Shuffled scenario should have at least one event");
    const resolved = diag.eventFromMapFeature({
        properties: {
            osloc_dataset_id: firstEvent.datasetId,
            osloc_event_id: firstEvent.id,
        }
    });
    assert(resolved?.key === firstEvent.key, "Shuffled feature click should resolve to event");

    return {
        found,
        expectedEvents,
        clickResolved: resolved?.key === firstEvent.key,
    };
}

function runEventCardStateSeparationCheck(diag, scenario) {
    buildRuntime(diag, scenario);
    const found = diag.scanAll(`harness-${scenario.name}-card-state`);
    assert(found > 0, "Card-state validation requires scanned events");
    const event = diag.state.events[0];
    assert(event, "Need at least one event for card-state validation");

    diag.state.enabledEventKeys = new Set([event.key]);
    diag.state.mode = "timeline";
    diag.state.currentMs = Number.isFinite(event.startMs) ? event.startMs : (diag.timelineRange()?.min ?? null);
    diag.state.selectedEventKey = null;

    const classFlags = new Map();
    const row = {
        getAttribute(name) {
            if (name === "data-event-key") return event.key;
            return "";
        },
        classList: {
            toggle(name, enabled) {
                classFlags.set(name, !!enabled);
            },
        },
    };

    const root = {
        querySelector(selector) {
            if (selector === "[data-role='visible-count']") {
                return { textContent: "" };
            }
            return null;
        },
        querySelectorAll(selector) {
            if (selector === "[data-event-key]") return [row];
            return [];
        },
    };

    diag.state.container = {
        querySelector(selector) {
            if (selector === ".osloc-v028") return root;
            return null;
        },
    };

    diag.updateDynamicUI();

    const visibleNotSelected =
        classFlags.get("osloc-v028__event--active") === true &&
        classFlags.get("osloc-v028__event--selected") !== true;

    diag.state.selectedEventKey = event.key;
    diag.updateDynamicUI();
    const selectedWhenExplicit = classFlags.get("osloc-v028__event--selected") === true;

    assert(visibleNotSelected, "Timeline-visible event cards must not become selected implicitly");
    assert(selectedWhenExplicit, "Selected class must still apply when an event is explicitly selected");

    return {
        visibleNotSelected,
        selectedWhenExplicit,
        activeClassWhenVisible: classFlags.get("osloc-v028__event--active") === true,
    };
}

function runGeojsonSharedLayerVisibilityCheck(diag, features) {
    const scenario = makeGeojsonSharedLayerScenario(features);
    const hostLayerIds = scenario.styleLayers.map(layer => layer.id);
    const runtime = buildRuntime(diag, scenario);
    const found = diag.scanAll("harness-geojson-shared");
    assert(found > 0, "GeoJSON shared-layer scenario should discover events");

    const pluginEvidenceLayers = scenario.styleLayers.filter(layer =>
        String(layer.id || "").startsWith("osloc-dat-viz-evidence-")
    );
    assert(pluginEvidenceLayers.length >= 3, "Plugin should own fill, line, and point evidence layers");
    assert(pluginEvidenceLayers.length <= 4, "Plugin evidence rendering must remain bounded");

    for (const hostLayerId of hostLayerIds) {
        const hostLayer = runtime.map.getLayer(hostLayerId);
        assert(hostLayer?.layout?.visibility === "none", `Host layer must be suppressed: ${hostLayerId}`);
    }

    for (const layer of pluginEvidenceLayers) {
        assert(layer.source === "src_store_geojson_shared", `Plugin layer must reuse the host source: ${layer.id}`);
        assert(layer.layout?.visibility === "none", `Initial hide-all must hide plugin layer: ${layer.id}`);
        assert(JSON.stringify(layer.filter).includes("[\"==\",1,0]"), `Initial filter must reject all features: ${layer.id}`);
    }

    assert(diag.state.mappingStats.sharedFilteredLayers > 0, "Plugin-owned shared-layer mapping should be active");
    assert(diag.state.mappingStats.ambiguousRenderLayers === 0, "Shared layers should not be marked ambiguous");

    const initiallyVisible = diag.state.events.filter(diag.shouldShow).length;
    assert(initiallyVisible === 0, "Initial plugin visible count must be zero");

    const sharedLayerIds = [...diag.state.sharedNativeLayerEventKeys.keys()];
    assert(sharedLayerIds.length > 0, "Shared layer ids should be discovered");
    assert(sharedLayerIds.length <= 6, "Shared-layer architecture should remain bounded");

    for (const layerId of sharedLayerIds) {
        const layer = runtime.map.getLayer(layerId);
        assert(layer, `Shared layer must exist: ${layerId}`);
        assert((layer.layout?.visibility || "visible") === "none", `Initial hide-all must hide ${layerId}`);
    }

    const initialRepeat = measure(runtime, () => {
        diag.state.enabledEventKeys.clear();
        diag.state.mode = "overview";
        diag.applyVisibility(true);
    });
    assert(initialRepeat.setFilterCalls === 0, "Repeated Hide All should not churn filters");

    const removedOwnedLayerId = pluginEvidenceLayers[0].id;
    runtime.map.removeLayer(removedOwnedLayerId);
    for (const hostLayerId of hostLayerIds) {
        runtime.map.setLayoutProperty(hostLayerId, "visibility", "visible");
    }
    diag.reconcileGeojsonRendering();
    assert(runtime.map.getLayer(removedOwnedLayerId), "Style reconciliation should restore a missing owned layer");
    for (const hostLayerId of hostLayerIds) {
        assert(runtime.map.getLayer(hostLayerId)?.layout?.visibility === "none", `Reconciliation must re-suppress host layer: ${hostLayerId}`);
    }

    const sample = diag.state.events.slice(0, 10);
    diag.state.mode = "overview";
    diag.state.enabledEventKeys = new Set(sample.map(e => e.key));
    const deltaShowSubset = measure(runtime, () => diag.applyVisibility(true));
    assert(deltaShowSubset.setFilterCalls > 0, "Visibility update should apply shared layer filters");

    const showAll = measure(runtime, () => {
        diag.state.mode = "overview";
        diag.state.enabledEventKeys = new Set(diag.state.events.map(e => e.key));
        diag.applyVisibility(true);
    });
    assert(showAll.setFilterCalls >= 0, "Show All should complete without mapping loss");
    for (const layerId of sharedLayerIds) {
        const serialized = JSON.stringify(runtime.map.getLayer(layerId)?.filter || null);
        assert(!serialized.includes("osloc_event_id"), `Show All must not build an event-id list: ${layerId}`);
    }
    assert(
        runtime.op.labelFeatureCountLast === found,
        `Show All labels should match visible event count (${runtime.op.labelFeatureCountLast} !== ${found}; ` +
        `temporal=${diag.state.events.filter(e => Number.isFinite(e.startMs) && Number.isFinite(e.endMs)).length}; ` +
        `enabled=${diag.state.labelsEnabled}; visible=${diag.state.labelLayersVisible}; ` +
        `empty=${diag.state.labelsLastEmpty}; updates=${runtime.op.labelSetDataCalls})`
    );

    diag.state.enabledEventKeys.clear();
    const deltaHideAll = measure(runtime, () => diag.applyVisibility(true));
    assert(deltaHideAll.setFilterCalls > 0, "Hide-all should update shared layer filters");
    assert(runtime.op.labelFeatureCountLast === 0, "Hide All must clear map labels");

    const repeatHideAll = measure(runtime, () => diag.applyVisibility(true));
    assert(repeatHideAll.setFilterCalls === 0, "Repeated Hide All should remain stable");

    const temporal = diag.state.events.filter(e => Number.isFinite(e.startMs));
    if (temporal.length) {
        const pick = temporal[Math.min(25, temporal.length - 1)];
        diag.state.mode = "timeline";
        diag.state.enabledEventKeys = new Set(diag.state.events.map(e => e.key));
        diag.state.currentMs = pick.startMs;
        const timelineDelta = measure(runtime, () => diag.applyVisibility(true));
        const timelineVisible = diag.state.events.filter(diag.shouldShow).length;
        const sampleLayerId = sharedLayerIds[0];
        const signature = diag.state.sharedNativeLayerAppliedSignature.get(sampleLayerId) || "";
        const timelineFilter = JSON.stringify(runtime.map.getLayer(sampleLayerId)?.filter || null);
        assert(timelineFilter.includes("osloc_start_epoch_ms"), "Timeline filter must use numeric start epochs");
        assert(timelineFilter.includes("osloc_end_epoch_ms"), "Timeline filter must use numeric end epochs");
        assert(!timelineFilter.includes("osloc_event_id"), "Timeline filter must not contain event-id lists");
        assert(timelineFilter.length < 1000, "Timeline filter expression should remain bounded");
        if (timelineVisible === 0) {
            assert(signature === "hidden", "Timeline with 0 visible events should apply hidden signature");
        } else {
            assert(signature.startsWith("timeline:"), "Timeline visibility should use a bounded time signature");
        }
    }

    const diagnostics = diag.collectOslocLayerDiagnostics();
    assert(diagnostics, "Layer diagnostics should be available");

    const pointLayer = diagnostics.oslocLayers.find(layer =>
        layer.id.startsWith("osloc-dat-viz-evidence-point-")
    );
    if (pointLayer) {
        const serializedFilter = JSON.stringify(pointLayer.filter || "");
        // Hidden anchor points should not pass the component/event filter.
        assert(!serializedFilter.includes("tower_sector\",\"center_point") || serializedFilter.includes("distance_only"), "Point filters should distinguish hidden anchors from visible points");
    }

    const fillLayer = diagnostics.oslocLayers.find(layer =>
        layer.id.startsWith("osloc-dat-viz-evidence-fill-")
    );
    const lineLayer = diagnostics.oslocLayers.find(layer =>
        layer.id.startsWith("osloc-dat-viz-evidence-line-")
    );
    if (fillLayer) {
        const fillColor = JSON.stringify(fillLayer.paint?.["fill-color"] || "");
        assert(fillColor.includes("distance_band") || fillColor.includes("rgba"), "Fill layer should apply OS-LOC component-aware colors");
    }
    if (lineLayer) {
        const lineColor = JSON.stringify(lineLayer.paint?.["line-color"] || "");
        assert(lineColor.includes("reported_distance") || lineColor.includes("rgba"), "Line layer should apply OS-LOC component-aware colors");
    }

    return {
        found,
        initialVisibleCount: initiallyVisible,
        sharedLayerIds,
        sharedFilteredLayers: diag.state.mappingStats.sharedFilteredLayers,
        ambiguousRenderLayers: diag.state.mappingStats.ambiguousRenderLayers,
        initialRepeatHideAllFilterCalls: initialRepeat.setFilterCalls,
        showSubsetFilterCalls: deltaShowSubset.setFilterCalls,
        showAllFilterCalls: showAll.setFilterCalls,
        hideAllFilterCalls: deltaHideAll.setFilterCalls,
        repeatHideAllFilterCalls: repeatHideAll.setFilterCalls,
        diagnostics,
    };
}

function runGeojsonClickResolutionCoverageCheck(diag) {
    const dataset = "diag_dataset";
    const synthetic = [
        {
            type: "Feature",
            properties: { osloc_dataset_id: dataset, osloc_event_id: "event_poly", osloc_event_type: "tower_sector", osloc_component_type: "tower_sector" },
            geometry: { type: "Polygon", coordinates: [[[-77.61, 43.15], [-77.62, 43.15], [-77.62, 43.16], [-77.61, 43.15]]] },
        },
        {
            type: "Feature",
            properties: { osloc_dataset_id: dataset, osloc_event_id: "event_line", osloc_event_type: "tower_sector_distance", osloc_component_type: "reported_distance" },
            geometry: { type: "LineString", coordinates: [[-77.61, 43.15], [-77.62, 43.16]] },
        },
        {
            type: "Feature",
            properties: { osloc_dataset_id: dataset, osloc_event_id: "event_point_distance", osloc_event_type: "distance_only", osloc_component_type: "center_point" },
            geometry: { type: "Point", coordinates: [-77.61, 43.15] },
        },
        {
            type: "Feature",
            properties: { osloc_dataset_id: dataset, osloc_event_id: "event_point_location", osloc_event_type: "location", osloc_component_type: "location_point" },
            geometry: { type: "Point", coordinates: [-77.62, 43.16] },
        },
    ];

    const scenario = makeGeojsonSharedLayerScenario(synthetic);
    buildRuntime(diag, scenario);
    const found = diag.scanAll("harness-geojson-click-resolution");
    assert(found === 4, "Synthetic click-resolution scenario should discover four events");

    const failures = [];
    for (const feature of synthetic) {
        const expectedKey = eventKeyFromProps(feature.properties || {});
        const resolved = diag.eventFromMapFeature({ properties: feature.properties || {} });
        if (!resolved || resolved.key !== expectedKey) {
            failures.push({ expectedKey, resolvedKey: resolved?.key || null, component: feature.properties.osloc_component_type });
        }
    }

    assert(failures.length === 0, `Click resolution failed for components: ${JSON.stringify(failures)}`);

    return {
        found,
        checkedComponents: synthetic.map(feature => feature.properties.osloc_component_type),
    };
}

function runLateGeojsonOwnershipCheck(diag, features) {
    const scenario = makeGeojsonSharedLayerScenario(features.slice(0, 100));
    const lateHostLayers = scenario.styleLayers.map(layer => ({ ...layer, layout: {} }));
    scenario.styleLayers = [];
    const runtime = buildRuntime(diag, scenario);

    const found = diag.scanAll("harness-geojson-before-host-layers");
    assert(found > 0, "Events should be discoverable before host render layers exist");
    assert(diag.state.pluginEvidenceLayerIds.size === 0, "Ownership should wait for a render source");

    for (const layer of lateHostLayers) runtime.map.addLayer(layer);
    diag.reconcileGeojsonRendering();

    assert(diag.state.pluginEvidenceLayerIds.size === 3, "Late host layers should create three owned evidence layers");
    for (const layer of lateHostLayers) {
        const current = runtime.map.getLayer(layer.id);
        assert(current?.layout?.visibility === "none", `Late host layer must be hidden: ${layer.id}`);
        assert(JSON.stringify(current?.filter) === JSON.stringify(["==", 1, 0]), `Late host layer must reject all features: ${layer.id}`);
    }

    return { found, ownedLayers: diag.state.pluginEvidenceLayerIds.size };
}

function runGeojsonFocusCheck(diag) {
    const scenario = makeGeojsonSharedLayerScenario([
        {
            type: "Feature",
            properties: {
                osloc_dataset_id: "focus_dataset",
                osloc_event_id: "focus_one",
                osloc_event_type: "location",
                osloc_component_type: "location_point",
                osloc_start_time: "2024-01-15T14:00:00Z",
                osloc_end_time: "2024-01-15T14:30:00Z",
            },
            geometry: { type: "Point", coordinates: [-77.61, 43.15] },
        },
        {
            type: "Feature",
            properties: {
                osloc_dataset_id: "focus_dataset",
                osloc_event_id: "focus_two",
                osloc_event_type: "location",
                osloc_component_type: "location_point",
                osloc_start_time: "2024-01-15T15:00:00Z",
                osloc_end_time: "2024-01-15T15:30:00Z",
            },
            geometry: { type: "Point", coordinates: [-77.62, 43.16] },
        },
    ]);
    const runtime = buildRuntime(diag, scenario);
    const found = diag.scanAll("harness-geojson-focus");
    assert(found === 2, "Focus scenario should discover two events");

    const target = diag.state.events[0];
    const eventSection = diag.renderEventList([target]);
    const eventList = eventSection.children[0];
    const eventRow = eventList.children[0];
    const eventBody = eventRow.children[1];
    const nestedTitle = eventBody.children[0];
    eventList.dispatchEvent({ type: "click", target: nestedTitle });
    const visible = diag.state.events.filter(diag.shouldShow);
    assert(visible.length === 1 && visible[0].key === target.key, "Record activation must make exactly its target visible");
    assert(runtime.op.fitBoundsCalls === 1, "Record activation must frame its visible target");
    assert(diag.state.selectedEventKey === target.key, "Record activation must select its target");
    assert(runtime.op.openFloatingPanelCalls === 1, "Record activation must open event details");

    for (const layerId of diag.state.pluginEvidenceLayerIds) {
        const filter = JSON.stringify(runtime.map.getLayer(layerId)?.filter || null);
        assert(filter.includes("osloc_event_key"), `Focused GeoJSON layer must filter by full event key: ${layerId}`);
        assert(!filter.includes("osloc_event_id"), `Focused GeoJSON layer must not use ambiguous event ids: ${layerId}`);
    }

    return {
        found,
        visible: visible.length,
        fitBoundsCalls: runtime.op.fitBoundsCalls,
        openFloatingPanelCalls: runtime.op.openFloatingPanelCalls,
    };
}

function runDescriptionParityCheck(diag) {
    const sector = {
        properties: { osloc_component_type: "tower_sector", description: "Sector details" },
    };
    const leg = {
        properties: { osloc_component_type: "left_leg", description: "Leg details" },
    };
    const band = {
        properties: { osloc_component_type: "distance_band", description: "Band details" },
    };
    const reported = {
        properties: { osloc_component_type: "reported_distance", description: "Line details" },
    };
    const event = {
        eventType: "tower_sector_distance",
        description: "Sector details",
        features: [sector, leg, band, reported],
    };

    assert(diag.detailDescriptionForFeature(event, leg) === "Sector details", "Leg popup should match consolidated KML sector details");
    assert(diag.detailDescriptionForFeature(event, reported) === "Band details", "Reported line popup should match consolidated KML band details");
    return { sectorGroup: true, distanceGroup: true };
}

function runPresentationFormattingCheck(diag) {
    const event = {
        startMs: Date.parse("2023-02-01T01:14:41Z"),
        endMs: Date.parse("2023-02-01T01:44:41Z"),
        timezone: "America/New_York",
        localStart: "2023-01-31T20:14:41-05:00",
        displayTime: "2023-02-01 01:14:41",
    };
    const expectedTitle = "01/31/2023, 8:14:41 PM";
    assert(diag.formatMainEventLabel(event) === expectedTitle, "Event title should use the full corrected local date and time");
    assert(diag.formatMapTimeLabel(event) === expectedTitle, "Map label should match the full event title");

    const description = diag.parseDescription(
        '<table><tr><td><b>Tower:</b></td><td>43.16619974, -77.5910047</td></tr>' +
        '<tr><td><b>Azimuth:</b></td><td>30.0°</td></tr></table>'
    );
    assert(
        description === "Tower: 43.16619974, -77.5910047\nAzimuth: 30.0°",
        "KML table details should retain one readable field per line"
    );
    return { title: expectedTitle, details: description };
}

function runDateRangeFilterCheck(diag) {
    const features = [
        {
            type: "Feature",
            properties: {
                osloc_dataset_id: "date_dataset",
                osloc_dataset_name: "Date Filter Records",
                osloc_event_id: "event_one",
                osloc_event_type: "location",
                osloc_component_type: "location_point",
                osloc_start_time: "2023-02-01T01:14:41Z",
                osloc_end_time: "2023-02-01T01:44:41Z",
                osloc_local_start_time: "2023-01-31T20:14:41-05:00",
                osloc_local_end_time: "2023-01-31T20:44:41-05:00",
                osloc_timezone: "America/New_York",
            },
            geometry: { type: "Point", coordinates: [-77.61, 43.15] },
        },
        {
            type: "Feature",
            properties: {
                osloc_dataset_id: "date_dataset",
                osloc_dataset_name: "Date Filter Records",
                osloc_event_id: "event_two",
                osloc_event_type: "location",
                osloc_component_type: "location_point",
                osloc_start_time: "2023-02-01T14:00:00Z",
                osloc_end_time: "2023-02-01T14:30:00Z",
                osloc_local_start_time: "2023-02-01T09:00:00-05:00",
                osloc_local_end_time: "2023-02-01T09:30:00-05:00",
                osloc_timezone: "America/New_York",
            },
            geometry: { type: "Point", coordinates: [-77.62, 43.16] },
        },
        {
            type: "Feature",
            properties: {
                osloc_dataset_id: "date_dataset",
                osloc_dataset_name: "Date Filter Records",
                osloc_event_id: "event_three",
                osloc_event_type: "location",
                osloc_component_type: "location_point",
                osloc_start_time: "2023-02-02T14:00:00Z",
                osloc_end_time: "2023-02-02T14:30:00Z",
                osloc_local_start_time: "2023-02-02T09:00:00-05:00",
                osloc_local_end_time: "2023-02-02T09:30:00-05:00",
                osloc_timezone: "America/New_York",
            },
            geometry: { type: "Point", coordinates: [-77.63, 43.17] },
        },
    ];
    const runtime = buildRuntime(diag, makeGeojsonSharedLayerScenario(features));
    assert(diag.scanAll("harness-date-range") === 3, "Date-range scenario should discover three events");
    diag.state.enabledEventKeys = new Set(diag.state.events.map(event => event.key));
    diag.state.enabledEventsVersion++;

    assert(diag.state.dateFilterAuto === true, "Discovered data should begin with automatic filter bounds");
    assert(
        diag.state.dateFilterStart === "2023-01-31T20:14",
        "The automatic From value should use the earliest corrected local record time"
    );
    assert(
        diag.state.dateFilterEnd === "2023-02-02T09:00",
        "The automatic Through value should use the latest corrected local record time"
    );
    assert(
        diag.state.events.filter(diag.shouldShow).length === 3,
        "Suggested bounds must not filter records before Apply is selected"
    );

    assert(
        diag.eventDisplayMinute(diag.state.events[0]) === "2023-01-31T20:14",
        "Date/time filtering must use the corrected local time rather than canonical UTC"
    );
    assert(
        diag.applyDateFilter("2023-02-01", "2023-02-01") === true,
        "A valid inclusive date range should apply"
    );

    const visible = diag.state.events.filter(diag.shouldShow);
    assert(visible.length === 1, "A one-day range should show exactly one matching event");
    assert(visible[0].id === "event_two", "Both date endpoints must be inclusive");

    const range = diag.timelineRange();
    assert(range.min === Date.parse("2023-02-01T14:00:00Z"), "Filtered timeline should begin with the first in-range event");
    assert(range.max === Date.parse("2023-02-01T14:30:00Z"), "Filtered timeline should end with the last in-range event");

    const pluginFilters = [...diag.state.pluginEvidenceLayerIds]
        .map(layerId => JSON.stringify(runtime.map.getLayer(layerId)?.filter || null))
        .join("\n");
    assert(pluginFilters.includes("date_dataset::event_two"), "Shared GeoJSON filters must include the in-range event");
    assert(!pluginFilters.includes("date_dataset::event_one"), "Shared GeoJSON filters must exclude the prior local day");
    assert(!pluginFilters.includes("date_dataset::event_three"), "Shared GeoJSON filters must exclude dates after Through");

    diag.focusEvents(diag.state.events);
    assert(diag.state.events.filter(diag.shouldShow).length === 1, "Focus All must respect the active date range");
    assert(runtime.op.fitBoundsCalls === 1, "Focus All should frame the filtered evidence");

    assert(
        diag.applyDateFilter("2023-02-03", "2023-02-01") === false,
        "An inverted date range should be rejected"
    );
    assert(diag.state.dateFilterStart === "2023-02-01T00:00", "Rejected input must preserve the active From time");
    assert(diag.state.dateFilterEnd === "2023-02-01T23:59", "Rejected input must preserve the active Through time");

    assert(diag.applyDateFilter("", "") === true, "All Times should clear the range");
    assert(diag.state.events.filter(diag.shouldShow).length === 3, "Clearing the range should restore all enabled events");

    const control = diag.makeDateFilterControl();
    const descendants = [];
    const visit = element => {
        descendants.push(element);
        for (const child of element.children || []) visit(child);
    };
    visit(control);
    const dateInputs = descendants.filter(element => element.type === "datetime-local");
    const buttonLabels = descendants
        .filter(element => element.type === "button")
        .map(element => element.textContent);
    assert(dateInputs.length === 2, "Date-range control should render From and Through date/time pickers");
    assert(
        dateInputs.every(input => !input.min && !input.max),
        "Date pickers must not clamp or clear partially typed dates"
    );
    dateInputs[0].value = "2023-01-31T20:14";
    dateInputs[1].value = "2023-02-01T09:00";
    dateInputs[0].dispatchEvent({ type: "change" });
    dateInputs[1].dispatchEvent({ type: "change" });
    assert(
        dateInputs.every(input => !input.min && !input.max),
        "Date picker changes must not constrain the other field"
    );
    assert(buttonLabels.includes("Apply"), "Date-range control should include Apply");
    assert(buttonLabels.includes("All Times"), "Date-range control should include All Times");

    const about = diag.makeAboutSection();
    const aboutDescendants = [];
    const visitAbout = element => {
        aboutDescendants.push(element);
        for (const child of element.children || []) visitAbout(child);
    };
    visitAbout(about);
    const aboutText = aboutDescendants.map(element => element.textContent || "").join("\n");
    assert(aboutText.includes("About & licenses"), "Viewer panel should expose license information");
    assert(aboutText.includes("GNU General Public License v3.0"), "Viewer panel should identify the plugin license");
    assert(aboutText.includes("GeoLibre 3.0.0"), "Viewer panel should identify the bundled GeoLibre version");
    assert(aboutText.includes("MIT License"), "Viewer panel should identify the GeoLibre license");

    const pluginSource = fs.readFileSync(pluginPath, "utf8");
    assert(!pluginSource.includes("◀ 1 min"), "Timeline should not include the back-one-minute button");
    assert(!pluginSource.includes("1 min ▶"), "Timeline should not include the forward-one-minute button");

    return {
        correctedLocalDate: "2023-01-31",
        inclusiveVisible: visible.length,
        restoredVisible: diag.state.events.filter(diag.shouldShow).length,
        datePickers: dateInputs.length,
    };
}

async function main() {
    const features = loadFeatures();
    const diag = await loadDiagModule();

    const complexity = runComplexityComparison(features);

    const eventScenario = makeEventLayerScenario(features);
    const componentScenario = makeComponentLayerScenario(features);

    const eventScan = runScanTiming(diag, eventScenario);
    const componentScan = runScanTiming(diag, componentScenario);

    const lifecycle = runLifecycleMetrics(diag, makeEventLayerScenario(features));
    const scanGate = runScanGateChecks(diag, makeEventLayerScenario(features));
    const cardState = runEventCardStateSeparationCheck(diag, makeEventLayerScenario(features));
    const consolidatedRecognition = runConsolidatedRecognitionCheck(diag, features);
    const shuffledOrdering = runShuffledFeatureOrderingCheck(diag, features);
    const geojsonSharedVisibility = runGeojsonSharedLayerVisibilityCheck(diag, features);
    const geojsonClickResolutionCoverage = runGeojsonClickResolutionCoverageCheck(diag);
    const lateGeojsonOwnership = runLateGeojsonOwnershipCheck(diag, features);
    const geojsonFocus = runGeojsonFocusCheck(diag);
    const descriptionParity = runDescriptionParityCheck(diag);
    const presentationFormatting = runPresentationFormattingCheck(diag);
    const dateRangeFilter = runDateRangeFilterCheck(diag);

    const result = {
        kmlFeatures: features.length,
        complexity,
        pluginTimings: {
            eventScenarioScanMs: eventScan.ms,
            componentScenarioScanMs: componentScan.ms,
            eventScenarioFound: eventScan.found,
            componentScenarioFound: componentScan.found,
        },
        lifecycle,
        scanGate,
        cardState,
        consolidatedRecognition,
        shuffledOrdering,
        geojsonSharedVisibility,
        geojsonClickResolutionCoverage,
        lateGeojsonOwnership,
        geojsonFocus,
        descriptionParity,
        presentationFormatting,
        dateRangeFilter,
    };

    console.log(JSON.stringify(result, null, 2));
}

main().catch(err => {
    console.error(err.stack || String(err));
    process.exit(1);
});
