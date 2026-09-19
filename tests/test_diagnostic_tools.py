"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

import unittest
import xml.etree.ElementTree as ET

from tools.generate_geolibre_import_diagnostics import (
    NS,
    apply_minimal_style_urls,
    filter_placemarks_by_geometry,
    first_point_coordinates,
    geometry_kind,
    q,
    set_minimal_styles,
)


class DiagnosticToolTests(unittest.TestCase):
    def setUp(self):
        self.placemark = ET.fromstring(f"""
            <Placemark xmlns="{NS['k']}">
                <name>Current consolidated event</name>
                <ExtendedData>
                    <Data name="osloc_component_type"><value>tower_sector</value></Data>
                </ExtendedData>
                <styleUrl>#osloc-tower-sector-event</styleUrl>
                <MultiGeometry>
                    <Polygon><outerBoundaryIs><LinearRing><coordinates>
                        -77.2,43.1,0 -77.3,43.1,0 -77.2,43.1,0
                    </coordinates></LinearRing></outerBoundaryIs></Polygon>
                    <LineString><coordinates>-77.2,43.1,0 -77.3,43.2,0</coordinates></LineString>
                    <Point><coordinates>-77.123456789,43.987654321,0</coordinates></Point>
                </MultiGeometry>
            </Placemark>
        """)

    def test_multigeometry_variants_retain_only_requested_primitives(self):
        self.assertEqual("mixed", geometry_kind(self.placemark))

        for kind, tag in (
            ("polygon", "Polygon"),
            ("line", "LineString"),
            ("point", "Point"),
        ):
            with self.subTest(kind=kind):
                filtered = filter_placemarks_by_geometry([self.placemark], kind)
                self.assertEqual(1, len(filtered))
                self.assertEqual(kind, geometry_kind(filtered[0]))
                self.assertEqual(1, len(filtered[0].findall(f".//k:{tag}", NS)))

    def test_nested_source_point_and_mixed_minimal_style_are_preserved(self):
        self.assertEqual(
            "-77.123456789,43.987654321,0",
            first_point_coordinates([self.placemark]),
        )

        root = ET.Element(q("kml"))
        document = ET.SubElement(root, q("Document"))
        document.append(self.placemark)
        set_minimal_styles(document)
        apply_minimal_style_urls(root)

        self.assertEqual(
            "#diag-all",
            self.placemark.findtext("k:styleUrl", namespaces=NS),
        )


if __name__ == "__main__":
    unittest.main()