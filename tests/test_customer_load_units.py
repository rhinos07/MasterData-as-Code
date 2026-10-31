"""Customer-level carrier catalog: customers/<c>/load_unit_types.yaml
extends the global elements/load_unit_types.yaml."""

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from validate import (  # noqa: E402
    check_customer_load_units,
    collect_element_ids,
    load_carriers,
    validate_company_file,
)

CRATE = {
    "id": "own_crate",
    "dimensions": {
        "width": {"value": 0.4, "unit": "m"},
        "depth": {"value": 0.6, "unit": "m"},
        "height": {"value": 0.3, "unit": "m"},
    },
    "max_weight": {"value": 25, "unit": "kg"},
}


def write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def make_company(tmp: str, carriers: list | None, case_carrier: str, case_qty: int = 10) -> Path:
    """Minimal company with one category, one item (1 kg) and a case on
    case_carrier."""
    root = Path(tmp) / "customers" / "acme"
    company = write(root / "company.yaml", {
        "api_version": "masterdata-as-code/v1",
        "company": {"id": "acme", "name": "Acme", "categories": ["categories/parts/category.yaml"]},
    })
    if carriers is not None:
        write(root / "load_unit_types.yaml", {"load_unit_types": carriers})
    cat = root / "categories" / "parts"
    write(cat / "category.yaml", {
        "api_version": "masterdata-as-code/v1",
        "category": {
            "id": "parts",
            "name": "Parts",
            "default_attributes": {"default_uom": "each"},
            "imports": ["structure/items.yaml", "structure/packaging.yaml"],
        },
    })
    write(cat / "structure" / "items.yaml", {
        "items": [{"id": "P1", "description": "Part", "weight": {"value": 1, "unit": "kg"}}],
    })
    write(cat / "structure" / "packaging.yaml", {
        "packaging": [{"item_id": "P1", "uom_hierarchy": [
            {"uom": "each", "quantity_of_previous": 1},
            {"uom": "case", "quantity_of_previous": case_qty, "load_unit_type": case_carrier},
        ]}],
    })
    return company


class GlobalCatalogTest(unittest.TestCase):
    def test_autostore_variants_exist(self):
        carriers = load_carriers()
        heights = {cid: c["dimensions"]["height"]["value"] for cid, c in carriers.items()}
        self.assertEqual(heights["autostore_bin_220"], 0.22)
        self.assertEqual(heights["autostore_bin_330"], 0.33)
        self.assertEqual(heights["autostore_bin_425"], 0.425)


class CustomerCatalogTest(unittest.TestCase):
    def test_customer_carrier_is_known(self):
        with tempfile.TemporaryDirectory() as tmp:
            company = make_company(tmp, [CRATE], "own_crate")
            self.assertEqual(validate_company_file(company, collect_element_ids()), [])
            self.assertIn("own_crate", load_carriers(company))

    def test_unknown_carrier_without_customer_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            company = make_company(tmp, None, "own_crate")
            errors = validate_company_file(company, collect_element_ids())
            self.assertTrue(any("load_unit_type 'own_crate' not found" in e for e in errors), errors)

    def test_customer_carrier_payload_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            light = dict(CRATE, max_weight={"value": 5, "unit": "kg"})
            # 10 x 1 kg goods exceed the crate's 5 kg max_weight
            company = make_company(tmp, [light], "own_crate", case_qty=10)
            errors = validate_company_file(company, collect_element_ids())
            self.assertTrue(any("exceeds load_unit_type 'own_crate'" in e for e in errors), errors)

    def test_global_id_clash_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            clash = dict(CRATE, id="pallet_euro")
            company = make_company(tmp, [clash], "pallet_euro")
            errors = check_customer_load_units(company, collect_element_ids()["load_unit_types"])
            self.assertTrue(any("'pallet_euro' already exists" in e for e in errors), errors)

    def test_duplicate_customer_id_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            company = make_company(tmp, [CRATE, CRATE], "own_crate")
            errors = check_customer_load_units(company, set())
            self.assertTrue(any("duplicate load_unit_types ids" in e for e in errors), errors)

    def test_schema_applies_to_customer_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            company = make_company(tmp, [{"id": "Bad-Id"}], "carton")
            errors = check_customer_load_units(company, set())
            self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
