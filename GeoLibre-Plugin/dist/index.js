/*
 * Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
 * Licensed under the GNU General Public License v3.0 - see LICENSE for details
 */

const PLUGIN_ID = "osloc-dat-viz-viewer";
const PLUGIN_VERSION = "0.0.39";
const PANEL_ID = "osloc-dat-viz-panel";
const DETAILS_ID = "osloc-dat-viz-details";
const LABEL_SOURCE_ID = "osloc-dat-viz-time-labels-source";
const LABEL_INSIDE_LAYER_ID = "osloc-dat-viz-time-labels-inside-layer";
const LABEL_POINT_LAYER_ID = "osloc-dat-viz-time-labels-point-layer";
const EVIDENCE_LAYER_PREFIX = "osloc-dat-viz-evidence-";
const START_EPOCH_PROPERTY = "osloc_start_epoch_ms";
const END_EPOCH_PROPERTY = "osloc_end_epoch_ms";
const NEVER_MATCH_FILTER = ["==", 1, 0];

const SHARED_FILL_COMPONENTS = [
  "tower_sector",
  "coverage_circle",
  "distance_band",
  "accuracy_circle",
];

const SHARED_LINE_COMPONENTS = [
  "tower_sector",
  "left_leg",
  "right_leg",
  "coverage_circle",
  "reported_distance",
  "accuracy_circle",
];

let unregisterPanel = null;
let unregisterMenu = null;
let unregisterDetails = null;

let pollTimer = null;
let scanRetryTimer = null;
let scanDebounceTimer = null;
let playbackRaf = null;
let scrubVisibilityTimer = null;
let renderReconcileTimer = null;
let detachMapEvents = [];
let simplifiedChromeObserver = null;
let simplifiedToolbar = null;

let timelineEl = null;
let lastLayerSignature = "";
let lastVisibilitySignature = "";
let lastEventDataSignature = "";
let lastScannedRelevantSignature = "";
let lastNativeStyleSignature = "";
let nativeReconcileInProgress = false;
let panelRenderToken = 0;

const state = {
  app: null,
  container: null,

  datasets: [],
  events: [],
  eventKeysKnownLastScan: new Set(),
  enabledEventKeys: new Set(),

  collapsedDatasets: new Set(),

  mode: "overview", // overview | timeline
  currentMs: null,
  playing: false,
  scrubbing: false,
  speed: 60, // evidence seconds per real second
  durationOverrideMs: null, // null = use each KML's generated TimeSpan
  labelsEnabled: true,
  dateFilterStart: "", // YYYY-MM-DDTHH:mm local time, inclusive; empty = open bound
  dateFilterEnd: "",   // YYYY-MM-DDTHH:mm local time, inclusive; empty = open bound
  dateFilterAuto: true,
  lastFrameRealMs: null,

  nativeIdsByEventKey: new Map(),
  nativeOwnerByLayerId: new Map(),
  nativeMappingKindByLayerId: new Map(),
  ambiguousNativeIds: new Set(),

  // GeoLibre can render KML Point geometries even when their KML IconStyle
  // intentionally uses scale=0. Track only render layers that we can tie
  // unambiguously to those hidden anchor placemarks.
  hiddenAnchorCircleLayerIds: new Set(),
  hiddenAnchorSymbolLayerIds: new Set(),
  hiddenAnchorOriginalIconSizes: new Map(),
  hiddenAnchorSuppressedSymbolLayerIds: new Set(),

  mappingStats: {
    nativeMapped: 0,
    nativeMetadata: 0,
    fallbackMapped: 0,
    ambiguousRenderLayers: 0,
    ambiguousSourceGroups: 0,
    sharedFilteredLayers: 0,
    unmappedEvents: 0,
    suppressedHiddenAnchorLayers: 0
  },

  // GeoJSON imports often render many events through shared style layers.
  // We keep those layers always present and control visibility by filter.
  sharedNativeLayerBaseFilter: new Map(),
  sharedNativeLayerEventKeys: new Map(),
  sharedNativeLayerAppliedSignature: new Map(),
  sharedNativeLayerVisibilityById: new Map(),
  sharedNativeLayerSupportsEpochs: new Map(),

  geojsonSourceGroups: new Map(),
  pluginEvidenceLayerIds: new Set(),
  suppressedHostLayerIds: new Set(),
  hostLayerOriginalVisibility: new Map(),
  hostLayerOriginalFilter: new Map(),

  selectedEventKey: null,
  lastScanReason: "",

  layerVisibilityByNativeId: new Map(),
  lastVisibleEventSignature: "",
  lastReorderLayerSignature: "",
  lastLabelSignature: "",
  labelsLastEmpty: true,
  labelLayersVisible: false,
  eventByKey: new Map(),
  enabledEventsVersion: 0,
  timelineBoundaries: [],
  commonTimezoneValue: "",
  timelineIncludesDate: false,
  autoShowAll: false,
  autoFocus: false,
  simplifiedViewer: false,
  startupDatasetId: "",
  startupBehaviorApplied: false,
};

function nextAnimationFrame(callback) {
  if (typeof requestAnimationFrame === "function") {
    return requestAnimationFrame(callback);
  }
  return setTimeout(callback, 0);
}

function updateSimplifiedChrome() {
  if (!state.simplifiedViewer || typeof document === "undefined") {
    simplifiedToolbar?.classList.remove("osloc-simplified-viewer-toolbar");
    simplifiedToolbar = null;
    return;
  }

  const menuButton = [...document.querySelectorAll("header button")].find(
    button => button.getAttribute("aria-label") === "OS-LOC-DAT-VIZ"
  );
  const nextToolbar = menuButton?.closest("header") ?? null;
  if (nextToolbar === simplifiedToolbar) return;

  simplifiedToolbar?.classList.remove("osloc-simplified-viewer-toolbar");
  simplifiedToolbar = nextToolbar;
  nextToolbar?.classList.add("osloc-simplified-viewer-toolbar");
}

function setSimplifiedChrome(enabled) {
  state.simplifiedViewer = enabled;
  updateSimplifiedChrome();

  if (!enabled) {
    simplifiedChromeObserver?.disconnect();
    simplifiedChromeObserver = null;
    return;
  }

  if (
    !simplifiedChromeObserver &&
    typeof MutationObserver !== "undefined" &&
    document.body
  ) {
    simplifiedChromeObserver = new MutationObserver(updateSimplifiedChrome);
    simplifiedChromeObserver.observe(document.body, { childList: true, subtree: true });
  }
}

function firstProp(p, ...names) {
  for (const name of names) {
    const value = p?.[name];
    if (value !== undefined && value !== null && String(value) !== "") return String(value);
  }
  return "";
}

function safeListLayers() {
  try { return state.app?.listLayers?.() ?? []; }
  catch (err) {
    console.warn("[OSLOC] listLayers failed", err);
    return [];
  }
}

function safeFeatures(layerId) {
  try { return state.app?.getLayerFeatures?.(layerId) ?? []; }
  catch { return []; }
}

function layerSignature(layers) {
  return layers.map(l => `${l.id}|${l.name}|${l.type}`).sort().join("\n");
}

function isPluginOwnedLayer(layer) {
  const id = String(layer?.id ?? "");
  if (!id) return false;

  if (
    id === LABEL_INSIDE_LAYER_ID ||
    id === LABEL_POINT_LAYER_ID ||
    id === LABEL_SOURCE_ID ||
    id.startsWith("osloc-dat-viz-")
  ) {
    return true;
  }

  const source = String(layer?.source ?? "");
  return source === LABEL_SOURCE_ID;
}

function relevantLayerSignature(layers) {
  return layers
    .filter(layer => !isPluginOwnedLayer(layer))
    .map(layer => [
      String(layer?.id ?? ""),
      String(layer?.name ?? ""),
      String(layer?.type ?? ""),
      String(layer?.source ?? ""),
      String(layer?.["source-layer"] ?? "")
    ].join("|"))
    .sort()
    .join("\n");
}

function eventDataSignature(events) {
  return events.map(e => [
    e.key, e.start || "", e.end || "", e.label || "",
    e.eventType || "", e.datasetName || "", e.timezone || "",
    [...e.componentTypes].sort().join(",")
  ].join("|")).sort().join("\n");
}

function datasetMeta(p) {
  const id = firstProp(p, "osloc_dataset_id", "osloc_export_id") || "legacy";
  const name =
    firstProp(p, "osloc_dataset_name", "osloc_export_name") ||
    (id === "legacy" ? "Legacy OS-LOC-DAT-VIZ data" : id);
  const schema = firstProp(p, "osloc_schema_version") || "legacy";
  return { id, name, schema };
}

function eventKeyFromProps(p) {
  const eventId = firstProp(p, "osloc_event_id");
  if (!eventId) return "";
  const dataset = datasetMeta(p);
  return `${dataset.id}::${eventId}`;
}

function isIntentionallyHiddenKmlAnchorFeature(feature) {
  if (feature?.geometry?.type !== "Point") return false;

  const p = feature?.properties ?? {};
  const componentType = firstProp(p, "osloc_component_type");
  const eventType = firstProp(p, "osloc_event_type");

  // These are scale=0 label anchors in the KML generator. They are not
  // intended to be visible point symbols.
  if (
    eventType === "tower_sector" ||
    eventType === "tower_sector_distance" ||
    eventType === "tower_no_azimuth"
  ) {
    if (
      componentType === "center_point" ||
      componentType === "tower_sector" ||
      componentType === "coverage_circle"
    ) {
      return true;
    }
  }

  if (
    eventType === "location_accuracy" &&
    (
      componentType === "location_point" ||
      componentType === "accuracy_circle"
    )
  ) {
    return true;
  }

  // Deliberately NOT hidden:
  // - distance_only center_point (visible red center pin in current KML)
  // - location event without an accuracy circle (visible GPS point)
  return false;
}

function restoreHiddenAnchorSymbolStyles() {
  const map = state.app?.getMap?.();
  if (!map) return;

  for (const [layerId, original] of state.hiddenAnchorOriginalIconSizes.entries()) {
    try {
      if (!map.getLayer?.(layerId)) continue;
      map.setLayoutProperty?.(
        layerId,
        "icon-size",
        original.hadProperty ? original.value : null
      );
    } catch { }
  }

  state.hiddenAnchorOriginalIconSizes = new Map();
  state.hiddenAnchorSuppressedSymbolLayerIds = new Set();
}

function applyHiddenAnchorSymbolSuppression() {
  const map = state.app?.getMap?.();
  if (!map) return;

  for (const layerId of state.hiddenAnchorSymbolLayerIds) {
    try {
      const layer = map.getLayer?.(layerId);
      if (!layer) continue;

      if (!state.hiddenAnchorOriginalIconSizes.has(layerId)) {
        const layout = layer.layout ?? {};
        const hadProperty = Object.prototype.hasOwnProperty.call(layout, "icon-size");
        state.hiddenAnchorOriginalIconSizes.set(layerId, {
          hadProperty,
          value: hadProperty ? layout["icon-size"] : undefined,
        });
      }

      // Hide only the point icon. Any text label in the same symbol layer is
      // intentionally left alone.
      if (state.hiddenAnchorSuppressedSymbolLayerIds.has(layerId)) continue;
      map.setLayoutProperty?.(layerId, "icon-size", 0);
      state.hiddenAnchorSuppressedSymbolLayerIds.add(layerId);
    } catch { }
  }
}

function parseKmlColorAabbggrr(value, fallbackRgba) {
  const color = String(value ?? "").trim().toLowerCase();
  const match = color.match(/^[0-9a-f]{8}$/);
  if (!match) return fallbackRgba;

  const aa = parseInt(color.slice(0, 2), 16);
  const bb = parseInt(color.slice(2, 4), 16);
  const gg = parseInt(color.slice(4, 6), 16);
  const rr = parseInt(color.slice(6, 8), 16);
  const alpha = Number((aa / 255).toFixed(3));
  return `rgba(${rr}, ${gg}, ${bb}, ${alpha})`;
}

function anyEqualsExpr(prop, values) {
  if (!values.length) return ["==", 1, 0];
  if (values.length === 1) return ["==", ["get", prop], values[0]];
  return ["any", ...values.map(value => ["==", ["get", prop], value])];
}

function composeBaseFilter(existingFilter, extraFilter) {
  if (!existingFilter) return extraFilter;
  if (!extraFilter) return existingFilter;
  return ["all", existingFilter, extraFilter];
}

function firstFeatureFromLayerSource(map, layer) {
  const sourceId = typeof layer?.source === "string" ? layer.source : "";
  if (!sourceId) return null;

  try {
    const sourceLayer = layer?.["source-layer"] || "";
    const options = sourceLayer ? { sourceLayer } : undefined;
    const features = map.querySourceFeatures?.(sourceId, options) ?? [];
    return features.find(feature => eventKeyFromProps(feature?.properties ?? {})) ?? null;
  } catch { }

  return null;
}

function stylePaletteForLayer(map, layer) {
  const feature = firstFeatureFromLayerSource(map, layer);
  const p = feature?.properties ?? {};

  const legColor = firstProp(p, "osloc_style_leg_color") || "ff000000";
  const shadedColor = firstProp(p, "osloc_style_shaded_color") || "7d00ffff";
  const bandColor = firstProp(p, "osloc_style_band_color") || "7dff9900";
  const gpsLineColor = firstProp(p, "osloc_style_gps_line_color") || "ff00ff00";
  const gpsFillColor = firstProp(p, "osloc_style_gps_fill_color") || "4d00ff00";
  const reportedDistanceColor = firstProp(p, "osloc_style_reported_distance_color") || "ff000000";
  const distanceCenterColor = firstProp(p, "osloc_style_distance_center_color") || "ff0000ff";

  return {
    legLine: parseKmlColorAabbggrr(legColor, "rgba(0, 0, 0, 1)"),
    towerFill: parseKmlColorAabbggrr(shadedColor, "rgba(255, 255, 0, 0.49)"),
    distanceFill: parseKmlColorAabbggrr(bandColor, "rgba(255, 153, 0, 0.49)"),
    gpsLine: parseKmlColorAabbggrr(gpsLineColor, "rgba(0, 255, 0, 1)"),
    gpsFill: parseKmlColorAabbggrr(gpsFillColor, "rgba(0, 255, 0, 0.30)"),
    reportedDistance: parseKmlColorAabbggrr(reportedDistanceColor, "rgba(0, 0, 0, 1)"),
    distanceCenter: parseKmlColorAabbggrr(distanceCenterColor, "rgba(255, 0, 0, 1)"),
  };
}

function sharedPointVisibilityFilter() {
  return ["any",
    ["all",
      ["==", ["get", "osloc_event_type"], "distance_only"],
      ["==", ["get", "osloc_component_type"], "center_point"]
    ],
    ["all",
      ["==", ["get", "osloc_event_type"], "location"],
      ["==", ["get", "osloc_component_type"], "location_point"]
    ]
  ];
}

function isGeojsonEvidenceFeature(feature) {
  const p = feature?.properties ?? {};
  return Boolean(
    eventKeyFromProps(p) &&
    (
      firstProp(p, "osloc_event_key") ||
      firstProp(p, "osloc_source_coordinate_text") ||
      firstProp(p, "osloc_style_leg_color") ||
      firstProp(p, "osloc_style_leg_color_rgba")
    )
  );
}

