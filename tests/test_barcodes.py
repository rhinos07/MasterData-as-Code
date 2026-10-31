import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from barcodes import collect_barcodes, find_duplicate_codes, gtin_check_digit_ok  # noqa: E402
from validate import (  # noqa: E402
    check_packaging_refs,
    collect_element_ids,
    make_validator,
    validate_company_file,
)


PACKAGING_VALIDATOR = make_validator("packaging.schema.json")


def packaging(item_id, *levels):
    return {"item_id": item_id, "uom_hierarchy": [
        {"uom": uom, "quantity_of_previous": qty, "barcodes": codes} for uom, qty, codes in levels
    ]}


def gtin(code, **extra):
    return {"code": code, "type": "gtin", **extra}


class GtinCheckDigitTest(unittest.TestCase):
    def test_known_valid_codes(self):
        # GTIN-13, GTIN-8, GTIN-12 (UPC-A) examples with known check digits.
        for code in ("4006381333931", "96385074", "036000291452"):
            with self.subTest(code=code):
                self.assertTrue(gtin_check_digit_ok(code))

    def test_wrong_check_digit(self):
        self.assertFalse(gtin_check_digit_ok("4006381333932"))

    def test_wrong_length_or_letters(self):
        for code in ("123", "40063813339A1", "400638133393100"):
            with self.subTest(code=code):
                self.assertFalse(gtin_check_digit_ok(code))


class BarcodeSchemaTest(unittest.TestCase):
    def test_gtin_and_internal_are_valid(self):
        entry = packaging("I1", ("each", 1, [gtin("4006381333931", primary=True), {"code": "X-1", "type": "internal"}]))
        self.assertEqual(list(PACKAGING_VALIDATOR.iter_errors(entry)), [])

    def test_gtin_must_be_digits_of_valid_length(self):
        for code in ("40063813339", "ABC4006381333"):
            with self.subTest(code=code):
                entry = packaging("I1", ("each", 1, [gtin(code)]))
                self.assertTrue(list(PACKAGING_VALIDATOR.iter_errors(entry)))

    def test_unknown_type_is_rejected(self):
        entry = packaging("I1", ("each", 1, [{"code": "1", "type": "qr"}]))
        self.assertTrue(list(PACKAGING_VALIDATOR.iter_errors(entry)))


class PackagingBarcodeChecksTest(unittest.TestCase):
    def check(self, entries):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "packaging.yaml"
            path.write_text(yaml.safe_dump({"packaging": entries}), encoding="utf-8")
            return check_packaging_refs(path, {"I1", "I2"}, collect_element_ids())

    def test_wrong_check_digit_fails(self):
        errors = self.check([packaging("I1", ("each", 1, [gtin("4006381333932")]))])
        self.assertTrue(any("wrong check digit" in e for e in errors))

    def test_two_primary_codes_fail(self):
        codes = [gtin("4006381333931", primary=True), {"code": "X", "type": "internal", "primary": True}]
        errors = self.check([packaging("I1", ("each", 1, codes))])
        self.assertTrue(any("more than one barcode marked primary" in e for e in errors))


class UniquenessTest(unittest.TestCase):
    def duplicates(self, owners, entries):
        return find_duplicate_codes(collect_barcodes({"packaging": entries}, owners, Path("packaging.yaml")))

    def test_same_code_on_two_items_of_same_owner_fails(self):
        entries = [packaging("I1", ("each", 1, [gtin("4006381333931")])),
                   packaging("I2", ("each", 1, [gtin("4006381333931")]))]
        self.assertTrue(self.duplicates({"I1": "a", "I2": "a"}, entries))

    def test_same_code_on_two_levels_fails(self):
        entries = [packaging("I1", ("each", 1, [gtin("4006381333931")]), ("case", 6, [gtin("4006381333931")]))]
        self.assertTrue(self.duplicates({"I1": None}, entries))

    def test_same_code_for_two_owners_passes(self):
        entries = [packaging("I1", ("each", 1, [gtin("4006381333931")])),
                   packaging("I2", ("each", 1, [gtin("4006381333931")]))]
        self.assertEqual(self.duplicates({"I1": "a", "I2": "b"}, entries), [])

    def test_single_owner_company_is_one_scope(self):
        entries = [packaging("I1", ("each", 1, [gtin("4006381333931")])),
                   packaging("I2", ("each", 1, [gtin("4006381333931")]))]
        self.assertTrue(self.duplicates({"I1": None, "I2": None}, entries))


class CompanyWideTest(unittest.TestCase):
    def test_example_customers_validate(self):
        for name in ("example_customer", "example_3pl"):
            with self.subTest(customer=name):
                company = REPO_ROOT / "customers" / name / "company.yaml"
                self.assertEqual(validate_company_file(company, collect_element_ids()), [])

    def test_duplicate_across_categories_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, item in (("c1", "I1"), ("c2", "I2")):
                (root / name / "structure").mkdir(parents=True)
                (root / name / "category.yaml").write_text(yaml.safe_dump({
                    "api_version": "masterdata-as-code/v1",
                    "category": {"id": name, "default_attributes": {"default_uom": "each"},
                                 "imports": ["structure/items.yaml", "structure/packaging.yaml"]},
                }), encoding="utf-8")
                (root / name / "structure" / "items.yaml").write_text(
                    yaml.safe_dump({"items": [{"id": item}]}), encoding="utf-8")
                (root / name / "structure" / "packaging.yaml").write_text(
                    yaml.safe_dump({"packaging": [packaging(item, ("each", 1, [gtin("4006381333931")]))]}),
                    encoding="utf-8")
            (root / "company.yaml").write_text(yaml.safe_dump({"company": {
                "id": "x", "name": "X", "categories": ["c1/category.yaml", "c2/category.yaml"],
            }}), encoding="utf-8")
            errors = validate_company_file(root / "company.yaml", collect_element_ids())
        self.assertTrue(any("already used on I1/each within the company" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
