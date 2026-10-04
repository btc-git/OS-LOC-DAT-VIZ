"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

import hashlib
import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pandas as pd

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication, QMessageBox

from import_wizard import ImportWizardDialog, SourceFileLoadWorker
from kml_generator import KMLGenerator
from main_window import MainWindow
from output_io import write_output_set
from source_io import read_csv_text, read_hashed_source
from test_geojson_parity import generator_settings


LATITUDE = '40.1234567890123456789'
LONGITUDE = '-77.9876543210987654321'
SOURCE_CSV = (
    'Timestamp,Latitude,Longitude,Azimuth,Site ID,Sector ID\n'
    f'2024-01-15T14:00:00Z,{LATITUDE},{LONGITUDE},90,000123,007\n'
)


def run_generator(path, dataframe=None, reference_sites=None):
    worker = KMLGenerator(
        str(path), 'Tower/Sector', generator_settings(),
        dataframe=dataframe, reference_sites=reference_sites,
    )
    outputs, errors = [], []
    worker.finished.connect(outputs.append)
    worker.error.connect(errors.append)
    worker.run()
    if errors or len(outputs) != 1:
        raise AssertionError(f"Generation failed: {errors}")
    return worker, outputs[0]


class LoadedSourceTests(unittest.TestCase):
    def test_csv_preserves_coordinates_ids_and_missing_value_behavior(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.csv'
            path.write_text(SOURCE_CSV, encoding='utf-8')
            result = SourceFileLoadWorker.read_source(path)
            row = result['dataframe'].iloc[0]
            self.assertEqual(LATITUDE, row['Latitude'])
            self.assertEqual(LONGITUDE, row['Longitude'])
            self.assertEqual('000123', row['Site ID'])
            self.assertEqual('007', row['Sector ID'])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                             result['source_sha256'])
            inspection = SourceFileLoadWorker.read_source(path, inspect_only=True)
            self.assertEqual(LATITUDE, inspection['dataframe'].iloc[0]['Latitude'])
            path.write_text('Latitude,Accuracy,Azimuth\n40.12345,,NA\n', encoding='utf-8')
            frame, _digest = read_hashed_source(path, read_csv_text)
            self.assertTrue(pd.isna(frame.iloc[0]['Accuracy']))
            self.assertTrue(pd.isna(frame.iloc[0]['Azimuth']))

    def test_direct_csv_generation_preserves_precision_in_both_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.csv'
            path.write_text(SOURCE_CSV, encoding='utf-8')
            worker, outputs = run_generator(path)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                             worker.source_sha256)
            properties = json.loads(outputs['geojson'])['features'][0]['properties']
            self.assertEqual(LATITUDE, properties['osloc_source_latitude'])
            self.assertEqual(LONGITUDE, properties['osloc_source_longitude'])
            root = ET.fromstring(outputs['kml'])
            points = root.findall(
                './/{http://www.opengis.net/kml/2.2}Point/'
                '{http://www.opengis.net/kml/2.2}coordinates'
            )
            self.assertIn(f'{LONGITUDE},{LATITUDE},0', [p.text.strip() for p in points])

    def test_ordinary_coordinates_produce_same_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.csv'
            path.write_text(
                SOURCE_CSV.replace(LATITUDE, '40.12345').replace(LONGITUDE, '-77.98765'),
                encoding='utf-8',
            )
            _worker, text_outputs = run_generator(path)
            _worker, inferred_outputs = run_generator(path, dataframe=pd.read_csv(path))
            text_features = json.loads(text_outputs['geojson'])['features']
            inferred_features = json.loads(inferred_outputs['geojson'])['features']
            self.assertEqual(
                [feature['geometry'] for feature in inferred_features],
                [feature['geometry'] for feature in text_features],
            )
            self.assertEqual(
                [feature['properties']['osloc_start_time'] for feature in inferred_features],
                [feature['properties']['osloc_start_time'] for feature in text_features],
            )

    def test_source_modified_during_loading_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.csv'
            path.write_text(SOURCE_CSV, encoding='utf-8')

            def modifying_reader(handle):
                frame = read_csv_text(handle)
                with path.open('ab') as output:
                    output.write(b'\n')
                return frame

            with self.assertRaisesRegex(ValueError, 'changed while loading'):
                read_hashed_source(path, modifying_reader)

    def test_csv_numeric_fields_and_missing_accuracy_match_inferred_behavior(self):
        cases = (
            ('Distance from Tower',
             'Timestamp,Latitude,Longitude,Azimuth,Distance\n'
             '2024-01-15T14:00:00Z,40.12345,-77.98765,90,1.25\n'),
            ('Location Point',
             'Timestamp,Latitude,Longitude,Accuracy\n'
             '2024-01-15T14:00:00Z,40.12345,-77.98765,NA\n'
             '2024-01-15T14:01:00Z,40.12346,-77.98766,15\n'
             '2024-01-15T14:02:00Z,40.12347,-77.98767,0\n'),
        )
        for data_type, text in cases:
            with self.subTest(data_type=data_type), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'source.csv'
                path.write_text(text, encoding='utf-8')
                feature_sets, summaries = [], []
                for dataframe in (None, pd.read_csv(path)):
                    worker = KMLGenerator(
                        str(path), data_type, generator_settings(), dataframe=dataframe
                    )
                    outputs, errors = [], []
                    worker.finished.connect(outputs.append)
                    worker.error.connect(errors.append)
                    worker.run()
                    self.assertEqual([], errors)
                    feature_sets.append([
                        feature['geometry']
                        for feature in json.loads(outputs[0]['geojson'])['features']
                    ])
                    summaries.append(worker.audit_summary)
                self.assertEqual(feature_sets[0], feature_sets[1])
                self.assertEqual(summaries[0], summaries[1])


