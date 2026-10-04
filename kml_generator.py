"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

import pandas as pd
import math
import textwrap
import re
import copy
import json
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from PyQt6.QtCore import QThread, pyqtSignal


class TimestampResolutionError(Exception):
    """Raised when a local timestamp cannot be mapped to one UTC instant."""


OSLOC_SCHEMA_VERSION = "1"
PRELIMINARY_REVIEW_NOTICE = (
    "Preliminary visualization only. All data, assumptions, conversions, "
    "and generated geometry require independent expert verification."
)

DATA_TYPE_LABELS = {
    'Tower/Sector': 'Cell Site/Sector',
    'Distance from Tower': 'Distance from Cell Site',
    'Location Point': 'Location Point',
}


def data_type_label(data_type: str) -> str:
    """Display record types without changing compatibility identifiers."""
    return DATA_TYPE_LABELS.get(data_type, data_type)


EVENT_TYPES = {
    'tower_sector': 'tower_sector',
    'tower_sector_distance': 'tower_sector_distance',
    'tower_no_azimuth': 'tower_no_azimuth',
    'distance_only': 'distance_only',
    'location': 'location',
    'location_accuracy': 'location_accuracy',
    'reference_site': 'reference_site',
    'marker': 'marker',
}

COMPONENT_TYPES = {
    'tower_sector': 'tower_sector',
    'coverage_circle': 'coverage_circle',
    'left_leg': 'left_leg',
    'right_leg': 'right_leg',
    'center_point': 'center_point',
    'distance_band': 'distance_band',
    'reported_distance': 'reported_distance',
    'accuracy_circle': 'accuracy_circle',
    'location_point': 'location_point',
    'reference_site': 'reference_site',
    'marker': 'marker',
}


