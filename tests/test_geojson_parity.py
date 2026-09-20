"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from kml_generator import KMLGenerator
from main_window import MainWindow


KML_NAMESPACE = {'kml': 'http://www.opengis.net/kml/2.2'}


def generator_settings():
    return {
        'enable_time_animation': True,
        'duration_minutes': 30,
        'source_utc_offset_minutes': 0,
        'source_timezone_name': None,
        'source_date_order': 'MDY',
        'azimuth_spread': 120,
        'leg_length': 3.0,
        'shaded_area_length': 1.0,
        'band_thickness_before': 0.0,
        'band_thickness': 0.1,
        'band_thickness_units': 'Miles',
        'ta_distance_units': 'Miles',
        'gps_units': 'Meters',
        'default_accuracy': 100,
        'band_color': 'ff0099ff',
        'leg_color': 'ffffffff',
        'shaded_color': 'ff00ff00',
        'gps_color': 'ff00ffff',
        'num_points': 5,
        'consolidate_event_placemarks': True,
    }


def parse_kml_extended_data(node):
    return {
        item.get('name'): item.findtext('kml:value', namespaces=KML_NAMESPACE)
        for item in node.findall('kml:ExtendedData/kml:Data', KML_NAMESPACE)
    }


def kml_primitive_counts_by_event(kml_text):
    root = ET.fromstring(kml_text)
    counts = {}

    for placemark in root.findall('.//kml:Placemark', KML_NAMESPACE):
        metadata = parse_kml_extended_data(placemark)
        event_id = metadata.get('osloc_event_id')
        dataset_id = metadata.get('osloc_dataset_id')
        if not event_id or not dataset_id:
            continue

        key = f"{dataset_id}::{event_id}"
        if key not in counts:
            counts[key] = {'Polygon': 0, 'LineString': 0, 'Point': 0}

        counts[key]['Polygon'] += len(placemark.findall('kml:Polygon', KML_NAMESPACE))
        counts[key]['LineString'] += len(placemark.findall('kml:LineString', KML_NAMESPACE))
        counts[key]['Point'] += len(placemark.findall('kml:Point', KML_NAMESPACE))

        for mg in placemark.findall('kml:MultiGeometry', KML_NAMESPACE):
            counts[key]['Polygon'] += len(mg.findall('kml:Polygon', KML_NAMESPACE))
            counts[key]['LineString'] += len(mg.findall('kml:LineString', KML_NAMESPACE))
            counts[key]['Point'] += len(mg.findall('kml:Point', KML_NAMESPACE))

    return counts


def geojson_primitive_counts_by_event(geojson_text):
    payload = json.loads(geojson_text)
    counts = {}

    for feature in payload.get('features', []):
        props = feature.get('properties', {})
        key = props.get('osloc_event_key')
        if not key:
            dataset_id = props.get('osloc_dataset_id')
            event_id = props.get('osloc_event_id')
            if dataset_id and event_id:
                key = f"{dataset_id}::{event_id}"
        if not key:
            continue

        if key not in counts:
            counts[key] = {'Polygon': 0, 'LineString': 0, 'Point': 0}

        geometry_type = feature.get('geometry', {}).get('type')
        if geometry_type in counts[key]:
            counts[key][geometry_type] += 1

    return counts