function stableLayerToken(value) {
  let hash = 2166136261;
  for (const character of String(value)) {
    hash ^= character.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function sourceGroupKey(sourceId, sourceLayer) {
  return `${sourceId}\u0000${sourceLayer || ""}`;
}

function evidenceLayerIds(groupKey) {
  const token = stableLayerToken(groupKey);
  return {
    fill: `${EVIDENCE_LAYER_PREFIX}fill-${token}`,
    line: `${EVIDENCE_LAYER_PREFIX}line-${token}`,
    point: `${EVIDENCE_LAYER_PREFIX}point-${token}`,
  };
}

function featureColorExpression(property, fallback) {
  return ["coalesce", ["get", property], fallback];
}

function pluginEvidenceLayerDefinitions(group) {
  const ids = evidenceLayerIds(group.key);
  const source = { source: group.sourceId };
  if (group.sourceLayer) source["source-layer"] = group.sourceLayer;

  const fillFilter = ["all",
    ["==", ["geometry-type"], "Polygon"],
    anyEqualsExpr("osloc_component_type", SHARED_FILL_COMPONENTS)
  ];
  const lineFilter = ["all",
    ["==", ["geometry-type"], "LineString"],
    anyEqualsExpr("osloc_component_type", SHARED_LINE_COMPONENTS)
  ];
  const pointFilter = ["all",
    ["==", ["geometry-type"], "Point"],
    sharedPointVisibilityFilter()
  ];

  const palette = group.palette;
  const legLine = featureColorExpression("osloc_style_leg_color_rgba", palette.legLine);
  const towerFill = featureColorExpression("osloc_style_shaded_color_rgba", palette.towerFill);
  const distanceFill = featureColorExpression("osloc_style_band_color_rgba", palette.distanceFill);
  const gpsLine = featureColorExpression("osloc_style_gps_line_color_rgba", palette.gpsLine);
  const gpsFill = featureColorExpression("osloc_style_gps_fill_color_rgba", palette.gpsFill);
  const reportedDistance = featureColorExpression(
    "osloc_style_reported_distance_color_rgba",
    palette.reportedDistance
  );
  const distanceCenter = featureColorExpression(
    "osloc_style_distance_center_color_rgba",
    palette.distanceCenter
  );

  return [
    {
      id: ids.fill,
      type: "fill",
      ...source,
      filter: fillFilter,
      metadata: { oslocPluginOwned: true, oslocSourceGroup: group.key },
      layout: { visibility: "none" },
      paint: {
        "fill-color": ["case",
          ["==", ["get", "osloc_component_type"], "distance_band"], distanceFill,
          ["==", ["get", "osloc_component_type"], "accuracy_circle"], gpsFill,
          towerFill
        ],
        "fill-outline-color": ["case",
          ["==", ["get", "osloc_component_type"], "distance_band"], distanceFill,
          ["==", ["get", "osloc_component_type"], "accuracy_circle"], gpsLine,
          legLine
        ],
      },
    },
    {
      id: ids.line,
      type: "line",
      ...source,
      filter: lineFilter,
      metadata: { oslocPluginOwned: true, oslocSourceGroup: group.key },
      layout: { visibility: "none" },
      paint: {
        "line-color": ["case",
          ["==", ["get", "osloc_component_type"], "accuracy_circle"], gpsLine,
          ["==", ["get", "osloc_component_type"], "reported_distance"], reportedDistance,
          legLine
        ],
        "line-width": ["case",
          ["==", ["get", "osloc_component_type"], "coverage_circle"], 1,
          2
        ],
      },
    },
    {
      id: ids.point,
      type: "circle",
      ...source,
      filter: pointFilter,
      metadata: { oslocPluginOwned: true, oslocSourceGroup: group.key },
      layout: { visibility: "none" },
      paint: {
        "circle-color": ["case",
          ["==", ["get", "osloc_event_type"], "distance_only"], distanceCenter,
          gpsLine
        ],
        "circle-radius": 4,
        "circle-stroke-width": 1,
        "circle-stroke-color": "rgba(0, 0, 0, 0.75)",
      },
    },
  ];
}

function restoreSuppressedHostLayer(map, layerId) {
  const original = state.hostLayerOriginalVisibility.get(layerId) ?? "visible";
  const originalFilter = state.hostLayerOriginalFilter.get(layerId) ?? null;
  try {
    if (map.getLayer?.(layerId)) {
      map.setLayoutProperty?.(layerId, "visibility", original);
      map.setFilter?.(layerId, originalFilter);
    }
  } catch { }
  state.hostLayerOriginalVisibility.delete(layerId);
  state.hostLayerOriginalFilter.delete(layerId);
}

function takeOwnershipOfGeojsonSources(map, groups) {
  const previousPluginLayerIds = new Set(state.pluginEvidenceLayerIds);
  const previousSuppressedHostIds = new Set(state.suppressedHostLayerIds);
  const nextPluginLayerIds = new Set();
  const nextSuppressedHostIds = new Set();

  for (const group of groups.values()) {
    const eventKeys = [...group.eventKeys].sort();
    if (!eventKeys.length) continue;

    for (const hostLayerId of group.hostLayerIds) {
      const hostLayer = map.getLayer?.(hostLayerId);
      if (!hostLayer) continue;

      nextSuppressedHostIds.add(hostLayerId);
      if (!state.hostLayerOriginalVisibility.has(hostLayerId)) {
        state.hostLayerOriginalVisibility.set(
          hostLayerId,
          String(hostLayer.layout?.visibility ?? "visible")
        );
        state.hostLayerOriginalFilter.set(hostLayerId, hostLayer.filter ?? null);
      }

      if (String(hostLayer.layout?.visibility ?? "visible") !== "none") {
        try { map.setLayoutProperty?.(hostLayerId, "visibility", "none"); }
        catch { }
      }
      if (JSON.stringify(hostLayer.filter ?? null) !== JSON.stringify(NEVER_MATCH_FILTER)) {
        try { map.setFilter?.(hostLayerId, NEVER_MATCH_FILTER); }
        catch { }
      }
    }

    for (const definition of pluginEvidenceLayerDefinitions(group)) {
      nextPluginLayerIds.add(definition.id);
      previousPluginLayerIds.delete(definition.id);

      try {
        if (!map.getLayer?.(definition.id)) {
          map.addLayer?.(definition);
        }
      } catch (err) {
        console.warn(`[OSLOC] Could not create evidence layer ${definition.id}`, err);
        continue;
      }

      if (!map.getLayer?.(definition.id)) continue;
      state.sharedNativeLayerBaseFilter.set(definition.id, definition.filter);
      state.sharedNativeLayerEventKeys.set(definition.id, eventKeys);
      state.sharedNativeLayerSupportsEpochs.set(definition.id, group.supportsEpochs);
      state.mappingStats.sharedFilteredLayers++;
    }
  }

  for (const layerId of previousPluginLayerIds) {
    try {
      if (map.getLayer?.(layerId)) map.removeLayer?.(layerId);
    } catch { }
  }

  for (const layerId of previousSuppressedHostIds) {
    if (!nextSuppressedHostIds.has(layerId)) {
      restoreSuppressedHostLayer(map, layerId);
    }
  }

  state.geojsonSourceGroups = groups;
  state.pluginEvidenceLayerIds = nextPluginLayerIds;
  state.suppressedHostLayerIds = nextSuppressedHostIds;
  state.mappingStats.ownedEvidenceLayers = nextPluginLayerIds.size;
  state.mappingStats.suppressedHostLayers = nextSuppressedHostIds.size;
}

function removeGeojsonRenderingOwnership() {
  const map = state.app?.getMap?.();
  if (!map) return;

  for (const layerId of state.pluginEvidenceLayerIds) {
    try {
      if (map.getLayer?.(layerId)) map.removeLayer?.(layerId);
    } catch { }
  }
  for (const layerId of state.suppressedHostLayerIds) {
    restoreSuppressedHostLayer(map, layerId);
  }

  state.geojsonSourceGroups = new Map();
  state.pluginEvidenceLayerIds = new Set();
  state.suppressedHostLayerIds = new Set();
  state.hostLayerOriginalVisibility = new Map();
  state.hostLayerOriginalFilter = new Map();
}

function nativeStyleSignature(map) {
  return (map?.getStyle?.()?.layers ?? [])
    .filter(layer => !isPluginOwnedLayer(layer))
    .map(layer => [
      String(layer?.id ?? ""),
      String(layer?.type ?? ""),
      String(layer?.source ?? ""),
      String(layer?.["source-layer"] ?? ""),
    ].join("|"))
    .sort()
    .join("\n");
}

function knownGeojsonGroupsForCurrentStyle(map) {
  const styleLayers = map?.getStyle?.()?.layers ?? [];
  const groups = new Map();

  for (const existing of state.geojsonSourceGroups.values()) {
    const group = {
      ...existing,
      eventKeys: new Set(existing.eventKeys),
      hostLayerIds: new Set(),
    };

    for (const layer of styleLayers) {
      if (isPluginOwnedLayer(layer)) continue;
      if (String(layer?.source ?? "") !== group.sourceId) continue;
      if (String(layer?.["source-layer"] ?? "") !== group.sourceLayer) continue;
      group.hostLayerIds.add(String(layer.id));
    }

    groups.set(group.key, group);
  }

  return groups;
}

function reconcileGeojsonRendering() {
  const map = state.app?.getMap?.();
  if (!map || nativeReconcileInProgress || !state.events.length) return;

  nativeReconcileInProgress = true;
  try {
    const signature = nativeStyleSignature(map);
    if (
      signature !== lastNativeStyleSignature ||
      !state.geojsonSourceGroups.size
    ) {
      rebuildNativeIndex(safeListLayers());
      state.sharedNativeLayerAppliedSignature = new Map();
      state.sharedNativeLayerVisibilityById = new Map();
      lastVisibilitySignature = "";
      applyVisibility(true);
      lastNativeStyleSignature = nativeStyleSignature(map);
      return;
    }

    const pluginLayerMissing = [...state.pluginEvidenceLayerIds]
      .some(layerId => !map.getLayer?.(layerId));
    const hostLayerUnsuppressed = [...state.suppressedHostLayerIds].some(layerId => {
      const layer = map.getLayer?.(layerId);
      return layer && (
        String(layer.layout?.visibility ?? "visible") !== "none" ||
        JSON.stringify(layer.filter ?? null) !== JSON.stringify(NEVER_MATCH_FILTER)
      );
    });

    if (
      !pluginLayerMissing &&
      !hostLayerUnsuppressed
    ) {
      return;
    }

    const groups = knownGeojsonGroupsForCurrentStyle(map);
    takeOwnershipOfGeojsonSources(map, groups);
    state.sharedNativeLayerAppliedSignature = new Map();
    state.sharedNativeLayerVisibilityById = new Map();
    lastVisibilitySignature = "";
    applyVisibility(true);
    lastNativeStyleSignature = nativeStyleSignature(map);
  } finally {
    nativeReconcileInProgress = false;
  }
}

function scheduleRenderingReconcile() {
  if (renderReconcileTimer !== null) clearTimeout(renderReconcileTimer);
  renderReconcileTimer = setTimeout(() => {
    renderReconcileTimer = null;
    reconcileGeojsonRendering();
  }, 80);
}

function applySharedLayerStyling() {
  const map = state.app?.getMap?.();
  if (!map) return;

  for (const layerId of state.sharedNativeLayerEventKeys.keys()) {
    if (state.pluginEvidenceLayerIds.has(layerId)) continue;
    const layer = map.getLayer?.(layerId);
    if (!layer) continue;

    const palette = stylePaletteForLayer(map, layer);
    const type = String(layer.type || "");

    if (type === "fill") {
      const componentFilter = anyEqualsExpr("osloc_component_type", SHARED_FILL_COMPONENTS);
      state.sharedNativeLayerBaseFilter.set(
        layerId,
        composeBaseFilter(state.sharedNativeLayerBaseFilter.get(layerId) ?? null, componentFilter)
      );

      try {
        map.setPaintProperty?.(layerId, "fill-color", ["case",
          ["==", ["get", "osloc_component_type"], "distance_band"], palette.distanceFill,
          ["==", ["get", "osloc_component_type"], "accuracy_circle"], palette.gpsFill,
          palette.towerFill
        ]);
        map.setPaintProperty?.(layerId, "fill-outline-color", ["case",
          ["==", ["get", "osloc_component_type"], "distance_band"], palette.distanceFill,
          ["==", ["get", "osloc_component_type"], "accuracy_circle"], palette.gpsLine,
          palette.legLine
        ]);
      } catch { }
      continue;
    }

    if (type === "line") {
      const componentFilter = anyEqualsExpr("osloc_component_type", SHARED_LINE_COMPONENTS);
      state.sharedNativeLayerBaseFilter.set(
        layerId,
        composeBaseFilter(state.sharedNativeLayerBaseFilter.get(layerId) ?? null, componentFilter)
      );

      try {
        map.setPaintProperty?.(layerId, "line-color", ["case",
          ["==", ["get", "osloc_component_type"], "accuracy_circle"], palette.gpsLine,
          ["==", ["get", "osloc_component_type"], "reported_distance"], palette.reportedDistance,
          palette.legLine
        ]);
        map.setPaintProperty?.(layerId, "line-width", ["case",
          ["==", ["get", "osloc_component_type"], "coverage_circle"], 1,
          2
        ]);
      } catch { }
      continue;
    }

    if (type === "circle") {
      const componentFilter = sharedPointVisibilityFilter();
      state.sharedNativeLayerBaseFilter.set(
        layerId,
        composeBaseFilter(state.sharedNativeLayerBaseFilter.get(layerId) ?? null, componentFilter)
      );

      try {
        map.setPaintProperty?.(layerId, "circle-color", ["case",
          ["==", ["get", "osloc_event_type"], "distance_only"], palette.distanceCenter,
          palette.gpsLine
        ]);
        map.setPaintProperty?.(layerId, "circle-radius", 4);
        map.setPaintProperty?.(layerId, "circle-stroke-width", 1);
        map.setPaintProperty?.(layerId, "circle-stroke-color", "rgba(0, 0, 0, 0.75)");
      } catch { }
      continue;
    }

    if (type === "symbol") {
      // Keep text labels if any, but hide icon anchors unless component/event
      // semantics explicitly require visible points.
      const componentFilter = anyEqualsExpr(
        "osloc_component_type",
        [...SHARED_FILL_COMPONENTS, ...SHARED_LINE_COMPONENTS, "center_point", "location_point"]
      );
      state.sharedNativeLayerBaseFilter.set(
        layerId,
        composeBaseFilter(state.sharedNativeLayerBaseFilter.get(layerId) ?? null, componentFilter)
      );

      try {
        map.setLayoutProperty?.(layerId, "icon-size", ["case",
          ["all",
            ["==", ["get", "osloc_event_type"], "distance_only"],
            ["==", ["get", "osloc_component_type"], "center_point"]
          ], 1,
          ["all",
            ["==", ["get", "osloc_event_type"], "location"],
            ["==", ["get", "osloc_component_type"], "location_point"]
          ], 1,
          0
        ]);
        map.setPaintProperty?.(layerId, "icon-color", ["case",
          ["==", ["get", "osloc_event_type"], "distance_only"], palette.distanceCenter,
          palette.gpsLine
        ]);
      } catch { }
    }
  }
}

function restoreSharedLayerFilters() {
  const map = state.app?.getMap?.();
  if (!map?.setFilter) return;

  for (const [layerId, baseFilter] of state.sharedNativeLayerBaseFilter.entries()) {
    if (state.pluginEvidenceLayerIds.has(layerId)) continue;
    try {
      if (!map.getLayer?.(layerId)) continue;
      map.setFilter(layerId, baseFilter ?? null);
    } catch { }
  }

  state.sharedNativeLayerAppliedSignature = new Map();
  state.sharedNativeLayerVisibilityById = new Map();
}

function buildSharedLayerFilter(baseFilter, visibleKeys, useEventKeys = false) {
  const impossible = ["==", 1, 0];
  const ids = useEventKeys
    ? visibleKeys
    : visibleKeys.map(key => {
      const splitAt = key.indexOf("::");
      return splitAt >= 0 ? key.slice(splitAt + 2) : "";
    });
  const filteredIds = ids.filter(Boolean);

  const visibleFilter = filteredIds.length
    ? [
      "match",
      ["get", useEventKeys ? "osloc_event_key" : "osloc_event_id"],
      filteredIds,
      true,
      false,
    ]
    : impossible;

  if (!baseFilter) return visibleFilter;
  return ["all", baseFilter, visibleFilter];
}

function allEventsEnabledForLayer(layerEventKeys) {
  return layerEventKeys.every(key => state.enabledEventKeys.has(key));
}

function buildTimelineEpochFilter(baseFilter) {
  if (state.currentMs === null) {
    return composeBaseFilter(baseFilter, ["==", 1, 0]);
  }

  const endExpression = state.durationOverrideMs === null
    ? ["get", END_EPOCH_PROPERTY]
    : ["+", ["get", START_EPOCH_PROPERTY], state.durationOverrideMs];
  const activeFilter = ["any",
    ["!", ["has", START_EPOCH_PROPERTY]],
    ["all",
      ["has", END_EPOCH_PROPERTY],
      ["<=", ["get", START_EPOCH_PROPERTY], state.currentMs],
      [">", endExpression, state.currentMs]
    ]
  ];
  return composeBaseFilter(baseFilter, activeFilter);
}

function sharedLayerFilterState(layerId, layerEventKeys, visibleForLayer) {
  const baseFilter = state.sharedNativeLayerBaseFilter.get(layerId) ?? null;

  if (!visibleForLayer.length) {
    return {
      signature: "hidden",
      visibility: "none",
      filter: composeBaseFilter(baseFilter, ["==", 1, 0]),
    };
  }

  const allEnabled = allEventsEnabledForLayer(layerEventKeys);
  const supportsEpochs = state.sharedNativeLayerSupportsEpochs.get(layerId) === true;

  if (
    state.mode === "overview" &&
    allEnabled &&
    visibleForLayer.length === layerEventKeys.length
  ) {
    return {
      signature: "overview-all",
      visibility: "visible",
      filter: baseFilter,
    };
  }

  if (
    state.mode === "timeline" &&
    allEnabled &&
    supportsEpochs &&
    !dateFilterActive()
  ) {
    return {
      signature: `timeline:${state.currentMs}`,
      visibility: "visible",
      filter: buildTimelineEpochFilter(baseFilter),
    };
  }

  return {
    signature: `events:${visibleForLayer.join("|")}`,
    visibility: "visible",
    filter: buildSharedLayerFilter(
      baseFilter,
      visibleForLayer,
      state.pluginEvidenceLayerIds.has(layerId)
    ),
  };
}

function isTemporalEvent(event) {
  return Number.isFinite(event?.startMs) && Number.isFinite(event?.endMs);
}

function dateFilterActive() {
  return !state.dateFilterAuto && Boolean(
    state.dateFilterStart || state.dateFilterEnd
  );
}

export function normalizeDateTimeFilterValue(value, through = false) {
  const text = String(value || "").trim();
  if (!text) return "";

  const match = text.match(
    /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?$/
  );
  if (!match) return null;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  const validDate = parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day;
  if (!validDate) return null;

  if (match[4] === undefined) {
    return `${match[1]}-${match[2]}-${match[3]}T${through ? "23:59" : "00:00"}`;
  }

  const hour = Number(match[4]);
  const minute = Number(match[5]);
  if (hour > 23 || minute > 59) return null;
  return `${match[1]}-${match[2]}-${match[3]}T${match[4]}:${match[5]}`;
}

export function eventDisplayMinute(event) {
  if (!isTemporalEvent(event)) return "";

  const literalLocal = String(event.localStart || "").match(
    /^\s*(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})/
  );
  if (literalLocal) {
    return `${literalLocal[1]}T${literalLocal[2].padStart(2, "0")}:${literalLocal[3]}`;
  }

  if (isUsableIanaZone(event.timezone)) {
    const parts = Object.fromEntries(
      new Intl.DateTimeFormat("en-US", {
        timeZone: event.timezone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).formatToParts(new Date(event.startMs))
        .filter(part => part.type !== "literal")
        .map(part => [part.type, part.value])
    );
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
  }

  const fixedOffset = String(event.timezone || "").match(
    /(?:FIXED\s+)?UTC\s*([+-])\s*(\d{1,2}):(\d{2})/i
  );
  if (fixedOffset) {
    const direction = fixedOffset[1] === "+" ? 1 : -1;
    const minutes = direction * (
      Number(fixedOffset[2]) * 60 + Number(fixedOffset[3])
    );
    return new Date(event.startMs + minutes * 60000).toISOString().slice(0, 16);
  }

  return new Date(event.startMs).toISOString().slice(0, 16);
}

export function eventDateTimeBounds(events = state.events) {
  const minutes = (events ?? [])
    .map(eventDisplayMinute)
    .filter(Boolean)
    .sort();
  return {
    start: minutes[0] ?? "",
    end: minutes[minutes.length - 1] ?? "",
  };
}

function updateAutomaticDateFilterBounds() {
  if (!state.dateFilterAuto) return;
  const bounds = eventDateTimeBounds();
  state.dateFilterStart = bounds.start;
  state.dateFilterEnd = bounds.end;
}

export function eventMatchesDateTimeBounds(event, start, end) {
  const eventMinute = eventDisplayMinute(event);
  if (!eventMinute) return false;
  if (start && eventMinute < start) return false;
  if (end && eventMinute > end) return false;
  return true;
}

function eventMatchesDateFilter(event) {
  if (!dateFilterActive()) return true;
  return eventMatchesDateTimeBounds(
    event, state.dateFilterStart, state.dateFilterEnd
  );
}

function eventsMatchingDateFilter(events = state.events) {
  return (events ?? []).filter(eventMatchesDateFilter);
}

function applyDateFilter(startValue, endValue) {
  const start = normalizeDateTimeFilterValue(startValue, false);
  const end = normalizeDateTimeFilterValue(endValue, true);

  if (start === null || end === null || (start && end && start > end)) {
    return false;
  }

  stopPlayback();
  state.dateFilterStart = start;
  state.dateFilterEnd = end;
  state.dateFilterAuto = false;

  rebuildTimelineBoundaries();
  const range = timelineRange();
  if (!range) {
    state.currentMs = null;
  } else if (
    state.currentMs === null ||
    state.currentMs < range.min ||
    state.currentMs > range.max
  ) {
    state.currentMs = range.min;
  }

  if (
    state.selectedEventKey &&
    !eventMatchesDateFilter(state.eventByKey.get(state.selectedEventKey))
  ) {
    state.selectedEventKey = null;
    state.app?.closeFloatingPanel?.(DETAILS_ID);
    unregisterDetails?.();
    unregisterDetails = null;
  }

  lastVisibilitySignature = "";
  state.lastVisibleEventSignature = "";
  state.lastLabelSignature = "";
  applyVisibility(true);
  renderPanelSafe();
  renderTimelineOverlay();
  return true;
}

function effectiveEndMs(event) {
  if (!isTemporalEvent(event)) return NaN;

  return state.durationOverrideMs === null
    ? event.endMs
    : event.startMs + state.durationOverrideMs;
}

function rebuildTimelineBoundaries() {
  const boundaries = [];
  const timezones = new Set();
  for (const event of state.events) {
    if (!isTemporalEvent(event) || !eventMatchesDateFilter(event)) continue;
    boundaries.push(event.startMs, effectiveEndMs(event));
    if (event.timezone) timezones.add(event.timezone);
  }
  boundaries.sort((a, b) => a - b);
  state.timelineBoundaries = boundaries.filter(
    (value, index) => index === 0 || value !== boundaries[index - 1]
  );
  state.commonTimezoneValue = timezones.size === 1 ? [...timezones][0] : "";

  const range = timelineRange();
  if (!range) {
    state.timelineIncludesDate = false;
  } else if (isUsableIanaZone(state.commonTimezoneValue)) {
    const formatter = new Intl.DateTimeFormat("en-CA", {
      timeZone: state.commonTimezoneValue,
      year: "numeric", month: "2-digit", day: "2-digit"
    });
    state.timelineIncludesDate =
      formatter.format(new Date(range.min)) !== formatter.format(new Date(range.max));
  } else {
    state.timelineIncludesDate =
      new Date(range.min).toISOString().slice(0, 10) !==
      new Date(range.max).toISOString().slice(0, 10);
  }
}

function timelineBoundaryBucket(ms) {
  if (ms === null || !state.timelineBoundaries.length) return -1;

  let low = 0;
  let high = state.timelineBoundaries.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (state.timelineBoundaries[middle] <= ms) low = middle + 1;
    else high = middle;
  }
  return low - 1;
}

function markEnabledEventsChanged() {
  state.enabledEventsVersion++;
}

function effectiveDurationMs(event) {
  if (!isTemporalEvent(event)) return 0;
  return Math.max(0, effectiveEndMs(event) - event.startMs);
}

function parseDescription(value) {
  if (!value) return "";
  const raw = String(value);
  // Preserve useful line breaks while stripping simple HTML if a viewer exposes HTML descriptions.
  const withBreaks = raw
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>/gi, "\n")
    .replace(/<\/div>/gi, "\n");
  const holder = document.createElement("div");
  holder.innerHTML = withBreaks;

  const tableRows = [...holder.querySelectorAll("tr")]
    .map(row => [...row.querySelectorAll("th, td")]
      .map(cell => (cell.textContent || "").replace(/\s+/g, " ").trim())
      .filter(Boolean)
      .join(" "))
    .filter(Boolean);
  if (tableRows.length) return tableRows.join("\n");

  return (holder.textContent || holder.innerText || "")
    .replace(/\r/g, "")
    .replace(/\n[ \t]+\n/g, "\n\n")
    .trim();
}