class KMLGenerator(QThread):
    """Background thread for KML generation"""
    progress = pyqtSignal(int)
    finished = pyqtSignal(object)  # output payload
    error = pyqtSignal(str)     # error message
    status_message = pyqtSignal(str)  # status messages for console
    
    def __init__(self, data_file, data_type, settings, dataframe=None,
                 reference_sites=None, markers=None):
        super().__init__()
        self.data_file = data_file
        self.data_type = data_type
        self.settings = settings
        self.dataframe = dataframe
        self.reference_sites = reference_sites
        self.markers = list(markers or [])
        self.audit_summary = {}
        self.export_metadata = None
        self._reference_site_cache_key = None
        self._reference_site_cache = []
        self._reference_site_stats = {}

    @staticmethod
    def format_coord(value):
        """Format coordinates at fixed precision to reduce KML size deterministically."""
        return f"{float(value):.6f}"

    @classmethod
    def format_coord_triplet(cls, lon, lat):
        return f"{cls.format_coord(lon)},{cls.format_coord(lat)},0"

    @staticmethod
    def format_source_coord(value):
        """Preserve supplied coordinate precision for source/evidence points."""
        if isinstance(value, str):
            text_value = value.strip()
            if not text_value:
                raise ValueError("Coordinate text is empty")
            try:
                decimal_value = Decimal(text_value)
            except InvalidOperation:
                return text_value
            if 'e' in text_value.lower():
                return format(decimal_value, 'f')
            return text_value
        return format(float(value), '.15g')

    @classmethod
    def format_source_coord_triplet(cls, lon, lat):
        return f"{cls.format_source_coord(lon)},{cls.format_source_coord(lat)},0"

    @staticmethod
    def kml_color_to_css_rgba(value):
        """Convert KML AABBGGRR color text to a MapLibre CSS color."""
        color = str(value or '').strip().lower()
        if not re.fullmatch(r'[0-9a-f]{8}', color):
            raise ValueError(f"Invalid KML color: {value}")

        alpha = int(color[0:2], 16)
        blue = int(color[2:4], 16)
        green = int(color[4:6], 16)
        red = int(color[6:8], 16)
        alpha_text = f"{alpha / 255:.3f}".rstrip('0').rstrip('.')
        return f"rgba({red}, {green}, {blue}, {alpha_text})"

    @staticmethod
    def css_hex_to_kml_color(value):
        """Convert #RRGGBB marker colors to opaque KML AABBGGRR text."""
        match = re.fullmatch(r'#?([0-9a-fA-F]{6})', str(value or '').strip())
        if not match:
            raise ValueError(f"Invalid marker color: {value}")
        red_green_blue = match.group(1).lower()
        return (
            'ff' + red_green_blue[4:6] + red_green_blue[2:4]
            + red_green_blue[0:2]
        )

    @staticmethod
    def iso_timestamp_to_epoch_ms(value):
        """Derive an epoch-millisecond index without changing canonical time text."""
        if not value:
            return None

        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        utc_value = parsed.astimezone(timezone.utc)
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        delta = utc_value - epoch
        return (
            delta.days * 86_400_000
            + delta.seconds * 1_000
            + delta.microseconds // 1_000
        )

    @staticmethod
    def style_id(name):
        return f"osloc-{name}"

    @classmethod
    def style_url(cls, name):
        return f"#{cls.style_id(name)}"

    def begin_export(self, dataset_name):
        """Create metadata that remains stable for one generated KML document."""
        self.export_metadata = {
            'osloc_schema_version': OSLOC_SCHEMA_VERSION,
            'osloc_dataset_id': str(uuid4()),
            'osloc_dataset_name': dataset_name,
        }
        return self.export_metadata

    def create_document_extended_data(self, indent="        "):
        """Create export-level metadata for the KML Document."""
        if not self.export_metadata:
            return ""
        values = [
            *self.export_metadata.items(),
            ('osloc_review_notice', PRELIMINARY_REVIEW_NOTICE),
        ]
        return self.create_data_element_block(values, indent)

    def create_kml_header(self, dataset_name):
        """Start one export and create its KML Document header."""
        self.begin_export(dataset_name)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
            '<Document>\n'
            f'    <name>{xml_escape(dataset_name)}</name>\n'
            f'    <description>{xml_escape(PRELIMINARY_REVIEW_NOTICE)}</description>\n'
            + self.create_document_extended_data("    ")
            + self.create_shared_styles("    ")
        )

    def use_flattened_event_output(self):
        """Emit one dataset-level folder unless legacy event folders are requested."""
        return bool(self.settings.get('flatten_event_folders', True))

    def use_consolidated_event_placemarks(self):
        """Reduce per-event placemark count using MultiGeometry where safe."""
        return bool(self.settings.get('consolidate_event_placemarks', True))

    @staticmethod
    def extract_placemarks_from_event_fragment(fragment):
        """Convert one event-level Folder fragment into a sequence of Placemark siblings."""
        if not fragment:
            return ""
        try:
            root = ET.fromstring(fragment)
        except ET.ParseError:
            return fragment
        if root.tag != 'Folder':
            return fragment
        placemarks = [
            ET.tostring(child, encoding='unicode')
            for child in list(root)
            if child.tag == 'Placemark'
        ]
        return "\n".join(placemarks) + ("\n" if placemarks else "")

    def wrap_dataset_folder(self, dataset_name, placemarks):
        return textwrap.dedent(f'''\
            <Folder>
                <name>{xml_escape(dataset_name)}</name>
                <visibility>0</visibility>
{textwrap.indent(placemarks, '        ')}            </Folder>
        ''')

    def reference_dataset_metadata(self, dataset_name):
        """Return a stable second dataset identity for static site points."""
        if not self.export_metadata:
            self.begin_export(dataset_name)
        reference_name = f"{dataset_name} - Reference Cell Sites"
        reference_id = uuid5(
            UUID(self.export_metadata['osloc_dataset_id']), 'reference-sites'
        )
        return {
            'osloc_schema_version': OSLOC_SCHEMA_VERSION,
            'osloc_dataset_id': str(reference_id),
            'osloc_dataset_name': reference_name,
        }

    def marker_dataset_metadata(self, dataset_name):
        """Return a stable auxiliary dataset identity for user markers."""
        if not self.export_metadata:
            self.begin_export(dataset_name)
        marker_name = f"{dataset_name} - Markers"
        marker_id = uuid5(
            UUID(self.export_metadata['osloc_dataset_id']), 'markers'
        )
        return {
            'osloc_schema_version': OSLOC_SCHEMA_VERSION,
            'osloc_dataset_id': str(marker_id),
            'osloc_dataset_name': marker_name,
        }

    def maybe_flatten_event_fragment(self, fragment):
        fragment = self.maybe_consolidate_event_fragment(fragment)
        if not self.use_flattened_event_output():
            return fragment
        return self.extract_placemarks_from_event_fragment(fragment)

    @staticmethod
    def placemark_metadata_value(placemark, key):
        for data in placemark.findall('ExtendedData/Data'):
            if data.get('name') == key:
                return data.findtext('value')
        return None

    @staticmethod
    def set_placemark_metadata_value(placemark, key, value):
        extended_data = placemark.find('ExtendedData')
        if extended_data is None:
            return
        for data in extended_data.findall('Data'):
            if data.get('name') == key:
                value_element = data.find('value')
                if value_element is not None:
                    value_element.text = value
                return

    @staticmethod
    def geometry_children(placemark):
        geometry_tags = {'Polygon', 'LineString', 'Point', 'MultiGeometry'}
        return [child for child in list(placemark) if child.tag in geometry_tags]

    def consolidated_groups_for_event_type(self, event_type):
        if event_type == EVENT_TYPES['tower_sector']:
            return [
                {
                    'components': [
                        COMPONENT_TYPES['tower_sector'],
                        COMPONENT_TYPES['left_leg'],
                        COMPONENT_TYPES['right_leg'],
                        COMPONENT_TYPES['center_point'],
                    ],
                    'style': 'tower-sector-event',
                    'component_type': COMPONENT_TYPES['tower_sector'],
                }
            ]
        if event_type == EVENT_TYPES['tower_no_azimuth']:
            return [
                {
                    'components': [
                        COMPONENT_TYPES['coverage_circle'],
                        COMPONENT_TYPES['center_point'],
                    ],
                    'style': 'tower-circle-event',
                    'component_type': COMPONENT_TYPES['coverage_circle'],
                }
            ]
        if event_type == EVENT_TYPES['distance_only']:
            return [
                {
                    'components': [
                        COMPONENT_TYPES['distance_band'],
                        COMPONENT_TYPES['reported_distance'],
                        COMPONENT_TYPES['center_point'],
                    ],
                    'style': 'distance-only-event',
                    'component_type': COMPONENT_TYPES['distance_band'],
                }
            ]
        if event_type == EVENT_TYPES['location_accuracy']:
            return [
                {
                    'components': [
                        COMPONENT_TYPES['accuracy_circle'],
                        COMPONENT_TYPES['location_point'],
                    ],
                    'style': 'location-accuracy-event',
                    'component_type': COMPONENT_TYPES['accuracy_circle'],
                }
            ]
        if event_type == EVENT_TYPES['tower_sector_distance']:
            return [
                {
                    'components': [
                        COMPONENT_TYPES['tower_sector'],
                        COMPONENT_TYPES['left_leg'],
                        COMPONENT_TYPES['right_leg'],
                        COMPONENT_TYPES['center_point'],
                    ],
                    'style': 'tower-distance-sector-event',
                    'component_type': COMPONENT_TYPES['tower_sector'],
                },
                {
                    'components': [
                        COMPONENT_TYPES['distance_band'],
                        COMPONENT_TYPES['reported_distance'],
                    ],
                    'style': 'tower-distance-band-event',
                    'component_type': COMPONENT_TYPES['distance_band'],
                },
            ]
        return []

    def build_consolidated_placemark(self, group, components_map, event_type):
        selected = [
            components_map[component]
            for component in group['components']
            if component in components_map
        ]
        if not selected:
            return None, set()

        metadata_anchor = self.metadata_anchor_component(event_type)
        if metadata_anchor in group['components'] and metadata_anchor in components_map:
            base = components_map[metadata_anchor]
        else:
            base = selected[0]
        consolidated = copy.deepcopy(base)

        for geometry in self.geometry_children(consolidated):
            consolidated.remove(geometry)

        existing_multi_geometry = consolidated.find('MultiGeometry')
        if existing_multi_geometry is not None:
            consolidated.remove(existing_multi_geometry)

        style_url = consolidated.find('styleUrl')
        if style_url is None:
            style_url = ET.Element('styleUrl')
            consolidated.insert(0, style_url)
        style_url.text = self.style_url(group['style'])

        self.set_placemark_metadata_value(
            consolidated, 'osloc_component_type', group['component_type']
        )

        multi_geometry = ET.Element('MultiGeometry')
        for placemark in selected:
            for geometry in self.geometry_children(placemark):
                if geometry.tag == 'MultiGeometry':
                    for child in list(geometry):
                        multi_geometry.append(copy.deepcopy(child))
                else:
                    multi_geometry.append(copy.deepcopy(geometry))
        consolidated.append(multi_geometry)

        return consolidated, set(group['components'])

    def maybe_consolidate_event_fragment(self, fragment):
        if not self.use_consolidated_event_placemarks() or not fragment:
            return fragment

        try:
            root = ET.fromstring(fragment)
        except ET.ParseError:
            return fragment

        if root.tag != 'Folder':
            return fragment

        placemarks = root.findall('Placemark')
        if len(placemarks) <= 1:
            return fragment

        components_map = {}
        for placemark in placemarks:
            component_type = self.placemark_metadata_value(
                placemark, 'osloc_component_type'
            )
            if component_type:
                components_map[component_type] = placemark

        event_type = self.placemark_metadata_value(placemarks[0], 'osloc_event_type')
        if not event_type:
            return fragment

        groups = self.consolidated_groups_for_event_type(event_type)
        if not groups:
            return fragment

        consolidated = []
        consumed_components = set()
        for group in groups:
            consolidated_placemark, consumed = self.build_consolidated_placemark(
                group, components_map, event_type
            )
            if consolidated_placemark is None:
                continue
            consolidated.append(consolidated_placemark)
            consumed_components.update(consumed)

        if not consolidated:
            return fragment

        for placemark in placemarks:
            component_type = self.placemark_metadata_value(
                placemark, 'osloc_component_type'
            )
            if component_type and component_type in consumed_components:
                continue
            consolidated.append(copy.deepcopy(placemark))

        for placemark in list(root.findall('Placemark')):
            root.remove(placemark)
        for placemark in consolidated:
            root.append(placemark)

        return ET.tostring(root, encoding='unicode')

    def create_shared_styles(self, indent="    "):
        """Define document-level styles and reference them via styleUrl in placemarks."""
        shaded_poly_color = f"7d{self.settings['shaded_color'][2:]}"
        band_poly_color = f"7d{self.settings['band_color'][2:]}"
        gps_poly_color = f"4d{self.settings['gps_color'][2:]}"
        leg_color = self.settings['leg_color']
        gps_color = self.settings['gps_color']
        reference_site_color = self.settings.get(
            'reference_site_color', 'ff000000'
        )

        styles = {
            'tower-area': textwrap.dedent(f'''\
                <Style id="{self.style_id('tower-area')}">
{self.create_balloon_style(f"{indent}    ")}
                    <LineStyle><color>{leg_color}</color><width>1</width></LineStyle>
                    <PolyStyle><color>{shaded_poly_color}</color></PolyStyle>
                </Style>
            '''),
            'hidden-center': textwrap.dedent(f'''\
                <Style id="{self.style_id('hidden-center')}">
{self.create_balloon_style(f"{indent}    ")}
                    <IconStyle><scale>0</scale></IconStyle>
                    <LabelStyle><color>ffffffff</color><scale>0.8</scale></LabelStyle>
                </Style>
            '''),
            'leg-line': textwrap.dedent(f'''\
                <Style id="{self.style_id('leg-line')}">
{self.create_balloon_style(f"{indent}    ")}
                    <LineStyle><color>{leg_color}</color><width>2</width></LineStyle>
                </Style>
            '''),
            'distance-band': textwrap.dedent(f'''\
                <Style id="{self.style_id('distance-band')}">
{self.create_balloon_style(f"{indent}    ")}
                    <PolyStyle><color>{band_poly_color}</color><fill>1</fill><outline>0</outline></PolyStyle>
                </Style>
            '''),
            'reported-distance': textwrap.dedent(f'''\
                <Style id="{self.style_id('reported-distance')}">
{self.create_balloon_style(f"{indent}    ")}
                    <LineStyle><color>ff000000</color><width>2</width></LineStyle>
                </Style>
            '''),
            'distance-center': textwrap.dedent(f'''\
                <Style id="{self.style_id('distance-center')}">
{self.create_balloon_style(f"{indent}    ")}
                    <IconStyle>
                        <Icon><href>http://maps.google.com/mapfiles/kml/pushpin/wht-pushpin.png</href></Icon>
                        <color>ff0000ff</color>
                    </IconStyle>
                </Style>
            '''),
            'gps-circle': textwrap.dedent(f'''\
                <Style id="{self.style_id('gps-circle')}">
{self.create_balloon_style(f"{indent}    ")}
                    <LineStyle><color>{gps_color}</color><width>2</width></LineStyle>
                    <PolyStyle><color>{gps_poly_color}</color></PolyStyle>
                </Style>
            '''),
            'location-hidden': textwrap.dedent(f'''\
                <Style id="{self.style_id('location-hidden')}">
{self.create_balloon_style(f"{indent}    ")}
                    <IconStyle><scale>0</scale></IconStyle>
                    <LabelStyle><color>ffffffff</color><scale>0.8</scale></LabelStyle>
                </Style>
            '''),
            'location-visible': textwrap.dedent(f'''\
                <Style id="{self.style_id('location-visible')}">
{self.create_balloon_style(f"{indent}    ")}
                    <IconStyle><scale>1</scale><color>{gps_color}</color></IconStyle>
                    <LabelStyle><color>ffffffff</color><scale>0.8</scale></LabelStyle>
                </Style>
            '''),
            'pin-default': textwrap.dedent(f'''\
                <Style id="{self.style_id('pin-default')}">
{self.create_balloon_style(f"{indent}    ")}
                    <IconStyle><color>ffffffff</color></IconStyle>
                </Style>
            '''),
            'reference-site': textwrap.dedent(f'''\
                <Style id="{self.style_id('reference-site')}">
{self.create_balloon_style(f"{indent}    ")}
                    <IconStyle>
                        <scale>0.75</scale>
                        <color>{reference_site_color}</color>
                        <Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon>
                    </IconStyle>
                    <LabelStyle><scale>0</scale></LabelStyle>
                </Style>
            '''),
            'tower-sector-event': textwrap.dedent(f'''\
                <Style id="{self.style_id('tower-sector-event')}">
{self.create_balloon_style(f"{indent}    ")}
                    <LineStyle><color>{leg_color}</color><width>2</width></LineStyle>
                    <PolyStyle><color>{shaded_poly_color}</color></PolyStyle>
                    <IconStyle><scale>0</scale></IconStyle>
                    <LabelStyle><color>ffffffff</color><scale>0.8</scale></LabelStyle>
                </Style>
            '''),
            'tower-circle-event': textwrap.dedent(f'''\
                <Style id="{self.style_id('tower-circle-event')}">
{self.create_balloon_style(f"{indent}    ")}
                    <LineStyle><color>{leg_color}</color><width>1</width></LineStyle>
                    <PolyStyle><color>{shaded_poly_color}</color></PolyStyle>
                    <IconStyle><scale>0</scale></IconStyle>
                    <LabelStyle><color>ffffffff</color><scale>0.8</scale></LabelStyle>
                </Style>
            '''),
            'distance-only-event': textwrap.dedent(f'''\
                <Style id="{self.style_id('distance-only-event')}">
{self.create_balloon_style(f"{indent}    ")}
                    <LineStyle><color>ff000000</color><width>2</width></LineStyle>
                    <PolyStyle><color>{band_poly_color}</color><fill>1</fill><outline>0</outline></PolyStyle>
                    <IconStyle>
                        <Icon><href>http://maps.google.com/mapfiles/kml/pushpin/wht-pushpin.png</href></Icon>
                        <color>ff0000ff</color>
                    </IconStyle>
                    <LabelStyle><color>ffffffff</color><scale>0.8</scale></LabelStyle>
                </Style>
            '''),
            'location-accuracy-event': textwrap.dedent(f'''\
                <Style id="{self.style_id('location-accuracy-event')}">
{self.create_balloon_style(f"{indent}    ")}
                    <LineStyle><color>{gps_color}</color><width>2</width></LineStyle>
                    <PolyStyle><color>{gps_poly_color}</color></PolyStyle>
                    <IconStyle><scale>0</scale></IconStyle>
                    <LabelStyle><color>ffffffff</color><scale>0.8</scale></LabelStyle>
                </Style>
            '''),
            'tower-distance-sector-event': textwrap.dedent(f'''\
                <Style id="{self.style_id('tower-distance-sector-event')}">
{self.create_balloon_style(f"{indent}    ")}
                    <LineStyle><color>{leg_color}</color><width>2</width></LineStyle>
                    <PolyStyle><color>{shaded_poly_color}</color></PolyStyle>
                    <IconStyle><scale>0</scale></IconStyle>
                    <LabelStyle><color>ffffffff</color><scale>0.8</scale></LabelStyle>
                </Style>
            '''),
            'tower-distance-band-event': textwrap.dedent(f'''\
                <Style id="{self.style_id('tower-distance-band-event')}">
{self.create_balloon_style(f"{indent}    ")}
                    <LineStyle><color>ff000000</color><width>2</width></LineStyle>
                    <PolyStyle><color>{band_poly_color}</color><fill>1</fill><outline>0</outline></PolyStyle>
                </Style>
            '''),
        }

        return "".join(textwrap.indent(styles[key], indent) for key in [
            'tower-area',
            'hidden-center',
            'leg-line',
            'distance-band',
            'reported-distance',
            'distance-center',
            'gps-circle',
            'location-hidden',
            'location-visible',
            'pin-default',
            'reference-site',
            'tower-sector-event',
            'tower-circle-event',
            'distance-only-event',
            'location-accuracy-event',
            'tower-distance-sector-event',
            'tower-distance-band-event',
        ])

    @staticmethod
    def create_data_element_block(values, indent):
        data_elements = "".join(
            f'{indent}    <Data name="{name}"><value>{xml_escape(str(value))}</value></Data>\n'
            for name, value in values if value is not None
        )
        return f"{indent}<ExtendedData>\n{data_elements}{indent}</ExtendedData>\n"
    @staticmethod
    def create_balloon_style(indent="        "):
        """Create Google Earth balloon text without dumping ExtendedData."""
        return textwrap.indent(textwrap.dedent('''\
            <BalloonStyle>
                <text><![CDATA[
                    <div style="font-family: Arial, sans-serif; line-height: 1.35;">
                        <h3 style="margin: 0 0 4px 0;">$[name]</h3>
                        <div style="margin: 0 0 8px 0; font-size: 11px; color: #666666;">$[osloc_dataset_name]</div>
                        <div>$[description]</div>
                    </div>
                ]]></text>
            </BalloonStyle>
        '''), indent)
    
    def run(self):
        try:
            # Load data
            self.progress.emit(10)
            
            if self.dataframe is not None:
                df = self.dataframe.copy()
            else:
                # Read file based on extension (with Excel date handling)
                file_extension = Path(self.data_file).suffix.lower()
                if file_extension == '.xlsx':
                    df = pd.read_excel(self.data_file, engine='openpyxl')
                elif file_extension == '.csv':
                    df = pd.read_csv(self.data_file)
                else:
                    raise ValueError(f"Unsupported file format: {file_extension}")
            
            # Generate KML based on data type
            self.progress.emit(30)
            if self.data_type == "Tower/Sector":
                kml_content = self.generate_cell_tower_kml(df)
                geojson_content = self.generate_cell_tower_geojson(df)
            elif self.data_type == "Distance from Tower":
                kml_content = self.generate_distance_from_tower_kml(df)
                geojson_content = self.generate_distance_from_tower_geojson(df)
            elif self.data_type == "Location Point":
                kml_content = self.generate_gps_kml(df)
                geojson_content = self.generate_gps_geojson(df)
            else:
                raise ValueError(f"Unknown data type: {self.data_type}")
            
            self.progress.emit(100)
            self.finished.emit({
                'kml': kml_content,
                'geojson': geojson_content,
            })
            
        except Exception as e:
            self.error.emit(str(e))
    
    def destination_point(self, lat, lon, azimuth_deg, distance_miles):
        """Calculate destination point given starting point, bearing and distance"""
        R = 3960.0  # Earth radius in miles
        azimuth = math.radians(azimuth_deg)
        lat1 = math.radians(lat)
        lon1 = math.radians(lon)
        d_div_r = distance_miles / R

        if d_div_r < 1e-9:
            return lat, lon

        lat2 = math.asin(math.sin(lat1) * math.cos(d_div_r) +
                         math.cos(lat1) * math.sin(d_div_r) * math.cos(azimuth))
        lon2 = lon1 + math.atan2(math.sin(azimuth) * math.sin(d_div_r) * math.cos(lat1),
                                 math.cos(d_div_r) - math.sin(lat1) * math.sin(lat2))
        return math.degrees(lat2), math.degrees(lon2)

    @staticmethod
    def distance_between_points_miles(first_lat, first_lon, second_lat,
                                      second_lon):
        """Return great-circle distance using the generator's 3960-mile Earth."""
        first_lat_radians = math.radians(first_lat)
        second_lat_radians = math.radians(second_lat)
        latitude_delta = second_lat_radians - first_lat_radians
        longitude_delta = math.radians(second_lon - first_lon)
        haversine_value = (
            math.sin(latitude_delta / 2) ** 2
            + math.cos(first_lat_radians)
            * math.cos(second_lat_radians)
            * math.sin(longitude_delta / 2) ** 2
        )
        central_angle = 2 * math.asin(
            math.sqrt(min(max(haversine_value, 0.0), 1.0))
        )
        return 3960.0 * central_angle

    @staticmethod
    def reference_site_id_text(value):
        if pd.isna(value) or not str(value).strip():
            return None
        text = str(value).strip()
        if re.fullmatch(r'[+-]?\d+\.0+', text):
            return text.split('.', 1)[0]
        return text

    @staticmethod
    def reference_row_numbers(value):
        if isinstance(value, (list, tuple, set)):
            candidates = value
        elif value is None or pd.isna(value):
            return []
        else:
            candidates = re.split(r'\s*,\s*', str(value).strip())

        row_numbers = []
        for candidate in candidates:
            try:
                number = float(candidate)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number) and number.is_integer() and number >= 1:
                row_number = int(number)
                if row_number not in row_numbers:
                    row_numbers.append(row_number)
        return row_numbers

    def grouped_reference_sites(self, dataframe, include_source_rows=False):
        """Combine sectors and repeated rows that share one physical location."""
        grouped = {}
        for row_position, (_, row) in enumerate(dataframe.iterrows()):
            coordinates = self.get_valid_coordinates_with_text(row)
            if coordinates is None:
                continue
            lat, lon, lat_text, lon_text = coordinates
            location_key = (lat, lon)
            if location_key not in grouped:
                grouped[location_key] = {
                    'latitude': lat,
                    'longitude': lon,
                    'latitude_text': lat_text,
                    'longitude_text': lon_text,
                    'site_ids': [],
                    'csl_source_rows': [],
                    'source_rows': [],
                }
            site_id = self.reference_site_id_text(self.get_column_value(
                row,
                ['Site ID', 'Site', 'Site Name', 'Tower ID', 'Tower',
                 'Tower Name', 'Node ID', 'Node'],
            ))
            if site_id and site_id not in grouped[location_key]['site_ids']:
                grouped[location_key]['site_ids'].append(site_id)
            csl_source_rows = self.reference_row_numbers(
                row['CSL Source Rows']
                if 'CSL Source Rows' in row.index else None
            )
            for source_row in csl_source_rows:
                if source_row not in grouped[location_key]['csl_source_rows']:
                    grouped[location_key]['csl_source_rows'].append(source_row)
            if include_source_rows and not csl_source_rows:
                source_row = self.source_row_number(row_position, row)
                if source_row not in grouped[location_key]['source_rows']:
                    grouped[location_key]['source_rows'].append(source_row)
        return list(grouped.values())

    def reference_sites_for_records(self, records):
        """Select unique used sites and radius-limited CSL neighbors."""
        cache_key = (id(records), id(self.reference_sites))
        if self._reference_site_cache_key == cache_key:
            return self._reference_site_cache

        enabled = bool(self.settings.get('include_reference_sites', False))
        if not enabled or self.data_type not in (
            'Tower/Sector', 'Distance from Tower'
        ):
            selected_sites = []
            source_name = 'disabled'
            considered_count = 0
        else:
            used_sites = self.grouped_reference_sites(
                records, include_source_rows=True
            )
            if self.reference_sites is None:
                selected_sites = used_sites
                source_name = 'record coordinates'
                considered_count = len(used_sites)
            else:
                candidate_sites = self.grouped_reference_sites(
                    self.reference_sites
                )
                source_name = 'cell site list'
                considered_count = len(candidate_sites)
                try:
                    radius_miles = float(self.settings.get(
                        'reference_site_radius_miles', 25.0
                    ))
                except (TypeError, ValueError):
                    radius_miles = 25.0
                radius_miles = max(radius_miles, 0.0)
                selected_sites = [
                    site for site in candidate_sites
                    if any(
                        self.distance_between_points_miles(
                            used_site['latitude'], used_site['longitude'],
                            site['latitude'], site['longitude'],
                        ) <= radius_miles
                        for used_site in used_sites
                    )
                ]

        self._reference_site_cache_key = cache_key
        self._reference_site_cache = selected_sites
        self._reference_site_stats = {
            'reference_site_source': source_name,
            'reference_sites_considered': considered_count,
            'reference_sites_generated': len(selected_sites),
        }
        return selected_sites

    def create_reference_site_placemark(self, site, position, dataset_name):
        reference_metadata = self.reference_dataset_metadata(dataset_name)
        site_ids = site['site_ids']
        site_ids_text = ', '.join(site_ids) if site_ids else None
        title = (
            f"Cell Site {site_ids_text}"
            if site_ids else f"Reference Cell Site {position + 1}"
        )
        coordinate_text = self.source_coord_pair_text(
            site['latitude'], site['longitude'], site['latitude_text'],
            site['longitude_text']
        )
        csl_source_rows_text = ', '.join(
            str(row_number) for row_number in site['csl_source_rows']
        ) or None
        source_rows_text = ', '.join(
            str(row_number) for row_number in site['source_rows']
        ) or None
        description_rows = []
        if csl_source_rows_text:
            description_rows.append((
                'CSL Row' if len(site['csl_source_rows']) == 1 else 'CSL Rows',
                csl_source_rows_text,
            ))
        elif source_rows_text:
            description_rows.append((
                'Source Row' if len(site['source_rows']) == 1 else 'Source Rows',
                source_rows_text,
            ))
        if site_ids_text:
            description_rows.append(('Site ID', site_ids_text))
        description_rows.append(('Coordinates', coordinate_text))
        description = self.build_description_table(description_rows)
        reference_color = self.settings.get(
            'reference_site_color', 'ff000000'
        )
        values = [
            *reference_metadata.items(),
            ('osloc_event_id', f"reference_site_{position + 1:06d}"),
            ('osloc_event_label', title),
            ('osloc_event_type', EVENT_TYPES['reference_site']),
            ('osloc_component_type', COMPONENT_TYPES['reference_site']),
            ('osloc_site_ids', site_ids_text),
            ('osloc_csl_source_rows', csl_source_rows_text),
            ('osloc_source_rows', source_rows_text),
            ('osloc_source_latitude', site['latitude_text']),
            ('osloc_source_longitude', site['longitude_text']),
            ('osloc_source_coordinate_text', coordinate_text),
            ('osloc_style_reference_color', reference_color),
            (
                'osloc_style_reference_color_rgba',
                self.kml_color_to_css_rgba(reference_color),
            ),
        ]
        extended_data = self.create_data_element_block(values, '            ')
        return textwrap.dedent(f'''\
            <Placemark>
                <name>{xml_escape(title)}</name>
                <description><![CDATA[{description}]]></description>
                <Snippet maxLines="0"></Snippet>
{extended_data}                <styleUrl>{self.style_url('reference-site')}</styleUrl>
                <Point>
                    <coordinates>{self.format_source_coord_triplet(site['longitude_text'], site['latitude_text'])}</coordinates>
                </Point>
            </Placemark>
        ''')

    def create_reference_site_folder(self, records, dataset_name):
        sites = self.reference_sites_for_records(records)
        if not sites:
            return ""
        placemarks = ''.join(
            self.create_reference_site_placemark(site, position, dataset_name)
            for position, site in enumerate(sites)
        )
        reference_name = self.reference_dataset_metadata(dataset_name)[
            'osloc_dataset_name'
        ]
        return self.wrap_dataset_folder(reference_name, placemarks)

    def reference_site_geojson_features(self, records, dataset_name):
        fragment = self.create_reference_site_folder(records, dataset_name)
        return self.geojson_features_from_event_fragment(fragment, {})

    def create_marker_placemark(self, marker, position, dataset_name):
        marker_metadata = self.marker_dataset_metadata(dataset_name)
        title = str(marker['label']).strip()
        latitude_text = str(marker.get(
            'latitude_text', self.format_source_coord(marker['latitude'])
        )).strip()
        longitude_text = str(marker.get(
            'longitude_text', self.format_source_coord(marker['longitude'])
        )).strip()
        coordinate_text = f"{latitude_text}, {longitude_text}"
        marker_color = self.css_hex_to_kml_color(marker['color'])
        description = self.build_description_table([
            ('Label', title),
            ('Coordinates', coordinate_text),
            ('Marker List Row', marker.get('source_row')),
        ])
        values = [
            *marker_metadata.items(),
            ('osloc_event_id', f"marker_{position + 1:06d}"),
            ('osloc_event_label', title),
            ('osloc_event_type', EVENT_TYPES['marker']),
            ('osloc_component_type', COMPONENT_TYPES['marker']),
            ('osloc_marker_source_row', marker.get('source_row')),
            ('osloc_source_latitude', latitude_text),
            ('osloc_source_longitude', longitude_text),
            ('osloc_source_coordinate_text', coordinate_text),
            ('osloc_style_marker_color', marker_color),
            (
                'osloc_style_marker_color_rgba',
                self.kml_color_to_css_rgba(marker_color),
            ),
        ]
        extended_data = self.create_data_element_block(values, '            ')
        marker_style = textwrap.dedent(f'''\
                <Style>
{self.create_balloon_style('                    ')}                    <IconStyle>
                        <scale>1</scale>
                        <color>{marker_color}</color>
                        <Icon><href>http://maps.google.com/mapfiles/kml/pushpin/wht-pushpin.png</href></Icon>
                    </IconStyle>
                    <LabelStyle><color>ffffffff</color><scale>0.9</scale></LabelStyle>
                </Style>
        ''')
        return textwrap.dedent(f'''\
            <Placemark>
                <name>{xml_escape(title)}</name>
                <description><![CDATA[{description}]]></description>
                <Snippet maxLines="0"></Snippet>
{extended_data}{marker_style}                <Point>
                    <coordinates>{self.format_source_coord_triplet(longitude_text, latitude_text)}</coordinates>
                </Point>
            </Placemark>
        ''')

    def create_marker_folder(self, dataset_name):
        if not self.markers:
            return ""
        placemarks = ''.join(
            self.create_marker_placemark(marker, position, dataset_name)
            for position, marker in enumerate(self.markers)
        )
        marker_name = self.marker_dataset_metadata(dataset_name)[
            'osloc_dataset_name'
        ]
        return self.wrap_dataset_folder(marker_name, placemarks)

    def marker_geojson_features(self, dataset_name):
        fragment = self.create_marker_folder(dataset_name)
        return self.geojson_features_from_event_fragment(fragment, {})

    def report_marker_summary(self):
        marker_count = len(self.markers)
        self.audit_summary['markers_generated'] = marker_count
        if marker_count:
            self.status_message.emit(
                f"📍 Markers: generated {marker_count} static "
                f"marker{'s' if marker_count != 1 else ''}"
            )

    def calculate_sector_area_sq_miles(self, radius_miles, sector_width_degrees):
        """Calculate sector area in square miles."""
        radius = max(float(radius_miles), 0.0)
        sector_width = max(float(sector_width_degrees), 0.0)
        return (sector_width / 360.0) * math.pi * (radius ** 2)

    def calculate_band_area_sq_miles(self, center_distance_miles, sector_width_degrees, band_before_miles, band_after_miles):
        """Calculate sector band area in square miles."""
        sector_width = max(float(sector_width_degrees), 0.0)
        center_distance = max(float(center_distance_miles), 0.0)
        inner_radius = max(center_distance - max(float(band_before_miles), 0.0), 0.0)
        outer_radius = max(center_distance + max(float(band_after_miles), 0.0), inner_radius)
        return (sector_width / 360.0) * math.pi * ((outer_radius ** 2) - (inner_radius ** 2))
    
    def generate_cell_tower_kml(self, df):
        """Generate KML for site/sector data"""
        # Use custom label if provided, otherwise default
        dataset_name = self.settings.get('custom_label') or "Cell Site/Sector Data"
        kml_header = self.create_kml_header(dataset_name)
        
        kml_footer = textwrap.dedent('''\
            </Document>
            </kml>
        ''')
        
        placemarks = ""
        total_rows = len(df)
        missing_azimuth_count = 0
        invalid_coordinate_count = 0
        dst_conflict_rows = []
        untimed_timestamp_rows = []
        generated_count = 0
        
        for idx, (_, row) in enumerate(df.iterrows()):
            if idx % 10 == 0:  # Update progress every 10 rows
                progress = 30 + int((idx / total_rows) * 50)
                self.progress.emit(progress)

            # Get required columns
            coordinates = self.get_valid_coordinates_with_text(row)
            timestamp = self.get_timestamp_value(row)
            azimuth = self.get_numeric_column_value(
                row, ['Azimuth', 'azimuth', 'bearing', 'direction']
            )
            
            if coordinates is None:
                invalid_coordinate_count += 1
                continue
            lat, lon, lat_source_text, lon_source_text = coordinates
            
            timestamp_missing = self.is_missing_timestamp(timestamp)
            
            # Generate sector or circle based on azimuth availability
            if azimuth is not None:
                event_metadata = self.create_event_metadata(
                    idx, timestamp, EVENT_TYPES['tower_sector'], row
                )
                placemarks += self.maybe_flatten_event_fragment(self.create_sector_placemark(
                    lat, lon, azimuth, event_metadata, lat_source_text,
                    lon_source_text
                ))
            else:
                missing_azimuth_count += 1
                # Create 360-degree circle instead of directional wedge
                event_metadata = self.create_event_metadata(
                    idx, timestamp, EVENT_TYPES['tower_no_azimuth'], row
                )
                placemarks += self.maybe_flatten_event_fragment(self.create_circle_placemark(
                    lat, lon, event_metadata, lat_source_text, lon_source_text
                ))
            if timestamp_missing or event_metadata['timestamp_parse_failed']:
                untimed_timestamp_rows.append(event_metadata['source_row'])
            if event_metadata['timestamp_dst_conflict']:
                dst_conflict_rows.append(event_metadata['source_row'])
            generated_count += 1
        
        # Report missing azimuth data
        if missing_azimuth_count > 0:
            self.status_message.emit(f"⚠️ Cell Site/Sector Data: {missing_azimuth_count} points had no azimuth data - used 360° visualization circles")
        if invalid_coordinate_count > 0:
            self.status_message.emit(f"⚠️ Cell Site/Sector Data: {invalid_coordinate_count} rows were skipped because latitude or longitude was missing or invalid")
        self.report_untimed_timestamps(
            "Cell Site/Sector Data", untimed_timestamp_rows
        )
        self.report_dst_conflicts("Cell Site/Sector Data", dst_conflict_rows)
        self.audit_summary = {
            'input_rows': total_rows,
            'generated_rows': generated_count,
            'skipped_invalid_coordinates': invalid_coordinate_count,
            'skipped_missing_timestamp': 0,
            'skipped_dst_conflict': 0,
            'generated_with_dst_conflict': len(dst_conflict_rows),
            'generated_without_timeline': len(untimed_timestamp_rows),
        }

        reference_sites = self.reference_sites_for_records(df)
        self.audit_summary.update(self._reference_site_stats)
        if self.settings.get('include_reference_sites', False):
            self.status_message.emit(
                f"📊 Reference Cell Sites: generated {len(reference_sites)} static "
                f"site {'point' if len(reference_sites) == 1 else 'points'} from "
                f"{self._reference_site_stats['reference_site_source']}"
            )

        body = (
            self.wrap_dataset_folder(dataset_name, placemarks)
            if self.use_flattened_event_output()
            else placemarks
        )
        reference_body = self.create_reference_site_folder(df, dataset_name)
        marker_body = self.create_marker_folder(dataset_name)
        self.report_marker_summary()
        return kml_header + body + reference_body + marker_body + kml_footer
    
    def generate_distance_from_tower_kml(self, df):
        """Generate KML for distance from site data with arc visualization"""
        # Use custom label if provided, otherwise default
        dataset_name = self.settings.get('custom_label') or "Distance from Cell Site Analysis"
        kml_header = self.create_kml_header(dataset_name)
        
        kml_footer = textwrap.dedent('''\
            </Document>
            </kml>
        ''')
        
        placemarks = ""
        total_rows = len(df)
        missing_azimuth_count = 0
        missing_distance_count = 0
        invalid_coordinate_count = 0
        dst_conflict_rows = []
        untimed_timestamp_rows = []
        generated_count = 0
        
        for idx, (_, row) in enumerate(df.iterrows()):
            if idx % 10 == 0:
                progress = 30 + int((idx / total_rows) * 50)
                self.progress.emit(progress)

            coordinates = self.get_valid_coordinates_with_text(row)
            timestamp = self.get_timestamp_value(row)
            azimuth = self.get_numeric_column_value(
                row, ['Azimuth', 'bearing', 'direction']
            )
            distance = self.get_numeric_column_value(
                row,
                ['Distance', 'range', 'distance (m)', 'distance (meters)'],
            )
            
            if coordinates is None:
                invalid_coordinate_count += 1
                continue
            lat, lon, lat_source_text, lon_source_text = coordinates
            
            timestamp_missing = self.is_missing_timestamp(timestamp)
            
            # Determine visualization based on available data
            has_azimuth = azimuth is not None
            has_distance = distance is not None and distance >= 0
            
            if has_azimuth and has_distance:
                # Case 1: Has both azimuth and distance - create combined site/sector + distance arc visualization
                distance_miles = self.convert_ta_distance_to_miles(distance, self.settings.get('ta_distance_units', 'Meters'))
                event_metadata = self.create_event_metadata(
                    idx, timestamp, EVENT_TYPES['tower_sector_distance'], row
                )
                placemarks += self.maybe_flatten_event_fragment(self.create_combined_sector_and_arc(
                    lat, lon, azimuth, distance_miles, event_metadata,
                    lat_source_text, lon_source_text
                ))

            elif has_azimuth and not has_distance:
                # Case 2: Has azimuth but missing distance - create directional wedge
                missing_distance_count += 1
                event_metadata = self.create_event_metadata(
                    idx, timestamp, EVENT_TYPES['tower_sector'], row
                )
                placemarks += self.maybe_flatten_event_fragment(self.create_sector_placemark(
                    lat, lon, azimuth, event_metadata, lat_source_text,
                    lon_source_text
                ))

            elif not has_azimuth and has_distance:
                # Case 3: Missing azimuth but has distance - create distance band (donut/pizza-crust visualization)
                missing_azimuth_count += 1
                distance_miles = self.convert_ta_distance_to_miles(distance, self.settings.get('ta_distance_units', 'Meters'))
                event_metadata = self.create_event_metadata(
                    idx, timestamp, EVENT_TYPES['distance_only'], row
                )
                placemarks += self.maybe_flatten_event_fragment(self.create_distance_band(
                    lat, lon, distance_miles, event_metadata,
                    lat_source_text, lon_source_text
                ))

            else:
                # Case 4: Missing both azimuth and distance - create 360° circle using shaded area length
                missing_azimuth_count += 1
                missing_distance_count += 1
                event_metadata = self.create_event_metadata(
                    idx, timestamp, EVENT_TYPES['tower_no_azimuth'], row
                )
                placemarks += self.maybe_flatten_event_fragment(self.create_circle_placemark(
                    lat, lon, event_metadata, lat_source_text, lon_source_text
                ))
            if timestamp_missing or event_metadata['timestamp_parse_failed']:
                untimed_timestamp_rows.append(event_metadata['source_row'])
            if event_metadata['timestamp_dst_conflict']:
                dst_conflict_rows.append(event_metadata['source_row'])
            generated_count += 1
        
        # Report missing data
        if missing_azimuth_count > 0:
            self.status_message.emit(f"⚠️ Distance from Cell Site Data: {missing_azimuth_count} points had no azimuth data - used 360° visualization areas")
        if missing_distance_count > 0:
            self.status_message.emit(f"⚠️ Distance from Cell Site Data: {missing_distance_count} points had no distance data - distance from cell site not drawn")
        if invalid_coordinate_count > 0:
            self.status_message.emit(f"⚠️ Distance from Cell Site Data: {invalid_coordinate_count} rows were skipped because latitude or longitude was missing or invalid")
        self.report_untimed_timestamps(
            "Distance from Cell Site Data", untimed_timestamp_rows
        )
        self.report_dst_conflicts("Distance from Cell Site Data", dst_conflict_rows)
        self.audit_summary = {
            'input_rows': total_rows,
            'generated_rows': generated_count,
            'skipped_invalid_coordinates': invalid_coordinate_count,
            'skipped_missing_timestamp': 0,
            'skipped_dst_conflict': 0,
            'generated_with_dst_conflict': len(dst_conflict_rows),
            'generated_without_timeline': len(untimed_timestamp_rows),
        }

        reference_sites = self.reference_sites_for_records(df)
        self.audit_summary.update(self._reference_site_stats)
        if self.settings.get('include_reference_sites', False):
            self.status_message.emit(
                f"📊 Reference Cell Sites: generated {len(reference_sites)} static "
                f"site {'point' if len(reference_sites) == 1 else 'points'} from "
                f"{self._reference_site_stats['reference_site_source']}"
            )

        body = (
            self.wrap_dataset_folder(dataset_name, placemarks)
            if self.use_flattened_event_output()
            else placemarks
        )
        reference_body = self.create_reference_site_folder(df, dataset_name)
        marker_body = self.create_marker_folder(dataset_name)
        self.report_marker_summary()
        return kml_header + body + reference_body + marker_body + kml_footer
    
    def generate_gps_kml(self, df):
        """Generate KML for location point data"""
        # Use custom label if provided, otherwise default
        dataset_name = self.settings.get('custom_label') or "Location Point Data"
        kml_header = self.create_kml_header(dataset_name)
        
        kml_footer = textwrap.dedent('''\
            </Document>
            </kml>
        ''')
        
        placemarks = ""
        total_rows = len(df)
        missing_accuracy_count = 0
        invalid_accuracy_count = 0
        zero_accuracy_count = 0
        invalid_coordinate_count = 0
        dst_conflict_rows = []
        untimed_timestamp_rows = []
        generated_count = 0
        
        for idx, (_, row) in enumerate(df.iterrows()):
            if idx % 10 == 0:
                progress = 30 + int((idx / total_rows) * 50)
                self.progress.emit(progress)

            coordinates = self.get_valid_coordinates_with_text(row)
            timestamp = self.get_timestamp_value(row)
            gps_accuracy = self.get_column_value(row, ['GPS Accuracy', 'Accuracy', 'gps_accuracy', 'accuracy'])
            
            if coordinates is None:
                invalid_coordinate_count += 1
                continue
            lat, lon, lat_source_text, lon_source_text = coordinates
            
            radius_miles, accuracy_display, accuracy_outcome = (
                self.resolve_location_accuracy(gps_accuracy)
            )
            if accuracy_outcome == 'missing':
                missing_accuracy_count += 1
            elif accuracy_outcome == 'invalid':
                invalid_accuracy_count += 1
            elif accuracy_outcome == 'zero':
                zero_accuracy_count += 1
            
            # Create location point accuracy circle
            event_type = (
                EVENT_TYPES['location_accuracy']
                if radius_miles is not None
                else EVENT_TYPES['location']
            )
            event_metadata = self.create_event_metadata(
                idx, timestamp, event_type, row
            )
            placemarks += self.maybe_flatten_event_fragment(self.create_gps_accuracy_circle(
                lat, lon, radius_miles, event_metadata, lat_source_text,
                lon_source_text, accuracy_display
            ))
            if self.is_missing_timestamp(timestamp) or event_metadata['timestamp_parse_failed']:
                untimed_timestamp_rows.append(event_metadata['source_row'])
            if event_metadata['timestamp_dst_conflict']:
                dst_conflict_rows.append(event_metadata['source_row'])
            generated_count += 1
        
        # Report missing accuracy data
        if missing_accuracy_count > 0:
            default_accuracy = self.settings.get('default_accuracy', 0)
            default_units = self.settings.get('gps_units', 'Meters')
            if float(default_accuracy) == 0:
                self.status_message.emit(f"⚠️ Location Point Data: {missing_accuracy_count} points had no accuracy data - accuracy unknown; displayed as points without accuracy circles")
            else:
                self.status_message.emit(f"⚠️ Location Point Data: {missing_accuracy_count} points had no accuracy data - used {default_accuracy} {default_units.lower()} default radius")
        if invalid_accuracy_count > 0:
            self.status_message.emit(f"⚠️ Location Point Data: {invalid_accuracy_count} points had invalid accuracy data - displayed as points without accuracy circles")
        if zero_accuracy_count > 0:
            self.status_message.emit(f"⚠️ Location Point Data: {zero_accuracy_count} points had zero accuracy data - accuracy unknown, not exact; displayed as points without accuracy circles")
        if invalid_coordinate_count > 0:
            self.status_message.emit(f"⚠️ Location Point Data: {invalid_coordinate_count} rows were skipped because latitude or longitude was missing or invalid")
        self.report_untimed_timestamps(
            "Location Point Data", untimed_timestamp_rows
        )
        self.report_dst_conflicts("Location Point Data", dst_conflict_rows)
        self.audit_summary = {
            'input_rows': total_rows,
            'generated_rows': generated_count,
            'skipped_invalid_coordinates': invalid_coordinate_count,
            'skipped_missing_timestamp': 0,
            'skipped_dst_conflict': 0,
            'generated_with_dst_conflict': len(dst_conflict_rows),
            'generated_without_timeline': len(untimed_timestamp_rows),
        }

        body = (
            self.wrap_dataset_folder(dataset_name, placemarks)
            if self.use_flattened_event_output()
            else placemarks
        )
        marker_body = self.create_marker_folder(dataset_name)
        self.report_marker_summary()
        return kml_header + body + marker_body + kml_footer
    
    def resolve_location_accuracy(self, accuracy_value):
        units = self.settings.get('gps_units', 'Meters')
        if pd.isna(accuracy_value):
            default_accuracy = self.settings.get('default_accuracy', 0)
            radius_miles = self.convert_gps_accuracy_to_miles(default_accuracy, units)
            accuracy_display = (
                'Unknown (no accuracy supplied; default 0, no accuracy circle)'
                if radius_miles == 0
                else f"{default_accuracy} {units} (default)"
            )
            outcome = 'missing'
        else:
            try:
                radius_miles = self.convert_gps_accuracy_to_miles(accuracy_value, units)
            except (ValueError, TypeError):
                return None, f"{accuracy_value} ({units}, invalid)", 'invalid'
            accuracy_display = (
                f"Unknown (supplied {accuracy_value} {units}; zero does not mean exact)"
                if radius_miles == 0
                else f"{accuracy_value} {units}"
            )
            outcome = 'zero' if radius_miles == 0 else 'supplied'
        return (radius_miles if radius_miles > 0 else None), accuracy_display, outcome

    def convert_gps_accuracy_to_miles(self, accuracy_value, units):
        """Convert location point accuracy from various units to miles"""
        accuracy_float = float(accuracy_value)
        if not math.isfinite(accuracy_float) or accuracy_float < 0:
            raise ValueError("Accuracy must be a non-negative finite number")

        if units == "Meters":
            return accuracy_float * 0.000621371  # meters to miles
        elif units == "Feet":
            return accuracy_float * 0.000189394  # feet to miles
        elif units == "Miles":
            return accuracy_float  # already in miles
        elif units == "Kilometers":
            return accuracy_float * 0.621371  # kilometers to miles
        else:
            # Default to meters if unknown unit
            return accuracy_float * 0.000621371
    
    def create_gps_accuracy_circle(self, lat, lon, radius_miles, event_metadata,
                                   lat_source_text=None, lon_source_text=None,
                                   accuracy_display=None):
        """Create a location point accuracy circle using the location point color"""
        event_title = event_metadata['title']
        time_range = event_metadata['time_range']
        source_pair = self.source_coord_pair_text(
            lat, lon, lat_source_text, lon_source_text
        )

        # Create folder to group circle and timestamp label
        placemark = textwrap.dedent(f'''\
            <Folder>
                <name>{event_title}</name>
                <visibility>0</visibility>
        ''')

        # Add timestamp if successfully interpreted
        placemark += self.create_time_element(time_range)

        # 1. Create location point accuracy circle when valid accuracy was supplied
        if radius_miles is not None:
            accuracy_description = self.build_description_table([
                ('Location', source_pair),
                ('Accuracy', accuracy_display),
                ('Accuracy Radius (derived)', f"{radius_miles:.6f} miles"),
            ], event_metadata['source_row'])
            placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{event_title}</name>
                    <description><![CDATA[{accuracy_description}]]></description>
                    <Snippet maxLines="0"></Snippet>
            ''')

            placemark += self.create_placemark_temporal_elements(
                event_metadata, COMPONENT_TYPES['accuracy_circle'], "            "
            )

            placemark += textwrap.dedent(f'''\
                    <styleUrl>{self.style_url('gps-circle')}</styleUrl>
                    <Polygon>
                        <outerBoundaryIs>
                            <LinearRing>
                                <coordinates>
            ''')

            # Generate circle points
            for i in range(37):  # 36 points + close the loop
                angle = i * 10  # Every 10 degrees
                circle_lat, circle_lon = self.destination_point(lat, lon, angle, radius_miles)
                placemark += f"                    {self.format_coord_triplet(circle_lon, circle_lat)}\n"

            placemark += textwrap.dedent('''\
                                </coordinates>
                            </LinearRing>
                        </outerBoundaryIs>
                    </Polygon>
                </Placemark>
            ''')

        # 2. Add the center point and timestamp label
        point_description = self.build_description_table([
            ('Location', source_pair),
            ('Accuracy', accuracy_display),
            ('Point Visibility', 'Visible because accuracy is unknown, zero, or invalid' if radius_miles is None else 'Hidden anchor for circle event'),
        ], event_metadata['source_row'])
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{event_title}</name>
                    <description><![CDATA[{point_description}]]></description>
                    <Snippet maxLines="0"></Snippet>
        ''')
        
        placemark += self.create_placemark_temporal_elements(
            event_metadata, COMPONENT_TYPES['location_point'], "            "
        )
        
        placemark += textwrap.dedent(f'''\
                    <styleUrl>{self.style_url('location-visible' if radius_miles is None else 'location-hidden')}</styleUrl>
                    <Point>
                        <coordinates>{self.format_source_coord_triplet(lon_source_text if lon_source_text is not None else lon, lat_source_text if lat_source_text is not None else lat)}</coordinates>
                    </Point>
                </Placemark>
            </Folder>
        ''')
        
        return placemark
    
    def get_column_value(self, row, possible_names):
        """Get value from row using flexible column naming"""
        normalized_columns = {self.normalize_column_name(column): column for column in row.index}
        for name in possible_names:
            column = normalized_columns.get(self.normalize_column_name(name))
            if column is not None and not pd.isna(row[column]):
                return row[column]
        return None

    def get_numeric_column_value(self, row, possible_names):
        """Return a finite numeric column value, including numeric text."""
        value = self.get_column_value(row, possible_names)
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric_value):
            return None
        return int(numeric_value) if numeric_value.is_integer() else numeric_value

    def get_valid_coordinates(self, row):
        """Return validated decimal-degree coordinates or None."""
        result = self.get_valid_coordinates_with_text(row)
        if result is None:
            return None
        latitude, longitude, _, _ = result
        return latitude, longitude

    def get_valid_coordinates_with_text(self, row):
        """Return validated coordinates plus source-preserving coordinate text."""
        latitude = self.get_column_value(row, ['Latitude', 'lat', 'Lat'])
        longitude = self.get_column_value(row, ['Longitude', 'lon', 'Lon', 'Long'])
        try:
            latitude_float = float(latitude)
            longitude_float = float(longitude)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(latitude_float) or not math.isfinite(longitude_float):
            return None
        if not -90 <= latitude_float <= 90 or not -180 <= longitude_float <= 180:
            return None
        try:
            latitude_text = self.format_source_coord(latitude)
            longitude_text = self.format_source_coord(longitude)
        except (TypeError, ValueError):
            return None
        return latitude_float, longitude_float, latitude_text, longitude_text

    def report_dst_conflicts(self, data_type, row_numbers):
        """Report records retained without choosing a daylight-saving instant."""
        if not row_numbers:
            return
        rows = ", ".join(str(row_number) for row_number in row_numbers[:10])
        suffix = "..." if len(row_numbers) > 10 else ""
        self.status_message.emit(
            f"⚠️ {data_type}: {len(row_numbers)} rows were mapped without a date/time because their local times were ambiguous or nonexistent during a daylight-saving transition (source rows: {rows}{suffix}). Use an explicit UTC offset to resolve them."
        )

    def report_untimed_timestamps(self, data_type, row_numbers):
        """Report valid geometry exported without resolvable timestamp data."""
        if not row_numbers:
            return
        rows = ", ".join(str(row_number) for row_number in row_numbers[:10])
        suffix = "..." if len(row_numbers) > 10 else ""
        self.status_message.emit(
            f"⚠️ {data_type}: {len(row_numbers)} rows had missing, unreadable, or "
            "unresolved dates/times and were exported without timeline metadata "
            f"(source rows: {rows}{suffix})."
        )

    def normalize_column_name(self, column_name):
        """Normalize punctuation and spacing for case-insensitive column matching."""
        return re.sub(r'[^a-z0-9]+', ' ', str(column_name).lower()).strip()

    def get_timestamp_value(self, row):
        """Return a combined timestamp or join separate date and time columns."""
        for column in row.index:
            if str(column).strip().lower() == 'starttime' and not pd.isna(row[column]):
                return row[column]

        combined_value = self.get_column_value(row, [
            'Timestamp', 'Date & Time', 'Date/Time', 'DateTime',
            'Start DateTime', 'Start Date/Time',
            'Record Open Date/Time', 'Msg Send Date', 'Message Send Date',
        ])
        if combined_value is not None:
            return combined_value

        date_names = ['Date', 'Conn Date', 'Connection Date', 'Start Date']
        utc_time_names = ['Time (UTC)', 'Conn Time (UTC)', 'Connection Time (UTC)']
        time_names = ['Time', 'Conn Time', 'Connection Time', 'Start Time']
        date_value = self.get_column_value(row, date_names)
        time_value = self.get_column_value(row, utc_time_names)
        time_is_utc = time_value is not None
        if time_value is None:
            time_value = self.get_column_value(row, time_names)

        if date_value is None:
            return time_value
        if time_value is None:
            return date_value

        if isinstance(date_value, (datetime, pd.Timestamp)):
            date_text = date_value.strftime('%Y-%m-%d')
        else:
            date_text = str(date_value).strip()

        if isinstance(time_value, (datetime, pd.Timestamp)):
            time_text = time_value.strftime('%H:%M:%S.%f').rstrip('0').rstrip('.')
        elif hasattr(time_value, 'isoformat'):
            time_text = time_value.isoformat()
        else:
            time_text = str(time_value).strip()

        if time_is_utc:
            time_text += ' UTC'

        return f"{date_text} {time_text}"

    @staticmethod
    def is_missing_timestamp(value):
        """Return whether a timestamp value is absent rather than malformed."""
        if value is None:
            return True
        try:
            if pd.isna(value):
                return True
        except (TypeError, ValueError):
            pass
        return str(value).strip().lower() in ('', 'none', 'nan', 'nat')
    
    def parse_timestamp_to_kml(self, timestamp_str):
        """Parse a timestamp and return the established UTC/display pair."""
        kml_timestamp, display_label, _, _ = self.parse_timestamp_details(timestamp_str)
        return kml_timestamp, display_label

    def parse_timestamp_details(self, timestamp_str):
        """Parse once and retain the timezone used to resolve the source time."""
        if self.is_missing_timestamp(timestamp_str):
            return None, "Unknown", None, None
        
        timestamp_str = str(timestamp_str).strip()
        source_offset_minutes = int(self.settings.get('source_utc_offset_minutes', 0))
        source_timezone_name = self.settings.get('source_timezone_name')
        source_date_order = self.settings.get('source_date_order', 'MDY')
        
        # Try Excel serial date format first (numeric value like 45696.7637037037)
        try:
            timestamp_float = float(timestamp_str)
            # Excel serial dates are stored as days since 1900-01-01
            # Check if it's a reasonable Excel serial (between 1 and ~50000, which covers years 1900-2037)
            if 1 <= timestamp_float <= 50000:
                excel_epoch = datetime(1899, 12, 30)
                days_offset = int(timestamp_float)
                if days_offset < 60:
                    days_offset += 1
                fractional_day = timestamp_float - int(timestamp_float)
                dt = excel_epoch + timedelta(days=days_offset, seconds=fractional_day * 86400)
                display_label = dt.strftime('%Y-%m-%d %H:%M:%S')
                return self.create_timestamp_details(
                    dt, display_label, source_offset_minutes, source_timezone_name
                )
        except (ValueError, OverflowError):
            pass
        
        timestamp_str_clean, explicit_offset_minutes = self.extract_timezone_offset(timestamp_str)
        effective_offset_minutes = explicit_offset_minutes if explicit_offset_minutes is not None else source_offset_minutes
        effective_timezone_name = None if explicit_offset_minutes is not None else source_timezone_name
        
        # Strip milliseconds and microseconds (e.g., "2025-02-11 11:06:07.557" -> "2025-02-11 11:06:07")
        timestamp_str_clean = re.sub(r'(\d{2}):(\d{2}):(\d{2})\.\d+', r'\1:\2:\3', timestamp_str_clean)

        meridiem = None
        meridiem_match = re.search(
            r'\s+([APap][Mm])\s*$', timestamp_str_clean
        )
        if meridiem_match and ':' in timestamp_str_clean:
            meridiem = meridiem_match.group(1).lower()
            timestamp_str_clean = timestamp_str_clean[
                :meridiem_match.start()
            ].strip()
        
        # Common timestamp patterns
        patterns = [
            # ISO format variations
            r'(\d{4})-(\d{1,2})-(\d{1,2})[T\s](\d{1,2}):(\d{1,2}):(\d{1,2})',
            r'(\d{4})-(\d{1,2})-(\d{1,2})[T\s](\d{1,2}):(\d{1,2})',
            r'(\d{4})-(\d{1,2})-(\d{1,2})',
            # ISO forward-slash format (2025/02/03 18:36:04)
            r'(\d{4})/(\d{1,2})/(\d{1,2})[T\s](\d{1,2}):(\d{1,2}):(\d{1,2})',
            r'(\d{4})/(\d{1,2})/(\d{1,2})[T\s](\d{1,2}):(\d{1,2})',
            r'(\d{4})/(\d{1,2})/(\d{1,2})',
            # US format variations (with 4-digit years)
            r'(\d{1,2})/(\d{1,2})/(\d{4})[T\s](\d{1,2}):(\d{1,2}):(\d{1,2})',
            r'(\d{1,2})/(\d{1,2})/(\d{4})[T\s](\d{1,2}):(\d{1,2})',
            r'(\d{1,2})/(\d{1,2})/(\d{4})',
            # US format with 2-digit years (07/30/24 13:00:20)
            r'(\d{1,2})/(\d{1,2})/(\d{2})[T\s](\d{1,2}):(\d{1,2}):(\d{1,2})',
            r'(\d{1,2})/(\d{1,2})/(\d{2})[T\s](\d{1,2}):(\d{1,2})',
            r'(\d{1,2})/(\d{1,2})/(\d{2})',
            # Numeric dash formats; ambiguous month/day order uses the setting
            r'(\d{1,2})-(\d{1,2})-(\d{4})[T\s](\d{1,2}):(\d{1,2}):(\d{1,2})',
            r'(\d{1,2})-(\d{1,2})-(\d{4})[T\s](\d{1,2}):(\d{1,2})',
            r'(\d{1,2})-(\d{1,2})-(\d{4})',
            r'(\d{1,2})-(\d{1,2})-(\d{2})[T\s](\d{1,2}):(\d{1,2}):(\d{1,2})',
            r'(\d{1,2})-(\d{1,2})-(\d{2})[T\s](\d{1,2}):(\d{1,2})',
            r'(\d{1,2})-(\d{1,2})-(\d{2})',
            # European format variations (DD.MM.YYYY)
            r'(\d{1,2})\.(\d{1,2})\.(\d{4})[T\s](\d{1,2}):(\d{1,2}):(\d{1,2})',
            r'(\d{1,2})\.(\d{1,2})\.(\d{4})[T\s](\d{1,2}):(\d{1,2})',
            r'(\d{1,2})\.(\d{1,2})\.(\d{4})',
            # Time-only patterns (use today's date)
            r'(\d{1,2}):(\d{1,2}):(\d{1,2})\s*([APap][Mm])?',
            r'(\d{1,2}):(\d{1,2})\s*([APap][Mm])?',
        ]
        
        for pattern in patterns:
            match = re.fullmatch(pattern, timestamp_str_clean)
            if match:
                groups = match.groups()
                
                try:
                    # Check if this is a time-only pattern
                    if ':' in timestamp_str_clean and not any(char in timestamp_str_clean for char in ['/', '-', '.']):
                        # Time-only format - use today's date
                        hour = int(groups[0])
                        minute = int(groups[1])
                        second = int(groups[2]) if len(groups) > 2 and groups[2] else 0
                        
                        # Handle AM/PM
                        is_time_only = True
                        if meridiem:
                            if meridiem == 'pm' and hour != 12:
                                hour += 12
                            elif meridiem == 'am' and hour == 12:
                                hour = 0
                        
                        # Use today's date for time-only entries
                        today = datetime.now()
                        dt = datetime(today.year, today.month, today.day, hour, minute, second)
                        is_time_only = True
                        
                    else:
                        is_time_only = False
                        first_value = int(groups[0])
                        second_value = int(groups[1])
                        third_value = int(groups[2])
                        first_token = re.match(r'\s*(\d+)', timestamp_str_clean)
                        year_first = bool(
                            first_token and len(first_token.group(1)) == 4
                        )

                        if year_first:
                            if source_date_order == 'YDM':
                                year, day, month = (
                                    first_value, second_value, third_value
                                )
                            else:
                                year, month, day = (
                                    first_value, second_value, third_value
                                )
                        elif '.' in timestamp_str_clean:
                            day, month, year = (
                                first_value, second_value, third_value
                            )
                        elif first_value > 12 and second_value <= 12:
                            day, month, year = (
                                first_value, second_value, third_value
                            )
                        elif second_value > 12 and first_value <= 12:
                            month, day, year = (
                                first_value, second_value, third_value
                            )
                        elif source_date_order == 'DMY':
                            day, month, year = (
                                first_value, second_value, third_value
                            )
                        else:
                            month, day, year = (
                                first_value, second_value, third_value
                            )
                        
                        # Handle 2-digit years (convert to 4-digit)
                        if year < 100:
                            # Assume 00-30 is 2000-2030, 31-99 is 1931-1999
                            year = 2000 + year if year <= 30 else 1900 + year
                        
                        # Handle time if present
                        hour = int(groups[3]) if len(groups) > 3 else 0
                        minute = int(groups[4]) if len(groups) > 4 else 0
                        second = int(groups[5]) if len(groups) > 5 else 0
                        
                        # Handle AM/PM (check if there's an AM/PM marker in the original string)
                        if meridiem:
                            if meridiem == 'pm' and hour != 12:
                                hour += 12
                            elif meridiem == 'am' and hour == 12:
                                hour = 0
                        
                        # Create datetime object
                        dt = datetime(year, month, day, hour, minute, second)
                    
                    # Format for KML (ISO 8601)
                    # Create display label - show only time for time-only entries
                    if is_time_only:
                        # For time-only entries, show just the time in a clean format
                        if meridiem:
                            # Keep AM/PM format if it was in the original
                            display_label = dt.strftime('%I:%M:%S %p').lstrip('0')
                        else:
                            # Use 24-hour format
                            display_label = dt.strftime('%H:%M:%S')
                    else:
                        # For full timestamps, show date and time
                        display_label = dt.strftime('%Y-%m-%d %H:%M:%S')
                    
                    return self.create_timestamp_details(
                        dt, display_label, effective_offset_minutes,
                        effective_timezone_name
                    )
                    
                except (ValueError, OverflowError):
                    continue
        
        # If no pattern matches, return None for KML timestamp but keep original as label
        return None, xml_escape(timestamp_str), None, None

    def create_timestamp_details(self, source_datetime, display_label,
                                 source_offset_minutes, timezone_name):
        """Return canonical UTC plus the already-resolved source timezone."""
        aware_datetime = self.resolve_source_datetime(
            source_datetime, source_offset_minutes, timezone_name
        )
        utc_datetime = aware_datetime.astimezone(timezone.utc)
        if timezone_name:
            timezone_description = timezone_name
        else:
            sign = '+' if source_offset_minutes >= 0 else '-'
            hours, minutes = divmod(abs(source_offset_minutes), 60)
            timezone_description = f"Fixed UTC {sign}{hours:02d}:{minutes:02d}"
        return (
            utc_datetime.strftime('%Y-%m-%dT%H:%M:%SZ'),
            display_label,
            aware_datetime.tzinfo,
            timezone_description,
        )

    def extract_timezone_offset(self, timestamp_str):
        """Remove supported timezone suffixes and return their UTC offset in minutes."""
        abbreviation_offsets = {
            'UTC': 0, 'GMT': 0,
            'EST': -300, 'EDT': -240,
            'CST': -360, 'CDT': -300,
            'MST': -420, 'MDT': -360,
            'PST': -480, 'PDT': -420,
        }
        offset_patterns = [
            r'\s*\((?:GMT|UTC)\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?\)\s*$',
            r'\s*(?:GMT|UTC)\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?\s*$',
            r'\s*([+-])(\d{2}):?(\d{2})\s*$',
        ]

        for pattern in offset_patterns:
            match = re.search(pattern, timestamp_str, flags=re.IGNORECASE)
            if match:
                hours = int(match.group(2))
                minutes = int(match.group(3) or 0)
                if hours > 14 or minutes > 59:
                    return timestamp_str, None
                sign = 1 if match.group(1) == '+' else -1
                return timestamp_str[:match.start()].strip(), sign * ((hours * 60) + minutes)

        abbreviation_match = re.search(r'(?:\s+(UTC|GMT|EST|EDT|CST|CDT|MST|MDT|PST|PDT)|(?<=\d)(Z))\s*$', timestamp_str, flags=re.IGNORECASE)
        if abbreviation_match:
            abbreviation = (abbreviation_match.group(1) or abbreviation_match.group(2)).upper()
            offset_minutes = 0 if abbreviation == 'Z' else abbreviation_offsets[abbreviation]
            return timestamp_str[:abbreviation_match.start()].strip(), offset_minutes

        return timestamp_str, None

    def convert_datetime_to_utc(self, source_datetime, source_offset_minutes, timezone_name=None):
        """Convert a source datetime to UTC using a named zone or fixed offset."""
        aware_datetime = self.resolve_source_datetime(
            source_datetime, source_offset_minutes, timezone_name
        )
        utc_datetime = aware_datetime.astimezone(timezone.utc)
        return utc_datetime.strftime('%Y-%m-%dT%H:%M:%SZ')

    def resolve_source_datetime(self, source_datetime, source_offset_minutes,
                                timezone_name=None):
        """Resolve a naive source datetime using the configured timezone policy."""
        if timezone_name:
            source_timezone = ZoneInfo(timezone_name)
            first_occurrence = source_datetime.replace(tzinfo=source_timezone, fold=0)
            second_occurrence = source_datetime.replace(tzinfo=source_timezone, fold=1)
            first_roundtrip = first_occurrence.astimezone(timezone.utc).astimezone(source_timezone).replace(tzinfo=None)
            second_roundtrip = second_occurrence.astimezone(timezone.utc).astimezone(source_timezone).replace(tzinfo=None)

            first_valid = first_roundtrip == source_datetime
            second_valid = second_roundtrip == source_datetime
            is_ambiguous = first_valid and second_valid and first_occurrence.utcoffset() != second_occurrence.utcoffset()
            if not first_valid and not second_valid:
                raise TimestampResolutionError(
                    f"Timestamp {source_datetime} does not exist in {timezone_name}"
                )
            if is_ambiguous:
                raise TimestampResolutionError(
                    f"Timestamp {source_datetime} occurs twice in {timezone_name}"
                )
            aware_datetime = first_occurrence if first_valid else second_occurrence
        else:
            source_timezone = timezone(timedelta(minutes=source_offset_minutes))
            aware_datetime = source_datetime.replace(tzinfo=source_timezone)

        return aware_datetime

    def calculate_end_timestamp(self, kml_timestamp, duration_minutes):
        """Calculate end timestamp by adding duration to the begin timestamp"""
        try:
            # Parse the KML timestamp (ISO format: YYYY-MM-DDTHH:MM:SS or YYYY-MM-DD)
            if 'T' in kml_timestamp:
                # Full datetime
                dt = datetime.fromisoformat(kml_timestamp.replace('Z', '+00:00'))
            else:
                # Date only - assume start of day
                dt = datetime.fromisoformat(kml_timestamp + 'T00:00:00')
            
            # Add duration
            end_dt = dt + timedelta(minutes=duration_minutes)
            
            # Return in KML format
            if 'T' in kml_timestamp:
                return end_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            else:
                # If original was date-only, return date-only for end as well
                return end_dt.strftime('%Y-%m-%d')
                
        except (ValueError, TypeError) as e:
            # If parsing fails, return None to fall back to begin-only
            return None
    
    @staticmethod
    def create_event_id(row_position):
        """Create a deterministic identifier from the row's generation order."""
        return f"event_{row_position + 1:06d}"

    def source_row_number(self, row_position, row):
        """Return the one-based physical source row, including its header."""
        source_index = getattr(row, 'name', row_position)
        try:
            source_offset = int(source_index)
            if source_offset != source_index or source_offset < 0:
                source_offset = row_position
        except (TypeError, ValueError, OverflowError):
            source_offset = row_position

        try:
            header_row = max(int(self.settings.get('source_header_row', 1)), 1)
        except (TypeError, ValueError):
            header_row = 1
        return header_row + source_offset + 1

    def create_event_metadata(self, row_position, timestamp, event_type, row=None):
        """Create metadata once for every component of one logical input row."""
        timestamp_dst_conflict = False
        try:
            kml_timestamp, display_label, source_timezone, timezone_description = (
                self.parse_timestamp_details(timestamp)
            )
        except TimestampResolutionError:
            timestamp_dst_conflict = True
            kml_timestamp, display_label, source_timezone, timezone_description = (
                None, None, None, None
            )
        timestamp_parse_failed = (
            kml_timestamp is None
            and not self.is_missing_timestamp(timestamp)
        )
        if kml_timestamp is None:
            display_label = f"Entry {row_position + 1} (date/time unavailable)"
        time_range = self.create_time_range(kml_timestamp)
        display_timezone, display_timezone_description = self.resolve_display_timezone(
            source_timezone, timezone_description
        )
        local_time_range = self.create_local_time_range(time_range, display_timezone)
        local_start = local_time_range[0] if local_time_range else None
        event_title = self.format_event_title(local_start, display_label)
        return {
            'event_id': self.create_event_id(row_position),
            'source_row': self.source_row_number(row_position, row),
            'event_label': self.create_event_label(event_title, row),
            'title': event_title,
            'event_type': event_type,
            'display_label': display_label,
            'timestamp_parse_failed': bool(timestamp_parse_failed),
            'timestamp_dst_conflict': timestamp_dst_conflict,
            'time_range': time_range,
            'local_time_range': local_time_range,
            'timezone': display_timezone_description,
        }

    @staticmethod
    def format_event_title(local_timestamp, fallback):
        """Format a resolved local instant consistently for user-facing labels."""
        if not local_timestamp:
            return fallback
        try:
            local_datetime = datetime.fromisoformat(
                str(local_timestamp).replace('Z', '+00:00')
            )
        except (TypeError, ValueError):
            return fallback

        hour = local_datetime.hour % 12 or 12
        meridiem = 'AM' if local_datetime.hour < 12 else 'PM'
        return (
            f"{local_datetime.month:02d}/{local_datetime.day:02d}/"
            f"{local_datetime.year:04d}, {hour}:{local_datetime.minute:02d}:"
            f"{local_datetime.second:02d} {meridiem}"
        )

    def resolve_display_timezone(self, source_timezone, source_timezone_description):
        """Resolve the timezone used for local metadata display values."""
        target_timezone_name = self.settings.get('target_timezone_name')
        target_offset_minutes = self.settings.get('target_utc_offset_minutes')

        if target_timezone_name:
            return ZoneInfo(target_timezone_name), target_timezone_name

        if target_offset_minutes is not None:
            offset_minutes = int(target_offset_minutes)
            sign = '+' if offset_minutes >= 0 else '-'
            hours, minutes = divmod(abs(offset_minutes), 60)
            description = f"Fixed UTC {sign}{hours:02d}:{minutes:02d}"
            return timezone(timedelta(minutes=offset_minutes)), description

        return source_timezone, source_timezone_description

    def create_event_label(self, display_label, row):
        """Combine the existing display time with concise row identifiers."""
        if row is None:
            return display_label

        identifier_groups = [
            (
                'Cell Site',
                ['Cell Site', 'Cell Site Name', 'Cell Site ID',
                 'Site', 'Site Name', 'Site ID'],
            ),
            ('Cell Site', ['Tower', 'Tower Name', 'Tower ID']),
            ('Cell', ['Cell', 'Cell Name', 'Cell ID']),
            ('Sector', ['Sector', 'Sector Name', 'Sector ID']),
            ('Location', ['Location', 'Location Name', 'Label', 'Name']),
        ]
        identifiers = []
        seen_values = set()
        for label, names in identifier_groups:
            value = self.get_column_value(row, names)
            if value is None:
                continue
            value_text = str(value).strip()
            if value_text and value_text not in seen_values:
                identifiers.append(f"{label} {value_text}")
                seen_values.add(value_text)
        return f"{display_label} - {' / '.join(identifiers)}" if identifiers else display_label

    def create_time_range(self, kml_timestamp):
        """Return the normalized begin/end pair used by one logical event."""
        if not kml_timestamp or not self.settings.get('enable_time_animation', True):
            return None

        duration_minutes = self.settings.get('duration_minutes', 30)
        end_timestamp = self.calculate_end_timestamp(kml_timestamp, duration_minutes)
        return kml_timestamp, end_timestamp

    @staticmethod
    def create_local_time_range(time_range, source_timezone):
        """Project the canonical UTC range into its already-resolved source zone."""
        if not time_range or source_timezone is None:
            return None

        local_values = []
        for timestamp_value in time_range:
            if timestamp_value is None:
                local_values.append(None)
                continue
            utc_datetime = datetime.fromisoformat(timestamp_value.replace('Z', '+00:00'))
            local_values.append(
                utc_datetime.astimezone(source_timezone).isoformat(timespec='seconds')
            )
        return tuple(local_values)

    def create_time_element(self, time_range, indent="        "):
        """Create the canonical TimeSpan element from a normalized time range."""
        if not time_range:
            return ""

        begin_timestamp, end_timestamp = time_range
        if end_timestamp:
            return f"{indent}<TimeSpan><begin>{begin_timestamp}</begin><end>{end_timestamp}</end></TimeSpan>\n"
        return f"{indent}<TimeSpan><begin>{begin_timestamp}</begin></TimeSpan>\n"

    def create_extended_data(self, event_metadata, component_type, indent="        "):
        """Create shared identity and optional temporal feature attributes."""
        if not self.export_metadata:
            self.begin_export(self.settings.get('custom_label') or data_type_label(self.data_type))
        values = list(self.export_metadata.items())
        is_anchor = self.is_event_metadata_anchor(event_metadata, component_type)
        time_range = event_metadata['time_range']
        if time_range and is_anchor:
            begin_timestamp, end_timestamp = time_range
            local_begin, local_end = event_metadata['local_time_range']
            values.extend([
                ('osloc_start_time', begin_timestamp),
                ('osloc_end_time', end_timestamp),
                ('osloc_local_start_time', local_begin),
                ('osloc_local_end_time', local_end),
                ('osloc_timezone', event_metadata['timezone']),
                ('osloc_display_time', event_metadata['display_label']),
            ])
        values.extend([
            ('osloc_event_id', event_metadata['event_id']),
            ('osloc_source_row', event_metadata['source_row']),
            ('osloc_event_label', event_metadata['event_label'] if is_anchor else None),
            ('osloc_event_type', event_metadata['event_type']),
            ('osloc_component_type', component_type),
        ])
        return self.create_data_element_block(values, indent)

    @staticmethod
    def metadata_anchor_component(event_type):
        anchor_by_event_type = {
            EVENT_TYPES['tower_sector']: COMPONENT_TYPES['tower_sector'],
            EVENT_TYPES['tower_sector_distance']: COMPONENT_TYPES['tower_sector'],
            EVENT_TYPES['tower_no_azimuth']: COMPONENT_TYPES['coverage_circle'],
            EVENT_TYPES['distance_only']: COMPONENT_TYPES['distance_band'],
            EVENT_TYPES['location_accuracy']: COMPONENT_TYPES['accuracy_circle'],
            EVENT_TYPES['location']: COMPONENT_TYPES['location_point'],
        }
        return anchor_by_event_type.get(event_type)

    def is_event_metadata_anchor(self, event_metadata, component_type):
        """Store heavier temporal fields once per logical event to reduce KML size."""
        anchor = self.metadata_anchor_component(event_metadata['event_type'])
        return anchor == component_type

    def create_placemark_temporal_elements(self, event_metadata, component_type,
                                           indent="        "):
        """Create canonical and supplemental temporal data from one time range."""
        return (
            self.create_time_element(event_metadata['time_range'], indent)
            + self.create_extended_data(event_metadata, component_type, indent)
        )

    @staticmethod
    def parse_kml_coordinate_rows(text):
        rows = []
        for token in re.split(r'\s+', (text or '').strip()):
            if not token or ',' not in token:
                continue
            parts = token.split(',')
            try:
                lon = float(parts[0])
                lat = float(parts[1])
            except (TypeError, ValueError, IndexError):
                continue
            if len(parts) > 2:
                try:
                    altitude = float(parts[2])
                    rows.append([lon, lat, altitude])
                except (TypeError, ValueError):
                    rows.append([lon, lat])
            else:
                rows.append([lon, lat])
        return rows

    def placemark_properties_for_geojson(self, placemark, source_properties):
        properties = {
            item.get('name'): item.findtext('value')
            for item in placemark.findall('ExtendedData/Data')
            if item.get('name')
        }
        name = placemark.findtext('name')
        if name:
            properties['name'] = name
        description = placemark.findtext('description')
        if description:
            properties['description'] = description

        time_begin = placemark.findtext('TimeSpan/begin')
        time_end = placemark.findtext('TimeSpan/end')
        if time_begin and 'osloc_start_time' not in properties:
            properties['osloc_start_time'] = time_begin
        if time_end and 'osloc_end_time' not in properties:
            properties['osloc_end_time'] = time_end

        start_epoch_ms = self.iso_timestamp_to_epoch_ms(
            properties.get('osloc_start_time')
        )
        end_epoch_ms = self.iso_timestamp_to_epoch_ms(
            properties.get('osloc_end_time')
        )
        if start_epoch_ms is not None:
            properties['osloc_start_epoch_ms'] = start_epoch_ms
        if end_epoch_ms is not None:
            properties['osloc_end_epoch_ms'] = end_epoch_ms

        dataset_id = properties.get('osloc_dataset_id')
        event_id = properties.get('osloc_event_id')
        if dataset_id and event_id:
            properties['osloc_event_key'] = f"{dataset_id}::{event_id}"

        properties.update(source_properties)
        return properties

    def geojson_geometries_from_placemark(self, placemark):
        primitives = []

        def append_polygon(polygon):
            ring_text = polygon.findtext('outerBoundaryIs/LinearRing/coordinates')
            ring = self.parse_kml_coordinate_rows(ring_text)
            if ring:
                primitives.append({'type': 'Polygon', 'coordinates': [ring]})

        def append_line(line_string):
            rows = self.parse_kml_coordinate_rows(line_string.findtext('coordinates'))
            if rows:
                primitives.append({'type': 'LineString', 'coordinates': rows})

        def append_point(point):
            rows = self.parse_kml_coordinate_rows(point.findtext('coordinates'))
            if rows:
                primitives.append({'type': 'Point', 'coordinates': rows[0]})

        for polygon in placemark.findall('Polygon'):
            append_polygon(polygon)
        for line_string in placemark.findall('LineString'):
            append_line(line_string)
        for point in placemark.findall('Point'):
            append_point(point)

        for multi_geometry in placemark.findall('MultiGeometry'):
            for polygon in multi_geometry.findall('Polygon'):
                append_polygon(polygon)
            for line_string in multi_geometry.findall('LineString'):
                append_line(line_string)
            for point in multi_geometry.findall('Point'):
                append_point(point)

        return primitives

    def geojson_features_from_event_fragment(self, fragment, source_properties):
        if not fragment:
            return []

        try:
            root = ET.fromstring(fragment)
        except ET.ParseError:
            return []

        placemarks = []
        if root.tag == 'Placemark':
            placemarks = [root]
        elif root.tag == 'Folder':
            placemarks = root.findall('Placemark')
        else:
            placemarks = root.findall('.//Placemark')

        features = []
        for placemark in placemarks:
            properties = self.placemark_properties_for_geojson(
                placemark, source_properties
            )
            geometries = self.geojson_geometries_from_placemark(placemark)
            for geometry_index, geometry in enumerate(geometries):
                feature_properties = dict(properties)
                if len(geometries) > 1:
                    feature_properties['osloc_geometry_part_index'] = geometry_index
                features.append({
                    'type': 'Feature',
                    'geometry': geometry,
                    'properties': feature_properties,
                })

        return features

    def create_geojson_collection(self, dataset_name, features):
        metadata = self.export_metadata
        if not metadata:
            metadata = self.begin_export(dataset_name)
        return json.dumps({
            'type': 'FeatureCollection',
            'name': metadata['osloc_dataset_name'],
            'features': features,
            'osloc_schema_version': metadata['osloc_schema_version'],
            'osloc_dataset_id': metadata['osloc_dataset_id'],
            'osloc_dataset_name': metadata['osloc_dataset_name'],
            'osloc_review_notice': PRELIMINARY_REVIEW_NOTICE,
        }, indent=2)

    def source_geojson_properties(self, lat_source_text, lon_source_text):
        leg_color = self.settings.get('leg_color') or 'ff000000'
        shaded_color = f"7d{(self.settings.get('shaded_color') or 'ff00ffff')[2:]}"
        band_color = f"7d{(self.settings.get('band_color') or 'ff0099ff')[2:]}"
        gps_line_color = self.settings.get('gps_color') or 'ff00ff00'
        gps_fill_color = f"4d{gps_line_color[2:]}"
        reported_distance_color = 'ff000000'
        distance_center_color = 'ff0000ff'
        properties = {
            'osloc_style_leg_color': leg_color,
            'osloc_style_shaded_color': shaded_color,
            'osloc_style_band_color': band_color,
            'osloc_style_gps_line_color': gps_line_color,
            'osloc_style_gps_fill_color': gps_fill_color,
            'osloc_style_reported_distance_color': reported_distance_color,
            'osloc_style_distance_center_color': distance_center_color,
            'osloc_style_leg_color_rgba': self.kml_color_to_css_rgba(leg_color),
            'osloc_style_shaded_color_rgba': self.kml_color_to_css_rgba(shaded_color),
            'osloc_style_band_color_rgba': self.kml_color_to_css_rgba(band_color),
            'osloc_style_gps_line_color_rgba': self.kml_color_to_css_rgba(gps_line_color),
            'osloc_style_gps_fill_color_rgba': self.kml_color_to_css_rgba(gps_fill_color),
            'osloc_style_reported_distance_color_rgba': self.kml_color_to_css_rgba(
                reported_distance_color
            ),
            'osloc_style_distance_center_color_rgba': self.kml_color_to_css_rgba(
                distance_center_color
            ),
        }
        if lat_source_text is None or lon_source_text is None:
            return properties
        properties.update({
            'osloc_source_latitude': lat_source_text,
            'osloc_source_longitude': lon_source_text,
            'osloc_source_coordinate_text': f"{lat_source_text}, {lon_source_text}",
        })
        return properties

    def generate_cell_tower_geojson(self, df):
        dataset_name = self.settings.get('custom_label') or "Cell Site/Sector Data"
        features = []

        for idx, (_, row) in enumerate(df.iterrows()):
            coordinates = self.get_valid_coordinates_with_text(row)
            timestamp = self.get_timestamp_value(row)
            azimuth = self.get_numeric_column_value(
                row, ['Azimuth', 'azimuth', 'bearing', 'direction']
            )

            if coordinates is None:
                continue
            lat, lon, lat_source_text, lon_source_text = coordinates
            if azimuth is not None:
                event_metadata = self.create_event_metadata(
                    idx, timestamp, EVENT_TYPES['tower_sector'], row
                )
                fragment = self.create_sector_placemark(
                    lat, lon, azimuth, event_metadata, lat_source_text,
                    lon_source_text
                )
            else:
                event_metadata = self.create_event_metadata(
                    idx, timestamp, EVENT_TYPES['tower_no_azimuth'], row
                )
                fragment = self.create_circle_placemark(
                    lat, lon, event_metadata, lat_source_text, lon_source_text
                )
            features.extend(self.geojson_features_from_event_fragment(
                fragment,
                self.source_geojson_properties(lat_source_text, lon_source_text),
            ))

        features.extend(self.reference_site_geojson_features(df, dataset_name))
        features.extend(self.marker_geojson_features(dataset_name))
        return self.create_geojson_collection(dataset_name, features)

    def generate_distance_from_tower_geojson(self, df):
        dataset_name = self.settings.get('custom_label') or "Distance from Cell Site Analysis"
        features = []

        for idx, (_, row) in enumerate(df.iterrows()):
            coordinates = self.get_valid_coordinates_with_text(row)
            timestamp = self.get_timestamp_value(row)
            azimuth = self.get_numeric_column_value(
                row, ['Azimuth', 'bearing', 'direction']
            )
            distance = self.get_numeric_column_value(
                row,
                ['Distance', 'range', 'distance (m)', 'distance (meters)'],
            )

            if coordinates is None:
                continue
            lat, lon, lat_source_text, lon_source_text = coordinates

            has_azimuth = azimuth is not None
            has_distance = distance is not None and distance >= 0

            if has_azimuth and has_distance:
                distance_miles = self.convert_ta_distance_to_miles(
                    distance, self.settings.get('ta_distance_units', 'Meters')
                )
                event_metadata = self.create_event_metadata(
                    idx, timestamp, EVENT_TYPES['tower_sector_distance'], row
                )
                fragment = self.create_combined_sector_and_arc(
                    lat, lon, azimuth, distance_miles, event_metadata,
                    lat_source_text, lon_source_text
                )
            elif has_azimuth and not has_distance:
                event_metadata = self.create_event_metadata(
                    idx, timestamp, EVENT_TYPES['tower_sector'], row
                )
                fragment = self.create_sector_placemark(
                    lat, lon, azimuth, event_metadata, lat_source_text,
                    lon_source_text
                )
            elif not has_azimuth and has_distance:
                distance_miles = self.convert_ta_distance_to_miles(
                    distance, self.settings.get('ta_distance_units', 'Meters')
                )
                event_metadata = self.create_event_metadata(
                    idx, timestamp, EVENT_TYPES['distance_only'], row
                )
                fragment = self.create_distance_band(
                    lat, lon, distance_miles, event_metadata,
                    lat_source_text, lon_source_text
                )
            else:
                event_metadata = self.create_event_metadata(
                    idx, timestamp, EVENT_TYPES['tower_no_azimuth'], row
                )
                fragment = self.create_circle_placemark(
                    lat, lon, event_metadata, lat_source_text, lon_source_text
                )

            features.extend(self.geojson_features_from_event_fragment(
                fragment,
                self.source_geojson_properties(lat_source_text, lon_source_text),
            ))

        features.extend(self.reference_site_geojson_features(df, dataset_name))
        features.extend(self.marker_geojson_features(dataset_name))
        return self.create_geojson_collection(dataset_name, features)

    def generate_gps_geojson(self, df):
        dataset_name = self.settings.get('custom_label') or "Location Point Data"
        features = []

        for idx, (_, row) in enumerate(df.iterrows()):
            coordinates = self.get_valid_coordinates_with_text(row)
            timestamp = self.get_timestamp_value(row)
            gps_accuracy = self.get_column_value(
                row, ['GPS Accuracy', 'Accuracy', 'gps_accuracy', 'accuracy']
            )

            if coordinates is None:
                continue
            lat, lon, lat_source_text, lon_source_text = coordinates

            radius_miles, accuracy_display, _ = self.resolve_location_accuracy(
                gps_accuracy
            )

            event_type = (
                EVENT_TYPES['location_accuracy']
                if radius_miles is not None
                else EVENT_TYPES['location']
            )
            event_metadata = self.create_event_metadata(
                idx, timestamp, event_type, row
            )
            fragment = self.create_gps_accuracy_circle(
                lat, lon, radius_miles, event_metadata, lat_source_text,
                lon_source_text, accuracy_display
            )
            features.extend(self.geojson_features_from_event_fragment(
                fragment,
                self.source_geojson_properties(lat_source_text, lon_source_text),
            ))

        features.extend(self.marker_geojson_features(dataset_name))
        return self.create_geojson_collection(dataset_name, features)

    def source_coord_pair_text(self, lat, lon, lat_source_text=None,
                               lon_source_text=None):
        source_lat = (
            lat_source_text if lat_source_text is not None
            else self.format_source_coord(lat)
        )
        source_lon = (
            lon_source_text if lon_source_text is not None
            else self.format_source_coord(lon)
        )
        return f"{source_lat}, {source_lon}"

    def build_description_table(self, rows, source_row=None):
        if source_row is not None:
            rows = [('Source Row', source_row), *rows]
        table_rows = "".join(
            (
                '<tr>'
                '<td style="padding: 2px 14px 2px 0; vertical-align: top;">'
                f'<b>{xml_escape(str(label))}:</b></td>'
                '<td style="padding: 2px 0;">'
                f'{xml_escape(str(value))}</td>'
                '</tr>'
            )
            for label, value in rows
            if value is not None and str(value).strip() != ""
        )
        return f'<table style="border-collapse: collapse;">{table_rows}</table>'

    def create_sector_placemark(self, lat, lon, azimuth, event_metadata,
                                lat_source_text=None, lon_source_text=None):
        """Create a sector wedge placemark with extended directional lines (SWGDE style)"""
        event_title = event_metadata['title']
        time_range = event_metadata['time_range']
        
        start_angle = azimuth - self.settings['azimuth_spread'] / 2
        end_angle = azimuth + self.settings['azimuth_spread'] / 2
        source_pair = self.source_coord_pair_text(
            lat, lon, lat_source_text, lon_source_text
        )
        sector_description = self.build_description_table([
            ('Cell Site', source_pair),
            ('Azimuth', f"{azimuth}°"),
            ('Sector Width', f"{self.settings['azimuth_spread']}°"),
            ('Sector Length', f"{self.settings['shaded_area_length']} miles"),
            ('Leg Length', f"{self.settings['leg_length']} miles"),
        ], event_metadata['source_row'])
        
        # Create folder to group sector and extended lines
        placemark = textwrap.dedent(f'''\
            <Folder>
                <name>{event_title}</name>
                <visibility>0</visibility>
        ''')
        
        # Add timestamp if successfully interpreted and time animation is enabled
        placemark += self.create_time_element(time_range)
        
        # 1. Create the shaded sector wedge
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{event_title}</name>
                    <description><![CDATA[{sector_description}]]></description>
                    <Snippet maxLines="0"></Snippet>
        ''')
        
        placemark += self.create_placemark_temporal_elements(
            event_metadata, COMPONENT_TYPES['tower_sector'], "            "
        )
        
        placemark += textwrap.dedent(f'''\
                    <styleUrl>{self.style_url('tower-area')}</styleUrl>
                    <Polygon>
                        <outerBoundaryIs><LinearRing><coordinates>
                            {self.format_source_coord_triplet(lon_source_text if lon_source_text is not None else lon, lat_source_text if lat_source_text is not None else lat)}
        ''')
        
        # Generate arc points for shaded area
        for i in range(self.settings['num_points'] + 1):
            angle = start_angle + (end_angle - start_angle) * i / self.settings['num_points']
            arc_lat, arc_lon = self.destination_point(lat, lon, angle, self.settings['shaded_area_length'])
            placemark += f"                {self.format_coord_triplet(arc_lon, arc_lat)}\n"
        
        placemark += f"                {self.format_source_coord_triplet(lon_source_text if lon_source_text is not None else lon, lat_source_text if lat_source_text is not None else lat)}\n"
        placemark += textwrap.dedent('''\
                        </coordinates></LinearRing></outerBoundaryIs>
                    </Polygon>
                </Placemark>
        ''')
        
        # 2. Create center point label (no icon, just show timestamp)
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{event_title}</name>
        ''')
        
        placemark += self.create_placemark_temporal_elements(
            event_metadata, COMPONENT_TYPES['center_point'], "            "
        )
        
        placemark += textwrap.dedent(f'''\
                    <styleUrl>{self.style_url('hidden-center')}</styleUrl>
                    <Point>
                        <coordinates>{self.format_source_coord_triplet(lon_source_text if lon_source_text is not None else lon, lat_source_text if lat_source_text is not None else lat)}</coordinates>
                    </Point>
                </Placemark>
        ''')
        
        # 3. Create extended directional lines (legs)
        leg_length = self.settings['leg_length']
        
        # Left directional line
        left_lat, left_lon = self.destination_point(lat, lon, start_angle, leg_length)
        left_description = self.build_description_table([
            ('Cell Site', source_pair),
            ('Azimuth', f"{azimuth}°"),
            ('Leg Direction', f"{start_angle:.2f}°"),
            ('Leg Length', f"{leg_length} miles"),
        ], event_metadata['source_row'])
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{event_title} - Left leg</name>
                    <description><![CDATA[{left_description}]]></description>
                    <Snippet maxLines="0"></Snippet>
        ''')
        
        placemark += self.create_placemark_temporal_elements(
            event_metadata, COMPONENT_TYPES['left_leg'], "            "
        )
        
        placemark += textwrap.dedent(f'''\
                    <styleUrl>{self.style_url('leg-line')}</styleUrl>
                    <LineString>
                        <coordinates>
                            {self.format_source_coord_triplet(lon_source_text if lon_source_text is not None else lon, lat_source_text if lat_source_text is not None else lat)}
                            {self.format_coord_triplet(left_lon, left_lat)}
                        </coordinates>
                    </LineString>
                </Placemark>
        ''')
        
        # Right directional line
        right_lat, right_lon = self.destination_point(lat, lon, end_angle, leg_length)
        right_description = self.build_description_table([
            ('Cell Site', source_pair),
            ('Azimuth', f"{azimuth}°"),
            ('Leg Direction', f"{end_angle:.2f}°"),
            ('Leg Length', f"{leg_length} miles"),
        ], event_metadata['source_row'])
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{event_title} - Right leg</name>
                    <description><![CDATA[{right_description}]]></description>
                    <Snippet maxLines="0"></Snippet>
        ''')
        
        placemark += self.create_placemark_temporal_elements(
            event_metadata, COMPONENT_TYPES['right_leg'], "            "
        )
        
        placemark += textwrap.dedent(f'''\
                    <styleUrl>{self.style_url('leg-line')}</styleUrl>
                    <LineString>
                        <coordinates>
                            {self.format_source_coord_triplet(lon_source_text if lon_source_text is not None else lon, lat_source_text if lat_source_text is not None else lat)}
                            {self.format_coord_triplet(right_lon, right_lat)}
                        </coordinates>
                    </LineString>
                </Placemark>
            </Folder>
        ''')
        
        return placemark
    
    def create_circle_placemark(self, lat, lon, event_metadata,
                                lat_source_text=None, lon_source_text=None):
        """Create a circular visualization placemark"""
        event_title = event_metadata['title']
        time_range = event_metadata['time_range']
        source_pair = self.source_coord_pair_text(
            lat, lon, lat_source_text, lon_source_text
        )
        circle_description = self.build_description_table([
            ('Cell Site', source_pair),
            ('Visualization Radius', f"{self.settings['shaded_area_length']} miles"),
            ('Reason', 'Azimuth not available; using 360° visualization circle'),
        ], event_metadata['source_row'])
        
        # Create folder to group circle and center label
        placemark = textwrap.dedent(f'''\
            <Folder>
                <name>{event_title}</name>
                <visibility>0</visibility>
        ''')
        
        # Add timestamp if successfully parsed and time animation is enabled
        placemark += self.create_time_element(time_range)
        
        # 1. Create the circle
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{event_title}</name>
                    <description><![CDATA[{circle_description}]]></description>
                    <Snippet maxLines="0"></Snippet>
        ''')
        
        placemark += self.create_placemark_temporal_elements(
            event_metadata, COMPONENT_TYPES['coverage_circle'], "            "
        )
        
        placemark += textwrap.dedent(f'''\
                    <styleUrl>{self.style_url('tower-area')}</styleUrl>
                    <Polygon>
                        <outerBoundaryIs><LinearRing><coordinates>
        ''')
        
        # Generate circle points
        for i in range(37):  # 0 to 360 degrees, every 10 degrees
            angle = i * 10
            arc_lat, arc_lon = self.destination_point(lat, lon, angle, self.settings['shaded_area_length'])
            placemark += f"                            {self.format_coord_triplet(arc_lon, arc_lat)}\n"
        
        placemark += textwrap.dedent(f'''\
                        </coordinates></LinearRing></outerBoundaryIs>
                    </Polygon>
                </Placemark>
        
                <Placemark>
                    <name>{event_title}</name>
        ''')
        
        placemark += self.create_placemark_temporal_elements(
            event_metadata, COMPONENT_TYPES['center_point'], "            "
        )
        
        placemark += textwrap.dedent(f'''\
                    <styleUrl>{self.style_url('hidden-center')}</styleUrl>
                    <Point>
                        <coordinates>{self.format_source_coord_triplet(lon_source_text if lon_source_text is not None else lon, lat_source_text if lat_source_text is not None else lat)}</coordinates>
                    </Point>
                </Placemark>
            </Folder>
        ''')
        
        return placemark
    
    def create_pin_placemark(self, lat, lon, color, event_metadata):
        """Create a pin placemark"""
        event_title = event_metadata['title']
        
        placemark = textwrap.dedent(f'''\
            <Placemark>
                <name>{event_title}</name>
        ''')
        
        # Add timestamp if successfully interpreted and time animation is enabled
        placemark += self.create_placemark_temporal_elements(
            event_metadata, COMPONENT_TYPES['location_point']
        )
        
        placemark += textwrap.dedent(f'''\
                <styleUrl>{self.style_url('pin-default')}</styleUrl>
                <Point>
                    <coordinates>{self.format_source_coord_triplet(lon, lat)}</coordinates>
                </Point>
            </Placemark>
        ''')
        
        return placemark
    
    def create_combined_sector_and_arc(self, lat, lon, azimuth, distance_miles,
                                       event_metadata, lat_source_text=None,
                                       lon_source_text=None):
        """Create combined site/sector visualization with distance arc in a single folder"""
        event_title = event_metadata['title']
        time_range = event_metadata['time_range']
        source_pair = self.source_coord_pair_text(
            lat, lon, lat_source_text, lon_source_text
        )
        
        # Get settings
        azimuth_spread = self.settings.get('azimuth_spread', 120)
        half_spread = azimuth_spread / 2
        leg_length = self.settings.get('leg_length', 3.0)
        shaded_area_length = self.settings.get('shaded_area_length', 1.0)
        band_thickness_before = self.settings.get('band_thickness_before', 0.0)
        band_thickness = self.settings.get('band_thickness', 0.0)
        band_units = self.settings.get('band_thickness_units', 'Meters')
        band_thickness_before_miles = self.convert_ta_distance_to_miles(band_thickness_before, band_units)
        band_thickness_miles = self.convert_ta_distance_to_miles(band_thickness, band_units)
        band_area_sq_miles = self.calculate_band_area_sq_miles(
            distance_miles,
            azimuth_spread,
            band_thickness_before_miles,
            band_thickness_miles
        )
        
        # Calculate start and end angles for the sector
        start_angle = azimuth - half_spread
        end_angle = azimuth + half_spread
        
        # Create single folder for both sector and arc
        placemark = textwrap.dedent(f'''\
            <Folder>
                <name>{event_title}</name>
                <visibility>0</visibility>
        ''')
        
        # Add timestamp for time animation
        placemark += self.create_time_element(time_range)

        description_html = self.build_description_table([
            ('Cell Site', source_pair),
            ('Azimuth', f"{azimuth}°"),
            ('Sector Width', f"{azimuth_spread}°"),
            ('Distance', f"{distance_miles:.2f} miles"),
            ('Band Area', f"{band_area_sq_miles:.2f} sq mi"),
            ('Band Inner Width', f"{band_thickness_before} {band_units}"),
            ('Band Outer Width', f"{band_thickness} {band_units}"),
        ], event_metadata['source_row'])
        
        # 1. Create the shaded sector wedge
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{event_title}</name>
                    <description><![CDATA[{description_html}]]></description>
                    <Snippet maxLines="0"></Snippet>
        ''')
        
        placemark += self.create_placemark_temporal_elements(
            event_metadata, COMPONENT_TYPES['tower_sector'], "            "
        )
        
        placemark += textwrap.dedent(f'''\
                    <styleUrl>{self.style_url('tower-area')}</styleUrl>
                    <Polygon>
                        <outerBoundaryIs>
                            <LinearRing>
                                <coordinates>
                                    {self.format_source_coord_triplet(lon_source_text if lon_source_text is not None else lon, lat_source_text if lat_source_text is not None else lat)}
        ''')
        
        # Generate arc points for the sector wedge
        num_points = self.settings.get('num_points', 20)
        for i in range(num_points + 1):
            angle = start_angle + (i / num_points) * azimuth_spread
            arc_lat, arc_lon = self.destination_point(lat, lon, angle, shaded_area_length)
            placemark += f"                                    {self.format_coord_triplet(arc_lon, arc_lat)}\n"
        
        placemark += textwrap.dedent(f'''\
                                    {self.format_source_coord_triplet(lon_source_text if lon_source_text is not None else lon, lat_source_text if lat_source_text is not None else lat)}
                                </coordinates>
                            </LinearRing>
                        </outerBoundaryIs>
                    </Polygon>
                </Placemark>
        ''')
        
        # 2. Create left directional line
        left_lat, left_lon = self.destination_point(lat, lon, start_angle, leg_length)
        left_description = self.build_description_table([
            ('Cell Site', source_pair),
            ('Azimuth', f"{azimuth}°"),
            ('Leg Direction', f"{start_angle:.2f}°"),
            ('Leg Length', f"{leg_length} miles"),
            ('Distance', f"{distance_miles:.2f} miles"),
        ], event_metadata['source_row'])
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{event_title} - Left leg</name>
                    <description><![CDATA[{left_description}]]></description>
                    <Snippet maxLines="0"></Snippet>
        ''')
        
        placemark += self.create_placemark_temporal_elements(
            event_metadata, COMPONENT_TYPES['left_leg'], "            "
        )
        
        placemark += textwrap.dedent(f'''\
                    <styleUrl>{self.style_url('leg-line')}</styleUrl>
                    <LineString>
                        <coordinates>
                            {self.format_source_coord_triplet(lon_source_text if lon_source_text is not None else lon, lat_source_text if lat_source_text is not None else lat)}
                            {self.format_coord_triplet(left_lon, left_lat)}
                        </coordinates>
                    </LineString>
                </Placemark>
        ''')
        
        # 3. Create right directional line
        right_lat, right_lon = self.destination_point(lat, lon, end_angle, leg_length)
        right_description = self.build_description_table([
            ('Cell Site', source_pair),
            ('Azimuth', f"{azimuth}°"),
            ('Leg Direction', f"{end_angle:.2f}°"),
            ('Leg Length', f"{leg_length} miles"),
            ('Distance', f"{distance_miles:.2f} miles"),
        ], event_metadata['source_row'])
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{event_title} - Right leg</name>
                    <description><![CDATA[{right_description}]]></description>
                    <Snippet maxLines="0"></Snippet>
        ''')
        
        placemark += self.create_placemark_temporal_elements(
            event_metadata, COMPONENT_TYPES['right_leg'], "            "
        )
        
        placemark += textwrap.dedent(f'''\
                    <styleUrl>{self.style_url('leg-line')}</styleUrl>
                    <LineString>
                        <coordinates>
                            {self.format_source_coord_triplet(lon_source_text if lon_source_text is not None else lon, lat_source_text if lat_source_text is not None else lat)}
                            {self.format_coord_triplet(right_lon, right_lat)}
                        </coordinates>
                    </LineString>
                </Placemark>
        ''')
        
        # 4. Create the distance band (instead of arc line)
        band_placemark = self.create_sector_distance_band(
            lat, lon, distance_miles, start_angle, end_angle, event_metadata,
            lat_source_text, lon_source_text
        )
        placemark += textwrap.indent(band_placemark, "        ")
        
        # 5. Add invisible center point label to show timestamp
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{event_title}</name>
                    <description><![CDATA[{self.build_description_table([('Cell Site', source_pair), ('Distance', f"{distance_miles:.2f} miles")], event_metadata['source_row'])}]]></description>
                    <Snippet maxLines="0"></Snippet>
        ''')
        
        placemark += self.create_placemark_temporal_elements(
            event_metadata, COMPONENT_TYPES['center_point'], "            "
        )
        
        placemark += textwrap.dedent(f'''\
                    <styleUrl>{self.style_url('hidden-center')}</styleUrl>
                    <Point>
                        <coordinates>{self.format_source_coord_triplet(lon_source_text if lon_source_text is not None else lon, lat_source_text if lat_source_text is not None else lat)}</coordinates>
                    </Point>
                </Placemark>
            </Folder>
        ''')
        
        return placemark
    
    def create_sector_distance_band(self, lat, lon, distance_miles, start_angle, end_angle,
                                    event_metadata, lat_source_text=None,
                                    lon_source_text=None):
        """Create a band polygon constrained to a sector wedge (for Case 1: azimuth + distance)"""
        event_title = event_metadata['title']
        band_thickness_before = self.settings.get('band_thickness_before', 0.0)
        band_thickness = self.settings.get('band_thickness', 0.0)
        band_units = self.settings.get('band_thickness_units', 'Meters')
        # Convert band thicknesses to miles
        band_thickness_before_miles = self.convert_ta_distance_to_miles(band_thickness_before, band_units)
        band_thickness_miles = self.convert_ta_distance_to_miles(band_thickness, band_units)
        
        # Calculate inner and outer distances
        inner_distance_miles = max(distance_miles - band_thickness_before_miles, 0.0)
        outer_distance_miles = distance_miles + band_thickness_miles
        
        # Create inner and outer arc coordinates for the sector band
        inner_coords = []
        outer_coords = []
        
        # Get settings for calculation
        num_points = self.settings.get('num_points', 20)
        
        # Generate points along the sector (from start_angle to end_angle)
        for i in range(num_points + 1):
            angle = start_angle + (i / num_points) * (end_angle - start_angle)
            inner_point = self.destination_point(lat, lon, angle, inner_distance_miles)
            outer_point = self.destination_point(lat, lon, angle, outer_distance_miles)
            inner_coords.append(self.format_coord_triplet(inner_point[1], inner_point[0]))
            outer_coords.append(self.format_coord_triplet(outer_point[1], outer_point[0]))
        
        # Create the sector band polygon: inner arc + outer arc (reverse) + closing edges
        # Order: start on inner arc, go to end, then outer arc back to start
        band_coords = inner_coords + list(reversed(outer_coords)) + [inner_coords[0]]
        coordinates_string = ' '.join(band_coords)
        
        placemark = textwrap.dedent(f'''
            <Placemark>
                <name>{event_title} - Distance band</name>
                <description><![CDATA[{self.build_description_table([
                    ('Cell Site', self.source_coord_pair_text(lat, lon, lat_source_text, lon_source_text)),
                    ('Azimuth Span', f"{start_angle:.2f}° to {end_angle:.2f}°"),
                    ('Distance', f"{distance_miles:.2f} miles"),
                    ('Band Inner', f"{inner_distance_miles:.2f} miles"),
                    ('Band Outer', f"{outer_distance_miles:.2f} miles"),
                ], event_metadata['source_row'])}]]></description>
                <Snippet maxLines="0"></Snippet>
        ''')

        placemark += self.create_placemark_temporal_elements(
            event_metadata, COMPONENT_TYPES['distance_band'], "        "
        )

        placemark += textwrap.dedent(f'''
                <styleUrl>{self.style_url('distance-band')}</styleUrl>
                <Polygon>
                    <outerBoundaryIs>
                        <LinearRing>
                            <coordinates>
{textwrap.indent(coordinates_string, " " * 32)}
                            </coordinates>
                        </LinearRing>
                    </outerBoundaryIs>
                </Polygon>
            </Placemark>
        ''')
        
        # Add a black line at the exact reported distance
        reported_coords = []
        for i in range(num_points + 1):
            angle = start_angle + (i / num_points) * (end_angle - start_angle)
            rpt = self.destination_point(lat, lon, angle, distance_miles)
            reported_coords.append(self.format_coord_triplet(rpt[1], rpt[0]))
        reported_coords_string = ' '.join(reported_coords)
        
        placemark += textwrap.dedent(f'''
            <Placemark>
                <name>{event_title} - Reported distance</name>
                <description><![CDATA[{self.build_description_table([
                    ('Cell Site', self.source_coord_pair_text(lat, lon, lat_source_text, lon_source_text)),
                    ('Azimuth Span', f"{start_angle:.2f}° to {end_angle:.2f}°"),
                    ('Reported Distance', f"{distance_miles:.2f} miles"),
                ], event_metadata['source_row'])}]]></description>
                <Snippet maxLines="0"></Snippet>
        ''')

        placemark += self.create_placemark_temporal_elements(
            event_metadata, COMPONENT_TYPES['reported_distance'], "        "
        )

        placemark += textwrap.dedent(f'''
                <styleUrl>{self.style_url('reported-distance')}</styleUrl>
                <LineString>
                    <coordinates>
{textwrap.indent(reported_coords_string, " " * 24)}
                    </coordinates>
                </LineString>
            </Placemark>
        ''')
        
        return placemark
    
    def create_distance_band(self, lat, lon, distance_miles, event_metadata,
                             lat_source_text=None, lon_source_text=None):
        """Create a band polygon at the distance from site (inner arc + outer arc + edges)"""
        event_title = event_metadata['title']
        time_range = event_metadata['time_range']
        source_pair = self.source_coord_pair_text(
            lat, lon, lat_source_text, lon_source_text
        )
        
        band_thickness_before = self.settings.get('band_thickness_before', 0.0)
        band_thickness = self.settings.get('band_thickness', 0.0)
        band_units = self.settings.get('band_thickness_units', 'Meters')
        # Convert band thicknesses to miles
        band_thickness_before_miles = self.convert_ta_distance_to_miles(band_thickness_before, band_units)
        band_thickness_miles = self.convert_ta_distance_to_miles(band_thickness, band_units)
        
        # Calculate inner and outer distances
        inner_distance_miles = max(distance_miles - band_thickness_before_miles, 0.0)
        outer_distance_miles = distance_miles + band_thickness_miles
        
        # Create inner and outer arc coordinates for the band
        inner_coords = []
        outer_coords = []
        
        # Generate 37 points around the circle (every 10 degrees, 0-360)
        reported_coords = []
        for bearing in range(0, 361, 10):
            inner_point = self.destination_point(lat, lon, bearing, inner_distance_miles)
            outer_point = self.destination_point(lat, lon, bearing, outer_distance_miles)
            reported_point = self.destination_point(lat, lon, bearing, distance_miles)
            inner_coords.append(self.format_coord_triplet(inner_point[1], inner_point[0]))
            outer_coords.append(self.format_coord_triplet(outer_point[1], outer_point[0]))
            reported_coords.append(self.format_coord_triplet(reported_point[1], reported_point[0]))
        reported_coords_string = ' '.join(reported_coords)
        
        # Create the band polygon: inner arc + outer arc (reverse) + closing point
        # The ring must close, so we go: inner_start -> inner_end -> outer_end -> outer_start -> inner_start
        band_coords = inner_coords + list(reversed(outer_coords)) + [inner_coords[0]]
        coordinates_string = ' '.join(band_coords)
        
        placemark = textwrap.dedent(f'''\
            <Folder>
                <name>{event_title}</name>
                <visibility>0</visibility>
        ''')
        
        # Add time element on the folder
        placemark += self.create_time_element(time_range)
        
        # Band polygon placemark
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{event_title}</name>
                    <description><![CDATA[{self.build_description_table([
                        ('Cell Site', source_pair),
                        ('Reported Distance', f"{distance_miles:.2f} miles"),
                        ('Band Inner', f"{inner_distance_miles:.2f} miles"),
                        ('Band Outer', f"{outer_distance_miles:.2f} miles"),
                    ], event_metadata['source_row'])}]]></description>
                    <Snippet maxLines="0"></Snippet>
        ''')
        
        placemark += self.create_placemark_temporal_elements(
            event_metadata, COMPONENT_TYPES['distance_band'], "            "
        )
        
        placemark += textwrap.dedent(f'''\
                    <styleUrl>{self.style_url('distance-band')}</styleUrl>
                    <Polygon>
                        <outerBoundaryIs>
                            <LinearRing>
                                <coordinates>
{textwrap.indent(coordinates_string, " " * 32)}
                                </coordinates>
                            </LinearRing>
                        </outerBoundaryIs>
                    </Polygon>
                </Placemark>
        ''')
        
        # Reported distance line placemark
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{event_title} - Reported distance</name>
                    <description><![CDATA[{self.build_description_table([
                        ('Cell Site', source_pair),
                        ('Reported Distance', f"{distance_miles:.2f} miles"),
                    ], event_metadata['source_row'])}]]></description>
                    <Snippet maxLines="0"></Snippet>
        ''')
        
        placemark += self.create_placemark_temporal_elements(
            event_metadata, COMPONENT_TYPES['reported_distance'], "            "
        )
        
        placemark += textwrap.dedent(f'''\
                    <styleUrl>{self.style_url('reported-distance')}</styleUrl>
                    <LineString>
                        <coordinates>
{textwrap.indent(reported_coords_string, ' ' * 28)}
                        </coordinates>
                    </LineString>
                </Placemark>
        ''')
        
        # Center point placemark
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{event_title}</name>
                    <description><![CDATA[{self.build_description_table([
                        ('Cell Site', source_pair),
                        ('Reported Distance', f"{distance_miles:.2f} miles"),
                    ], event_metadata['source_row'])}]]></description>
                    <Snippet maxLines="0"></Snippet>
        ''')
        
        placemark += self.create_placemark_temporal_elements(
            event_metadata, COMPONENT_TYPES['center_point'], "            "
        )
        
        placemark += textwrap.dedent(f'''\
                    <styleUrl>{self.style_url('distance-center')}</styleUrl>
                    <Point>
                        <coordinates>{self.format_source_coord_triplet(lon_source_text if lon_source_text is not None else lon, lat_source_text if lat_source_text is not None else lat)}</coordinates>
                    </Point>
                </Placemark>
            </Folder>
        ''')
        
        return placemark
    
    def convert_ta_distance_to_miles(self, distance, units):
        """Convert distance from site distance to miles based on user-selected units"""
        distance_float = float(distance)
        if not math.isfinite(distance_float) or distance_float < 0:
            raise ValueError("Distance must be a non-negative finite number")

        if units == "Meters":
            return distance_float / 1609.34  # meters to miles
        elif units == "Feet":
            return distance_float / 5280  # feet to miles
        elif units == "Miles":
            return distance_float  # already in miles
        elif units == "Kilometers":
            return distance_float / 1.60934  # kilometers to miles
        else:
            # Default to meters if unknown unit
            return distance_float / 1609.34