class OutputSetTests(unittest.TestCase):
    def test_staging_failure_preserves_all_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / f'result.{suffix}' for suffix in ('kml', 'geojson', 'txt')]
            for path in paths:
                path.write_text('original', encoding='utf-8')
            real_fsync = os.fsync
            calls = 0

            def fail_second_stage(descriptor):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError('synthetic stage failure')
                real_fsync(descriptor)

            with patch('output_io.os.fsync', side_effect=fail_second_stage):
                with self.assertRaisesRegex(OSError, 'synthetic stage failure'):
                    write_output_set(dict.fromkeys(paths, 'replacement'))
            self.assertEqual(['original'] * 3, [p.read_text() for p in paths])
            self.assertEqual(set(paths), set(root.iterdir()))

    def test_replacement_failure_restores_previous_set(self):
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paths = [root / f'result.{suffix}' for suffix in (
                    'kml', 'geojson', 'txt', 'geolibre',
                )]
                if existing:
                    for path in paths:
                        path.write_text(f'original {path.suffix}', encoding='utf-8')
                real_replace = Path.replace

                def fail_second_replace(path, target):
                    if path.suffix == '.tmp' and target == paths[1]:
                        raise OSError('synthetic replacement failure')
                    return real_replace(path, target)

                with patch.object(Path, 'replace', new=fail_second_replace):
                    with self.assertRaisesRegex(OSError, 'synthetic replacement failure'):
                        write_output_set(dict.fromkeys(paths, 'replacement'))
                if existing:
                    self.assertEqual(
                        [f'original {p.suffix}' for p in paths],
                        [p.read_text() for p in paths],
                    )
                    self.assertEqual(set(paths), set(root.iterdir()))
                else:
                    self.assertEqual([], list(root.iterdir()))

    def test_output_directory_does_not_leave_partial_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'result.geojson'
            path.mkdir()
            with self.assertRaisesRegex(OSError, 'not a file'):
                MainWindow.write_visualization_outputs(path, '<kml/>', '{}')
            self.assertFalse(path.with_suffix('.kml').exists())

    def test_incomplete_recovery_retains_backup_and_reports_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / 'result.kml', root / 'result.geojson']
            for path in paths:
                path.write_text('original', encoding='utf-8')
            real_replace = Path.replace

            def fail_save_and_restore(path, target):
                if (
                    path.suffix == '.tmp' and target == paths[1]
                    or path.suffix == '.bak' and target == paths[0]
                ):
                    raise OSError('synthetic access failure')
                return real_replace(path, target)

            with patch.object(Path, 'replace', new=fail_save_and_restore):
                with self.assertRaisesRegex(OSError, 'Recovery was incomplete.*backup'):
                    write_output_set(dict.fromkeys(paths, 'replacement'))
            backups = list(root.glob('.osloc-*.bak'))
            self.assertEqual(1, len(backups))
            self.assertEqual('original', backups[0].read_text())
            self.assertEqual([], list(root.glob('.osloc-*.tmp')))


class ImportAndSaveUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def window(self):
        with patch.object(MainWindow, 'show_disclaimer_dialog'):
            window = MainWindow()
        self.addCleanup(window.close)
        return window

    def test_wizard_csl_join_preserves_ids_precision_and_load_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records, sites = root / 'records.csv', root / 'sites.csv'
            records.write_text(
                'Timestamp,Site ID,Sector ID\n2024-01-15T14:00:00Z,000123,007\n',
                encoding='utf-8',
            )
            sites.write_text(
                'Site ID,Sector ID,Latitude,Longitude,Azimuth\n'
                f'000123,007,{LATITUDE},{LONGITUDE},90\n', encoding='utf-8',
            )
            dialog = ImportWizardDialog()
            self.addCleanup(dialog.close)
            dialog.load_file(str(records), background=False)
            dialog.record_type_combo.setCurrentIndex(
                dialog.record_type_combo.findData('Tower/Sector')
            )
            dialog.use_cell_site_list_checkbox.setChecked(True)
            dialog.load_cell_site_file(str(sites), background=False)
            dialog.accept_import()
            self.assertIsNotNone(dialog.normalized_dataframe)
            self.assertEqual(LATITUDE, dialog.normalized_dataframe.iloc[0]['Latitude'])
            self.assertEqual('000123', dialog.reference_sites_dataframe.iloc[0]['Site ID'])
            self.assertEqual(1, dialog.selected_cell_site_metadata['matched_rows'])
            self.assertEqual(hashlib.sha256(records.read_bytes()).hexdigest(),
                             dialog.source_sha256)
            self.assertEqual(hashlib.sha256(sites.read_bytes()).hexdigest(),
                             dialog.selected_cell_site_metadata['source_sha256'])
            _worker, outputs = run_generator(
                records, dialog.normalized_dataframe, dialog.reference_sites_dataframe
            )
            self.assertEqual(
                LATITUDE,
                json.loads(outputs['geojson'])['features'][0]['properties']['osloc_source_latitude'],
            )

    def test_marker_import_keeps_text_and_multiple_versions_of_same_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'markers.csv'
            window = self.window()
            path.write_text(
                f'Label,Latitude,Longitude,Color\nMarker,{LATITUDE},{LONGITUDE},red\n',
                encoding='utf-8',
            )
            first_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            window.import_marker_file(str(path))
            self.assertEqual(LATITUDE, window.marker_table.item(0, 1).text())
            path.write_text('Label,Latitude,Longitude,Color\nMarker,40.1,-77.1,red\n',
                            encoding='utf-8')
            second_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            window.import_marker_file(str(path))
            self.assertEqual(
                [first_hash, second_hash],
                [source['source_sha256'] for source in window.marker_import_sources],
            )
            window.clear_marker_rows()
            self.assertEqual([], window.marker_import_sources)

    def test_log_uses_loaded_hashes_even_if_inputs_change_or_disappear(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            window = self.window()
            source, sites, markers = [root / name for name in (
                'source.csv', 'sites.csv', 'markers.csv',
            )]
            hashes = {}
            for path in (source, sites, markers):
                path.write_text(SOURCE_CSV, encoding='utf-8')
                hashes[path] = SourceFileLoadWorker.read_source(path)['source_sha256']
            window.current_generation_source_file = str(source)
            window.current_generation_source_sha256 = hashes[source]
            window.current_import_metadata = {
                'cell_site_list': {
                    'enabled': True, 'file_path': str(sites),
                    'source_sha256': hashes[sites],
                },
            }
            window.current_marker_import_sources = [{
                'file_path': str(markers), 'source_sha256': hashes[markers],
            }]
            source.write_text('changed', encoding='utf-8')
            sites.unlink()
            markers.unlink()
            contents = ('<kml/>\n', '{"type":"FeatureCollection","features":[]}\n')
            selected = root / 'result.GEOJSON'
            log = window.build_generation_log(selected, output_contents=contents)
            self.assertIn(f'Source SHA-256: {hashes[source]}', log)
            self.assertIn(f'Cell site list SHA-256: {hashes[sites]}', log)
            self.assertIn(f'Marker list 1 SHA-256: {hashes[markers]}', log)
            kml, geojson = window.write_visualization_outputs(
                selected, *contents, log_content=log,
            )
            self.assertEqual(selected, geojson)
            self.assertIn(f'Output GeoJSON: {selected.name}', log)
            for label, path in (('KML', kml), ('GeoJSON', geojson)):
                self.assertIn(
                    f'Output {label} SHA-256: {hashlib.sha256(path.read_bytes()).hexdigest()}',
                    log,
                )

    def test_declining_overwrite_changes_no_siblings_and_does_not_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = root / 'result.geojson'
            for suffix in ('.kml', '.txt', '.geolibre'):
                selected.with_suffix(suffix).write_text('original', encoding='utf-8')
            window = self.window()
            window.current_generation_source_file = str(root / 'source.csv')
            window.open_viewer_after_generation = True
            with (
                patch('main_window.QFileDialog.getSaveFileName', return_value=(str(selected), '')),
                patch('main_window.QMessageBox.question',
                      return_value=QMessageBox.StandardButton.No) as question,
                patch.object(window, 'start_geolibre_viewer') as launch,
                patch.object(window, 'write_visualization_outputs') as write,
            ):
                window.on_generation_finished({'kml': '<kml/>', 'geojson': '{}'})
            write.assert_not_called()
            launch.assert_not_called()
            for suffix in ('.kml', '.txt', '.geolibre'):
                self.assertIn(str(selected.with_suffix(suffix)), question.call_args.args[2])
                self.assertEqual('original', selected.with_suffix(suffix).read_text())
            self.assertFalse(selected.exists())
            self.assertTrue(window.generate_button.isEnabled())

    def test_approved_overwrite_saves_complete_set_before_viewer_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = root / 'result.geojson'
            source = root / 'source.csv'
            source.write_text(SOURCE_CSV, encoding='utf-8')
            worker, outputs = run_generator(source)
            window = self.window()
            window.current_generation_source_file = str(source)
            window.current_generation_settings = generator_settings()
            window.current_generation_type = 'Tower/Sector'
            window.kml_generator = worker
            window.open_viewer_after_generation = True
            for suffix in ('.kml', '.geojson', '.txt', '.geolibre'):
                selected.with_suffix(suffix).write_text('original', encoding='utf-8')
            source.unlink()

            def check_saved_before_launch(path):
                self.assertEqual(selected, path)
                for suffix in ('.kml', '.geojson', '.txt', '.geolibre'):
                    self.assertNotEqual(
                        'original', selected.with_suffix(suffix).read_text(encoding='utf-8')
                    )
                log = selected.with_suffix('.txt').read_text(encoding='utf-8')
                self.assertIn(f'Source SHA-256: {worker.source_sha256}', log)
                for label, suffix in (('KML', '.kml'), ('GeoJSON', '.geojson')):
                    digest = hashlib.sha256(selected.with_suffix(suffix).read_bytes()).hexdigest()
                    self.assertIn(f'Output {label} SHA-256: {digest}', log)
                project = json.loads(selected.with_suffix('.geolibre').read_text(encoding='utf-8'))
                self.assertEqual(str(selected.resolve()), project['layers'][0]['sourcePath'])

            with (
                patch('main_window.QFileDialog.getSaveFileName', return_value=(str(selected), '')),
                patch('main_window.QMessageBox.question',
                      return_value=QMessageBox.StandardButton.Yes),
                patch.object(window, 'start_geolibre_viewer',
                             side_effect=check_saved_before_launch) as launch,
            ):
                window.on_generation_finished(outputs)
            launch.assert_called_once_with(selected)
            self.assertEqual([], list(root.glob('.osloc-*')))

    def test_log_preparation_failure_keeps_existing_outputs_and_reports_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = root / 'result.geojson'
            window = self.window()
            window.current_generation_source_file = str(root / 'source.csv')
            for suffix in ('.kml', '.geojson', '.txt'):
                selected.with_suffix(suffix).write_text('original', encoding='utf-8')
            with (
                patch('main_window.QFileDialog.getSaveFileName', return_value=(str(selected), '')),
                patch('main_window.QMessageBox.question',
                      return_value=QMessageBox.StandardButton.Yes),
                patch('main_window.QMessageBox.critical') as critical,
                patch.object(window, 'open_file_location') as open_location,
            ):
                window.on_generation_finished({'kml': '<kml/>', 'geojson': '{}'})
            critical.assert_called_once()
            self.assertIn('SHA-256 is missing', critical.call_args.args[2])
            open_location.assert_not_called()
            self.assertEqual(
                ['original'] * 3,
                [selected.with_suffix(suffix).read_text()
                 for suffix in ('.kml', '.geojson', '.txt')],
            )

    def test_beta_version_declarations_match(self):
        from version import APP_VERSION
        root = Path(__file__).resolve().parents[1]
        numeric_parts = APP_VERSION.replace('-beta.', '.').split('.')
        numeric_parts += ['0'] * (4 - len(numeric_parts))
        numeric_version = '.'.join(numeric_parts)
        numeric_tuple = ', '.join(numeric_parts)
        windows_metadata = (root / 'version_info.txt').read_text(encoding='utf-8')
        self.assertIn(f"StringStruct('ProductVersion', '{APP_VERSION}')", windows_metadata)
        self.assertIn(f'filevers=({numeric_tuple})', windows_metadata)
        self.assertIn(f'prodvers=({numeric_tuple})', windows_metadata)
        self.assertIn(f"StringStruct('FileVersion', '{numeric_version}')", windows_metadata)
        self.assertIn(f'**Version {APP_VERSION}**',
                      (root / 'README.md').read_text(encoding='utf-8'))
        self.assertIn(f'## [{APP_VERSION}]',
                      (root / 'CHANGELOG.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
