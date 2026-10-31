import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from validate import (  # noqa: E402
    check_tracking,
    collect_element_ids,
    make_validator,
    resolve_tracking,
    validate_company_file,
)


ITEM_VALIDATOR = make_validator("item.schema.json")
CATEGORY_TRACKING = {
    "lot": "required",
    "expiry": {"tracked": True, "min_remaining_at_receipt_days": 90, "total_shelf_life_days": 365},
}


def category(tracking=CATEGORY_TRACKING):
    return {"category": {"id": "c", "default_attributes": {"tracking": tracking}}}


def check(items, packaged=frozenset(), tracking=CATEGORY_TRACKING):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "items.yaml"
        path.write_text(yaml.safe_dump({"items": items}), encoding="utf-8")
        return check_tracking(path, category(tracking), set(packaged))


class TrackingSchemaTest(unittest.TestCase):
    def test_full_tracking_block_is_valid(self):
        item = {"id": "I1", "tracking": {
            "lot": "optional",
            "expiry": {"tracked": True, "min_remaining_at_receipt_days": 10, "total_shelf_life_days": 100},
            "serial": {"capture": "outbound"},
        }}
        self.assertEqual(list(ITEM_VALIDATOR.iter_errors(item)), [])

    def test_unknown_lot_level_is_rejected(self):
        self.assertTrue(list(ITEM_VALIDATOR.iter_errors({"id": "I1", "tracking": {"lot": "sometimes"}})))

    def test_unknown_tracking_field_is_rejected(self):
        self.assertTrue(list(ITEM_VALIDATOR.iter_errors({"id": "I1", "tracking": {"expiry_kind": "use_by"}})))

    def test_negative_days_are_rejected(self):
        item = {"id": "I1", "tracking": {"expiry": {"min_remaining_at_receipt_days": -1}}}
        self.assertTrue(list(ITEM_VALIDATOR.iter_errors(item)))


class ResolveTrackingTest(unittest.TestCase):
    def test_defaults_without_any_tracking(self):
        self.assertEqual(resolve_tracking({"id": "I1"}, None), {
            "lot": "none", "expiry": {"tracked": False}, "serial": {"capture": "none"},
        })

    def test_item_inherits_category_values(self):
        resolved = resolve_tracking({"id": "I1"}, CATEGORY_TRACKING)
        self.assertEqual(resolved["lot"], "required")
        self.assertEqual(resolved["expiry"]["total_shelf_life_days"], 365)

    def test_item_overrides_single_sub_field(self):
        item = {"id": "I1", "tracking": {"expiry": {"min_remaining_at_receipt_days": 30}}}
        expiry = resolve_tracking(item, CATEGORY_TRACKING)["expiry"]
        self.assertEqual(expiry, {"tracked": True, "min_remaining_at_receipt_days": 30, "total_shelf_life_days": 365})

    def test_switching_expiry_off_drops_inherited_days(self):
        item = {"id": "I1", "tracking": {"expiry": {"tracked": False}}}
        self.assertEqual(resolve_tracking(item, CATEGORY_TRACKING)["expiry"], {"tracked": False})


class CheckTrackingTest(unittest.TestCase):
    def test_inherited_values_pass(self):
        self.assertEqual(check([{"id": "I1"}]), [])

    def test_days_without_tracked_expiry_fail(self):
        items = [{"id": "I1", "tracking": {"expiry": {"tracked": False, "total_shelf_life_days": 10}}}]
        self.assertTrue(any("not tracked" in e for e in check(items)))

    def test_receipt_minimum_above_shelf_life_fails(self):
        items = [{"id": "I1", "tracking": {"expiry": {"min_remaining_at_receipt_days": 400}}}]
        self.assertTrue(any("exceeds total_shelf_life_days" in e for e in check(items)))

    def test_serial_without_packaging_fails(self):
        items = [{"id": "I1", "tracking": {"serial": {"capture": "always"}}}]
        self.assertTrue(any("needs a packaging uom_hierarchy" in e for e in check(items)))

    def test_serial_with_packaging_passes(self):
        items = [{"id": "I1", "tracking": {"serial": {"capture": "outbound"}}}]
        self.assertEqual(check(items, packaged={"I1"}), [])


class ExampleCustomerTest(unittest.TestCase):
    def test_example_customer_validates(self):
        company = REPO_ROOT / "customers" / "example_customer" / "company.yaml"
        self.assertEqual(validate_company_file(company, collect_element_ids()), [])


if __name__ == "__main__":
    unittest.main()