function detailDescriptionForFeature(event, feature = null) {
  const clickedComponent = firstProp(
    feature?.properties ?? {},
    "osloc_component_type"
  );
  const anchorByEventType = {
    tower_sector: "tower_sector",
    tower_no_azimuth: "coverage_circle",
    distance_only: "distance_band",
    location_accuracy: "accuracy_circle",
    location: "location_point",
  };
  const anchorComponent = event?.eventType === "tower_sector_distance"
    ? (["distance_band", "reported_distance"].includes(clickedComponent)
      ? "distance_band"
      : "tower_sector")
    : anchorByEventType[event?.eventType];

  for (const candidate of event?.features ?? []) {
    const properties = candidate?.properties ?? {};
    if (
      anchorComponent &&
      firstProp(properties, "osloc_component_type") !== anchorComponent
    ) {
      continue;
    }
    const description = parseDescription(
      firstProp(properties, "description", "Description", "popupContent", "popup")
    );
    if (description) return description;
  }

  return event?.description || parseDescription(
    firstProp(
      feature?.properties ?? {},
      "description", "Description", "popupContent", "popup"
    )
  );
}

function machineLocal(ms) {
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString([], {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "numeric", minute: "2-digit", second: "2-digit"
  });
}

function utcDateTime(ms) {
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = n => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`;
}

function utcClock(ms) {
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = n => String(n).padStart(2, "0");
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
}

function displayLocal(event) {
  if (event.displayTime) return event.displayTime;
  if (event.localStart) return event.localStart.replace("T", " ");
  if (isTemporalEvent(event)) return `${machineLocal(event.startMs)} (viewer local)`;
  return "";
}

function inferLabel(event) {
  if (event.label) return event.label;
  const local = displayLocal(event);
  if (local) return local;
  if (event.eventType) return humanizeEventType(event.eventType);
  return event.id;
}

function humanizeEventType(value) {
  const known = {
    tower_sector: "Tower sector",
    tower_sector_distance: "Tower sector + distance",
    tower_no_azimuth: "Tower / no azimuth",
    distance_only: "Distance only",
    location_accuracy: "Location + accuracy",
    location: "Location",
  };

  if (known[value]) return known[value];

  return String(value || "Event")
    .replaceAll("_", " ")
    .replace(/\b\w/g, ch => ch.toUpperCase());
}

function formatDurationMs(durationMs) {
  let totalSeconds = Math.max(0, Math.round(durationMs / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  totalSeconds -= hours * 3600;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds - minutes * 60;

  const parts = [];
  if (hours) parts.push(`${hours} hr${hours === 1 ? "" : "s"}`);
  if (minutes) parts.push(`${minutes} min`);
  if (seconds && !hours) parts.push(`${seconds} sec`);

  return parts.join(" ") || "0 sec";
}

function formatDisplayDuration(event) {
  if (!isTemporalEvent(event)) return "";
  return formatDurationMs(effectiveDurationMs(event));
}

function isUtcLikeTimezone(zone) {
  const z = String(zone || "").trim().toUpperCase().replace(/\s+/g, " ");
  if (!z) return false;

  return (
    z === "UTC" ||
    z === "GMT" ||
    z === "Z" ||
    z === "FIXED UTC +00:00" ||
    z === "FIXED UTC 00:00" ||
    z === "UTC +00:00" ||
    z === "UTC+00:00" ||
    z === "GMT +00:00" ||
    z === "GMT+00:00"
  );
}

function eventDisplayIsUtc(event) {
  if (isUtcLikeTimezone(event.timezone)) return true;

  const local = String(event.localStart || "");
  return /(?:Z|[+-]00:00)$/i.test(local);
}

function shouldShowUtcEquivalent(event) {
  return isTemporalEvent(event) && !eventDisplayIsUtc(event);
}

function formatClock12(hour, minute, second = null) {
  const h = Number(hour);
  const m = Number(minute);
  const s = second === null ? null : Number(second);

  if (![h, m].every(Number.isFinite) || (s !== null && !Number.isFinite(s))) {
    return "";
  }

  const suffix = h >= 12 ? "PM" : "AM";
  const displayHour = h % 12 || 12;
  const mm = String(m).padStart(2, "0");
  const ss = s === null ? "" : `:${String(s).padStart(2, "0")}`;

  return `${displayHour}:${mm}${ss} ${suffix}`;
}

function formatLiteralDateTime12(value) {
  if (!value) return "";

  // Preserve the written wall-clock value exactly; do not let JavaScript
  // reinterpret it through the viewer machine timezone.
  const m = String(value).match(
    /^\s*(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?/
  );

  if (!m) return String(value);

  const [, y, mo, d, hh, mm, ss] = m;
  return `${mo}/${d}/${y}, ${formatClock12(hh, mm, ss ?? null)}`;
}

function formatZonedDateTime12(ms, timeZone) {
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone,
    month: "2-digit",
    day: "2-digit",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  });
  const parts = Object.fromEntries(
    formatter.formatToParts(new Date(ms))
      .filter(part => part.type !== "literal")
      .map(part => [part.type, part.value])
  );
  return (
    `${parts.month}/${parts.day}/${parts.year}, ` +
    `${parts.hour}:${parts.minute}:${parts.second} ${parts.dayPeriod}`
  );
}

function formatCorrectedDisplayTime(event) {
  if (!isTemporalEvent(event)) return "";

  // IANA timezone: format the canonical UTC instant in the intended OS-LOC zone.
  if (isUsableIanaZone(event.timezone)) {
    return formatZonedDateTime12(event.startMs, event.timezone);
  }

  // Fixed-offset / literal local value: retain the wall-clock fields OS-LOC wrote.
  if (event.localStart) return formatLiteralDateTime12(event.localStart);

  // Final fallback only.
  return formatZonedDateTime12(event.startMs, undefined);
}

function formatRecordTime(event) {
  // Preserve the source/record-time text exactly as OS-LOC-DAT-VIZ wrote it.
  // Do not reinterpret it or force AM/PM formatting in the viewer.
  return event.displayTime ? String(event.displayTime) : "";
}

function formatTimezoneOffset(event) {
  const zone = String(event.timezone || "").trim();
  const local = String(event.localStart || "").trim();

  let offset = "";
  const offsetMatch = local.match(/(Z|[+-]\d{2}:\d{2})$/i);
  if (offsetMatch) {
    offset = offsetMatch[1].toUpperCase() === "Z"
      ? "UTC+00:00"
      : `UTC${offsetMatch[1]}`;
  }

  if (zone && offset) {
    // Avoid "Fixed UTC +00:00 (UTC+00:00)" style duplication.
    const compactZone = zone.replace(/\s+/g, "").toUpperCase();
    const compactOffset = offset.replace(/\s+/g, "").toUpperCase();

    if (
      compactZone.includes(compactOffset) ||
      (compactOffset === "UTC+00:00" && /UTC.*\+?00:00/i.test(zone))
    ) {
      return zone;
    }

    return `${zone} (${offset})`;
  }

  return zone || offset;
}

function formatMainEventLabel(event) {
  if (isTemporalEvent(event)) {
    return formatCorrectedDisplayTime(event) || inferLabel(event);
  }
  return inferLabel(event);
}

function temporalEvents() {
  return state.events.filter(event =>
    isTemporalEvent(event) && eventMatchesDateFilter(event)
  );
}

function timelineRange() {
  if (!state.timelineBoundaries.length) return null;

  return {
    min: state.timelineBoundaries[0],
    max: state.timelineBoundaries[state.timelineBoundaries.length - 1],
  };
}

function commonTimezone() {
  return state.commonTimezoneValue;
}

function isUsableIanaZone(zone) {
  if (!zone || !zone.includes("/")) return false;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: zone }).format(new Date());
    return true;
  } catch {
    return false;
  }
}

function formatPrimaryTimelineTime(ms, includeDate) {
  const zone = commonTimezone();
  const d = new Date(ms);

  if (isUsableIanaZone(zone)) {
    const opts = {
      timeZone: zone,
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      hour12: true,
    };
    if (includeDate) {
      opts.month = "2-digit";
      opts.day = "2-digit";
      opts.year = "numeric";
    }
    return d.toLocaleString([], opts);
  }

  // If multiple time zones are loaded, UTC is the only unambiguous common clock.
  if (!zone || state.datasets.length > 1) {
    const opts = {
      timeZone: "UTC",
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      hour12: true,
    };
    if (includeDate) {
      opts.month = "2-digit";
      opts.day = "2-digit";
      opts.year = "numeric";
    }
    return `${d.toLocaleString([], opts)} UTC`;
  }

  // Fixed-offset metadata is not directly understood by Intl. If it is UTC,
  // format it as a regular AM/PM clock. Event rows still show the explicit
  // corrected local wall-clock time from KML metadata.
  if (isUtcLikeTimezone(zone)) {
    const opts = {
      timeZone: "UTC",
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      hour12: true,
    };
    if (includeDate) {
      opts.month = "2-digit";
      opts.day = "2-digit";
      opts.year = "numeric";
    }
    return `${d.toLocaleString([], opts)} UTC`;
  }

  return includeDate ? utcDateTime(ms) : `${utcClock(ms)} UTC`;
}

function timelineNeedsDate() {
  return state.timelineIncludesDate;
}


function polygonCentroid(ring) {
  if (!Array.isArray(ring) || ring.length < 3) return null;

  let twiceArea = 0;
  let xTimes = 0;
  let yTimes = 0;

  for (let i = 0; i < ring.length - 1; i++) {
    const a = ring[i];
    const b = ring[i + 1];

    if (
      !Array.isArray(a) || !Array.isArray(b) ||
      !Number.isFinite(Number(a[0])) || !Number.isFinite(Number(a[1])) ||
      !Number.isFinite(Number(b[0])) || !Number.isFinite(Number(b[1]))
    ) {
      continue;
    }

    const ax = Number(a[0]);
    const ay = Number(a[1]);
    const bx = Number(b[0]);
    const by = Number(b[1]);

    const cross = ax * by - bx * ay;
    twiceArea += cross;
    xTimes += (ax + bx) * cross;
    yTimes += (ay + by) * cross;
  }

  if (Math.abs(twiceArea) < 1e-14) return null;

  const factor = 1 / (3 * twiceArea);
  return [xTimes * factor, yTimes * factor];
}

function eventTimeLabelAnchor(event) {
  /*
   * Sector events: place the adjusted time inside the actual sector wedge.
   * Location/GPS events and non-sector fallbacks: keep the label beside the
   * representative point.
   */
  if (
    event.eventType === "tower_sector" ||
    event.eventType === "tower_sector_distance"
  ) {
    for (const feature of event.features ?? []) {
      const p = feature?.properties ?? {};
      const componentType = firstProp(p, "osloc_component_type");
      const geometry = feature?.geometry;

      if (
        componentType === "tower_sector" &&
        geometry?.type === "Polygon" &&
        Array.isArray(geometry.coordinates?.[0])
      ) {
        const centroid = polygonCentroid(geometry.coordinates[0]);

        if (
          Array.isArray(centroid) &&
          Number.isFinite(centroid[0]) &&
          Number.isFinite(centroid[1])
        ) {
          return {
            coordinates: centroid,
            placement: "inside",
          };
        }
      }
    }
  }

  const priority = new Map([
    ["location_point", 0],
    ["center_point", 1],
    ["label_point", 2],
  ]);

  let best = null;
  let bestRank = Number.POSITIVE_INFINITY;

  for (const feature of event.features ?? []) {
    const geometry = feature?.geometry;
    if (!geometry || geometry.type !== "Point") continue;

    const coords = geometry.coordinates;
    if (
      !Array.isArray(coords) ||
      !Number.isFinite(Number(coords[0])) ||
      !Number.isFinite(Number(coords[1]))
    ) {
      continue;
    }

    const componentType = firstProp(
      feature?.properties ?? {},
      "osloc_component_type"
    );

    const rank = priority.has(componentType)
      ? priority.get(componentType)
      : 10;

    if (rank < bestRank) {
      bestRank = rank;
      best = [Number(coords[0]), Number(coords[1])];
    }
  }

  return best
    ? {
      coordinates: best,
      placement: "point",
    }
    : null;
}

function formatMapTimeLabel(event) {
  if (!isTemporalEvent(event)) return "";
  return formatCorrectedDisplayTime(event) || inferLabel(event);
}

function ensureMapLabelLayer() {
  const map = state.app?.getMap?.();
  if (!map) return false;

  try {
    if (!map.getSource?.(LABEL_SOURCE_ID)) {
      map.addSource(LABEL_SOURCE_ID, {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: [],
        },
      });
    }

    const commonPaint = {
      "text-color": "#111827",
      "text-halo-color": "rgba(255,255,255,0.98)",
      "text-halo-width": 2.5,
      "text-halo-blur": 0.5,
      "text-opacity": 1,
      "text-opacity-transition": {
        "duration": 0,
        "delay": 0,
      },
    };

    if (!map.getLayer?.(LABEL_INSIDE_LAYER_ID)) {
      map.addLayer({
        id: LABEL_INSIDE_LAYER_ID,
        type: "symbol",
        source: LABEL_SOURCE_ID,
        filter: ["==", ["get", "placement"], "inside"],
        layout: {
          "text-field": ["get", "label"],
          "text-size": 17,
          "text-anchor": "center",
          "text-offset": [0, 0],
          "text-allow-overlap": true,
          "text-ignore-placement": true,
          "visibility": state.labelsEnabled ? "visible" : "none",
        },
        paint: commonPaint,
      });
    }

    if (!map.getLayer?.(LABEL_POINT_LAYER_ID)) {
      map.addLayer({
        id: LABEL_POINT_LAYER_ID,
        type: "symbol",
        source: LABEL_SOURCE_ID,
        filter: ["==", ["get", "placement"], "point"],
        layout: {
          "text-field": ["get", "label"],
          "text-size": 17,
          "text-anchor": "left",
          "text-offset": [0.75, 0],
          "text-allow-overlap": true,
          "text-ignore-placement": true,
          "visibility": state.labelsEnabled ? "visible" : "none",
        },
        paint: commonPaint,
      });
    }

    return true;
  } catch (err) {
    console.warn("[OSLOC] Could not create time-label layers", err);
    return false;
  }
}

function updateMapLabels() {
  const map = state.app?.getMap?.();
  if (!map) return;

  if (!state.labelsEnabled) {
    if (state.labelLayersVisible) {
      try {
        map.setLayoutProperty?.(LABEL_INSIDE_LAYER_ID, "visibility", "none");
        map.setLayoutProperty?.(LABEL_POINT_LAYER_ID, "visibility", "none");
      } catch { }
      state.labelLayersVisible = false;
    }

    if (!state.labelsLastEmpty) {
      const disabledSource = map.getSource?.(LABEL_SOURCE_ID);
      if (disabledSource?.setData) {
        try {
          disabledSource.setData({ type: "FeatureCollection", features: [] });
        } catch { }
      }
      state.labelsLastEmpty = true;
      state.lastLabelSignature = "disabled";
    }
    return;
  }

  const visibleTemporalEvents = state.events.filter(event =>
    isTemporalEvent(event) && shouldShow(event)
  );

  if (!visibleTemporalEvents.length) {
    if (state.labelLayersVisible) {
      try {
        map.setLayoutProperty?.(LABEL_INSIDE_LAYER_ID, "visibility", "none");
        map.setLayoutProperty?.(LABEL_POINT_LAYER_ID, "visibility", "none");
      } catch { }
      state.labelLayersVisible = false;
    }

    if (!state.labelsLastEmpty) {
      const emptySource = map.getSource?.(LABEL_SOURCE_ID);
      if (emptySource?.setData) {
        try {
          emptySource.setData({ type: "FeatureCollection", features: [] });
        } catch { }
      }
      state.labelsLastEmpty = true;
      state.lastLabelSignature = "empty";
    }
    return;
  }

  if (!ensureMapLabelLayer()) return;

  const source = map.getSource?.(LABEL_SOURCE_ID);
  if (!source?.setData) return;

  const features = [];
  const signatureParts = [];

  for (const event of visibleTemporalEvents) {
    const anchor = eventTimeLabelAnchor(event);
    if (!anchor) continue;

    const label = formatMapTimeLabel(event);
    if (!label) continue;

    signatureParts.push(
      `${event.key}|${label}|${anchor.placement}|${anchor.coordinates[0]}|${anchor.coordinates[1]}`
    );

    features.push({
      type: "Feature",
      geometry: {
        type: "Point",
        coordinates: anchor.coordinates,
      },
      properties: {
        label,
        placement: anchor.placement,
        __oslocEventKey: event.key,
      },
    });
  }

  const newLabelSignature = signatureParts.join("\n");
  if (newLabelSignature === state.lastLabelSignature && state.labelLayersVisible) {
    return;
  }

  try {
    source.setData({
      type: "FeatureCollection",
      features,
    });
    if (!state.labelLayersVisible) {
      map.setLayoutProperty?.(LABEL_INSIDE_LAYER_ID, "visibility", "visible");
      map.setLayoutProperty?.(LABEL_POINT_LAYER_ID, "visibility", "visible");
      state.labelLayersVisible = true;
    }
    state.labelsLastEmpty = features.length === 0;
    state.lastLabelSignature = newLabelSignature;
  } catch (err) {
    console.warn("[OSLOC] Could not update time labels", err);
  }
}

function removeMapLabelLayer() {
  const map = state.app?.getMap?.();
  if (!map) return;

  for (const layerId of [LABEL_INSIDE_LAYER_ID, LABEL_POINT_LAYER_ID]) {
    try {
      if (map.getLayer?.(layerId)) {
        map.removeLayer(layerId);
      }
    } catch { }
  }

  try {
    if (map.getSource?.(LABEL_SOURCE_ID)) {
      map.removeSource(LABEL_SOURCE_ID);
    }
  } catch { }
}

function scanAll(reason = "scan") {
  const layers = safeListLayers();
  const previousEnabled = new Set(state.enabledEventKeys);
  const previousKeys = new Set(state.eventKeysKnownLastScan);
  const byEvent = new Map();

  for (const layer of layers) {
    const features = safeFeatures(layer.id);

    for (const feature of features) {
      const p = feature?.properties ?? {};
      const eventId = firstProp(p, "osloc_event_id");
      if (!eventId) continue;

      const dataset = datasetMeta(p);
      const key = `${dataset.id}::${eventId}`;

      if (!byEvent.has(key)) {
        const start = firstProp(p, "osloc_start_time");
        const end = firstProp(p, "osloc_end_time");

        const startEpoch = Number(p[START_EPOCH_PROPERTY]);
        const endEpoch = Number(p[END_EPOCH_PROPERTY]);

        byEvent.set(key, {
          key,
          id: eventId,
          datasetId: dataset.id,
          datasetName: dataset.name,
          schemaVersion: dataset.schema,

          start,
          end,
          startMs: Number.isFinite(startEpoch) ? startEpoch : (start ? Date.parse(start) : NaN),
          endMs: Number.isFinite(endEpoch) ? endEpoch : (end ? Date.parse(end) : NaN),

          localStart: firstProp(p, "osloc_local_start_time"),
          localEnd: firstProp(p, "osloc_local_end_time"),
          displayTime: firstProp(p, "osloc_display_time"),
          timezone: firstProp(p, "osloc_timezone"),

          label: firstProp(p, "osloc_event_label"),
          eventType: firstProp(p, "osloc_event_type"),

          description: parseDescription(
            firstProp(p, "description", "Description", "popupContent", "popup")
          ),

          componentTypes: new Set(),
          placemarkNames: new Set(),
          storeLayers: new Map(),
          features: [],
        });
      }

      const event = byEvent.get(key);

      const start = firstProp(p, "osloc_start_time");
      const end = firstProp(p, "osloc_end_time");
      const startEpoch = Number(p[START_EPOCH_PROPERTY]);
      const endEpoch = Number(p[END_EPOCH_PROPERTY]);

      if (!event.start && start) {
        event.start = start;
        event.startMs = Number.isFinite(startEpoch) ? startEpoch : Date.parse(start);
      }
      if (!event.end && end) {
        event.end = end;
        event.endMs = Number.isFinite(endEpoch) ? endEpoch : Date.parse(end);
      }

      event.localStart ||= firstProp(p, "osloc_local_start_time");
      event.localEnd ||= firstProp(p, "osloc_local_end_time");
      event.displayTime ||= firstProp(p, "osloc_display_time");
      event.timezone ||= firstProp(p, "osloc_timezone");
      event.label ||= firstProp(p, "osloc_event_label");
      event.eventType ||= firstProp(p, "osloc_event_type");

      if (!event.description) {
        event.description = parseDescription(
          firstProp(p, "description", "Description", "popupContent", "popup")
        );
      }

      const componentType = firstProp(p, "osloc_component_type");
      if (componentType) event.componentTypes.add(componentType);

      const placemarkName = firstProp(p, "name", "Name");
      if (placemarkName) event.placemarkNames.add(placemarkName);

      event.storeLayers.set(String(layer.id), {
        id: String(layer.id),
        name: String(layer.name ?? layer.id),
      });

      event.features.push(feature);
    }
  }

  const events = [...byEvent.values()].sort((a, b) => {
    const at = isTemporalEvent(a) ? a.startMs : Number.POSITIVE_INFINITY;
    const bt = isTemporalEvent(b) ? b.startMs : Number.POSITIVE_INFINITY;
    return at - bt || a.key.localeCompare(b.key);
  });

  const datasetsById = new Map();
  for (const event of events) {
    if (!datasetsById.has(event.datasetId)) {
      datasetsById.set(event.datasetId, {
        id: event.datasetId,
        name: event.datasetName,
        schemaVersion: event.schemaVersion,
        events: [],
      });
    }
    datasetsById.get(event.datasetId).events.push(event);
  }

  state.events = events;
  state.datasets = [...datasetsById.values()].sort((a, b) => a.name.localeCompare(b.name));
  state.eventByKey = new Map(events.map(event => [event.key, event]));
  updateAutomaticDateFilterBounds();

  // Preserve explicit user-enabled state for events we already know, but keep
  // newly discovered OS-LOC events hidden by default. This avoids immediately
  // rendering an entire large imported dataset before the user chooses Show All
  // or Timeline.
  const nextEnabled = new Set();
  for (const event of events) {
    if (previousEnabled.has(event.key)) {
      nextEnabled.add(event.key);
    }
  }
  state.enabledEventKeys = nextEnabled;
  markEnabledEventsChanged();
  state.eventKeysKnownLastScan = new Set(events.map(e => e.key));

  rebuildTimelineBoundaries();
  const range = timelineRange();
  if (range && (state.currentMs === null || state.currentMs < range.min || state.currentMs > range.max)) {
    state.currentMs = range.min;
  }

  if (state.selectedEventKey && !events.some(e => e.key === state.selectedEventKey)) {
    state.selectedEventKey = null;
  }

  state.lastScanReason = reason;

  const newEventDataSignature = eventDataSignature(events);
  const eventDataChanged = newEventDataSignature !== lastEventDataSignature;
  lastEventDataSignature = newEventDataSignature;

  rebuildNativeIndex(layers);
  state.layerVisibilityByNativeId = new Map();
  lastVisibilitySignature = "";
  state.lastVisibleEventSignature = "";
  state.lastReorderLayerSignature = "";
  state.lastLabelSignature = "";

  const startupDatasetReady = !state.startupDatasetId || events.some(
    event => event.datasetId === state.startupDatasetId
  );
  const applyStartupBehavior =
    !state.startupBehaviorApplied && events.length > 0 && startupDatasetReady;
  if (applyStartupBehavior) {
    state.startupBehaviorApplied = true;
    if (state.autoShowAll) {
      state.enabledEventKeys = new Set(events.map(event => event.key));
      markEnabledEventsChanged();
    }
  }

  applyVisibility(true);

  if (applyStartupBehavior && state.autoFocus) {
    nextAnimationFrame(() => focusEvents(state.events));
  }

  // Keep the same timeline DOM alive unless the loaded OS-LOC data actually
  // changed. This prevents an active native range drag from losing its element.
  if (eventDataChanged) {
    renderPanelSafe();
    renderTimelineOverlay();
  } else {
    updateDynamicUI();
    updateTimelineDynamicUI();
  }

  return events.length;
}

function activeAt(event, ms) {
  return isTemporalEvent(event) &&
    event.startMs <= ms &&
    ms < effectiveEndMs(event);
}

function shouldShow(event) {
  if (!state.enabledEventKeys.has(event.key)) return false;
  if (!eventMatchesDateFilter(event)) return false;
  if (state.mode === "overview") return true;
  if (!isTemporalEvent(event)) return true;
  return state.currentMs !== null && activeAt(event, state.currentMs);
}

function visibilitySignature() {
  const dateRange = `${state.dateFilterStart || "*"}:${state.dateFilterEnd || "*"}`;
  if (state.mode === "overview") {
    return `overview:${state.enabledEventsVersion}:${dateRange}`;
  }
  return `timeline:${state.enabledEventsVersion}:${timelineBoundaryBucket(state.currentMs)}:${dateRange}`;
}

function addNativeMapping(key, nativeId, kind) {
  if (!key || !nativeId) return false;

  // Once a render layer has been proven ambiguous, never let a later fallback
  // silently assign it to one event.
  if (state.ambiguousNativeIds.has(nativeId)) return false;

  const existingOwner = state.nativeOwnerByLayerId.get(nativeId);

  if (existingOwner && existingOwner !== key) {
    // A single MapLibre render layer must never be controlled by two logical
    // OS-LOC events. Remove the earlier assignment and mark it ambiguous.
    state.nativeIdsByEventKey.get(existingOwner)?.delete(nativeId);
    state.nativeOwnerByLayerId.delete(nativeId);
    state.nativeMappingKindByLayerId.delete(nativeId);
    state.ambiguousNativeIds.add(nativeId);
    return false;
  }

  if (!state.nativeIdsByEventKey.has(key)) {
    state.nativeIdsByEventKey.set(key, new Set());
  }

  const set = state.nativeIdsByEventKey.get(key);

  if (!set.has(nativeId)) {
    set.add(nativeId);
    state.nativeOwnerByLayerId.set(nativeId, key);
    state.nativeMappingKindByLayerId.set(nativeId, kind);
  }

  return true;
}

function pushLookup(map, key, value) {
  if (!key) return;
  if (!map.has(key)) map.set(key, []);
  map.get(key).push(value);
}

function uniqueTrigrams(value) {
  const grams = new Set();
  if (!value) return grams;

  if (value.length < 3) {
    grams.add(value);
    return grams;
  }

  for (let i = 0; i <= value.length - 3; i++) {
    grams.add(value.slice(i, i + 3));
  }

  return grams;
}

function buildStyleLayerLookup(styleLayers) {
  const byExactValue = new Map();
  const byToken = new Map();
  const byTrigram = new Map();
  const hayById = new Map();
  const layerById = new Map();
  const styleIndexById = new Map();

  for (let i = 0; i < styleLayers.length; i++) {
    const layer = styleLayers[i];
    const id = String(layer?.id ?? "");
    if (!id) continue;

    layerById.set(id, layer);
    styleIndexById.set(id, i);

    const values = [layer.id, layer.source, layer["source-layer"]]
      .filter(Boolean)
      .map(v => String(v).toLowerCase());

    for (const value of values) {
      pushLookup(byExactValue, value, layer);
    }

    const hay = values.join(" ");
    hayById.set(id, hay);

    for (const token of hay.split(/[^a-z0-9_-]+/)) {
      if (!token) continue;
      pushLookup(byToken, token, id);
    }

    for (const gram of uniqueTrigrams(hay)) {
      pushLookup(byTrigram, gram, id);
    }
  }

  function includesLookup(needle) {
    if (!needle) return [];

    let candidateIds = null;

    if (needle.length >= 3) {
      const grams = [...uniqueTrigrams(needle)];
      for (const gram of grams) {
        const ids = byTrigram.get(gram);
        if (!ids || !ids.length) return [];

        if (candidateIds === null) {
          candidateIds = new Set(ids);
          continue;
        }

        candidateIds = new Set(ids.filter(id => candidateIds.has(id)));
        if (!candidateIds.size) return [];
      }
    } else {
      const tokenIds = byToken.get(needle) ?? [];
      candidateIds = new Set(tokenIds);
    }

    if (candidateIds === null) {
      candidateIds = new Set(layerById.keys());
    }

    const out = [];
    for (const id of candidateIds) {
      const hay = hayById.get(id) ?? "";
      if (hay.includes(needle)) {
        const layer = layerById.get(id);
        if (layer) out.push(layer);
      }
    }

    out.sort((a, b) => {
      const ai = styleIndexById.get(String(a.id)) ?? Number.MAX_SAFE_INTEGER;
      const bi = styleIndexById.get(String(b.id)) ?? Number.MAX_SAFE_INTEGER;
      return ai - bi;
    });

    return out;
  }

  return {
    byExactValue,
    includesLookup,
  };
}

function rebuildNativeIndex(storeLayers = safeListLayers()) {
  // Restore icon sizing from any previous mapping before rebuilding.
  restoreHiddenAnchorSymbolStyles();
  restoreSharedLayerFilters();

  state.nativeIdsByEventKey = new Map();
  state.nativeOwnerByLayerId = new Map();
  state.nativeMappingKindByLayerId = new Map();
  state.ambiguousNativeIds = new Set();
  state.hiddenAnchorCircleLayerIds = new Set();
  state.hiddenAnchorSymbolLayerIds = new Set();

  state.mappingStats = {
    nativeMapped: 0,
    nativeMetadata: 0,
    fallbackMapped: 0,
    ambiguousRenderLayers: 0,
    ambiguousSourceGroups: 0,
    sharedFilteredLayers: 0,
    unmappedEvents: 0,
    suppressedHiddenAnchorLayers: 0
  };
  state.sharedNativeLayerBaseFilter = new Map();
  state.sharedNativeLayerEventKeys = new Map();
  state.sharedNativeLayerAppliedSignature = new Map();
  state.sharedNativeLayerVisibilityById = new Map();
  state.sharedNativeLayerSupportsEpochs = new Map();

  const map = state.app?.getMap?.();
  const styleLayers = map?.getStyle?.()?.layers ?? [];
  if (!map || !styleLayers.length) return;

  const styleLookup = buildStyleLayerLookup(styleLayers);

  /*
   * PASS 1: Map GeoLibre's individual imported layers to MapLibre render layers
   * using layer IDs first. This is the safest mapping when a KML component has
   * its own GeoLibre layer.
   */
  const hiddenAnchorStoreLayerIds = new Set();
  const eventKeysByStoreLayerId = new Map();

  for (const layer of storeLayers) {
    const features = safeFeatures(layer.id).filter(feature =>
      Boolean(eventKeyFromProps(feature?.properties ?? {}))
    );

    // Suppress a native render layer only when the corresponding GeoLibre
    // store layer contains OS-LOC Point features that are ALL known hidden
    // anchors. Mixed layers are intentionally left untouched.
    if (
      features.length > 0 &&
      features.every(isIntentionallyHiddenKmlAnchorFeature)
    ) {
      hiddenAnchorStoreLayerIds.add(String(layer.id));
    }
  }

  for (const event of state.events) {
    for (const store of event.storeLayers.values()) {
      const storeId = String(store.id);
      if (!eventKeysByStoreLayerId.has(storeId)) {
        eventKeysByStoreLayerId.set(storeId, []);
      }

      eventKeysByStoreLayerId.get(storeId).push(event.key);
    }
  }

  // Candidate native layers are collected first and accepted only if the
  // normal event mapping remains unambiguous after all mapping passes.
  const hiddenAnchorNativeCandidates = new Map();

  const uniqueNameCount = new Map();

  for (const layer of storeLayers) {
    const name = String(layer.name ?? "").toLowerCase();
    if (name) uniqueNameCount.set(name, (uniqueNameCount.get(name) ?? 0) + 1);
  }

  for (const layer of storeLayers) {
    const storeId = String(layer.id ?? "");
    if (!storeId) continue;

    const eventKeys = eventKeysByStoreLayerId.get(storeId) ?? [];
    if (!eventKeys.length) continue;

    // A single store layer containing multiple OS-LOC events is a shared
    // dataset layer (common with GeoJSON). Let metadata pass handle it.
    if (eventKeys.length > 1) {
      continue;
    }

    const idNeedle = storeId.toLowerCase();
    const nameNeedle = String(layer.name ?? "").toLowerCase();

    let candidates = styleLookup.byExactValue.get(idNeedle) ?? [];

    // GeoLibre often embeds its layer id inside a generated source/style id.
    if (!candidates.length && idNeedle.length >= 5) {
      candidates = styleLookup.includesLookup(idNeedle);
    }

    // Layer-name matching is only allowed when that name is globally unique.
    if (!candidates.length && nameNeedle && uniqueNameCount.get(nameNeedle) === 1) {
      candidates = styleLookup.includesLookup(nameNeedle);
    }

    for (const candidate of candidates) {
      const mapped = addNativeMapping(eventKeys[0], candidate.id, "fallback");

      if (
        mapped &&
        hiddenAnchorStoreLayerIds.has(storeId) &&
        (candidate.type === "circle" || candidate.type === "symbol")
      ) {
        hiddenAnchorNativeCandidates.set(candidate.id, candidate.type);
      }
    }
  }

  /*
   * PASS 2: Metadata-based mapping.
   *
   * querySourceFeatures() returns every feature in a source. A source may contain
   * several OS-LOC events. The old code assigned the same render layer to every
   * event found in that source, which could make a leg/line appear at the wrong
   * time. We now map from source metadata only when it resolves to ONE event, or
   * when the style layer's own filter/metadata clearly identifies one event.
   */
  const sourcePairCache = new Map();
  const geojsonSourceGroups = new Map();

  for (const styleLayer of styleLayers) {
    if (isPluginOwnedLayer(styleLayer)) continue;
    if (state.nativeOwnerByLayerId.has(styleLayer.id)) continue;
    if (state.ambiguousNativeIds.has(styleLayer.id)) continue;

    const sourceId = typeof styleLayer.source === "string" ? styleLayer.source : "";
    if (!sourceId) continue;

    const sourceLayer = styleLayer["source-layer"] || "";
    const cacheKey = `${sourceId}::${sourceLayer}`;

    let sourceInfo = sourcePairCache.get(cacheKey);

    if (!sourceInfo) {
      const keys = new Set();
      let oslocFeature = null;
      let temporalEpochsComplete = true;
      let sawTemporalEvent = false;

      try {
        const options = sourceLayer ? { sourceLayer } : undefined;
        const sourceFeatures = map.querySourceFeatures(sourceId, options) ?? [];

        for (const feature of sourceFeatures) {
          const key = eventKeyFromProps(feature?.properties ?? {});
          if (key) {
            keys.add(key);
          }
          if (!oslocFeature && isGeojsonEvidenceFeature(feature)) {
            oslocFeature = feature;
          }
          const p = feature?.properties ?? {};
          if (key && firstProp(p, "osloc_start_time")) {
            sawTemporalEvent = true;
            if (
              !Number.isFinite(Number(p[START_EPOCH_PROPERTY])) ||
              !Number.isFinite(Number(p[END_EPOCH_PROPERTY]))
            ) {
              temporalEpochsComplete = false;
            }
          }
        }
      } catch { }

      sourceInfo = {
        keys,
        oslocFeature,
        supportsEpochs: sawTemporalEvent && temporalEpochsComplete,
      };
      sourcePairCache.set(cacheKey, sourceInfo);
    }

    const keys = sourceInfo.keys;

    if (sourceInfo.oslocFeature && keys.size > 0) {
      const key = sourceGroupKey(sourceId, sourceLayer);
      if (!geojsonSourceGroups.has(key)) {
        geojsonSourceGroups.set(key, {
          key,
          sourceId,
          sourceLayer,
          eventKeys: new Set(keys),
          hostLayerIds: new Set(),
          supportsEpochs: sourceInfo.supportsEpochs,
          palette: stylePaletteForLayer(map, styleLayer),
        });
      }
      geojsonSourceGroups.get(key).hostLayerIds.add(String(styleLayer.id));
      continue;
    }

    if (keys.size === 1) {
      addNativeMapping([...keys][0], styleLayer.id, "metadata");
      continue;
    }

    if (keys.size > 1) {
      // Some render layers carry a filter or metadata that identifies the
      // specific event even though their shared source contains many events.
      const styleIdentity = JSON.stringify({
        filter: styleLayer.filter ?? null,
        metadata: styleLayer.metadata ?? null,
        sourceLayer: styleLayer["source-layer"] ?? null,
        id: styleLayer.id ?? null
      });

      const matches = [...keys].filter(key => {
        const splitAt = key.indexOf("::");
        const datasetId = splitAt >= 0 ? key.slice(0, splitAt) : "";
        const eventId = splitAt >= 0 ? key.slice(splitAt + 2) : key;

        const hasEvent = eventId && styleIdentity.includes(eventId);
        const hasDataset =
          !datasetId ||
          datasetId === "legacy" ||
          styleIdentity.includes(datasetId);

        return hasEvent && hasDataset;
      });

      if (matches.length === 1) {
        addNativeMapping(matches[0], styleLayer.id, "metadata");
      } else {
        // Shared GeoJSON layers intentionally contain many events.
        // Keep base style filters and apply dynamic per-event filtering later.
        state.sharedNativeLayerBaseFilter.set(styleLayer.id, styleLayer.filter ?? null);
        state.sharedNativeLayerEventKeys.set(styleLayer.id, [...keys]);
        state.mappingStats.sharedFilteredLayers++;
      }
    }
  }

  if (geojsonSourceGroups.size || state.events.length === 0) {
    takeOwnershipOfGeojsonSources(map, geojsonSourceGroups);
  } else if (state.geojsonSourceGroups.size) {
    takeOwnershipOfGeojsonSources(map, knownGeojsonGroupsForCurrentStyle(map));
  }
  lastNativeStyleSignature = nativeStyleSignature(map);

  if (!state.sharedNativeLayerEventKeys.size && map?.queryRenderedFeatures) {
    // Fallback: for GeoJSON imports where querySourceFeatures is unavailable
    // or sparse, sample rendered features to identify shared OS-LOC layers.
    for (const styleLayer of styleLayers) {
      if (state.nativeOwnerByLayerId.has(styleLayer.id)) continue;
      if (state.ambiguousNativeIds.has(styleLayer.id)) continue;

      let rendered = [];
      try {
        rendered = map.queryRenderedFeatures(undefined, { layers: [styleLayer.id] }) ?? [];
      } catch {
        try {
          rendered = map.queryRenderedFeatures({ layers: [styleLayer.id] }) ?? [];
        } catch {
          rendered = [];
        }
      }

      const renderedKeys = new Set();
      const datasetIds = new Set();
      for (const feature of rendered) {
        const p = feature?.properties ?? {};
        const key = eventKeyFromProps(p);
        if (!key) continue;
        renderedKeys.add(key);
        const splitAt = key.indexOf("::");
        if (splitAt >= 0) datasetIds.add(key.slice(0, splitAt));
      }

      if (!renderedKeys.size) continue;

      const candidateKeys = state.events
        .filter(event => datasetIds.size ? datasetIds.has(event.datasetId) : true)
        .map(event => event.key);

      state.sharedNativeLayerBaseFilter.set(styleLayer.id, styleLayer.filter ?? null);
      state.sharedNativeLayerEventKeys.set(
        styleLayer.id,
        candidateKeys.length ? candidateKeys : [...renderedKeys]
      );
      state.mappingStats.sharedFilteredLayers++;
    }
  }

  applySharedLayerStyling();

  const mappingKinds = [...state.nativeMappingKindByLayerId.values()];

  state.mappingStats.nativeMapped = state.nativeOwnerByLayerId.size;
  state.mappingStats.nativeMetadata =
    mappingKinds.filter(kind => kind === "metadata").length;
  state.mappingStats.fallbackMapped =
    mappingKinds.filter(kind => kind === "fallback").length;
  state.mappingStats.ambiguousRenderLayers = state.ambiguousNativeIds.size;

  state.mappingStats.unmappedEvents =
    state.events.filter(
      event => (state.nativeIdsByEventKey.get(event.key)?.size ?? 0) === 0
    ).length;

  // Only suppress candidates that survived normal ownership/ambiguity checks.
  for (const [layerId, type] of hiddenAnchorNativeCandidates.entries()) {
    if (!state.nativeOwnerByLayerId.has(layerId)) continue;
    if (state.ambiguousNativeIds.has(layerId)) continue;

    if (type === "circle") {
      state.hiddenAnchorCircleLayerIds.add(layerId);
    } else if (type === "symbol") {
      state.hiddenAnchorSymbolLayerIds.add(layerId);
    }
  }

  state.mappingStats.suppressedHiddenAnchorLayers =
    state.hiddenAnchorCircleLayerIds.size +
    state.hiddenAnchorSymbolLayerIds.size;

  applyHiddenAnchorSymbolSuppression();
}


function reorderVisibleEvidenceLayersChronologically() {
  /*
   * GeoLibre's imported MapLibre layer order is not necessarily chronological.
   * Without intervention a later event can become visible underneath an older
   * wedge. Reorder only the OS-LOC render layers that we have mapped
   * unambiguously, oldest -> newest, so later evidence is painted on top.
   *
   * The plugin-owned time-label layers remain above the evidence.
   */
  const map = state.app?.getMap?.();
  if (!map?.moveLayer || !map?.getStyle) return;

  const styleLayers = map.getStyle()?.layers ?? [];
  if (!styleLayers.length) return;

  const styleIndex = new Map(
    styleLayers.map((layer, index) => [String(layer.id), index])
  );

  const visibleEvents = state.events
    .map((event, originalIndex) => ({ event, originalIndex }))
    .filter(({ event }) => {
      if (!shouldShow(event)) return false;
      const ids = state.nativeIdsByEventKey.get(event.key);
      return ids && ids.size > 0;
    })
    .sort((a, b) => {
      const aTemporal = Number.isFinite(a.event.startMs);
      const bTemporal = Number.isFinite(b.event.startMs);

      // Static/non-temporal evidence has no chronological start. Keep it below
      // timed evidence while preserving its existing event order.
      if (aTemporal !== bTemporal) return aTemporal ? 1 : -1;

      if (aTemporal && bTemporal && a.event.startMs !== b.event.startMs) {
        return a.event.startMs - b.event.startMs;
      }

      return a.originalIndex - b.originalIndex;
    });

  if (!visibleEvents.length) return;

  // This gives us a stable "above evidence" anchor only when we actually
  // have visible evidence to reorder.
  ensureMapLabelLayer();

  // Insert OS-LOC evidence immediately below our label layer. Processing events
  // oldest -> newest means each later event is inserted above the earlier one.
  const anchorId = map.getLayer?.(LABEL_INSIDE_LAYER_ID)
    ? LABEL_INSIDE_LAYER_ID
    : (map.getLayer?.(LABEL_POINT_LAYER_ID) ? LABEL_POINT_LAYER_ID : null);

  const desiredIds = [];

  for (const { event } of visibleEvents) {
    const ids = [...(state.nativeIdsByEventKey.get(event.key) ?? [])]
      .filter(id => map.getLayer?.(id))
      // Preserve the event's existing internal component order. This avoids
      // arbitrarily putting a wedge above its own legs/lines/points.
      .sort((a, b) =>
        (styleIndex.get(String(a)) ?? Number.MAX_SAFE_INTEGER) -
        (styleIndex.get(String(b)) ?? Number.MAX_SAFE_INTEGER)
      );

    desiredIds.push(...ids);
  }

  if (!desiredIds.length) return;

  const desiredSet = new Set(desiredIds);
  const currentIds = styleLayers
    .map(layer => String(layer?.id ?? ""))
    .filter(id => desiredSet.has(id));

  const desiredKey = desiredIds.join("|");
  const currentKey = currentIds.join("|");
  const signature = `${desiredKey}::${currentKey}::${anchorId || "none"}`;

  if (signature === state.lastReorderLayerSignature || currentKey === desiredKey) {
    state.lastReorderLayerSignature = signature;
    return;
  }

  for (const id of desiredIds) {
    try {
      if (anchorId) map.moveLayer(id, anchorId);
      else map.moveLayer(id);
    } catch { }
  }

  state.lastReorderLayerSignature = signature;
}

function applyVisibility(force = false) {
  const map = state.app?.getMap?.();
  if (!map) return;

  const signature = visibilitySignature();
  if (!force && signature === lastVisibilitySignature) {
    return;
  }

  lastVisibilitySignature = signature;

  const seenNativeIds = new Set();
  const visibleEventKeys = [];
  const visibleEventKeySet = new Set();

  for (const event of state.events) {
    const ids = state.nativeIdsByEventKey.get(event.key) ?? new Set();
    const visibility = shouldShow(event) ? "visible" : "none";

    if (visibility === "visible") {
      visibleEventKeys.push(event.key);
      visibleEventKeySet.add(event.key);
    }

    for (const id of ids) {
      const nativeId = String(id);
      seenNativeIds.add(nativeId);

      const desiredVisibility = state.hiddenAnchorCircleLayerIds.has(nativeId)
        ? "none"
        : visibility;

      const currentVisibility = state.layerVisibilityByNativeId.get(nativeId);
      if (currentVisibility === desiredVisibility) {
        continue;
      }

      try {
        map.setLayoutProperty(nativeId, "visibility", desiredVisibility);
        state.layerVisibilityByNativeId.set(nativeId, desiredVisibility);
      }
      catch { }
    }
  }

  for (const nativeId of [...state.layerVisibilityByNativeId.keys()]) {
    if (!seenNativeIds.has(nativeId)) {
      state.layerVisibilityByNativeId.delete(nativeId);
    }
  }

  for (const [layerId, layerEventKeys] of state.sharedNativeLayerEventKeys.entries()) {
    if (!map.getLayer?.(layerId)) continue;

    const visibleForLayer = layerEventKeys.filter(key => visibleEventKeySet.has(key));
    const filterState = sharedLayerFilterState(
      layerId,
      layerEventKeys,
      visibleForLayer
    );

    const previousVisibility = state.sharedNativeLayerVisibilityById.get(layerId) ?? "visible";
    if (previousVisibility !== filterState.visibility) {
      try {
        map.setLayoutProperty?.(layerId, "visibility", filterState.visibility);
      } catch { }
      state.sharedNativeLayerVisibilityById.set(layerId, filterState.visibility);
    }

    const previousSignature = state.sharedNativeLayerAppliedSignature.get(layerId) ?? "";
    if (filterState.signature === previousSignature) continue;

    try {
      map.setFilter?.(layerId, filterState.filter);
      state.sharedNativeLayerAppliedSignature.set(layerId, filterState.signature);
    } catch { }
  }

  state.lastVisibleEventSignature = visibleEventKeys.join("|");

  // GeoLibre may recreate or normalize symbol layout properties while layers
  // are being shown/hidden, so enforce icon-only suppression here as well.
  applyHiddenAnchorSymbolSuppression();

  reorderVisibleEvidenceLayersChronologically();
  updateMapLabels();
  updateDynamicUI();
  updateTimelineDynamicUI();
}

function layerFeaturesForDiagnostics(map, layer) {
  const sourceId = typeof layer?.source === "string" ? layer.source : "";
  if (!sourceId) return [];

  const sourceLayer = layer?.["source-layer"] || "";

  try {
    const options = sourceLayer ? { sourceLayer } : undefined;
    const features = map.querySourceFeatures?.(sourceId, options) ?? [];
    if (features.length) return features;
  } catch { }

  try {
    return map.queryRenderedFeatures?.(undefined, { layers: [layer.id] }) ?? [];
  } catch {
    try {
      return map.queryRenderedFeatures?.({ layers: [layer.id] }) ?? [];
    } catch {
      return [];
    }
  }
}

function collectOslocLayerDiagnostics() {
  const map = state.app?.getMap?.();
  if (!map?.getStyle) return null;

  const style = map.getStyle?.() ?? {};
  const styleLayers = style.layers ?? [];
  const sources = style.sources ?? {};

  const allLayers = styleLayers.map(layer => {
    const features = layerFeaturesForDiagnostics(map, layer)
      .filter(feature => eventKeyFromProps(feature?.properties ?? {}));

    const componentTypes = [...new Set(features
      .map(feature => firstProp(feature?.properties ?? {}, "osloc_component_type"))
      .filter(Boolean)
    )].sort();

    return {
      id: String(layer?.id ?? ""),
      type: String(layer?.type ?? ""),
      source: String(layer?.source ?? ""),
      sourceLayer: String(layer?.["source-layer"] ?? ""),
      filter: layer?.filter ?? null,
      visibility: String(layer?.layout?.visibility ?? "visible"),
      layout: layer?.layout ?? {},
      paint: layer?.paint ?? {},
      oslocFeatureCountSampled: features.length,
      oslocComponentTypes: componentTypes,
    };
  });

  const oslocLayers = allLayers.filter(layer => layer.oslocFeatureCountSampled > 0);
  const sourceUsage = {};
  for (const layer of oslocLayers) {
    if (!layer.source) continue;
    sourceUsage[layer.source] = (sourceUsage[layer.source] ?? 0) + 1;
  }

  return {
    eventCount: state.events.length,
    visibleCount: state.events.filter(shouldShow).length,
    mapHasSetFilter: typeof map?.setFilter === "function",
    mapHasSetPaintProperty: typeof map?.setPaintProperty === "function",
    mapHasQuerySourceFeatures: typeof map?.querySourceFeatures === "function",
    totalStyleLayerCount: styleLayers.length,
    oslocStyleLayerCount: oslocLayers.length,
    oslocSourceIds: Object.keys(sourceUsage).sort(),
    oslocSourceLayerUsage: sourceUsage,
    oslocLayers,
    sharedLayerIds: [...state.sharedNativeLayerEventKeys.keys()].sort(),
    sharedLayerBaseFilters: [...state.sharedNativeLayerBaseFilter.entries()],
    sharedLayerAppliedSignatures: [...state.sharedNativeLayerAppliedSignature.entries()],
  };
}

function boundsForEvents(events) {
  let west = Infinity, south = Infinity, east = -Infinity, north = -Infinity;
  let found = false;

  function walk(c) {
    if (!Array.isArray(c)) return;

    if (typeof c[0] === "number" && typeof c[1] === "number") {
      west = Math.min(west, c[0]);
      east = Math.max(east, c[0]);
      south = Math.min(south, c[1]);
      north = Math.max(north, c[1]);
      found = true;
      return;
    }

    for (const child of c) walk(child);
  }

  for (const event of events) {
    for (const feature of event.features) walk(feature?.geometry?.coordinates);
  }

  return found ? [west, south, east, north] : null;
}

function stopPlayback() {
  if (playbackRaf !== null) cancelAnimationFrame(playbackRaf);
  playbackRaf = null;
  state.playing = false;
  state.lastFrameRealMs = null;
  updateTimelineDynamicUI();
}

function cancelPendingScrubVisibility() {
  if (scrubVisibilityTimer !== null) clearTimeout(scrubVisibilityTimer);
  scrubVisibilityTimer = null;
}

function scheduleScrubVisibility(finalUpdate = false) {
  cancelPendingScrubVisibility();

  scrubVisibilityTimer = setTimeout(() => {
    scrubVisibilityTimer = null;

    // During a drag the thumb/clock update every pointer movement, while
    // map visibility work is rate-limited.  A final update is always forced.
    if (finalUpdate) {
      lastVisibilitySignature = "";
      applyVisibility(true);
    } else {
      applyVisibility(false);
    }

    updateDynamicUI();
  }, finalUpdate ? 0 : 55);
}

function finishScrub() {
  if (!state.scrubbing) return;
  state.scrubbing = false;
  scheduleScrubVisibility(true);
  updateTimelineDynamicUI();
}

function setTime(ms, stop = true) {
  const range = timelineRange();
  if (!range) return;

  if (stop) stopPlayback();

  state.mode = "timeline";
  state.currentMs = Math.max(range.min, Math.min(range.max, ms));

  applyVisibility();
  updateDynamicUI();
  updateTimelineDynamicUI();
}

function playbackFrame(realNow) {
  const range = timelineRange();
  if (!range || !state.playing) return;

  if (state.lastFrameRealMs === null) state.lastFrameRealMs = realNow;

  const elapsed = realNow - state.lastFrameRealMs;
  state.lastFrameRealMs = realNow;

  state.currentMs += elapsed * state.speed;

  if (state.currentMs >= range.max) {
    state.currentMs = range.max;
    applyVisibility();
    stopPlayback();
    updateDynamicUI();
    return;
  }

  // Smooth clock/slider every animation frame.
  updateTimelineDynamicUI();

  // Expensive map visibility is cached and changes only at event boundaries.
  applyVisibility();

  playbackRaf = requestAnimationFrame(playbackFrame);
}

function togglePlayback() {
  const range = timelineRange();
  if (!range) return;

  if (state.playing) {
    stopPlayback();
    return;
  }

  state.mode = "timeline";

  if (state.currentMs === null || state.currentMs >= range.max) {
    state.currentMs = range.min;
  }

  state.playing = true;
  state.lastFrameRealMs = null;
  applyVisibility();
  updateDynamicUI();
  updateTimelineDynamicUI();

  playbackRaf = requestAnimationFrame(playbackFrame);
}

function jumpEvent(direction) {
  const temporal = temporalEvents();
  if (!temporal.length) return;

  const now = state.currentMs ?? temporal[0].startMs;

  if (direction > 0) {
    const next = temporal.find(e => e.startMs > now + 1);
    setTime(next ? next.startMs : temporal[temporal.length - 1].startMs);
  } else {
    const prior = [...temporal].reverse().find(e => e.startMs < now - 1);
    setTime(prior ? prior.startMs : temporal[0].startMs);
  }
}

function setDatasetEnabled(dataset, enabled) {
  for (const event of dataset.events) {
    if (enabled) state.enabledEventKeys.add(event.key);
    else state.enabledEventKeys.delete(event.key);
  }

  markEnabledEventsChanged();
  lastVisibilitySignature = "";
  applyVisibility(true);
  renderPanelSafe();
}

function focusEvents(events) {
  const targets = (events ?? []).filter(Boolean);
  if (!targets.length) return;

  stopPlayback();
  state.mode = "overview";
  state.enabledEventKeys = new Set(targets.map(event => event.key));
  markEnabledEventsChanged();
  lastVisibilitySignature = "";
  applyVisibility(true);
  renderPanelSafe();

  const bounds = boundsForEvents(targets.filter(eventMatchesDateFilter));
  if (bounds) state.app?.fitBounds?.(bounds);
}

function datasetEnabledState(dataset) {
  const selected = dataset.events.filter(e => state.enabledEventKeys.has(e.key)).length;
  return {
    checked: selected === dataset.events.length,
    indeterminate: selected > 0 && selected < dataset.events.length
  };
}

function makeButton(text, fn, className = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = text;
  if (className) button.className = className;
  button.addEventListener("click", fn);
  return button;
}

function makeDateFilterControl() {
  const control = document.createElement("section");
  control.className = "osloc-v028__date-filter";

  const heading = document.createElement("div");
  heading.className = "osloc-v028__date-filter-head";

  const title = document.createElement("strong");
  title.textContent = "Date/time range";

  const status = document.createElement("span");
  status.dataset.role = "date-filter-status";
  status.textContent = dateFilterActive()
    ? `${eventsMatchingDateFilter().length} of ${state.events.length} events`
    : "All times";
  heading.append(title, status);

  const fields = document.createElement("div");
  fields.className = "osloc-v028__date-filter-fields";

  const makeDateTimeInput = (labelText, value, role) => {
    const label = document.createElement("label");
    const text = document.createElement("span");
    text.textContent = labelText;

    const input = document.createElement("input");
    input.type = "datetime-local";
    input.step = "60";
    input.value = value;
    input.dataset.role = role;
    input.setAttribute("aria-label", `${labelText} event date and time`);
    input.addEventListener("input", () => input.setCustomValidity?.(""));

    label.append(text, input);
    return { label, input };
  };

  const from = makeDateTimeInput(
    "From",
    state.dateFilterStart,
    "date-filter-start"
  );
  const through = makeDateTimeInput(
    "Through",
    state.dateFilterEnd,
    "date-filter-end"
  );

  const actions = document.createElement("div");
  actions.className = "osloc-v028__date-filter-actions";

  const apply = makeButton("Apply", () => {
    through.input.setCustomValidity?.("");
    if (!applyDateFilter(from.input.value, through.input.value)) {
      through.input.setCustomValidity?.(
        "Through date and time must be the same as or later than From."
      );
      through.input.reportValidity?.();
    }
  });
  apply.dataset.role = "apply-date-filter";

  const allDates = makeButton("All Times", () => {
    applyDateFilter("", "");
  });
  allDates.dataset.role = "clear-date-filter";
  allDates.disabled = !dateFilterActive();

  actions.append(apply, allDates);
  fields.append(from.label, through.label, actions);
  control.append(heading, fields);
  control.title = "Filter by the corrected local date and time shown for each event.";
  return control;
}

function makeAboutSection() {
  const about = document.createElement("details");
  about.className = "osloc-v028__about";
  about.dataset.role = "about-licenses";

  const summary = document.createElement("summary");
  summary.textContent = "About & licenses";

  const body = document.createElement("div");
  body.className = "osloc-v028__about-body";

  const pluginNotice = document.createElement("p");
  pluginNotice.textContent =
    `OS-LOC-DAT-VIZ Viewer ${PLUGIN_VERSION} - GNU General Public License v3.0.`;

  const geolibreNotice = document.createElement("p");
  geolibreNotice.textContent =
    "GeoLibre 3.0.0 - Copyright (c) 2026 Qiusheng Wu - MIT License.";

  const links = document.createElement("div");
  links.className = "osloc-v028__about-links";
  const addLink = (label, url) => {
    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = label;
    link.addEventListener("click", event => {
      if (!state.app?.openExternalUrl) return;
      event.preventDefault();
      state.app.openExternalUrl(url);
    });
    links.appendChild(link);
  };
  addLink("OS-LOC-DAT-VIZ source and license", "https://github.com/btc-git/OS-LOC-DAT-VIZ");
  addLink("GeoLibre source and MIT license", "https://github.com/opengeos/GeoLibre");

  const bundledNotice = document.createElement("p");
  bundledNotice.textContent =
    "Full license notices are bundled with the application and installed viewer.";

  body.append(pluginNotice, geolibreNotice, links, bundledNotice);
  about.append(summary, body);
  return about;
}

function updateDynamicUI() {
  const root = state.container?.querySelector(".osloc-v028");
  if (!root) return;

  const visibleCount = root.querySelector("[data-role='visible-count']");
  if (visibleCount) {
    const inRangeCount = eventsMatchingDateFilter().length;
    visibleCount.textContent = dateFilterActive()
      ? `${state.events.filter(shouldShow).length} of ${inRangeCount} in-range events visible`
      : `${state.events.filter(shouldShow).length} of ${state.events.length} events visible`;
  }

  for (const row of root.querySelectorAll("[data-event-key]")) {
    const key = row.getAttribute("data-event-key");
    const event = state.eventByKey.get(key);
    if (!event) continue;

    row.classList.toggle(
      "osloc-v028__event--active",
      shouldShow(event) &&
      isTemporalEvent(event) &&
      state.mode === "timeline" &&
      state.currentMs !== null &&
      activeAt(event, state.currentMs)
    );

    row.classList.toggle(
      "osloc-v028__event--selected",
      state.selectedEventKey === event.key
    );

    row.classList.toggle("osloc-v028__event--hidden", !shouldShow(event));
  }
}

function updateTimelineDynamicUI() {
  if (!timelineEl) return;

  const range = timelineRange();
  if (!range) return;

  const includeDate = timelineNeedsDate();
  const current = state.currentMs ?? range.min;

  const mainClock = timelineEl.querySelector("[data-role='timeline-clock']");
  const utcClockEl = timelineEl.querySelector("[data-role='timeline-utc']");
  const slider = timelineEl.querySelector("[data-role='timeline-slider']");
  const play = timelineEl.querySelector("[data-role='timeline-play']");
  const mode = timelineEl.querySelector("[data-role='timeline-mode']");

  if (mainClock) mainClock.textContent = formatPrimaryTimelineTime(current, includeDate);
  if (utcClockEl) {
    const zone = commonTimezone();

    if (isUsableIanaZone(zone)) {
      // When primary time is local, keep UTC available as the secondary line.
      utcClockEl.textContent = utcDateTime(current);
    } else if (!includeDate) {
      // When the primary clock is already UTC, the secondary line only needs
      // to supply the date instead of repeating the entire timestamp.
      utcClockEl.textContent = new Date(current).toISOString().slice(0, 10);
    } else {
      utcClockEl.textContent = "";
    }
  }
  if (slider) {
    slider.value = String(Math.round((current - range.min) / 1000));
  }
  if (play) play.textContent = state.playing ? "Pause" : "Play";
  if (mode) mode.textContent = state.mode === "overview" ? "All Events" : "Timeline";
}

function removeTimelineOverlay() {
  cancelPendingScrubVisibility();
  state.scrubbing = false;
  if (timelineEl) timelineEl.remove();
  timelineEl = null;
}

function renderTimelineOverlay() {
  removeTimelineOverlay();

  const map = state.app?.getMap?.();
  const mapContainer = map?.getContainer?.();
  const range = timelineRange();

  if (!mapContainer || !range) return;

  const overlay = document.createElement("div");
  overlay.className = "osloc-v028-timeline";
  timelineEl = overlay;

  // The timeline lives inside MapLibre's map container. Prevent pointer,
  // mouse, touch, wheel, and double-click gestures on the timeline from
  // bubbling into the map's pan/zoom/drag handlers.
  for (const type of [
    "pointerdown", "pointermove", "pointerup", "pointercancel",
    "mousedown", "mousemove", "mouseup",
    "touchstart", "touchmove", "touchend",
    "click", "dblclick", "contextmenu", "wheel"
  ]) {
    overlay.addEventListener(type, event => {
      event.stopPropagation();
    });
  }

  const includeDate = timelineNeedsDate();

  const top = document.createElement("div");
  top.className = "osloc-v028-timeline__top";

  const left = document.createElement("div");
  left.className = "osloc-v028-timeline__clock-wrap";

  const mode = document.createElement("span");
  mode.dataset.role = "timeline-mode";
  mode.className = "osloc-v028-timeline__mode";
  mode.textContent = state.mode === "overview" ? "All Events" : "Timeline";

  const clock = document.createElement("strong");
  clock.dataset.role = "timeline-clock";
  clock.className = "osloc-v028-timeline__clock";
  clock.textContent = formatPrimaryTimelineTime(state.currentMs ?? range.min, includeDate);

  const utc = document.createElement("span");
  utc.dataset.role = "timeline-utc";
  utc.className = "osloc-v028-timeline__utc";

  const initialTime = state.currentMs ?? range.min;
  const initialZone = commonTimezone();

  if (isUsableIanaZone(initialZone)) {
    utc.textContent = utcDateTime(initialTime);
  } else if (!includeDate) {
    utc.textContent = new Date(initialTime).toISOString().slice(0, 10);
  } else {
    utc.textContent = "";
  }

  left.append(mode, clock, utc);

  const controls = document.createElement("div");
  controls.className = "osloc-v028-timeline__controls";

  const previousEventButton = makeButton("◀ Event", () => jumpEvent(-1));
  previousEventButton.title = "Jump to the previous event start time";
  controls.append(previousEventButton);

  const play = makeButton(
    state.playing ? "Pause" : "Play",
    togglePlayback,
    "osloc-v028-timeline__play"
  );
  play.dataset.role = "timeline-play";
  controls.appendChild(play);

  const nextEventButton = makeButton("Event ▶", () => jumpEvent(1));
  nextEventButton.title = "Jump to the next event start time";
  controls.append(nextEventButton);

  const speedLabel = document.createElement("label");
  speedLabel.className = "osloc-v028-timeline__speed";
  speedLabel.textContent = "Speed ";

  const speed = document.createElement("select");
  for (const value of [1, 5, 10, 30, 60, 120, 300]) {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = `${value}×`;
    option.selected = value === state.speed;
    speed.appendChild(option);
  }

  speed.addEventListener("change", () => {
    state.speed = Number(speed.value);
  });

  speedLabel.appendChild(speed);
  controls.appendChild(speedLabel);

  top.append(left, controls);
  overlay.appendChild(top);

  const sliderWrap = document.createElement("div");
  sliderWrap.className = "osloc-v028-timeline__slider-wrap";

  const slider = document.createElement("input");
  slider.type = "range";
  slider.dataset.role = "timeline-slider";
  slider.className = "osloc-v028-timeline__slider";
  // Use a small native range domain (seconds from timeline start) rather than
  // 13-digit epoch millisecond values.
  const durationSeconds = Math.max(1, Math.ceil((range.max - range.min) / 1000));
  slider.min = "0";
  slider.max = String(durationSeconds);
  slider.step = "1";
  slider.value = String(Math.round(((state.currentMs ?? range.min) - range.min) / 1000));

  slider.addEventListener("pointerdown", (event) => {
    event.stopPropagation();
    stopPlayback();
    state.scrubbing = true;
    state.mode = "timeline";
  });

  slider.addEventListener("input", (event) => {
    event.stopPropagation();

    if (!state.scrubbing) {
      stopPlayback();
      state.scrubbing = true;
    }

    state.mode = "timeline";

    const offsetSeconds = Number(slider.value);
    state.currentMs = Math.max(
      range.min,
      Math.min(range.max, range.min + offsetSeconds * 1000)
    );

    // The native thumb and clock move immediately.
    updateTimelineDynamicUI();

    // Update event visibility on every scrub input. applyVisibility() computes
    // the current visible-event signature first, so MapLibre layout changes
    // occur only when the playhead actually crosses an event start/end boundary.
    // Between boundaries this is just a cheap comparison and UI refresh.
    applyVisibility(false);
  });

  const finishNativeScrub = (event) => {
    event?.stopPropagation?.();
    if (!state.scrubbing) return;

    const offsetSeconds = Number(slider.value);
    state.currentMs = Math.max(
      range.min,
      Math.min(range.max, range.min + offsetSeconds * 1000)
    );

    state.scrubbing = false;

    // Final consistency pass. Normally this is a no-op because the most recent
    // input event already applied the correct boundary state.
    applyVisibility(false);
    updateTimelineDynamicUI();
    updateDynamicUI();
  };

  slider.addEventListener("pointerup", finishNativeScrub);
  slider.addEventListener("pointercancel", finishNativeScrub);
  slider.addEventListener("change", finishNativeScrub);
  slider.addEventListener("blur", finishNativeScrub);

  sliderWrap.appendChild(slider);

  const labels = document.createElement("div");
  labels.className = "osloc-v028-timeline__labels";

  const start = document.createElement("span");
  start.textContent = formatPrimaryTimelineTime(range.min, includeDate);

  const end = document.createElement("span");
  end.textContent = formatPrimaryTimelineTime(range.max, includeDate);

  labels.append(start, end);

  overlay.append(sliderWrap, labels);

  // Put the timeline inside the map container, spanning the full map width.
  if (getComputedStyle(mapContainer).position === "static") {
    mapContainer.style.position = "relative";
  }

  mapContainer.appendChild(overlay);
}

function showEventDetails(event, sourceFeature = null) {
  if (!event) return;

  state.selectedEventKey = event.key;
  updateDynamicUI();

  // Re-registering the same floating-panel id refreshes its content.
  unregisterDetails?.();

  // GeoLibre's floating-panel title is a plain string/single-line surface.
  // Keep the adjusted date/time in the chrome and put the dataset name directly
  // below it in the panel body so long export names are not truncated.
  const panelTitle = formatMainEventLabel(event);
  const detailDescription = detailDescriptionForFeature(event, sourceFeature);

  unregisterDetails = state.app?.registerFloatingPanel?.({
    id: DETAILS_ID,
    title: panelTitle,
    defaultWidth: 390,

    render(container) {
      container.innerHTML = "";

      const root = document.createElement("div");
      root.className = "osloc-v028-details";

      if (event.datasetName) {
        const dataset = document.createElement("div");
        dataset.className = "osloc-v028-details__dataset";
        dataset.textContent = event.datasetName;
        root.appendChild(dataset);
      }

      const grid = document.createElement("dl");

      const add = (label, value) => {
        if (!value) return;
        const dt = document.createElement("dt");
        dt.textContent = label;
        const dd = document.createElement("dd");
        dd.textContent = value;
        grid.append(dt, dd);
      };

      add("Type", humanizeEventType(event.eventType));

      if (isTemporalEvent(event)) {
        const recordTime = formatRecordTime(event);
        const zoneOffset = formatTimezoneOffset(event);

        if (recordTime) add("Original record time", recordTime);
        if (zoneOffset) add("Time zone / offset", zoneOffset);

        // The adjusted time is already the floating-panel title.
        // Keep canonical UTC available only when it adds additional information.
        if (shouldShowUtcEquivalent(event)) {
          add("UTC equivalent", utcDateTime(event.startMs));
        }

        add(
          state.durationOverrideMs === null
            ? "Display duration"
            : "Display duration (viewer)",
          formatDisplayDuration(event)
        );
      } else {
        add("Timing", "Static / non-temporal");
      }

      root.appendChild(grid);

      if (detailDescription) {
        const heading = document.createElement("h4");
        heading.textContent = "Event details";

        const description = document.createElement("div");
        description.className = "osloc-v028-details__description";
        description.textContent = detailDescription;

        root.append(heading, description);
      } else if (event.placemarkNames.size) {
        const heading = document.createElement("h4");
        heading.textContent = "Map components";

        const names = document.createElement("div");
        names.className = "osloc-v028-details__description";
        names.textContent = [...event.placemarkNames].join("\n");

        root.append(heading, names);
      }

      const actions = document.createElement("div");
      actions.className = "osloc-v028-details__actions";

      actions.append(
        makeButton("Zoom to Event", () => {
          focusEvents([event]);
        })
      );

      if (isTemporalEvent(event)) {
        actions.append(
          makeButton("Jump Timeline Here", () => setTime(event.startMs))
        );
      }

      root.appendChild(actions);
      container.appendChild(root);

      return () => { };
    }
  }) ?? null;

  state.app?.openFloatingPanel?.(DETAILS_ID);
}

function eventFromMapFeature(feature) {
  const p = feature?.properties ?? {};

  const pluginEventKey = firstProp(p, "__oslocEventKey");
  if (pluginEventKey) {
    const pluginEvent = state.events.find(e => e.key === pluginEventKey);
    if (pluginEvent) return pluginEvent;
  }

  const key = eventKeyFromProps(p);

  if (key) {
    const exact = state.events.find(e => e.key === key);
    if (exact) return exact;
  }

  // Legacy fallback: if dataset_id is absent, match by event id only if unique.
  const eventId = firstProp(p, "osloc_event_id");
  if (!eventId) return null;

  const matches = state.events.filter(e => e.id === eventId);
  return matches.length === 1 ? matches[0] : null;
}

function handleMapClick(e) {
  const map = state.app?.getMap?.();
  if (!map) return;

  let features = [];
  try { features = map.queryRenderedFeatures(e.point) ?? []; }
  catch { return; }

  for (const feature of features) {
    const event = eventFromMapFeature(feature);
    if (event) {
      showEventDetails(event, feature);
      return;
    }
  }
}

function renderPanelSafe() {
  if (!state.container) return;

  try { renderPanel(); }
  catch (err) {
    console.error("[OSLOC] panel render failed", err);

    state.container.innerHTML = "";
    const box = document.createElement("div");
    box.className = "osloc-v028 osloc-v028__error";
    box.textContent = `OS-LOC-DAT-VIZ Viewer error: ${err?.message ?? String(err)}`;
    state.container.appendChild(box);
  }
}

function makeEventRow(event) {
  const row = document.createElement("div");
  row.className = "osloc-v028__event";
  row.dataset.eventKey = event.key;

  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.checked = state.enabledEventKeys.has(event.key);
  cb.title = "Include this event";
  cb.dataset.role = "toggle-event";
  cb.dataset.eventKey = event.key;

  const body = document.createElement("button");
  body.type = "button";
  body.className = "osloc-v028__event-body";
  body.title = "Select event and show details";
  body.dataset.role = "select-event";
  body.dataset.eventKey = event.key;

  const title = document.createElement("strong");
  title.textContent = formatMainEventLabel(event);

  const type = document.createElement("span");
  type.className = "osloc-v028__type";
  type.textContent = humanizeEventType(event.eventType);

  body.append(title, type);

  if (isTemporalEvent(event)) {
    const recordTime = formatRecordTime(event);
    const zoneOffset = formatTimezoneOffset(event);

    if (recordTime) {
      const original = document.createElement("span");
      original.className = "osloc-v028__record-time";
      original.textContent = `Original record time: ${recordTime}`;
      body.append(original);
    }

    if (zoneOffset) {
      const adjustment = document.createElement("span");
      adjustment.className = "osloc-v028__timezone-offset";
      adjustment.textContent = `Time zone / offset: ${zoneOffset}`;
      body.append(adjustment);
    }

    const duration = document.createElement("span");
    duration.className = "osloc-v028__duration";
    duration.textContent =
      `${state.durationOverrideMs === null ? "Display duration" : "Display duration (viewer)"}: ${formatDisplayDuration(event)}`;
    body.append(duration);
  } else {
    const staticLabel = document.createElement("span");
    staticLabel.textContent = "Static / non-temporal";
    body.append(staticLabel);
  }

  row.append(cb, body);
  return row;
}

function getEventByKey(key) {
  if (!key) return null;
  return state.eventByKey.get(key) || state.events.find(e => e.key === key) || null;
}

function wireEventListDelegates(list) {
  list.addEventListener("change", event => {
    const target = event.target;
    if (target?.dataset?.role !== "toggle-event") return;

    const key = target.dataset.eventKey;
    const entry = getEventByKey(key);
    if (!entry) return;

    if (target.checked) state.enabledEventKeys.add(entry.key);
    else state.enabledEventKeys.delete(entry.key);

    markEnabledEventsChanged();
    applyVisibility(true);
  });

  list.addEventListener("click", event => {
    const target = event.target;
    if (target?.dataset?.role !== "select-event") return;

    const key = target.dataset.eventKey;
    const entry = getEventByKey(key);
    if (entry) showEventDetails(entry);
  });
}

function appendEventRowsChunked(list, events) {
  const token = panelRenderToken;
  const chunkSize = events.length > 400 ? 120 : events.length;
  let index = 0;

  const step = () => {
    if (token !== panelRenderToken) return;

    const end = Math.min(events.length, index + chunkSize);
    for (; index < end; index++) {
      list.appendChild(makeEventRow(events[index]));
    }

    if (index < events.length) {
      nextAnimationFrame(step);
    }
  };

  step();
}

function renderEventList(events, labelText = "") {
  if (!events.length) return null;

  const wrapper = document.createElement("div");
  wrapper.className = "osloc-v028__section";

  if (labelText) {
    const label = document.createElement("div");
    label.className = "osloc-v028__section-label";
    label.textContent = labelText;
    wrapper.appendChild(label);
  }

  const list = document.createElement("div");
  list.className = "osloc-v028__events";
  wireEventListDelegates(list);
  appendEventRowsChunked(list, events);

  wrapper.appendChild(list);
  return wrapper;
}

function makeLabelsControl() {
  const wrap = document.createElement("label");
  wrap.className = "osloc-v028__labels-control";
  wrap.title = "Show adjusted event times on the map.";

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = state.labelsEnabled;
  checkbox.setAttribute("aria-label", "Show times on map");

  const text = document.createElement("span");
  text.textContent = "Show times on map";

  checkbox.addEventListener("change", () => {
    state.labelsEnabled = checkbox.checked;
    updateMapLabels();
  });

  wrap.append(checkbox, text);
  return wrap;
}

function makeDurationControl() {
  const wrap = document.createElement("label");
  wrap.className = "osloc-v028__duration-control";
  wrap.title =
    "Change how long all temporal events remain visible in this viewer. The KML file is not modified.";

  const label = document.createElement("span");
  label.textContent = "Duration";

  const select = document.createElement("select");
  select.setAttribute("aria-label", "Display duration");

  const options = [
    ["", "KML"],
    ["60000", "1 min"],
    ["300000", "5 min"],
    ["600000", "10 min"],
    ["900000", "15 min"],
    ["1800000", "30 min"],
    ["3600000", "60 min"],
    ["7200000", "2 hr"],
  ];

  const current = state.durationOverrideMs === null
    ? ""
    : String(state.durationOverrideMs);

  for (const [value, text] of options) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    option.selected = value === current;
    select.appendChild(option);
  }

  select.addEventListener("change", () => {
    stopPlayback();

    state.durationOverrideMs =
      select.value === "" ? null : Number(select.value);

    rebuildTimelineBoundaries();
    const range = timelineRange();
    if (range && state.currentMs !== null) {
      state.currentMs = Math.max(
        range.min,
        Math.min(range.max, state.currentMs)
      );
    }

    lastVisibilitySignature = "";
    applyVisibility(true);

    // Event cards and the timeline range both depend on the chosen duration.
    renderPanelSafe();
    renderTimelineOverlay();
  });

  wrap.append(label, select);
  return wrap;
}

function renderPanel() {
  panelRenderToken++;
  const c = state.container;
  c.innerHTML = "";

  const root = document.createElement("div");
  root.className = "osloc-v028";

  const toolbar = document.createElement("div");
  toolbar.className = "osloc-v028__toolbar";

  toolbar.append(
    makeButton("Show All", () => {
      // Enable every event; an active date/time range remains an independent filter.
      stopPlayback();
      state.mode = "overview";
      for (const e of state.events) state.enabledEventKeys.add(e.key);
      markEnabledEventsChanged();
      lastVisibilitySignature = "";
      applyVisibility(true);
      renderPanelSafe();
      updateTimelineDynamicUI();
    }),

    makeButton("Timeline", () => {
      stopPlayback();
      state.mode = "timeline";

      const r = timelineRange();
      if (r && state.currentMs === null) state.currentMs = r.min;

      lastVisibilitySignature = "";
      applyVisibility(true);
      updateTimelineDynamicUI();
    }),

    makeButton("Hide All", () => {
      stopPlayback();
      state.enabledEventKeys.clear();
      markEnabledEventsChanged();
      lastVisibilitySignature = "";
      applyVisibility(true);
      renderPanelSafe();
    }),

    makeButton("Focus All", () => {
      focusEvents(state.events);
    })
  );

  const focusButton = toolbar.lastElementChild;
  if (focusButton) {
    focusButton.title = "Show and frame all record sets within the active date/time range";
    focusButton.disabled = eventsMatchingDateFilter().length === 0;
  }

  toolbar.appendChild(makeDurationControl());
  toolbar.appendChild(makeLabelsControl());

  root.appendChild(toolbar);
  root.appendChild(makeDateFilterControl());

  const summary = document.createElement("div");
  summary.className = "osloc-v028__summary";

  const left = document.createElement("strong");
  const eventsInRange = eventsMatchingDateFilter();
  left.textContent = dateFilterActive()
    ? `${eventsInRange.length} of ${state.events.length} events in range`
    : `${state.events.length} event${state.events.length === 1 ? "" : "s"}`;

  const right = document.createElement("span");
  right.dataset.role = "visible-count";
  right.textContent = dateFilterActive()
    ? `${state.events.filter(shouldShow).length} of ${eventsInRange.length} in-range events visible`
    : `${state.events.filter(shouldShow).length} of ${state.events.length} events visible`;

  summary.append(left, right);
  root.appendChild(summary);

  if (!state.events.length) {
    const empty = document.createElement("div");
    empty.className = "osloc-v028__empty";
    empty.innerHTML =
      "<strong>Waiting for OS-LOC-DAT-VIZ data…</strong><br>" +
      "Drag or load one or more KML or GeoJSON files into GeoLibre. The viewer will detect them automatically.";

    root.appendChild(empty);
    root.appendChild(makeAboutSection());
    c.appendChild(root);
    return;
  }

  const hint = document.createElement("div");
  hint.className = "osloc-v028__hint";

  const hintLine1 = document.createElement("div");
  hintLine1.textContent = "Click an event here or on the map to view its details.";

  const hintLine2 = document.createElement("div");
  hintLine2.textContent = "Date/time range also limits the timeline. Focus All frames every matching record set; Focus Set isolates one record set.";

  hint.append(hintLine1, hintLine2);
  root.appendChild(hint);

  const datasets = document.createElement("div");
  datasets.className = "osloc-v028__datasets";

  for (const dataset of state.datasets) {
    const matchingEvents = eventsMatchingDateFilter(dataset.events);
    const section = document.createElement("section");
    section.className = "osloc-v028__dataset";

    const dh = document.createElement("div");
    dh.className = "osloc-v028__dataset-head";

    const dsCheck = document.createElement("input");
    dsCheck.type = "checkbox";

    const dsState = datasetEnabledState(dataset);
    dsCheck.checked = dsState.checked;
    dsCheck.indeterminate = dsState.indeterminate;
    dsCheck.title = "Enable/disable this entire KML dataset";

    dsCheck.addEventListener("change", () => {
      setDatasetEnabled(dataset, dsCheck.checked);
    });

    const titleButton = document.createElement("button");
    titleButton.type = "button";
    titleButton.className = "osloc-v028__dataset-title";

    const collapsed = state.collapsedDatasets.has(dataset.id);

    titleButton.addEventListener("click", () => {
      if (collapsed) state.collapsedDatasets.delete(dataset.id);
      else state.collapsedDatasets.add(dataset.id);

      renderPanelSafe();
    });

    const title = document.createElement("strong");
    title.textContent = `${collapsed ? "▶" : "▼"} ${dataset.name}`;

    const meta = document.createElement("span");
    meta.textContent = dateFilterActive()
      ? `${matchingEvents.length} of ${dataset.events.length} events in range`
      : `${dataset.events.length} event${dataset.events.length === 1 ? "" : "s"}`;

    titleButton.append(title, meta);

    const zoom = makeButton("Focus Set", () => {
      focusEvents(dataset.events);
    });
    zoom.title = "Show only matching events from this record set and frame them on the map";
    zoom.disabled = matchingEvents.length === 0;

    dh.append(dsCheck, titleButton, zoom);
    section.appendChild(dh);

    if (!collapsed) {
      const temporal = matchingEvents.filter(isTemporalEvent);
      const statics = matchingEvents.filter(e => !isTemporalEvent(e));
      const mixed = temporal.length > 0 && statics.length > 0;

      // In the common case, put event cards directly under the dataset.
      // Only show subsection labels when temporal and static data coexist.
      const temporalList = renderEventList(
        temporal,
        mixed ? `Timeline events (${temporal.length})` : ""
      );

      const staticList = renderEventList(
        statics,
        mixed ? `Static events (${statics.length})` : ""
      );

      if (temporalList) section.appendChild(temporalList);
      if (staticList) section.appendChild(staticList);
      if (!matchingEvents.length) {
        const emptyRange = document.createElement("div");
        emptyRange.className = "osloc-v028__date-filter-empty";
        emptyRange.textContent = "No events in this date/time range";
        section.appendChild(emptyRange);
      }
    }

    datasets.appendChild(section);
  }

  root.appendChild(datasets);

  const diagnostics = document.createElement("details");
  diagnostics.className = "osloc-v028__diag";

  const summaryEl = document.createElement("summary");
  summaryEl.textContent = "Diagnostics";

  const detail = document.createElement("div");
  detail.textContent =
    `Last scan: ${state.lastScanReason || "startup"} • ` +
    `render mappings: ${state.mappingStats.nativeMapped} ` +
    `(metadata ${state.mappingStats.nativeMetadata}, layer match ${state.mappingStats.fallbackMapped}) • ` +
    `shared layers: ${state.mappingStats.sharedFilteredLayers} • ` +
    `ambiguous render layers: ${state.mappingStats.ambiguousRenderLayers} • ` +
    `ambiguous source groups: ${state.mappingStats.ambiguousSourceGroups} • ` +
    `unmapped events: ${state.mappingStats.unmappedEvents}`;

  diagnostics.append(summaryEl, detail);
  root.appendChild(diagnostics);
  root.appendChild(makeAboutSection());

  c.appendChild(root);
  updateDynamicUI();
}

function scheduleFullScan(reason, retries = 5) {
  if (scanDebounceTimer !== null) clearTimeout(scanDebounceTimer);

  scanDebounceTimer = setTimeout(() => {
    scanDebounceTimer = null;
    const layers = safeListLayers();
    const signature = relevantLayerSignature(layers);
    const shouldSkip =
      signature &&
      signature === lastScannedRelevantSignature &&
      state.events.length > 0;

    if (shouldSkip) {
      state.lastScanReason = `${reason}-skipped-unchanged`;
      updateDynamicUI();
      updateTimelineDynamicUI();
      return;
    }

    const found = scanAll(reason);
    lastScannedRelevantSignature = signature;

    if (scanRetryTimer !== null) clearInterval(scanRetryTimer);

    // Feature data is ready: no reason to continue recreating/re-indexing UI.
    if (found > 0) {
      scanRetryTimer = null;
      return;
    }

    let remaining = retries;

    scanRetryTimer = setInterval(() => {
      remaining--;

      if (remaining <= 0) {
        clearInterval(scanRetryTimer);
        scanRetryTimer = null;
        return;
      }

      const retryLayers = safeListLayers();
      const retrySignature = relevantLayerSignature(retryLayers);
      if (retrySignature === lastScannedRelevantSignature && state.events.length > 0) {
        clearInterval(scanRetryTimer);
        scanRetryTimer = null;
        return;
      }

      const retryFound = scanAll(`${reason}-retry`);
      lastScannedRelevantSignature = retrySignature;
      if (retryFound > 0) {
        clearInterval(scanRetryTimer);
        scanRetryTimer = null;
      }
    }, 700);
  }, 150);
}

function attachMapWatchers() {
  detachMapEvents.forEach(fn => fn());
  detachMapEvents = [];

  const map = state.app?.getMap?.();
  if (!map?.on || !map?.off) return;

  map.on("click", handleMapClick);
  map.on("styledata", scheduleRenderingReconcile);
  map.on("sourcedata", scheduleRenderingReconcile);

  detachMapEvents.push(() => {
    try { map.off("click", handleMapClick); } catch { }
    try { map.off("styledata", scheduleRenderingReconcile); } catch { }
    try { map.off("sourcedata", scheduleRenderingReconcile); } catch { }
  });
}

function startLayerMonitor() {
  if (pollTimer !== null) clearInterval(pollTimer);

  pollTimer = setInterval(() => {
    const layers = safeListLayers();
    const signature = relevantLayerSignature(layers);

    if (signature !== lastLayerSignature) {
      lastLayerSignature = signature;
      scheduleFullScan("layer-list-change", 8);
    }
  }, 1200);
}

export const plugin = {
  id: PLUGIN_ID,
  name: "OS-LOC-DAT-VIZ Viewer",
  version: PLUGIN_VERSION,
  restoresPanelCollapseState: true,

  applyProjectState(_app, projectState) {
    const settings = projectState && typeof projectState === "object" ? projectState : {};
    state.dateFilterStart = "";
    state.dateFilterEnd = "";
    state.dateFilterAuto = true;
    state.autoShowAll = settings.autoShowAll === true;
    state.autoFocus = settings.autoFocus === true;
    setSimplifiedChrome(settings.simplifiedViewer === true);
    state.startupDatasetId = String(settings.startupDatasetId ?? "");
    state.startupBehaviorApplied = false;
    lastScannedRelevantSignature = "";

    if (state.app) {
      if (state.simplifiedViewer) state.app.openRightPanel?.(PANEL_ID);
      scheduleFullScan("project-settings", 8);
    }
  },

  activate(app) {
    state.app = app;

    unregisterPanel = app.registerRightPanel?.({
      id: PANEL_ID,
      title: "OS-LOC-DAT-VIZ",
      dock: "replace-layers",
      defaultWidth: 440,

      render(container) {
        state.container = container;
        renderPanelSafe();

        attachMapWatchers();
        startLayerMonitor();
        lastLayerSignature = relevantLayerSignature(safeListLayers());
        scheduleFullScan("panel-open", 10);

        return () => {
          state.container = null;
          stopPlayback();
        };
      },

      onOpen() {
        attachMapWatchers();
        startLayerMonitor();
        lastLayerSignature = relevantLayerSignature(safeListLayers());
        scheduleFullScan("panel-reopen", 8);
      }
    }) ?? null;

    unregisterMenu = app.registerToolbarMenu?.({
      id: "osloc-dat-viz-menu",
      label: "OS-LOC-DAT-VIZ",
      items: [
        {
          id: "open",
          label: "Open Event Viewer",
          onSelect: () => app.openRightPanel?.(PANEL_ID)
        },
        {
          id: "show-all",
          label: "Show All Events",
          onSelect: () => {
            stopPlayback();
            state.mode = "overview";
            for (const e of state.events) state.enabledEventKeys.add(e.key);
            markEnabledEventsChanged();
            lastVisibilitySignature = "";
            applyVisibility(true);
            renderPanelSafe();
            updateTimelineDynamicUI();
            app.openRightPanel?.(PANEL_ID);
          }
        },
        {
          id: "fit-data",
          label: "Focus",
          onSelect: () => {
            focusEvents(state.events);
          }
        },
        {
          id: "about",
          label: "About & Licenses",
          onSelect: () => {
            app.openRightPanel?.(PANEL_ID);
            renderPanelSafe();
            nextAnimationFrame(() => {
              const about = state.container?.querySelector?.(
                "[data-role='about-licenses']"
              );
              if (!about) return;
              about.open = true;
              about.scrollIntoView?.({ block: "nearest" });
            });
          }
        },
        {
          id: "layer-diag",
          label: "Dump Layer Diagnostics",
          onSelect: () => {
            const report = collectOslocLayerDiagnostics();
            if (!report) {
              console.info("[OSLOC] Layer diagnostics unavailable");
              return;
            }
            console.info("[OSLOC] Layer diagnostics", report);
            console.info("[OSLOC] Layer diagnostics (json)", JSON.stringify(report, null, 2));
          }
        }
      ]
    }) ?? null;

    setSimplifiedChrome(state.simplifiedViewer);
    app.openRightPanel?.(PANEL_ID);
  },

  deactivate(app) {
    setSimplifiedChrome(false);
    stopPlayback();
    restoreHiddenAnchorSymbolStyles();
    restoreSharedLayerFilters();
    removeGeojsonRenderingOwnership();
    removeTimelineOverlay();
    removeMapLabelLayer();

    if (pollTimer !== null) clearInterval(pollTimer);
    if (scanRetryTimer !== null) clearInterval(scanRetryTimer);
    if (scanDebounceTimer !== null) clearTimeout(scanDebounceTimer);
    if (renderReconcileTimer !== null) clearTimeout(renderReconcileTimer);

    pollTimer = null;
    scanRetryTimer = null;
    scanDebounceTimer = null;
    renderReconcileTimer = null;
    lastLayerSignature = "";
    lastScannedRelevantSignature = "";
    lastNativeStyleSignature = "";

    detachMapEvents.forEach(fn => fn());
    detachMapEvents = [];

    app.closeFloatingPanel?.(DETAILS_ID);
    unregisterDetails?.();
    unregisterDetails = null;

    app.closeRightPanel?.(PANEL_ID);
    unregisterMenu?.();
    unregisterPanel?.();

    unregisterMenu = null;
    unregisterPanel = null;

    state.container = null;
    state.app = null;
  }
};

export default plugin;