class GeoJSONParityTests(unittest.TestCase):
    def test_geojson_preserves_source_coordinate_precision_text(self):
        dataframe = pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': '43.158310000123',
            'Longitude': '-77.609380000987',
            'Azimuth': 240,
        }])

        generator = KMLGenerator('', 'Tower/Sector', generator_settings())
        geojson_text = generator.generate_cell_tower_geojson(dataframe)
        payload = json.loads(geojson_text)

        self.assertTrue(payload['features'])
        source_props = payload['features'][0]['properties']
        self.assertEqual('43.158310000123', source_props['osloc_source_latitude'])
        self.assertEqual('-77.609380000987', source_props['osloc_source_longitude'])
        self.assertEqual(
            '43.158310000123, -77.609380000987',
            source_props['osloc_source_coordinate_text']
        )
        self.assertIn('osloc_style_leg_color', source_props)
        self.assertIn('osloc_style_shaded_color', source_props)
        self.assertIn('osloc_style_band_color', source_props)
        self.assertIn('osloc_style_gps_line_color', source_props)
        self.assertIn('osloc_style_gps_fill_color', source_props)
        self.assertEqual('rgba(255, 255, 255, 1)', source_props['osloc_style_leg_color_rgba'])
        self.assertEqual('rgba(0, 255, 0, 0.49)', source_props['osloc_style_shaded_color_rgba'])
        self.assertEqual('rgba(255, 153, 0, 0.49)', source_props['osloc_style_band_color_rgba'])

        expected_start = int(
            datetime(2024, 1, 15, 14, tzinfo=timezone.utc).timestamp() * 1000
        )
        for feature in payload['features']:
            properties = feature['properties']
            self.assertEqual('2', properties['osloc_source_row'])
            self.assertEqual('2024-01-15T14:00:00Z', properties['osloc_start_time'])
            self.assertEqual(expected_start, properties['osloc_start_epoch_ms'])
            self.assertEqual(expected_start + 30 * 60 * 1000, properties['osloc_end_epoch_ms'])
        self.assertTrue(any(
            '<b>Source Row:</b>' in feature['properties'].get('description', '')
            for feature in payload['features']
        ))

    def test_distance_output_has_event_and_primitive_parity_with_kml(self):
        dataframe = pd.DataFrame([
            {
                'Timestamp': '2024-01-15T14:00:00Z',
                'Latitude': 43.15,
                'Longitude': -77.61,
                'Azimuth': 240,
                'Distance': 2.0,
            },
            {
                'Timestamp': '2024-01-15T14:15:00Z',
                'Latitude': 43.151,
                'Longitude': -77.611,
                'Azimuth': None,
                'Distance': 1.25,
            },
        ])

        generator = KMLGenerator('', 'Distance from Tower', generator_settings())
        kml_text = generator.generate_distance_from_tower_kml(dataframe)
        geojson_text = generator.generate_distance_from_tower_geojson(dataframe)

        kml_counts = kml_primitive_counts_by_event(kml_text)
        geojson_counts = geojson_primitive_counts_by_event(geojson_text)

        self.assertEqual(set(kml_counts.keys()), set(geojson_counts.keys()))
        self.assertEqual(kml_counts, geojson_counts)

    def test_run_reuses_dataset_metadata_for_kml_and_geojson(self):
        dataframe = pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': 43.15,
            'Longitude': -77.61,
            'Accuracy': 120,
        }])

        generator = KMLGenerator('', 'Location Point', generator_settings(), dataframe=dataframe)
        captured = {}

        generator.finished.connect(lambda payload: captured.update(payload))
        generator.run()

        self.assertIn('kml', captured)
        self.assertIn('geojson', captured)

        root = ET.fromstring(captured['kml'])
        document = root.find('kml:Document', KML_NAMESPACE)
        document_metadata = parse_kml_extended_data(document)

        payload = json.loads(captured['geojson'])
        self.assertEqual(document_metadata['osloc_dataset_id'], payload['osloc_dataset_id'])
        self.assertEqual(document_metadata['osloc_dataset_name'], payload['osloc_dataset_name'])

    def test_geojson_retains_hidden_and_visible_point_records(self):
        distance_data = pd.DataFrame([
            {
                'Timestamp': '2024-01-15T14:00:00Z',
                'Latitude': 43.15,
                'Longitude': -77.61,
                'Azimuth': 240,
                'Distance': 2.0,
            },
            {
                'Timestamp': '2024-01-15T14:05:00Z',
                'Latitude': 43.151,
                'Longitude': -77.611,
                'Azimuth': None,
                'Distance': 1.0,
            },
            {
                'Timestamp': '2024-01-15T14:10:00Z',
                'Latitude': 43.152,
                'Longitude': -77.612,
                'Azimuth': None,
                'Distance': None,
            },
        ])
        generator = KMLGenerator('', 'Distance from Tower', generator_settings())
        distance_payload = json.loads(
            generator.generate_distance_from_tower_geojson(distance_data)
        )

        point_pairs = {
            (
                feature['properties']['osloc_event_type'],
                feature['properties']['osloc_component_type'],
            )
            for feature in distance_payload['features']
            if feature['geometry']['type'] == 'Point'
        }
        self.assertIn(('tower_sector_distance', 'center_point'), point_pairs)
        self.assertIn(('distance_only', 'center_point'), point_pairs)
        self.assertIn(('tower_no_azimuth', 'center_point'), point_pairs)

        location_data = pd.DataFrame([
            {
                'Timestamp': '2024-01-15T14:00:00Z',
                'Latitude': 43.15,
                'Longitude': -77.61,
                'Accuracy': 100,
            },
            {
                'Timestamp': '2024-01-15T14:05:00Z',
                'Latitude': 43.151,
                'Longitude': -77.611,
                'Accuracy': 'invalid',
            },
        ])
        location_payload = json.loads(generator.generate_gps_geojson(location_data))
        location_pairs = {
            (
                feature['properties']['osloc_event_type'],
                feature['properties']['osloc_component_type'],
            )
            for feature in location_payload['features']
            if feature['geometry']['type'] == 'Point'
        }
        self.assertIn(('location_accuracy', 'location_point'), location_pairs)
        self.assertIn(('location', 'location_point'), location_pairs)


class DualOutputTests(unittest.TestCase):
    def test_required_kml_and_geojson_siblings_are_written_together(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / 'result.kml'
            kml_path, geojson_path = MainWindow.write_visualization_outputs(
                output_path,
                '<kml/>',
                '{"type":"FeatureCollection","features":[]}',
            )

            self.assertEqual('<kml/>', kml_path.read_text(encoding='utf-8'))
            self.assertEqual(
                '{"type":"FeatureCollection","features":[]}',
                geojson_path.read_text(encoding='utf-8'),
            )

    def test_missing_geojson_does_not_write_kml_only_output(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / 'result.kml'

            with self.assertRaisesRegex(ValueError, 'GeoJSON'):
                MainWindow.write_visualization_outputs(output_path, '<kml/>', '')

            self.assertFalse(output_path.exists())
            self.assertFalse(output_path.with_suffix('.geojson').exists())


if __name__ == '__main__':
    unittest.main()
