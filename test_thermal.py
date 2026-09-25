"""Unit and provenance checks; fixture values are arithmetic scenarios, not soils."""
import math
import unittest

from thermal import conductivity_to_resistivity, convert_record


class ThermalTests(unittest.TestCase):
    def test_reciprocal_units_and_round_trip(self):
        values = [0.25, 0.5, 1.0, 2.0, 4.0]
        self.assertEqual(conductivity_to_resistivity(values), [4.0, 2.0, 1.0, 0.5, 0.25])
        self.assertEqual(conductivity_to_resistivity(conductivity_to_resistivity(values)), values)

    def test_reject_invalid_and_overflow(self):
        for value in [0, -1, math.inf, -math.inf, math.nan, None, True, "2", [2], 5e-324]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                conductivity_to_resistivity([value])

    def test_record_preserves_evidence_and_conditioning(self):
        original = dict(conductivity=2, conductivity_unit="W/(m K)", status="scenario",
                        source="arithmetic fixture; not a site measurement",
                        conditions={"volumetric_water_content": None})
        output = convert_record(original)
        self.assertEqual(output["thermal_resistivity"], 0.5)
        self.assertEqual(output["thermal_resistivity_unit"], "K m/W")
        self.assertEqual(output["thermal_resistivity_evidence"], "derived_from_scenario")
        self.assertFalse(output["ampacity_calculated"])
        output["conditions"]["volumetric_water_content"] = 0.2
        self.assertIsNone(original["conditions"]["volumetric_water_content"])
        self.assertNotIn("thermal_resistivity", original)

    def test_reject_wrong_quantity_and_missing_provenance(self):
        valid = dict(conductivity=2, conductivity_unit="W/(m K)", status="measured", source="fixture")
        for change in [dict(conductivity_unit="ohm m"), dict(conductivity_unit="m/s"),
                       dict(source=""), dict(status="approved"), dict(status="modelled")]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                convert_record({**valid, **change})
        self.assertEqual(convert_record({**valid, "status": "modelled", "model": "fixture-v1"})
                         ["thermal_resistivity_evidence"], "derived_from_modelled")


if __name__ == "__main__":
    unittest.main()
