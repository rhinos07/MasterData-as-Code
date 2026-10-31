import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from compile import compile_category  # noqa: E402
from validate import (  # noqa: E402
    check_item_refs,
    check_load_unit_payload,
    check_packaging_refs,
    collect_element_ids,
    validate_element_catalog,
)

ELEMENTS = REPO_ROOT / "elements"


def write(tmp, name, data):
    path = Path(tmp) / name
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


class CatalogsTest(unittest.TestCase):
    def test_catalogs_validate(self):
        for file, schema, key in (
            ("load_unit_types.yaml", "load-unit-type.schema.json", "load_unit_types"),
            ("storage_conditions.yaml", "storage-condition.schema.json", "storage_conditions"),
        ):
            with self.subTest(file=file):
                self.assertEqual(validate_element_catalog(ELEMENTS / file, schema, key), [])

    def test_every_carrier_has_a_tare(self):
        catalog = yaml.safe_load((ELEMENTS / "load_unit_types.yaml").read_text(encoding="utf-8"))
        for carrier in catalog["load_unit_types"]:
            with self.subTest(id=carrier["id"]):
                self.assertIn("tare_weight", carrier)

    def test_condition_ranges_are_ordered(self):
        catalog = yaml.safe_load((ELEMENTS / "storage_conditions.yaml").read_text(encoding="utf-8"))
        for condition in catalog["storage_conditions"]:
            with self.subTest(id=condition["id"]):
                self.assertLessEqual(condition["temperature"]["min"], condition["temperature"]["max"])


class StorageConditionTest(unittest.TestCase):
    def check(self, items, category_condition=None):
        defaults = {"default_uom": "each"}
        if category_condition:
            defaults["storage_condition"] = category_condition
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "items.yaml", {"items": items})
            return check_item_refs(path, {"category": {"default_attributes": defaults}}, collect_element_ids())

    def test_known_condition_passes(self):
        self.assertEqual(self.check([{"id": "I1", "storage_condition": "chilled"}]), [])

    def test_unknown_condition_fails(self):
        errors = self.check([{"id": "I1", "storage_condition": "lukewarm"}])
        self.assertTrue(any("storage_condition 'lukewarm'" in e for e in errors))

    def test_unknown_category_condition_fails_per_item(self):
        errors = self.check([{"id": "I1"}], category_condition="lukewarm")
        self.assertTrue(any("storage_condition 'lukewarm'" in e for e in errors))

    def test_compile_resolves_condition(self):
        items = {i["id"]: i for i in compile_category(
            REPO_ROOT / "customers" / "example_customer" / "categories" / "beverages" / "category.yaml")}
        self.assertEqual(items["ITEM_001"]["storage_condition"], "ambient")
        self.assertEqual(items["ITEM_003"]["storage_condition"], "chilled")


class LoadUnitTest(unittest.TestCase):
    def packaging(self, qty_case=6, qty_pallet=80, carrier="pallet_euro"):
        return {"packaging": [{"item_id": "I1", "uom_hierarchy": [
            {"uom": "each", "quantity_of_previous": 1},
            {"uom": "case", "quantity_of_previous": qty_case, "load_unit_type": "carton"},
            {"uom": "pallet", "quantity_of_previous": qty_pallet, "load_unit_type": carrier},
        ]}]}

    def payload(self, packaging, weight_kg=1.5):
        items = {"items": [{"id": "I1", "weight": {"value": weight_kg, "unit": "kg"}}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "packaging.yaml", packaging)
            return check_load_unit_payload(path, items)

    def test_within_limits_passes(self):
        # 6 x 1.5 = 9 kg per carton (max 20), 480 x 1.5 = 720 kg per pallet (max 1000)
        self.assertEqual(self.payload(self.packaging()), [])

    def test_overloaded_pallet_fails(self):
        errors = self.payload(self.packaging(qty_pallet=200))  # 1200 x 1.5 = 1800 kg
        self.assertTrue(any("exceeds load_unit_type 'pallet_euro'" in e for e in errors))

    def test_overloaded_carton_fails(self):
        errors = self.payload(self.packaging(qty_case=20))  # 30 kg
        self.assertTrue(any("load_unit_type 'carton'" in e for e in errors))

    def test_unknown_carrier_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "packaging.yaml", self.packaging(carrier="pallet_moon"))
            errors = check_packaging_refs(path, {"I1"}, collect_element_ids())
        self.assertTrue(any("load_unit_type 'pallet_moon' not found" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
