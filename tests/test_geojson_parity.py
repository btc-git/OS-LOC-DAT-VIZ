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
    def test_unknown_accuracy_exports_visible_points_without_circles(self):
        for default_accuracy in (None, 0, 100):
            for supplied_accuracy in (None, 0, '0', 'invalid', 25):
                for flattened in (False, True):
                    with self.subTest(
                        default=default_accuracy, supplied=supplied_accuracy,
                        flattened=flattened,
                    ):
                        settings = generator_settings()
                        if default_accuracy is None:
                            settings.pop('default_accuracy')
                        else:
                            settings['default_accuracy'] = default_accuracy
                        settings['flatten_event_folders'] = flattened
                        records = pd.DataFrame([{
                            'Timestamp': '2024-01-15T14:00:00Z',
                            'Latitude': '43.123456789',
                            'Longitude': '-77.123456789',
                            'Accuracy': supplied_accuracy,
                        }])
                        generator = KMLGenerator('', 'Location Point', settings)
                        messages = []
                        generator.status_message.connect(messages.append)
                        kml = generator.generate_gps_kml(records)
                        payload = json.loads(generator.generate_gps_geojson(records))
                        has_circle = (
                            supplied_accuracy == 25
                            or (supplied_accuracy is None and default_accuracy == 100)
                        )
                        self.assertEqual(
                            kml_primitive_counts_by_event(kml),
                            geojson_primitive_counts_by_event(json.dumps(payload)),
                        )
                        root = ET.fromstring(kml)
                        self.assertEqual(
                            int(has_circle),
                            len(root.findall('.//kml:Polygon', KML_NAMESPACE)),
                        )
                        if has_circle:
                            continue
                        self.assertEqual(1, len(payload['features']))
                        feature = payload['features'][0]
                        self.assertEqual('Point', feature['geometry']['type'])
                        self.assertEqual(
                            [-77.123456789, 43.123456789, 0],
                            feature['geometry']['coordinates'],
                        )
                        props = feature['properties']
                        self.assertEqual('location', props['osloc_event_type'])
                        self.assertEqual('location_point', props['osloc_component_type'])
                        self.assertEqual(
                            settings['gps_color'], props['osloc_style_gps_line_color']
                        )
                        point = next(
                            placemark for placemark in
                            root.findall('.//kml:Placemark', KML_NAMESPACE)
                            if placemark.find('kml:Point', KML_NAMESPACE) is not None
                        )
                        style_id = point.findtext(
                            'kml:styleUrl', namespaces=KML_NAMESPACE
                        )[1:]
                        style = root.find(
                            f".//kml:Style[@id='{style_id}']", KML_NAMESPACE
                        )
                        self.assertEqual(
                            '1', style.findtext(
                                'kml:IconStyle/kml:scale', namespaces=KML_NAMESPACE
                            ),
                        )
                        self.assertTrue(messages)
                        if supplied_accuracy != 'invalid':
                            self.assertIn('Unknown', props['description'])
                            self.assertTrue(any(
                                'accuracy unknown' in message for message in messages
                            ))

    def test_site_terminology_in_visible_exports_preserves_schema_identifiers(self):
        records = pd.DataFrame([
            {
                'Timestamp': '2024-01-15T14:00:00Z',
                'Latitude': '43.123456789', 'Longitude': '-77.123456789',
                'Azimuth': azimuth, 'Distance': distance,
            }
            for azimuth, distance in ((90, 2), (90, None), (None, 2), (None, None))
        ])
        cases = (
            (
                'Tower/Sector', 'generate_cell_tower_kml',
                'generate_cell_tower_geojson', 'Cell Site/Sector Data',
                {'tower_sector', 'tower_no_azimuth'},
            ),
            (
                'Distance from Tower', 'generate_distance_from_tower_kml',
                'generate_distance_from_tower_geojson',
                'Distance from Cell Site Analysis',
                {'tower_sector_distance', 'tower_sector', 'distance_only',
                 'tower_no_azimuth'},
            ),
        )
        for data_type, kml_method, json_method, name, event_types in cases:
            for consolidated in (False, True):
                for flattened in (False, True):
                    with self.subTest(
                        data_type=data_type, consolidated=consolidated,
                        flattened=flattened,
                    ):
                        settings = generator_settings()
                        settings['consolidate_event_placemarks'] = consolidated
                        settings['flatten_event_folders'] = flattened
                        generator = KMLGenerator('', data_type, settings)
                        warnings = []
                        generator.status_message.connect(warnings.append)
                        root = ET.fromstring(getattr(generator, kml_method)(records))
                        payload = json.loads(getattr(generator, json_method)(records))
                        self.assertEqual(name, payload['osloc_dataset_name'])
                        self.assertEqual(
                            name,
                            root.findtext('kml:Document/kml:name',
                                          namespaces=KML_NAMESPACE),
                        )
                        for node in root.findall('.//kml:name', KML_NAMESPACE):
                            self.assertNotIn('tower', (node.text or '').lower())
                        for node in root.findall('.//kml:description', KML_NAMESPACE):
                            self.assertNotIn('tower', (node.text or '').lower())
                        properties = [
                            feature['properties'] for feature in payload['features']
                        ]
                        self.assertEqual(
                            event_types,
                            {item['osloc_event_type'] for item in properties},
                        )
                        for item in properties:
                            for key in ('name', 'description', 'osloc_event_label',
                                        'osloc_dataset_name'):
                                self.assertNotIn(
                                    'tower', str(item.get(key, '')).lower()
                                )
                        descriptions = [
                            node.text or ''
                            for node in root.findall('.//kml:description', KML_NAMESPACE)
                        ]
                        self.assertTrue(any('<b>Cell Site:</b>' in text for text in descriptions))
                        self.assertTrue(any(
                            '<b>Cell Site:</b>' in item.get('description', '')
                            for item in properties
                        ))
                        self.assertTrue(warnings)
                        self.assertNotIn('tower', '\n'.join(warnings).lower())
                        self.assertEqual(
                            'Event - Cell Site SYNTHETIC-1',
                            generator.create_event_label(
                                'Event', pd.Series({'Tower ID': 'SYNTHETIC-1'})
                            ),
                        )

    def test_outputs_include_preliminary_review_notice(self):
        records = pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': 43.15,
            'Longitude': -77.61,
            'Azimuth': 240,
        }])
        generator = KMLGenerator('', 'Tower/Sector', generator_settings())

        kml_root = ET.fromstring(generator.generate_cell_tower_kml(records))
        geojson_payload = json.loads(
            generator.generate_cell_tower_geojson(records)
        )
        document = kml_root.find('kml:Document', KML_NAMESPACE)
        document_values = parse_kml_extended_data(document)

        self.assertIn(
            'Preliminary visualization only',
            document.findtext('kml:description', namespaces=KML_NAMESPACE),
        )
        self.assertEqual(
            document_values['osloc_review_notice'],
            geojson_payload['osloc_review_notice'],
        )
        self.assertIn(
            'independent expert verification',
            geojson_payload['osloc_review_notice'],
        )

    def test_untimed_timestamp_outcomes_match_between_output_formats(self):
        cases = (
            (
                'Tower/Sector',
                'generate_cell_tower_kml',
                'generate_cell_tower_geojson',
                {'Azimuth': 240},
                4,
            ),
            (
                'Distance from Tower',
                'generate_distance_from_tower_kml',
                'generate_distance_from_tower_geojson',
                {'Azimuth': 240, 'Distance': 2.0},
                4,
            ),
            (
                'Location Point',
                'generate_gps_kml',
                'generate_gps_geojson',
                {'Accuracy': 100},
                4,
            ),
        )

        for data_type, kml_method, geojson_method, fields, event_count in cases:
            with self.subTest(data_type=data_type):
                records = pd.DataFrame([
                    {
                        'Timestamp': '   ',
                        'Latitude': 43.15,
                        'Longitude': -77.61,
                        **fields,
                    },
                    {
                        'Timestamp': 'not a timestamp',
                        'Latitude': 43.16,
                        'Longitude': -77.62,
                        **fields,
                    },
                    {
                        'Timestamp': '2024-01-15T14:00:00+25:00',
                        'Latitude': 43.17,
                        'Longitude': -77.63,
                        **fields,
                    },
                    {
                        'Timestamp': '2024-01-15T14:00:00 trailing text',
                        'Latitude': 43.18,
                        'Longitude': -77.64,
                        **fields,
                    },
                ])
                generator = KMLGenerator('', data_type, generator_settings())

                kml_text = getattr(generator, kml_method)(records)
                geojson_text = getattr(generator, geojson_method)(records)
                kml_counts = kml_primitive_counts_by_event(kml_text)
                geojson_counts = geojson_primitive_counts_by_event(geojson_text)

                self.assertEqual(event_count, len(kml_counts))
                self.assertEqual(kml_counts, geojson_counts)
                self.assertTrue(all(
                    'osloc_start_time' not in feature['properties']
                    for feature in json.loads(geojson_text)['features']
                ))

    def test_all_record_types_retain_unresolved_times_without_inventing_dates(self):
        cases = (
            ('Tower/Sector', 'generate_cell_tower', {'Azimuth': 240}),
            ('Tower/Sector', 'generate_cell_tower', {}),
            ('Distance from Tower', 'generate_distance_from_tower',
             {'Azimuth': 240, 'Distance': 2.0}),
            ('Distance from Tower', 'generate_distance_from_tower', {'Azimuth': 240}),
            ('Distance from Tower', 'generate_distance_from_tower', {'Distance': 2.0}),
            ('Distance from Tower', 'generate_distance_from_tower', {}),
            ('Location Point', 'generate_gps', {'Accuracy': 100}),
            ('Location Point', 'generate_gps', {'Accuracy': 0}),
        )
        timestamps = [
            None, '', '   ', float('nan'), pd.NaT, 'not a timestamp',
            '2024-11-03 01:30:00', '2024-03-10 02:30:00',
            '2024-11-03T01:30:00-04:00', '2024-11-03T01:30:00-05:00',
        ]
        for data_type, method_prefix, fields in cases:
            for consolidated in (False, True):
                with self.subTest(data_type=data_type, fields=fields,
                                  consolidated=consolidated):
                    settings = generator_settings()
                    settings.update({
                        'source_timezone_name': 'America/New_York',
                        'source_header_row': 5,
                        'consolidate_event_placemarks': consolidated,
                    })
                    records = pd.DataFrame([
                        {'Timestamp': timestamp, 'Latitude': '43.15000001',
                         'Longitude': '-77.61000001', **fields}
                        for timestamp in timestamps
                    ])
                    records.loc[len(records)] = {
                        'Timestamp': None, 'Latitude': 999,
                        'Longitude': '-77.61000001', **fields,
                    }
                    generator = KMLGenerator('', data_type, settings)
                    messages = []
                    generator.status_message.connect(messages.append)

                    kml_text = getattr(generator, method_prefix + '_kml')(records)
                    geojson_text = getattr(generator, method_prefix + '_geojson')(records)

                    self.assertEqual(
                        kml_primitive_counts_by_event(kml_text),
                        geojson_primitive_counts_by_event(geojson_text),
                    )
                    self.assertEqual(10, len(kml_primitive_counts_by_event(kml_text)))
                    summary = generator.audit_summary
                    self.assertEqual(11, summary['input_rows'])
                    self.assertEqual(10, summary['generated_rows'])
                    self.assertEqual(8, summary['generated_without_timeline'])
                    self.assertEqual(2, summary['generated_with_dst_conflict'])
                    self.assertEqual(0, summary['skipped_missing_timestamp'])
                    self.assertEqual(0, summary['skipped_dst_conflict'])
                    self.assertEqual(1, summary['skipped_invalid_coordinates'])
                    untimed_warnings = [
                        message for message in messages
                        if 'exported without timeline metadata' in message
                    ]
                    self.assertEqual(1, len(untimed_warnings))
                    self.assertIn('source rows: 6, 7, 8, 9, 10, 11, 12, 13',
                                  untimed_warnings[0])
                    dst_warnings = [
                        message for message in messages
                        if 'daylight-saving transition' in message
                    ]
                    self.assertEqual(1, len(dst_warnings))
                    self.assertIn('source rows: 12, 13', dst_warnings[0])

                    kml_anchors = {
                        metadata['osloc_event_id']: metadata
                        for placemark in ET.fromstring(kml_text).findall(
                            './/kml:Placemark', KML_NAMESPACE
                        )
                        if (metadata := parse_kml_extended_data(placemark)).get(
                            'osloc_event_label'
                        )
                    }
                    geojson_anchors = {
                        properties['osloc_event_id']: properties
                        for feature in json.loads(geojson_text)['features']
                        if (properties := feature['properties']).get('osloc_event_label')
                    }
                    self.assertEqual(kml_anchors.keys(), geojson_anchors.keys())
                    for event_id, metadata in kml_anchors.items():
                        properties = geojson_anchors[event_id]
                        for key, value in metadata.items():
                            self.assertEqual(value, str(properties[key]), key)
                        if int(event_id.split('_')[1]) <= 8:
                            self.assertIn('date/time unavailable',
                                          metadata['osloc_event_label'])
                            self.assertNotIn('osloc_start_time', metadata)
                            self.assertNotIn('osloc_local_start_time', metadata)
                        else:
                            expected_start = (
                                '2024-11-03T05:30:00Z' if event_id == 'event_000009'
                                else '2024-11-03T06:30:00Z'
                            )
                            self.assertEqual(expected_start, metadata['osloc_start_time'])
                    root = ET.fromstring(kml_text)
                    for placemark in root.findall('.//kml:Placemark', KML_NAMESPACE):
                        metadata = parse_kml_extended_data(placemark)
                        if int(metadata['osloc_event_id'].split('_')[1]) <= 8:
                            self.assertIsNone(placemark.find('kml:TimeSpan', KML_NAMESPACE))

    def test_markers_are_exported_for_every_primary_record_type(self):
        marker = {
            'label': 'Reference Point',
            'latitude': 43.1,
            'longitude': -77.1,
            'latitude_text': '43.1',
            'longitude_text': '-77.1',
            'color': '#000000',
            'source_row': None,
        }
        cases = (
            ('Tower/Sector', 'generate_cell_tower_kml',
             'generate_cell_tower_geojson'),
            ('Distance from Tower', 'generate_distance_from_tower_kml',
             'generate_distance_from_tower_geojson'),
            ('Location Point', 'generate_gps_kml', 'generate_gps_geojson'),
        )

        for data_type, kml_method_name, geojson_method_name in cases:
            with self.subTest(data_type=data_type):
                generator = KMLGenerator(
                    '', data_type, generator_settings(), markers=[marker]
                )
                empty_records = pd.DataFrame()
                kml_text = getattr(generator, kml_method_name)(empty_records)
                geojson_payload = json.loads(
                    getattr(generator, geojson_method_name)(empty_records)
                )

                expected_name = {
                    'Tower/Sector': 'Cell Site/Sector Data',
                    'Distance from Tower': 'Distance from Cell Site Analysis',
                    'Location Point': 'Location Point',
                }[data_type]
                self.assertIn(expected_name, kml_text)
                self.assertEqual(
                    1,
                    sum(
                        feature['properties'].get('osloc_event_type') == 'marker'
                        for feature in geojson_payload['features']
                    ),
                )

    def test_markers_are_static_colored_auxiliary_dataset_in_both_formats(self):
        records = pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': '43.100000',
            'Longitude': '-77.100000',
            'Accuracy': 50,
        }])
        markers = [
            {
                'label': 'Residence',
                'latitude': 43.15831,
                'longitude': -77.60938,
                'latitude_text': '43.158310',
                'longitude_text': '-77.609380',
                'color': '#ff0000',
                'source_row': 2,
            },
            {
                'label': 'Meeting Point',
                'latitude': 43.2,
                'longitude': -77.7,
                'latitude_text': '43.2',
                'longitude_text': '-77.7',
                'color': '#3366cc',
                'source_row': None,
            },
        ]
        generator = KMLGenerator(
            '', 'Location Point', generator_settings(), markers=markers
        )

        kml_root = ET.fromstring(generator.generate_gps_kml(records))
        geojson_payload = json.loads(generator.generate_gps_geojson(records))

        folders = kml_root.findall('kml:Document/kml:Folder', KML_NAMESPACE)
        self.assertEqual(2, len(folders))
        marker_folder = folders[1]
        self.assertEqual(
            'Location Point Data - Markers',
            marker_folder.findtext('kml:name', namespaces=KML_NAMESPACE),
        )
        marker_placemarks = marker_folder.findall(
            'kml:Placemark', KML_NAMESPACE
        )
        self.assertEqual(2, len(marker_placemarks))
        self.assertTrue(all(
            placemark.find('kml:TimeSpan', KML_NAMESPACE) is None
            for placemark in marker_placemarks
        ))

        first_metadata = parse_kml_extended_data(marker_placemarks[0])
        primary_dataset_id = parse_kml_extended_data(
            kml_root.find('kml:Document', KML_NAMESPACE)
        )['osloc_dataset_id']
        self.assertNotEqual(primary_dataset_id, first_metadata['osloc_dataset_id'])
        self.assertEqual('marker', first_metadata['osloc_event_type'])
        self.assertEqual('marker', first_metadata['osloc_component_type'])
        self.assertEqual('Residence', first_metadata['osloc_event_label'])
        self.assertEqual('43.158310, -77.609380',
                         first_metadata['osloc_source_coordinate_text'])
        self.assertEqual('ff0000ff', first_metadata['osloc_style_marker_color'])
        self.assertEqual(
            '-77.609380,43.158310,0',
            marker_placemarks[0].findtext(
                'kml:Point/kml:coordinates', namespaces=KML_NAMESPACE
            ),
        )
        self.assertEqual(
            '0.9', marker_placemarks[0].findtext(
                'kml:Style/kml:LabelStyle/kml:scale', namespaces=KML_NAMESPACE
            ),
        )
        self.assertIn('Coordinates', marker_placemarks[0].findtext(
            'kml:description', namespaces=KML_NAMESPACE
        ))

        marker_features = [
            feature for feature in geojson_payload['features']
            if feature['properties'].get('osloc_event_type') == 'marker'
        ]
        self.assertEqual(2, len(marker_features))
        self.assertEqual(
            {first_metadata['osloc_dataset_id']},
            {
                feature['properties']['osloc_dataset_id']
                for feature in marker_features
            },
        )
        self.assertEqual(
            'rgba(255, 0, 0, 1)',
            marker_features[0]['properties'][
                'osloc_style_marker_color_rgba'
            ],
        )
        self.assertNotIn('osloc_start_epoch_ms', marker_features[0]['properties'])
        self.assertEqual(
            [-77.60938, 43.15831, 0.0], marker_features[0]['geometry']['coordinates']
        )
        self.assertEqual(2, generator.audit_summary['markers_generated'])

    def test_csl_reference_sites_are_static_deduplicated_and_radius_filtered(self):
        records = pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': 43.0,
            'Longitude': -77.0,
            'Azimuth': 90,
        }])
        cell_sites = pd.DataFrame([
            {'Site ID': 'USED', 'Latitude': 43.0, 'Longitude': -77.0,
             'CSL Source Rows': (2,)},
            {'Site ID': 'USED', 'Latitude': '43.000', 'Longitude': '-77.000',
             'CSL Source Rows': (3,)},
            {'Site ID': 'NEARBY', 'Latitude': 43.1, 'Longitude': -77.0,
             'CSL Source Rows': (4,)},
            {'Site ID': 'DISTANT', 'Latitude': 43.5, 'Longitude': -77.0,
             'CSL Source Rows': (5,)},
        ])
        settings = generator_settings()
        settings.update({
            'include_reference_sites': True,
            'reference_site_radius_miles': 25.0,
            'reference_site_color': 'ff000000',
        })
        generator = KMLGenerator(
            '', 'Tower/Sector', settings, reference_sites=cell_sites
        )

        kml_root = ET.fromstring(generator.generate_cell_tower_kml(records))
        geojson_payload = json.loads(
            generator.generate_cell_tower_geojson(records)
        )

        folders = kml_root.findall('kml:Document/kml:Folder', KML_NAMESPACE)
        self.assertEqual(2, len(folders))
        reference_folder = folders[1]
        self.assertEqual(
            'Cell Site/Sector Data - Reference Cell Sites',
            reference_folder.findtext('kml:name', namespaces=KML_NAMESPACE),
        )
        reference_placemarks = reference_folder.findall(
            'kml:Placemark', KML_NAMESPACE
        )
        self.assertEqual(2, len(reference_placemarks))
        self.assertTrue(all(
            placemark.find('kml:TimeSpan', KML_NAMESPACE) is None
            for placemark in reference_placemarks
        ))

        reference_metadata = [
            parse_kml_extended_data(placemark)
            for placemark in reference_placemarks
        ]
        reference_dataset_ids = {
            metadata['osloc_dataset_id'] for metadata in reference_metadata
        }
        primary_dataset_id = parse_kml_extended_data(
            kml_root.find('kml:Document', KML_NAMESPACE)
        )['osloc_dataset_id']
        self.assertEqual(1, len(reference_dataset_ids))
        self.assertNotIn(primary_dataset_id, reference_dataset_ids)
        self.assertEqual(
            {'reference_site'},
            {metadata['osloc_event_type'] for metadata in reference_metadata},
        )
        metadata_by_site = {
            metadata['osloc_site_ids']: metadata
            for metadata in reference_metadata
        }
        self.assertEqual('2, 3', metadata_by_site['USED']['osloc_csl_source_rows'])
        self.assertEqual('4', metadata_by_site['NEARBY']['osloc_csl_source_rows'])
        reference_style = next(
            style for style in kml_root.findall(
                'kml:Document/kml:Style', KML_NAMESPACE
            )
            if style.get('id') == 'osloc-reference-site'
        )
        self.assertEqual(
            'ff000000',
            reference_style.findtext(
                'kml:IconStyle/kml:color', namespaces=KML_NAMESPACE
            ),
        )

        reference_features = [
            feature for feature in geojson_payload['features']
            if feature['properties'].get('osloc_event_type') == 'reference_site'
        ]
        self.assertEqual(2, len(reference_features))
        self.assertEqual(
            reference_dataset_ids,
            {
                feature['properties']['osloc_dataset_id']
                for feature in reference_features
            },
        )
        self.assertEqual(
            {'USED', 'NEARBY'},
            {
                feature['properties']['osloc_site_ids']
                for feature in reference_features
            },
        )
        self.assertTrue(all(
            'osloc_start_epoch_ms' not in feature['properties']
            for feature in reference_features
        ))
        self.assertTrue(all(
            feature['properties']['osloc_style_reference_color_rgba']
            == 'rgba(0, 0, 0, 1)'
            for feature in reference_features
        ))
        self.assertEqual(
            {'USED': '2, 3', 'NEARBY': '4'},
            {
                feature['properties']['osloc_site_ids']:
                    feature['properties']['osloc_csl_source_rows']
                for feature in reference_features
            },
        )

    def test_reference_sites_without_csl_use_unique_record_coordinates(self):
        records = pd.DataFrame([
            {
                'Timestamp': '2024-01-15T14:00:00Z',
                'Latitude': '43.1000',
                'Longitude': '-77.1000',
                'Azimuth': 90,
            },
            {
                'Timestamp': '2024-01-15T14:05:00Z',
                'Latitude': 43.1,
                'Longitude': -77.1,
                'Azimuth': 180,
            },
            {
                'Timestamp': '2024-01-15T14:10:00Z',
                'Latitude': 43.2,
                'Longitude': -77.2,
                'Azimuth': 270,
            },
        ])
        settings = generator_settings()
        settings['include_reference_sites'] = True
        generator = KMLGenerator('', 'Tower/Sector', settings)

        kml_root = ET.fromstring(generator.generate_cell_tower_kml(records))
        geojson_payload = json.loads(
            generator.generate_cell_tower_geojson(records)
        )

        folders = kml_root.findall('kml:Document/kml:Folder', KML_NAMESPACE)
        self.assertEqual(2, len(folders))
        self.assertEqual(
            2,
            len(folders[1].findall('kml:Placemark', KML_NAMESPACE)),
        )
        self.assertEqual(
            2,
            sum(
                feature['properties'].get('osloc_event_type')
                == 'reference_site'
                for feature in geojson_payload['features']
            ),
        )
        reference_features = [
            feature for feature in geojson_payload['features']
            if feature['properties'].get('osloc_event_type') == 'reference_site'
        ]
        self.assertEqual(
            {'2, 3', '4'},
            {
                feature['properties']['osloc_source_rows']
                for feature in reference_features
            },
        )
        self.assertTrue(all(
            'osloc_site_ids' not in feature['properties']
            and 'Not available' not in feature['properties']['description']
            for feature in reference_features
        ))

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
