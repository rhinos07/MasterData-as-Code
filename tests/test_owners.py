import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from validate import (  # noqa: E402
    check_item_owners,
    collect_element_ids,
    make_validator,
    validate_company_file,
)


COMPANY_VALIDATOR = make_validator("company.schema.json")


def category(owner=None):
    defaults = {"default_uom": "each"}
    if owner:
        defaults["owner"] = owner
    return {"category": {"id": "c", "default_attributes": defaults}}


def check(items, owner_ids, category_owner=None):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "items.yaml"
        path.write_text(yaml.safe_dump({"items": items}), encoding="utf-8")
        return check_item_owners(path, category(category_owner), owner_ids)


class CompanyOwnerSchemaTest(unittest.TestCase):
    def company(self, owners):
        return {"company": {"id": "x", "name": "X", "categories": [], "owners": owners}}

    def test_owner_list_is_valid(self):
        data = self.company([{"id": "owner_a", "name": "A"}])
        self.assertEqual(list(COMPANY_VALIDATOR.iter_errors(data)), [])

    def test_owner_id_pattern_is_enforced(self):
        data = self.company([{"id": "Owner A", "name": "A"}])
        self.assertTrue(list(COMPANY_VALIDATOR.iter_errors(data)))

    def test_owner_needs_a_name(self):
        data = self.company([{"id": "owner_a"}])
        self.assertTrue(list(COMPANY_VALIDATOR.iter_errors(data)))


class CheckItemOwnersTest(unittest.TestCase):
    def test_single_owner_company_needs_nothing(self):
        self.assertEqual(check([{"id": "I1"}], set()), [])

    def test_owner_without_declared_owners_fails(self):
        errors = check([{"id": "I1", "owner": "owner_a"}], set())
        self.assertTrue(any("declares no owners" in e for e in errors))

    def test_missing_owner_in_multi_owner_company_fails(self):
        errors = check([{"id": "I1"}], {"owner_a"})
        self.assertTrue(any("no owner set" in e for e in errors))

    def test_inherited_owner_passes(self):
        self.assertEqual(check([{"id": "I1"}], {"owner_a"}, category_owner="owner_a"), [])

    def test_item_owner_overrides_category(self):
        items = [{"id": "I1", "owner": "owner_b"}]
        self.assertEqual(check(items, {"owner_a", "owner_b"}, category_owner="owner_a"), [])

    def test_unknown_item_owner_fails(self):
        errors = check([{"id": "I1", "owner": "owner_x"}], {"owner_a"})
        self.assertTrue(any("'owner_x' not declared" in e for e in errors))

    def test_unknown_category_owner_fails(self):
        errors = check([{"id": "I1"}], {"owner_a"}, category_owner="owner_x")
        self.assertTrue(any("default_attributes.owner 'owner_x'" in e for e in errors))

    def test_category_alone_skips_the_check(self):
        self.assertEqual(check([{"id": "I1", "owner": "owner_x"}], None), [])


class ExampleCustomersTest(unittest.TestCase):
    def test_example_customers_validate(self):
        for name in ("example_customer", "example_3pl"):
            with self.subTest(customer=name):
                company = REPO_ROOT / "customers" / name / "company.yaml"
                self.assertEqual(validate_company_file(company, collect_element_ids()), [])

    def test_duplicate_owner_ids_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "company.yaml"
            path.write_text(yaml.safe_dump({"company": {
                "id": "x", "name": "X", "categories": [],
                "owners": [{"id": "owner_a", "name": "A"}, {"id": "owner_a", "name": "A2"}],
            }}), encoding="utf-8")
            errors = validate_company_file(path, collect_element_ids())
        self.assertTrue(any("duplicate owner ids" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
