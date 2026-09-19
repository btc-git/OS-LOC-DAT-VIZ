"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from uuid import UUID

import pandas as pd

from kml_generator import KMLGenerator


KML_NAMESPACE = {'kml': 'http://www.opengis.net/kml/2.2'}


def generator_settings(enable_time_animation=True):
    return {
        'enable_time_animation': enable_time_animation,
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


def parse_kml(kml_content):
    return ET.fromstring(kml_content)


def extended_data(placemark):
    return {
        item.get('name'): item.findtext('kml:value', namespaces=KML_NAMESPACE)
        for item in placemark.findall('kml:ExtendedData/kml:Data', KML_NAMESPACE)
    }


def document_metadata(root):
    document = root.find('kml:Document', KML_NAMESPACE)
    return extended_data(document)


def style_element_for_placemark(root, placemark):
    inline_style = placemark.find('kml:Style', KML_NAMESPACE)
    if inline_style is not None:
        return inline_style
    style_url = placemark.findtext('kml:styleUrl', namespaces=KML_NAMESPACE)
    if not style_url:
        return None
    style_id = style_url[1:] if style_url.startswith('#') else style_url
    document = root.find('kml:Document', KML_NAMESPACE)
    if document is None:
        return None
    for style in document.findall('kml:Style', KML_NAMESPACE):
        if style.get('id') == style_id:
            return style
    return None


def placemark_style_text(root, placemark):
    style = style_element_for_placemark(root, placemark)
    if style is None:
        return None
    return style.findtext('kml:BalloonStyle/kml:text', namespaces=KML_NAMESPACE)


def icon_scale(root, placemark):
    style = style_element_for_placemark(root, placemark)
    if style is None:
        return None
    return style.findtext('kml:IconStyle/kml:scale', namespaces=KML_NAMESPACE)


def icon_color(root, placemark):
    style = style_element_for_placemark(root, placemark)
    if style is None:
        return None
    return style.findtext('kml:IconStyle/kml:color', namespaces=KML_NAMESPACE)


class KMLTemporalMetadataTests(unittest.TestCase):
    @staticmethod
    def geometry_counts(root):
        return {
            'polygon': len(root.findall('.//kml:Polygon', KML_NAMESPACE)),
            'line': len(root.findall('.//kml:LineString', KML_NAMESPACE)),
            'point': len(root.findall('.//kml:Point', KML_NAMESPACE)),
        }

    def assert_identity_only_placemark(self, placemark, expected_event_type):
        metadata = extended_data(placemark)
        self.assertIsNone(placemark.find('kml:TimeSpan', KML_NAMESPACE))
        allowed_keys = {
            'osloc_schema_version',
            'osloc_dataset_id',
            'osloc_dataset_name',
            'osloc_event_id',
            'osloc_event_type',
            'osloc_component_type',
            'osloc_event_label',
        }
        self.assertTrue(set(metadata).issubset(allowed_keys))
        self.assertTrue({'osloc_schema_version', 'osloc_dataset_id', 'osloc_dataset_name',
                         'osloc_event_id', 'osloc_event_type', 'osloc_component_type'}.issubset(set(metadata)))
        self.assertEqual('1', metadata['osloc_schema_version'])
        UUID(metadata['osloc_dataset_id'])
        self.assertEqual('event_000001', metadata['osloc_event_id'])
        self.assertEqual(expected_event_type, metadata['osloc_event_type'])
        if 'osloc_event_label' in metadata:
            self.assertTrue(metadata['osloc_event_label'])

    def test_ambiguous_numeric_dash_dates_use_selected_order(self):
        mdy_generator = KMLGenerator('', 'Tower/Sector', generator_settings())
        dmy_settings = generator_settings()
        dmy_settings['source_date_order'] = 'DMY'
        dmy_generator = KMLGenerator('', 'Tower/Sector', dmy_settings)

        self.assertEqual(
            '2026-04-10T14:30:00Z',
            mdy_generator.parse_timestamp_to_kml('04-10-2026 14:30:00')[0],
        )
        self.assertEqual(
            '2026-10-04T14:30:00Z',
            dmy_generator.parse_timestamp_to_kml('04-10-2026 14:30:00')[0],
        )
        self.assertEqual(
            '2026-09-15T14:30:00Z',
            dmy_generator.parse_timestamp_to_kml('2026-09-15 14:30:00')[0],
        )

    def test_event_title_uses_display_timezone_and_us_date_format(self):
        settings = generator_settings()
        settings['target_timezone_name'] = 'America/New_York'
        generator = KMLGenerator('', 'Tower/Sector', settings)
        root = parse_kml(generator.generate_cell_tower_kml(pd.DataFrame([{
            'Timestamp': '2023-02-01 01:14:41',
            'Latitude': 43.16619974,
            'Longitude': -77.5910047,
            'Azimuth': 30,
        }])))

        placemark = root.find('.//kml:Placemark', KML_NAMESPACE)
        metadata = extended_data(placemark)

        self.assertEqual(
            '01/31/2023, 8:14:41 PM',
            placemark.findtext('kml:name', namespaces=KML_NAMESPACE),
        )
        self.assertEqual('2023-02-01 01:14:41', metadata['osloc_display_time'])
        self.assertEqual(
            '2023-01-31T20:14:41-05:00', metadata['osloc_local_start_time']
        )

    def assert_temporal_placemark(self, placemark, expected_event_id=None,
                                  expected_event_type=None):
        begin = placemark.findtext('kml:TimeSpan/kml:begin', namespaces=KML_NAMESPACE)
        end = placemark.findtext('kml:TimeSpan/kml:end', namespaces=KML_NAMESPACE)
        metadata = extended_data(placemark)

        self.assertIsNotNone(begin)
        self.assertIsNotNone(end)
        self.assertTrue(begin.endswith('Z'))
        self.assertTrue(end.endswith('Z'))
        self.assertIn('osloc_event_id', metadata)
        self.assertEqual('1', metadata['osloc_schema_version'])
        UUID(metadata['osloc_dataset_id'])
        self.assertTrue(metadata['osloc_dataset_name'])
        self.assertTrue(metadata['osloc_component_type'])
        if metadata.get('osloc_start_time'):
            self.assertEqual(begin, metadata.get('osloc_start_time'))
            self.assertEqual(end, metadata.get('osloc_end_time'))
            local_begin = datetime.fromisoformat(metadata['osloc_local_start_time'])
            local_end = datetime.fromisoformat(metadata['osloc_local_end_time'])
            utc_begin = datetime.fromisoformat(begin.replace('Z', '+00:00'))
            utc_end = datetime.fromisoformat(end.replace('Z', '+00:00'))
            self.assertEqual(utc_begin, local_begin.astimezone(timezone.utc))
            self.assertEqual(utc_end, local_end.astimezone(timezone.utc))
        if expected_event_id:
            self.assertEqual(expected_event_id, metadata['osloc_event_id'])
        if expected_event_type:
            self.assertEqual(expected_event_type, metadata['osloc_event_type'])

    def test_every_temporal_placemark_has_matching_extended_data(self):
        dataframe = pd.DataFrame([
            {'Timestamp': '2024-01-15T14:00:00Z', 'Latitude': 43.15,
             'Longitude': -77.61, 'Azimuth': 240},
            {'Timestamp': '2024-01-15T14:15:00Z', 'Latitude': 43.16,
             'Longitude': -77.62, 'Azimuth': 90},
        ])
        settings = generator_settings()
        settings['custom_label'] = 'January Tower Review'
        settings['source_timezone_name'] = 'America/New_York'
        generator = KMLGenerator('', 'Tower/Sector', settings)
        root = parse_kml(generator.generate_cell_tower_kml(dataframe))
        folders = root.findall('.//kml:Folder', KML_NAMESPACE)
        placemarks = root.findall('.//kml:Placemark', KML_NAMESPACE)
        metadata_values = [extended_data(placemark) for placemark in placemarks]
        dataset_ids = {metadata['osloc_dataset_id'] for metadata in metadata_values}
        document_values = document_metadata(root)

        self.assertEqual('1', document_values['osloc_schema_version'])
        self.assertEqual('January Tower Review', document_values['osloc_dataset_name'])
        self.assertEqual({document_values['osloc_dataset_id']}, dataset_ids)

        second_root = parse_kml(generator.generate_cell_tower_kml(dataframe))
        self.assertNotEqual(
            document_values['osloc_dataset_id'],
            document_metadata(second_root)['osloc_dataset_id'],
        )

        self.assertEqual(1, len(folders))
        dataset_folder = folders[0]
        self.assertEqual(
            'January Tower Review',
            dataset_folder.findtext('kml:name', namespaces=KML_NAMESPACE),
        )
        folder_placemarks = dataset_folder.findall('kml:Placemark', KML_NAMESPACE)
        self.assertEqual(len(placemarks), len(folder_placemarks))
        event_ids = {
            extended_data(placemark)['osloc_event_id']
            for placemark in placemarks
        }
        self.assertEqual({'event_000001', 'event_000002'}, event_ids)
        for placemark in placemarks:
            self.assert_temporal_placemark(placemark, expected_event_type='tower_sector')

    def test_combined_distance_components_share_temporal_metadata(self):
        dataframe = pd.DataFrame([{
            'Timestamp': '2024-01-15 09:00:00',
            'Latitude': 43.15,
            'Longitude': -77.61,
            'Azimuth': 240,
            'Distance': 2.0,
            'Site': 'Alpha',
            'Cell ID': 'C-7',
        }])
        settings = generator_settings()
        settings['source_timezone_name'] = 'America/New_York'
        generator = KMLGenerator('', 'Distance from Tower', settings)
        root = parse_kml(generator.generate_distance_from_tower_kml(dataframe))
        placemarks = root.findall('.//kml:Placemark', KML_NAMESPACE)

        self.assertEqual(2, len(placemarks))
        shared_keys = {
            'osloc_schema_version', 'osloc_dataset_id', 'osloc_dataset_name',
            'osloc_event_id', 'osloc_event_type',
        }
        first_metadata = extended_data(placemarks[0])
        anchor_count = 0
        labeled_count = 0
        for placemark in placemarks:
            self.assert_temporal_placemark(
                placemark, 'event_000001', 'tower_sector_distance'
            )
            metadata = extended_data(placemark)
            if metadata.get('osloc_start_time'):
                anchor_count += 1
            if metadata.get('osloc_event_label'):
                labeled_count += 1
            self.assertEqual(
                {key: first_metadata[key] for key in shared_keys},
                {
                    key: metadata.get(key)
                    for key in shared_keys
                },
            )

        self.assertEqual(1, anchor_count)
        self.assertEqual(1, labeled_count)

        self.assertEqual('America/New_York', first_metadata['osloc_timezone'])
        self.assertEqual('2024-01-15T14:00:00Z', first_metadata['osloc_start_time'])
        self.assertEqual('2024-01-15T14:30:00Z', first_metadata['osloc_end_time'])
        self.assertEqual(
            '2024-01-15T09:00:00-05:00',
            first_metadata['osloc_local_start_time'],
        )
        self.assertEqual(
            '2024-01-15T09:30:00-05:00',
            first_metadata['osloc_local_end_time'],
        )
        event_title = '01/15/2024, 9:00:00 AM'
        self.assertEqual(
            f'{event_title} - Site Alpha / Cell C-7',
            first_metadata.get('osloc_event_label'),
        )
        self.assertEqual(
            {'tower_sector', 'distance_band'},
            {extended_data(placemark)['osloc_component_type'] for placemark in placemarks},
        )

        names = {
            placemark.findtext('kml:name', namespaces=KML_NAMESPACE): placemark
            for placemark in placemarks
        }
        distance_band = names[f'{event_title} - Distance band']
        self.assert_temporal_placemark(distance_band, 'event_000001')
        self.assertEqual({
            event_title,
            f'{event_title} - Distance band',
        }, set(names))
        self.assertIsNotNone(
            distance_band.find('kml:MultiGeometry/kml:Polygon', KML_NAMESPACE)
        )
        self.assertIsNotNone(
            distance_band.find('kml:MultiGeometry/kml:LineString', KML_NAMESPACE)
        )
        self.assertEqual(2, len(root.findall('.//kml:Polygon', KML_NAMESPACE)))
        self.assertEqual(3, len(root.findall('.//kml:LineString', KML_NAMESPACE)))
        self.assertEqual(1, len(root.findall('.//kml:Point', KML_NAMESPACE)))
        tower_sector = names[event_title]
        self.assertEqual(
            'ffffffff',
            style_element_for_placemark(root, tower_sector).findtext(
                'kml:LineStyle/kml:color', namespaces=KML_NAMESPACE
            ),
        )
        self.assertEqual(
            '7d00ff00',
            style_element_for_placemark(root, tower_sector).findtext(
                'kml:PolyStyle/kml:color', namespaces=KML_NAMESPACE
            ),
        )
        self.assertEqual(
            '-77.61,43.15,0',
            tower_sector.findtext(
                'kml:MultiGeometry/kml:Point/kml:coordinates', namespaces=KML_NAMESPACE
            ),
        )

    def test_location_accuracy_and_distance_only_outputs_are_temporal(self):
        gps_generator = KMLGenerator('', 'Location Point', generator_settings())
        gps_root = parse_kml(gps_generator.generate_gps_kml(pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': 43.15,
            'Longitude': -77.61,
            'Accuracy': 100,
        }])))
        gps_placemarks = gps_root.findall('.//kml:Placemark', KML_NAMESPACE)
        for placemark in gps_placemarks:
            self.assert_temporal_placemark(
                placemark, 'event_000001', 'location_accuracy'
            )
        self.assertEqual({'accuracy_circle'}, {extended_data(placemark)['osloc_component_type'] for placemark in gps_placemarks})

        distance_generator = KMLGenerator('', 'Distance from Tower', generator_settings())
        distance_root = parse_kml(distance_generator.generate_distance_from_tower_kml(pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': 43.15,
            'Longitude': -77.61,
            'Azimuth': None,
            'Distance': 2.0,
        }])))
        distance_placemarks = distance_root.findall('.//kml:Placemark', KML_NAMESPACE)
        for placemark in distance_placemarks:
            self.assert_temporal_placemark(
                placemark, 'event_000001', 'distance_only'
            )
        self.assertEqual({'distance_band'}, {extended_data(placemark)['osloc_component_type'] for placemark in distance_placemarks})

        center = next(
            placemark
            for placemark in distance_placemarks
            if extended_data(placemark)['osloc_component_type'] == 'distance_band'
        )
        self.assertEqual('ff0000ff', icon_color(distance_root, center))
        self.assertEqual(
            'http://maps.google.com/mapfiles/kml/pushpin/wht-pushpin.png',
            style_element_for_placemark(distance_root, center).findtext(
                'kml:IconStyle/kml:Icon/kml:href', namespaces=KML_NAMESPACE
            ),
        )

        circle_root = parse_kml(distance_generator.generate_distance_from_tower_kml(
            pd.DataFrame([{
                'Timestamp': '2024-01-15T14:00:00Z',
                'Latitude': 43.15,
                'Longitude': -77.61,
                'Azimuth': None,
                'Distance': None,
            }])
        ))
        circle_placemarks = circle_root.findall('.//kml:Placemark', KML_NAMESPACE)
        for placemark in circle_placemarks:
            self.assert_temporal_placemark(
                placemark, 'event_000001', 'tower_no_azimuth'
            )
        self.assertEqual(
            {'coverage_circle'},
            {extended_data(placemark)['osloc_component_type'] for placemark in circle_placemarks},
        )

    def test_balloonstyle_present_for_temporal_extendeddata_placemarks(self):
        settings = generator_settings()
        generator = KMLGenerator('', 'Distance from Tower', settings)
        root = parse_kml(generator.generate_distance_from_tower_kml(pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': 43.15,
            'Longitude': -77.61,
            'Azimuth': 240,
            'Distance': 2.0,
        }])))

        for placemark in root.findall('.//kml:Placemark', KML_NAMESPACE):
            metadata = extended_data(placemark)
            self.assertIn('osloc_schema_version', metadata)
            style_text = placemark_style_text(root, placemark)
            self.assertIsNotNone(style_text)
            self.assertIn('$[name]', style_text)
            self.assertIn('$[description]', style_text)
            self.assertIn('$[osloc_dataset_name]', style_text)

    def test_distance_only_balloonstyle_is_nested_inside_style(self):
        settings = generator_settings()
        generator = KMLGenerator('', 'Distance from Tower', settings)
        root = parse_kml(generator.generate_distance_from_tower_kml(pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': 43.15,
            'Longitude': -77.61,
            'Azimuth': None,
            'Distance': 2.0,
        }])))

        distance_only_placemarks = [
            placemark for placemark in root.findall('.//kml:Placemark', KML_NAMESPACE)
            if extended_data(placemark).get('osloc_event_type') == 'distance_only'
        ]

        self.assertEqual(1, len(distance_only_placemarks))

        for placemark in distance_only_placemarks:
            component_type = extended_data(placemark)['osloc_component_type']
            direct_balloon = placemark.find('kml:BalloonStyle', KML_NAMESPACE)
            self.assertIsNone(direct_balloon)

            style_text = placemark_style_text(root, placemark)
            self.assertIn(component_type, {'distance_band'})
            self.assertIsNotNone(style_text)
            self.assertIn('$[name]', style_text)
            self.assertIn('$[description]', style_text)
            self.assertIn('$[osloc_dataset_name]', style_text)

    def test_combined_sector_description_is_html_table(self):
        settings = generator_settings()
        root = parse_kml(KMLGenerator('', 'Distance from Tower', settings).generate_distance_from_tower_kml(pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': 43.16109,
            'Longitude': -77.65102,
            'Azimuth': 180,
            'Distance': 1.8,
        }])))

        expected_heading = '01/15/2024, 2:00:00 PM'
        tower_sector = next(
            placemark
            for placemark in root.findall('.//kml:Placemark', KML_NAMESPACE)
            if extended_data(placemark).get('osloc_component_type') == 'tower_sector'
        )
        description = tower_sector.findtext('kml:description', namespaces=KML_NAMESPACE)
        metadata = extended_data(tower_sector)
        style_text = placemark_style_text(root, tower_sector)

        self.assertEqual(expected_heading, tower_sector.findtext('kml:name', namespaces=KML_NAMESPACE))
        self.assertIn('$[name]', style_text)

        self.assertIn('<table', description)
        self.assertIn('<b>Tower:</b>', description)
        self.assertIn('<b>Azimuth:</b>', description)
        self.assertIn('<b>Sector Width:</b>', description)
        self.assertIn('<b>Distance:</b>', description)
        self.assertIn('<b>Band Area:</b>', description)
        self.assertIn('<b>Band Inner Width:</b>', description)
        self.assertIn('<b>Band Outer Width:</b>', description)
        self.assertIn('43.16109, -77.65102', description)
        self.assertIn('180°', description)
        self.assertIn('120°', description)
        self.assertIn('1.80 miles', description)
        self.assertIn('sq mi', description)
        self.assertIn('0.0 Miles', description)
        self.assertIn('0.1 Miles', description)
        self.assertEqual('tower_sector_distance', metadata['osloc_event_type'])
        self.assertEqual('tower_sector', metadata['osloc_component_type'])

    def test_hidden_anchor_scales_and_visible_location_point_color(self):
        settings = generator_settings()

        tower_root = parse_kml(KMLGenerator('', 'Tower/Sector', settings).generate_cell_tower_kml(pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': 43.15,
            'Longitude': -77.61,
            'Azimuth': 240,
        }])))
        tower_center = next(
            placemark
            for placemark in tower_root.findall('.//kml:Placemark', KML_NAMESPACE)
            if extended_data(placemark)['osloc_component_type'] == 'tower_sector'
        )
        self.assertEqual('0', icon_scale(tower_root, tower_center))

        distance_root = parse_kml(KMLGenerator('', 'Distance from Tower', settings).generate_distance_from_tower_kml(pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': 43.15,
            'Longitude': -77.61,
            'Azimuth': 240,
            'Distance': 2.0,
        }])))
        combined_center = next(
            placemark
            for placemark in distance_root.findall('.//kml:Placemark', KML_NAMESPACE)
            if extended_data(placemark)['osloc_component_type'] == 'tower_sector'
        )
        self.assertEqual('0', icon_scale(distance_root, combined_center))

        no_azimuth_root = parse_kml(KMLGenerator('', 'Distance from Tower', settings).generate_distance_from_tower_kml(pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': 43.15,
            'Longitude': -77.61,
            'Azimuth': None,
            'Distance': None,
        }])))
        no_azimuth_center = next(
            placemark
            for placemark in no_azimuth_root.findall('.//kml:Placemark', KML_NAMESPACE)
            if extended_data(placemark)['osloc_component_type'] == 'coverage_circle'
        )
        self.assertEqual('0', icon_scale(no_azimuth_root, no_azimuth_center))

        with_accuracy_root = parse_kml(KMLGenerator('', 'Location Point', settings).generate_gps_kml(pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': 43.15,
            'Longitude': -77.61,
            'Accuracy': 100,
        }])))
        hidden_location_point = next(
            placemark
            for placemark in with_accuracy_root.findall('.//kml:Placemark', KML_NAMESPACE)
            if extended_data(placemark)['osloc_component_type'] == 'accuracy_circle'
        )
        self.assertEqual('0', icon_scale(with_accuracy_root, hidden_location_point))

        visible_root = parse_kml(KMLGenerator('', 'Location Point', settings).generate_gps_kml(pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': 43.15,
            'Longitude': -77.61,
            'Accuracy': 'invalid',
        }])))
        visible_location_point = next(
            placemark
            for placemark in visible_root.findall('.//kml:Placemark', KML_NAMESPACE)
            if extended_data(placemark)['osloc_component_type'] == 'location_point'
        )
        self.assertEqual('1', icon_scale(visible_root, visible_location_point))
        self.assertEqual(settings['gps_color'], icon_color(visible_root, visible_location_point))
        self.assertEqual('location', extended_data(visible_location_point)['osloc_event_type'])

    def test_transparency_and_leg_colors_are_unchanged(self):
        settings = generator_settings()

        tower_root = parse_kml(KMLGenerator('', 'Tower/Sector', settings).generate_cell_tower_kml(pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': 43.15,
            'Longitude': -77.61,
            'Azimuth': 240,
        }])))
        tower_placemarks = tower_root.findall('.//kml:Placemark', KML_NAMESPACE)
        tower_sector = next(
            placemark
            for placemark in tower_placemarks
            if extended_data(placemark)['osloc_component_type'] == 'tower_sector'
        )
        self.assertEqual(
            f"7d{settings['shaded_color'][2:]}",
            style_element_for_placemark(tower_root, tower_sector).findtext(
                'kml:PolyStyle/kml:color', namespaces=KML_NAMESPACE
            ),
        )
        self.assertEqual(
            settings['leg_color'],
            style_element_for_placemark(tower_root, tower_sector).findtext(
                'kml:LineStyle/kml:color', namespaces=KML_NAMESPACE
            ),
        )

        distance_root = parse_kml(KMLGenerator('', 'Distance from Tower', settings).generate_distance_from_tower_kml(pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': 43.15,
            'Longitude': -77.61,
            'Azimuth': None,
            'Distance': 2.0,
        }])))
        distance_band = next(
            placemark
            for placemark in distance_root.findall('.//kml:Placemark', KML_NAMESPACE)
            if extended_data(placemark)['osloc_component_type'] == 'distance_band'
        )
        self.assertEqual(
            f"7d{settings['band_color'][2:]}",
            style_element_for_placemark(distance_root, distance_band).findtext(
                'kml:PolyStyle/kml:color', namespaces=KML_NAMESPACE
            ),
        )

        gps_root = parse_kml(KMLGenerator('', 'Location Point', settings).generate_gps_kml(pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': 43.15,
            'Longitude': -77.61,
            'Accuracy': 100,
        }])))
        accuracy_circle = next(
            placemark
            for placemark in gps_root.findall('.//kml:Placemark', KML_NAMESPACE)
            if extended_data(placemark)['osloc_component_type'] == 'accuracy_circle'
        )
        self.assertEqual(
            f"4d{settings['gps_color'][2:]}",
            style_element_for_placemark(gps_root, accuracy_circle).findtext(
                'kml:PolyStyle/kml:color', namespaces=KML_NAMESPACE
            ),
        )
        self.assertEqual(
            settings['gps_color'],
            style_element_for_placemark(gps_root, accuracy_circle).findtext(
                'kml:LineStyle/kml:color', namespaces=KML_NAMESPACE
            ),
        )

    def test_invalid_timestamp_output_has_identity_only_metadata(self):
        dataframe = pd.DataFrame([{
            'Timestamp': 'not a timestamp',
            'Latitude': 43.15,
            'Longitude': -77.61,
            'Azimuth': 240,
        }])
        generator = KMLGenerator('', 'Tower/Sector', generator_settings())
        root = parse_kml(generator.generate_cell_tower_kml(dataframe))

        placemarks = root.findall('.//kml:Placemark', KML_NAMESPACE)
        for placemark in placemarks:
            self.assert_identity_only_placemark(placemark, 'tower_sector')
        self.assertEqual(
            {'tower_sector'},
            {extended_data(placemark)['osloc_component_type'] for placemark in placemarks},
        )
        self.assertEqual('1', document_metadata(root)['osloc_schema_version'])

    def test_disabled_animation_output_has_identity_only_metadata(self):
        dataframe = pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': 43.15,
            'Longitude': -77.61,
            'Azimuth': 240,
        }])
        generator = KMLGenerator(
            '', 'Tower/Sector', generator_settings(enable_time_animation=False)
        )
        root = parse_kml(generator.generate_cell_tower_kml(dataframe))

        self.assertEqual([], root.findall('.//kml:TimeSpan', KML_NAMESPACE))
        for placemark in root.findall('.//kml:Placemark', KML_NAMESPACE):
            self.assert_identity_only_placemark(placemark, 'tower_sector')
        self.assertEqual('1', document_metadata(root)['osloc_schema_version'])

    def test_named_timezone_range_crosses_dst_using_canonical_instants(self):
        settings = generator_settings()
        settings['source_timezone_name'] = 'America/New_York'
        generator = KMLGenerator('', 'Tower/Sector', settings)
        root = parse_kml(generator.generate_cell_tower_kml(pd.DataFrame([{
            'Timestamp': '2024-03-10 01:45:00',
            'Latitude': 43.15,
            'Longitude': -77.61,
            'Azimuth': 240,
        }])))
        metadata = extended_data(root.find('.//kml:Placemark', KML_NAMESPACE))

        self.assertEqual('2024-03-10T06:45:00Z', metadata['osloc_start_time'])
        self.assertEqual('2024-03-10T07:15:00Z', metadata['osloc_end_time'])
        self.assertEqual(
            '2024-03-10T01:45:00-05:00', metadata['osloc_local_start_time']
        )
        self.assertEqual(
            '2024-03-10T03:15:00-04:00', metadata['osloc_local_end_time']
        )
        self.assertEqual('America/New_York', metadata['osloc_timezone'])
        self.assertEqual(
            datetime.fromisoformat(metadata['osloc_start_time'].replace('Z', '+00:00')),
            datetime.fromisoformat(metadata['osloc_local_start_time']).astimezone(timezone.utc),
        )
        self.assertEqual(
            datetime.fromisoformat(metadata['osloc_end_time'].replace('Z', '+00:00')),
            datetime.fromisoformat(metadata['osloc_local_end_time']).astimezone(timezone.utc),
        )

    def test_target_timezone_changes_local_metadata_but_keeps_utc_timespan(self):
        settings = generator_settings()
        settings['source_timezone_name'] = 'UTC'
        settings['source_utc_offset_minutes'] = 0
        settings['target_timezone_name'] = 'America/New_York'
        settings['target_utc_offset_minutes'] = None
        generator = KMLGenerator('', 'Tower/Sector', settings)
        root = parse_kml(generator.generate_cell_tower_kml(pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': 43.15,
            'Longitude': -77.61,
            'Azimuth': 240,
        }])))
        metadata = extended_data(root.find('.//kml:Placemark', KML_NAMESPACE))

        self.assertEqual('2024-01-15T14:00:00Z', metadata['osloc_start_time'])
        self.assertEqual('2024-01-15T14:30:00Z', metadata['osloc_end_time'])
        self.assertEqual('America/New_York', metadata['osloc_timezone'])
        self.assertEqual('2024-01-15T09:00:00-05:00', metadata['osloc_local_start_time'])
        self.assertEqual('2024-01-15T09:30:00-05:00', metadata['osloc_local_end_time'])

    def test_source_coordinates_keep_supplied_precision_derived_stays_six_decimals(self):
        settings = generator_settings()
        dataframe = pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': '43.123456789123',
            'Longitude': '-77.987654321987',
            'Azimuth': 240,
        }])
        kml_content = KMLGenerator('', 'Tower/Sector', settings).generate_cell_tower_kml(dataframe)
        root = parse_kml(kml_content)

        center = next(
            placemark
            for placemark in root.findall('.//kml:Placemark', KML_NAMESPACE)
            if extended_data(placemark)['osloc_component_type'] == 'tower_sector'
        )
        self.assertEqual(
            '-77.987654321987,43.123456789123,0',
            center.findtext('kml:MultiGeometry/kml:Point/kml:coordinates', namespaces=KML_NAMESPACE),
        )

        sector = next(
            placemark
            for placemark in root.findall('.//kml:Placemark', KML_NAMESPACE)
            if extended_data(placemark)['osloc_component_type'] == 'tower_sector'
        )
        coordinates_text = sector.findtext(
            'kml:MultiGeometry/kml:Polygon/kml:outerBoundaryIs/kml:LinearRing/kml:coordinates',
            namespaces=KML_NAMESPACE,
        )
        coordinate_rows = [line.strip() for line in coordinates_text.splitlines() if line.strip()]
        self.assertEqual('-77.987654321987,43.123456789123,0', coordinate_rows[0])
        self.assertEqual('-77.987654321987,43.123456789123,0', coordinate_rows[-1])
        self.assertRegex(coordinate_rows[1], r'^-?\d+\.\d{6},-?\d+\.\d{6},0$')

        leg_coords = sector.findtext('kml:MultiGeometry/kml:LineString/kml:coordinates', namespaces=KML_NAMESPACE)
        leg_rows = [line.strip() for line in leg_coords.splitlines() if line.strip()]
        self.assertEqual('-77.987654321987,43.123456789123,0', leg_rows[0])
        self.assertRegex(leg_rows[1], r'^-?\d+\.\d{6},-?\d+\.\d{6},0$')

        # Parsed root confirms the generated KML remains valid XML/KML.
        self.assertEqual('kml', root.tag.split('}')[-1])

    def test_flattened_output_uses_dataset_folder_not_event_folders(self):
        settings = generator_settings()
        dataframe = pd.DataFrame([
            {'Timestamp': '2024-01-15T14:00:00Z', 'Latitude': 43.15,
             'Longitude': -77.61, 'Azimuth': 240},
            {'Timestamp': '2024-01-15T14:15:00Z', 'Latitude': 43.16,
             'Longitude': -77.62, 'Azimuth': 90},
        ])
        root = parse_kml(KMLGenerator('', 'Tower/Sector', settings).generate_cell_tower_kml(dataframe))
        document = root.find('kml:Document', KML_NAMESPACE)
        folders = document.findall('kml:Folder', KML_NAMESPACE)

        self.assertEqual(1, len(folders))
        dataset_folder = folders[0]
        self.assertEqual('Tower/Sector Data', dataset_folder.findtext('kml:name', namespaces=KML_NAMESPACE))
        self.assertEqual(2, len(dataset_folder.findall('kml:Placemark', KML_NAMESPACE)))
        self.assertEqual([], dataset_folder.findall('kml:Folder', KML_NAMESPACE))

    def test_legacy_folder_mode_still_available_for_compatibility(self):
        settings = generator_settings()
        settings['flatten_event_folders'] = False
        dataframe = pd.DataFrame([
            {'Timestamp': '2024-01-15T14:00:00Z', 'Latitude': 43.15,
             'Longitude': -77.61, 'Azimuth': 240},
            {'Timestamp': '2024-01-15T14:15:00Z', 'Latitude': 43.16,
             'Longitude': -77.62, 'Azimuth': 90},
        ])
        root = parse_kml(KMLGenerator('', 'Tower/Sector', settings).generate_cell_tower_kml(dataframe))
        document = root.find('kml:Document', KML_NAMESPACE)
        folders = document.findall('kml:Folder', KML_NAMESPACE)

        self.assertEqual(2, len(folders))
        self.assertTrue(all(folder.find('kml:TimeSpan', KML_NAMESPACE) is not None for folder in folders))
        self.assertEqual(2, len(root.findall('.//kml:Placemark', KML_NAMESPACE)))

    def test_event_type_multigeometry_consolidation_minimums_and_primitive_preservation(self):
        rows = {
            'tower_sector': pd.DataFrame([{
                'Timestamp': '2024-01-15T14:00:00Z',
                'Latitude': 43.15,
                'Longitude': -77.61,
                'Azimuth': 240,
            }]),
            'tower_sector_distance': pd.DataFrame([{
                'Timestamp': '2024-01-15T14:00:00Z',
                'Latitude': 43.15,
                'Longitude': -77.61,
                'Azimuth': 240,
                'Distance': 2.0,
            }]),
            'tower_no_azimuth': pd.DataFrame([{
                'Timestamp': '2024-01-15T14:00:00Z',
                'Latitude': 43.15,
                'Longitude': -77.61,
                'Azimuth': None,
                'Distance': None,
            }]),
            'distance_only': pd.DataFrame([{
                'Timestamp': '2024-01-15T14:00:00Z',
                'Latitude': 43.15,
                'Longitude': -77.61,
                'Azimuth': None,
                'Distance': 2.0,
            }]),
            'location_accuracy': pd.DataFrame([{
                'Timestamp': '2024-01-15T14:00:00Z',
                'Latitude': 43.15,
                'Longitude': -77.61,
                'Accuracy': 100,
            }]),
            'location': pd.DataFrame([{
                'Timestamp': '2024-01-15T14:00:00Z',
                'Latitude': 43.15,
                'Longitude': -77.61,
                'Accuracy': 'invalid',
            }]),
        }

        expected = {
            'tower_sector': 1,
            'tower_sector_distance': 2,
            'tower_no_azimuth': 1,
            'distance_only': 1,
            'location_accuracy': 1,
            'location': 1,
        }

        for event_type, dataframe in rows.items():
            legacy_settings = generator_settings()
            legacy_settings['consolidate_event_placemarks'] = False
            consolidated_settings = generator_settings()

            if event_type in {'tower_sector', 'tower_no_azimuth'}:
                legacy_root = parse_kml(KMLGenerator('', 'Tower/Sector', legacy_settings).generate_cell_tower_kml(dataframe))
                consolidated_root = parse_kml(KMLGenerator('', 'Tower/Sector', consolidated_settings).generate_cell_tower_kml(dataframe))
            elif event_type in {'tower_sector_distance', 'distance_only'}:
                legacy_root = parse_kml(KMLGenerator('', 'Distance from Tower', legacy_settings).generate_distance_from_tower_kml(dataframe))
                consolidated_root = parse_kml(KMLGenerator('', 'Distance from Tower', consolidated_settings).generate_distance_from_tower_kml(dataframe))
            else:
                legacy_root = parse_kml(KMLGenerator('', 'Location Point', legacy_settings).generate_gps_kml(dataframe))
                consolidated_root = parse_kml(KMLGenerator('', 'Location Point', consolidated_settings).generate_gps_kml(dataframe))

            self.assertEqual(
                self.geometry_counts(legacy_root),
                self.geometry_counts(consolidated_root),
                f"Primitive geometry changed for {event_type}",
            )

            placemarks = consolidated_root.findall('.//kml:Placemark', KML_NAMESPACE)
            self.assertEqual(expected[event_type], len(placemarks), event_type)

            if event_type != 'location':
                self.assertEqual(expected[event_type], len(consolidated_root.findall('.//kml:MultiGeometry', KML_NAMESPACE)), event_type)

    def test_tower_sector_balloon_description_has_source_precision_and_human_fields(self):
        settings = generator_settings()
        dataframe = pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': '43.123456789123',
            'Longitude': '-77.987654321987',
            'Azimuth': 240,
        }])
        root = parse_kml(KMLGenerator('', 'Tower/Sector', settings).generate_cell_tower_kml(dataframe))
        sector = next(
            placemark
            for placemark in root.findall('.//kml:Placemark', KML_NAMESPACE)
            if extended_data(placemark)['osloc_component_type'] == 'tower_sector'
        )
        description = sector.findtext('kml:description', namespaces=KML_NAMESPACE)

        self.assertIn('43.123456789123, -77.987654321987', description)
        self.assertIn('<b>Azimuth:</b>', description)
        self.assertIn('240°', description)
        self.assertIn('<b>Sector Width:</b>', description)
        self.assertIn('<b>Sector Length:</b>', description)
        self.assertNotIn('osloc_', description)

    def test_distance_only_balloon_description_has_distance_fields(self):
        settings = generator_settings()
        root = parse_kml(KMLGenerator('', 'Distance from Tower', settings).generate_distance_from_tower_kml(pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': '43.111111111111',
            'Longitude': '-77.222222222222',
            'Azimuth': None,
            'Distance': 2.5,
        }])))
        band = next(
            placemark
            for placemark in root.findall('.//kml:Placemark', KML_NAMESPACE)
            if extended_data(placemark)['osloc_component_type'] == 'distance_band'
        )
        description = band.findtext('kml:description', namespaces=KML_NAMESPACE)

        self.assertIn('43.111111111111, -77.222222222222', description)
        self.assertIn('<b>Reported Distance:</b>', description)
        self.assertIn('2.50 miles', description)
        self.assertIn('<b>Band Inner:</b>', description)
        self.assertIn('<b>Band Outer:</b>', description)
        self.assertNotIn('osloc_', description)

    def test_location_accuracy_balloon_description_has_location_and_accuracy(self):
        settings = generator_settings()
        root = parse_kml(KMLGenerator('', 'Location Point', settings).generate_gps_kml(pd.DataFrame([{
            'Timestamp': '2024-01-15T14:00:00Z',
            'Latitude': '43.999999999999',
            'Longitude': '-77.000000000001',
            'Accuracy': 75,
        }])))
        circle = next(
            placemark
            for placemark in root.findall('.//kml:Placemark', KML_NAMESPACE)
            if extended_data(placemark)['osloc_component_type'] == 'accuracy_circle'
        )
        description = circle.findtext('kml:description', namespaces=KML_NAMESPACE)

        self.assertIn('43.999999999999, -77.000000000001', description)
        self.assertIn('<b>Accuracy:</b>', description)
        self.assertIn('75 Meters', description)
        self.assertIn('<b>Accuracy Radius (derived):</b>', description)
        self.assertNotIn('osloc_', description)


if __name__ == '__main__':
    unittest.main()