"""Offline checks for ground geometry helpers and the licence manifest."""
import json
import unittest
from pathlib import Path

from import_ground import borehole_record, clip_polygon, clip_ring, polygons_of, ring_area

BOX = (0.0, 0.0, 10.0, 10.0)


class ClipTests(unittest.TestCase):
    def test_inside_ring_unchanged(self):
        ring = [(1, 1), (4, 1), (4, 4), (1, 4), (1, 1)]
        self.assertEqual(clip_ring(ring, BOX), ring[:-1])

    def test_straddling_square_area(self):
        clipped = clip_ring([(-5, -5), (5, -5), (5, 5), (-5, 5)], BOX)
        self.assertAlmostEqual(abs(ring_area(clipped)), 25.0)

    def test_outside_and_degenerate_dropped(self):
        self.assertEqual(clip_ring([(20, 20), (30, 20), (30, 30)], BOX), [])
        self.assertIsNone(clip_polygon([[(20, 20), (30, 20), (30, 30)]], BOX))

    def test_hole_kept_when_inside(self):
        poly = clip_polygon([[(-1, -1), (11, -1), (11, 11), (-1, 11)], [(2, 2), (3, 2), (3, 3), (2, 3)]], BOX)
        self.assertEqual(len(poly), 2)
        self.assertAlmostEqual(abs(ring_area([tuple(p) for p in poly[0]])), 100.0)

    def test_polygons_of(self):
        self.assertEqual(len(polygons_of({'type': 'MultiPolygon', 'coordinates': [[[]], [[]]]})), 2)
        self.assertEqual(polygons_of(None), [])
        with self.assertRaises(ValueError):
            polygons_of({'type': 'Point', 'coordinates': [0, 0]})


class BoreholeTests(unittest.TestCase):
    base = {'easting': 1.0, 'northing': 2.0, 'reference': 'X1', 'scan_url': 'https://example.invalid/1'}

    def test_coded_length_stays_missing(self):
        rec = borehole_record({**self.base, 'length': -2.0})
        self.assertNotIn('drilled_length_m', rec)
        self.assertEqual(rec['length_code_as_recorded'], -2.0)
        self.assertNotIn('drilled_length_m', borehole_record({**self.base, 'length': None}))

    def test_known_length_and_link(self):
        rec = borehole_record({**self.base, 'length': 60.0})
        self.assertEqual(rec['drilled_length_m'], 60.0)
        self.assertEqual(rec['log_url'], 'https://example.invalid/1')


class ManifestTests(unittest.TestCase):
    def test_only_usable_sources_import(self):
        m = json.loads(Path(__file__).with_name('ground_sources.json').read_text(encoding='utf-8'))
        self.assertRegex(m['verified_on'], r'^\d{4}-\d{2}-\d{2}$')
        for s in m['sources']:
            with self.subTest(source=s['id']):
                self.assertTrue(s['verified_url'].startswith('https://'))
                self.assertTrue(s['licence'])
                if s['import']:
                    self.assertTrue(s['usable'])
                    self.assertEqual(s['licence'], 'OGL-UK-3.0')
                    self.assertTrue(s['attribution'])
                    self.assertIn('service', s)
                else:
                    self.assertTrue(s.get('finding'))


if __name__ == '__main__':
    unittest.main()
