"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

import argparse
import copy
import json
import re
from collections import OrderedDict
from pathlib import Path
import xml.etree.ElementTree as ET

KML_NS = "http://www.opengis.net/kml/2.2"
NS = {"k": KML_NS}
ET.register_namespace("", KML_NS)

ESSENTIAL_EVENT_KEYS = {
    "osloc_schema_version",
    "osloc_dataset_id",
    "osloc_dataset_name",
    "osloc_event_id",
    "osloc_event_label",
    "osloc_event_type",
    "osloc_component_type",
    "osloc_start_time",
    "osloc_end_time",
    "osloc_local_start_time",
    "osloc_local_end_time",
    "osloc_timezone",
    "osloc_display_time",
}


def q(tag):
    return f"{{{KML_NS}}}{tag}"


def local_name(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def deep_clone(elem):
    return copy.deepcopy(elem)


def find_document(root):
    document = root.find("k:Document", NS)
    if document is None:
        raise ValueError("KML Document element not found")
    return document


def first_dataset_folder(document):
    folder = document.find("k:Folder", NS)
    if folder is None:
        return None
    return folder


def parse_extended_data_map(placemark):
    result = {}
    for data in placemark.findall("k:ExtendedData/k:Data", NS):
        name = data.get("name")
        if not name:
            continue
        value = data.findtext("k:value", default="", namespaces=NS)
        result[name] = value
    return result


def group_placemarks_by_event(placemarks):
    ordered = OrderedDict()
    for index, placemark in enumerate(placemarks):
        props = parse_extended_data_map(placemark)
        event_id = props.get("osloc_event_id")
        dataset_id = props.get("osloc_dataset_id", "legacy")
        if not event_id:
            event_id = f"unknown_event_{index + 1:06d}"
        key = f"{dataset_id}::{event_id}"
        if key not in ordered:
            ordered[key] = []
        ordered[key].append(placemark)
    return ordered


def coordinate_tuple_count(root):
    total = 0
    for coordinates in root.findall(".//k:coordinates", NS):
        text = (coordinates.text or "").strip()
        if not text:
            continue
        tokens = re.split(r"\s+", text)
        total += sum(1 for token in tokens if token and "," in token)
    return total


def collect_stats(path):
    text = path.read_text(encoding="utf-8")
    root = ET.fromstring(text)
    polygons = root.findall(".//k:Polygon", NS)
    lines = root.findall(".//k:LineString", NS)
    points = root.findall(".//k:Point", NS)
    placemarks = root.findall(".//k:Placemark", NS)
    folders = root.findall(".//k:Folder", NS)

    event_ids = set()
    for placemark in placemarks:
        event_id = parse_extended_data_map(placemark).get("osloc_event_id")
        if event_id:
            event_ids.add(event_id)

    return {
        "file": path.name,
        "events": len(event_ids),
        "folders": len(folders),
        "placemarks": len(placemarks),
        "polygons": len(polygons),
        "linestrings": len(lines),
        "points": len(points),
        "geometry_primitives": len(polygons) + len(lines) + len(points),
        "coordinate_tuples": coordinate_tuple_count(root),
        "bytes": path.stat().st_size,
        "mb": round(path.stat().st_size / (1024 * 1024), 3),
    }


def make_document_skeleton(source_document, include_source_styles=True):
    kml = ET.Element(q("kml"))
    document = ET.SubElement(kml, q("Document"))

    for child in list(source_document):
        tag = local_name(child.tag)
        if tag in {"Folder", "Placemark"}:
            continue
        if not include_source_styles and tag in {"Style", "StyleMap"}:
            continue
        document.append(deep_clone(child))

    return kml, document


def add_dataset_folder(document, source_folder):
    folder = ET.SubElement(document, q("Folder"))
    if source_folder is not None:
        source_name = source_folder.findtext("k:name", default="", namespaces=NS)
    else:
        source_name = document.findtext("k:name", default="OS-LOC Diagnostic", namespaces=NS)
    name = ET.SubElement(folder, q("name"))
    name.text = source_name
    visibility = ET.SubElement(folder, q("visibility"))
    visibility.text = "0"
    return folder


def append_placemarks(folder, placemarks):
    for placemark in placemarks:
        folder.append(deep_clone(placemark))


def remove_descriptions(root):
    for placemark in root.findall(".//k:Placemark", NS):
        for description in placemark.findall("k:description", NS):
            placemark.remove(description)


def retain_only_essential_extended_data(root):
    for placemark in root.findall(".//k:Placemark", NS):
        ext = placemark.find("k:ExtendedData", NS)
        if ext is None:
            continue
        for data in list(ext.findall("k:Data", NS)):
            if data.get("name") not in ESSENTIAL_EVENT_KEYS:
                ext.remove(data)


def remove_balloonstyle_blocks(root):
    for style in root.findall(".//k:Style", NS):
        for balloon in list(style.findall("k:BalloonStyle", NS)):
            style.remove(balloon)


def remove_timespans(root):
    for placemark in root.findall(".//k:Placemark", NS):
        for timespan in list(placemark.findall("k:TimeSpan", NS)):
            placemark.remove(timespan)
    for folder in root.findall(".//k:Folder", NS):
        for timespan in list(folder.findall("k:TimeSpan", NS)):
            folder.remove(timespan)


def geometry_kind(placemark):
    kinds = [
        kind
        for kind, tag in (
            ("polygon", "Polygon"),
            ("line", "LineString"),
            ("point", "Point"),
        )
        if placemark.find(f".//k:{tag}", NS) is not None
    ]
    if len(kinds) == 1:
        return kinds[0]
    return "mixed" if kinds else "other"


def set_minimal_styles(document):
    for child in list(document):
        if local_name(child.tag) in {"Style", "StyleMap"}:
            document.remove(child)

    style_poly = ET.SubElement(document, q("Style"), {"id": "diag-poly"})
    poly_line = ET.SubElement(style_poly, q("LineStyle"))
    ET.SubElement(poly_line, q("color")).text = "ff606060"
    ET.SubElement(poly_line, q("width")).text = "1"
    poly_fill = ET.SubElement(style_poly, q("PolyStyle"))
    ET.SubElement(poly_fill, q("color")).text = "4d808080"

    style_line = ET.SubElement(document, q("Style"), {"id": "diag-line"})
    line_line = ET.SubElement(style_line, q("LineStyle"))
    ET.SubElement(line_line, q("color")).text = "ff909090"
    ET.SubElement(line_line, q("width")).text = "2"

    style_point = ET.SubElement(document, q("Style"), {"id": "diag-point"})
    icon_style = ET.SubElement(style_point, q("IconStyle"))
    ET.SubElement(icon_style, q("scale")).text = "0.9"
    label_style = ET.SubElement(style_point, q("LabelStyle"))
    ET.SubElement(label_style, q("scale")).text = "0.7"

    style_all = ET.SubElement(document, q("Style"), {"id": "diag-all"})
    all_line = ET.SubElement(style_all, q("LineStyle"))
    ET.SubElement(all_line, q("color")).text = "ff909090"
    ET.SubElement(all_line, q("width")).text = "2"
    all_fill = ET.SubElement(style_all, q("PolyStyle"))
    ET.SubElement(all_fill, q("color")).text = "4d808080"
    all_icon = ET.SubElement(style_all, q("IconStyle"))
    ET.SubElement(all_icon, q("scale")).text = "0.9"
    all_label = ET.SubElement(style_all, q("LabelStyle"))
    ET.SubElement(all_label, q("scale")).text = "0.7"


def apply_minimal_style_urls(root):
    style_by_kind = {
        "polygon": "#diag-poly",
        "line": "#diag-line",
        "point": "#diag-point",
        "mixed": "#diag-all",
    }
    for placemark in root.findall(".//k:Placemark", NS):
        kind = geometry_kind(placemark)
        style = style_by_kind.get(kind)
        if not style:
            continue
        style_url = placemark.find("k:styleUrl", NS)
        if style_url is None:
            style_url = ET.SubElement(placemark, q("styleUrl"))
        style_url.text = style


def first_point_coordinates(placemarks):
    preferred_components = {"center_point", "location_point"}

    for placemark in placemarks:
        props = parse_extended_data_map(placemark)
        component = props.get("osloc_component_type")
        if component in preferred_components:
            point = placemark.find(".//k:Point/k:coordinates", NS)
            if point is not None and (point.text or "").strip():
                return (point.text or "").strip()

    for placemark in placemarks:
        point = placemark.find(".//k:Point/k:coordinates", NS)
        if point is not None and (point.text or "").strip():
            return (point.text or "").strip()

    for placemark in placemarks:
        coordinates = placemark.find(".//k:coordinates", NS)
        if coordinates is None:
            continue
        tokens = re.split(r"\s+", (coordinates.text or "").strip())
        for token in tokens:
            if token and "," in token:
                return token

    return None


def first_timespan(placemarks):
    for placemark in placemarks:
        timespan = placemark.find("k:TimeSpan", NS)
        if timespan is not None:
            return deep_clone(timespan)
    return None


def combined_extended_data(placemarks):
    merged = {}
    for placemark in placemarks:
        for key, value in parse_extended_data_map(placemark).items():
            if key not in merged and value:
                merged[key] = value

    ext = ET.Element(q("ExtendedData"))
    for key in sorted(k for k in merged if k in ESSENTIAL_EVENT_KEYS):
        data = ET.SubElement(ext, q("Data"), {"name": key})
        ET.SubElement(data, q("value")).text = merged[key]
    return ext


def build_one_point_per_event(event_groups, source_document, source_folder):
    kml, document = make_document_skeleton(source_document, include_source_styles=False)
    set_minimal_styles(document)
    folder = add_dataset_folder(document, source_folder)

    for _, placemarks in event_groups.items():
        coords = first_point_coordinates(placemarks)
        if not coords:
            continue

        props = parse_extended_data_map(placemarks[0])
        label = props.get("osloc_event_label") or props.get("osloc_event_id") or "Event"

        placemark = ET.SubElement(folder, q("Placemark"))
        ET.SubElement(placemark, q("name")).text = f"{label} Source Point"

        timespan = first_timespan(placemarks)
        if timespan is not None:
            placemark.append(timespan)

        placemark.append(combined_extended_data(placemarks))
        ET.SubElement(placemark, q("styleUrl")).text = "#diag-point"
        point = ET.SubElement(placemark, q("Point"))
        ET.SubElement(point, q("coordinates")).text = coords

    return kml


def retain_geometry_kind(placemark, allowed_kind):
    allowed_tag = {
        "polygon": "Polygon",
        "line": "LineString",
        "point": "Point",
    }[allowed_kind]
    filtered = deep_clone(placemark)
    primitive_tags = {"Polygon", "LineString", "Point"}

    def prune(container):
        retained = False
        for child in list(container):
            tag = local_name(child.tag)
            if tag in primitive_tags:
                if tag == allowed_tag:
                    retained = True
                else:
                    container.remove(child)
            elif tag == "MultiGeometry":
                if prune(child):
                    retained = True
                else:
                    container.remove(child)
        return retained

    return filtered if prune(filtered) else None


def filter_placemarks_by_geometry(placemarks, allowed_kind):
    filtered = []
    for placemark in placemarks:
        retained = retain_geometry_kind(placemark, allowed_kind)
        if retained is not None:
            filtered.append(retained)
    return filtered


def collect_source_placemarks(document):
    top_level_folders = document.findall("k:Folder", NS)
    dataset_folder = None

    if len(top_level_folders) == 1:
        candidate = top_level_folders[0]
        # Flattened exports keep one dataset folder that owns all placemarks.
        if len(candidate.findall(".//k:Placemark", NS)) > 1:
            dataset_folder = candidate

    placemarks = document.findall(".//k:Placemark", NS)
    return dataset_folder, placemarks


def write_kml(path, root):
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    path.write_bytes(xml)


def variant_full_subset(source_document, source_folder, selected_placemarks):
    kml, document = make_document_skeleton(source_document)
    folder = add_dataset_folder(document, source_folder)
    append_placemarks(folder, selected_placemarks)
    return kml


def variant_min_metadata(source_document, source_folder, selected_placemarks):
    kml = variant_full_subset(source_document, source_folder, selected_placemarks)
    remove_descriptions(kml)
    retain_only_essential_extended_data(kml)
    remove_balloonstyle_blocks(kml)
    return kml


def variant_min_style(source_document, source_folder, selected_placemarks):
    kml, document = make_document_skeleton(source_document, include_source_styles=False)
    set_minimal_styles(document)
    folder = add_dataset_folder(document, source_folder)
    append_placemarks(folder, selected_placemarks)
    apply_minimal_style_urls(kml)
    return kml


def variant_no_timespan(source_document, source_folder, selected_placemarks):
    kml = variant_full_subset(source_document, source_folder, selected_placemarks)
    remove_timespans(kml)
    return kml


def produce_table_rows(rows):
    header = (
        "Variant | Events | Placemarks | Geometry primitives | Coordinate tuples | "
        "File MB | Metadata | Styles | TimeSpan"
    )
    sep = "---|---:|---:|---:|---:|---:|---|---|---"
    body = []
    for row in rows:
        body.append(
            f"{row['file']} | {row['events']} | {row['placemarks']} | "
            f"{row['geometry_primitives']} | {row['coordinate_tuples']} | {row['mb']:.3f} | "
            f"{row['metadata']} | {row['styles']} | {row['timespan']}"
        )
    return "\n".join([header, sep] + body)


def main():
    parser = argparse.ArgumentParser(
        description="Generate GeoLibre KML import diagnostic matrix variants"
    )
    parser.add_argument("--input-kml", required=True, help="Path to source production KML")
    parser.add_argument(
        "--output-dir",
        default="diagnostics/geolibre_import_matrix",
        help="Directory for diagnostic KML outputs",
    )
    args = parser.parse_args()

    input_path = Path(args.input_kml)
    if not input_path.exists():
        raise FileNotFoundError(f"Input KML not found: {input_path}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    source_root = ET.fromstring(input_path.read_text(encoding="utf-8"))
    source_document = find_document(source_root)
    source_folder, source_placemarks = collect_source_placemarks(source_document)

    event_groups = group_placemarks_by_event(source_placemarks)
    ordered_keys = list(event_groups.keys())
    total_events = len(ordered_keys)

    subset_sizes = [500, 1000, 2000, 3000, 4000, total_events]
    rows = []

    for size in subset_sizes:
        selected_keys = ordered_keys[: min(size, total_events)]
        subset = []
        for key in selected_keys:
            subset.extend(event_groups[key])
        file_name = f"DIAG_{size:04d}_FULL.kml" if size != total_events else "DIAG_FULL_FULL.kml"
        path = output_dir / file_name
        write_kml(path, variant_full_subset(source_document, source_folder, subset))
        stats = collect_stats(path)
        stats.update({"metadata": "Full", "styles": "Full", "timespan": "Yes"})
        rows.append(stats)

    full_subset = []
    for key in ordered_keys:
        full_subset.extend(event_groups[key])

    min_meta_path = output_dir / "DIAG_FULL_MIN_METADATA.kml"
    write_kml(min_meta_path, variant_min_metadata(source_document, source_folder, full_subset))
    min_meta_stats = collect_stats(min_meta_path)
    min_meta_stats.update({"metadata": "Minimal", "styles": "Full (no BalloonStyle)", "timespan": "Yes"})
    rows.append(min_meta_stats)

    min_style_path = output_dir / "DIAG_FULL_MIN_STYLE.kml"
    write_kml(min_style_path, variant_min_style(source_document, source_folder, full_subset))
    min_style_stats = collect_stats(min_style_path)
    min_style_stats.update({"metadata": "Full", "styles": "Minimal shared", "timespan": "Yes"})
    rows.append(min_style_stats)

    one_point_path = output_dir / "DIAG_FULL_ONE_POINT_PER_EVENT.kml"
    write_kml(one_point_path, build_one_point_per_event(event_groups, source_document, source_folder))
    one_point_stats = collect_stats(one_point_path)
    one_point_stats.update({"metadata": "Essential", "styles": "Minimal shared", "timespan": "Yes"})
    rows.append(one_point_stats)

    polygons_path = output_dir / "DIAG_FULL_POLYGONS_ONLY.kml"
    write_kml(polygons_path, variant_full_subset(
        source_document,
        source_folder,
        filter_placemarks_by_geometry(full_subset, "polygon"),
    ))
    polygons_stats = collect_stats(polygons_path)
    polygons_stats.update({"metadata": "Full", "styles": "Full", "timespan": "Yes"})
    rows.append(polygons_stats)

    lines_path = output_dir / "DIAG_FULL_LINES_ONLY.kml"
    write_kml(lines_path, variant_full_subset(
        source_document,
        source_folder,
        filter_placemarks_by_geometry(full_subset, "line"),
    ))
    lines_stats = collect_stats(lines_path)
    lines_stats.update({"metadata": "Full", "styles": "Full", "timespan": "Yes"})
    rows.append(lines_stats)

    points_path = output_dir / "DIAG_FULL_POINTS_ONLY.kml"
    write_kml(points_path, variant_full_subset(
        source_document,
        source_folder,
        filter_placemarks_by_geometry(full_subset, "point"),
    ))
    points_stats = collect_stats(points_path)
    points_stats.update({"metadata": "Full", "styles": "Full", "timespan": "Yes"})
    rows.append(points_stats)

    no_timespan_path = output_dir / "DIAG_FULL_NO_TIMESPAN.kml"
    write_kml(no_timespan_path, variant_no_timespan(source_document, source_folder, full_subset))
    no_timespan_stats = collect_stats(no_timespan_path)
    no_timespan_stats.update({"metadata": "Full", "styles": "Full", "timespan": "No"})
    rows.append(no_timespan_stats)

    report = {
        "input_kml": str(input_path),
        "output_dir": str(output_dir),
        "total_events_detected": total_events,
        "variants": rows,
    }

    (output_dir / "DIAG_REPORT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (output_dir / "DIAG_REPORT.md").write_text(produce_table_rows(rows) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
