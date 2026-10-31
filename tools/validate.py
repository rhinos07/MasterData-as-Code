#!/usr/bin/env python3
"""
Validates a company.yaml or category.yaml (and everything it references,
cascading down the Company -> Category hierarchy) against the JSON
schemas in schemas/ and runs cross-file consistency checks.

Usage:
    python tools/validate.py customers/example_customer/company.yaml
    python tools/validate.py customers/example_customer/categories/beverages/category.yaml

Either level can be passed directly; validation cascades downward from
whichever level you start at.
"""

import sys
import json
from pathlib import Path

import yaml
from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tracking import EXPIRY_DAY_FIELDS, resolve_tracking  # noqa: E402
from barcodes import collect_barcodes, find_duplicate_codes, gtin_check_digit_ok  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas"
ELEMENTS_DIR = REPO_ROOT / "elements"

ELEMENT_CATALOGS = {
    "uom_types.yaml": ("uom-type.schema.json", "uom_types"),
    "packaging_materials.yaml": ("packaging-material.schema.json", "packaging_materials"),
    "hazmat_classes.yaml": ("hazmat-class.schema.json", "hazmat_classes"),
    "load_unit_types.yaml": ("load-unit-type.schema.json", "load_unit_types"),
    "storage_conditions.yaml": ("storage-condition.schema.json", "storage_conditions"),
}

MASS_TO_KG = {"kg": 1.0, "g": 0.001, "t": 1000.0}


def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_schema(name: str) -> dict:
    with open(SCHEMA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_schema_registry() -> Registry:
    """Pre-load all local schemas into a referencing.Registry, keyed by
    their $id, so cross-file $ref resolves correctly."""
    resources = []
    for schema_file in SCHEMA_DIR.glob("*.json"):
        schema_data = json.loads(schema_file.read_text(encoding="utf-8"))
        uri = schema_data.get("$id") or f"{SCHEMA_DIR.as_uri()}/{schema_file.name}"
        resources.append((uri, Resource.from_contents(schema_data, default_specification=DRAFT7)))
    return Registry().with_resources(resources)


SCHEMA_REGISTRY: Registry = _build_schema_registry()


def make_validator(schema_name: str) -> Draft7Validator:
    schema = load_schema(schema_name)
    return Draft7Validator(schema, registry=SCHEMA_REGISTRY)


def collect_imports(category_file: Path) -> list[Path]:
    data = load_yaml(category_file)
    imports = data.get("category", {}).get("imports", [])
    base_dir = category_file.parent
    return [base_dir / rel for rel in imports]


def collect_relative_refs(path: Path, root_key: str, list_key: str) -> list[Path]:
    data = load_yaml(path)
    refs = data.get(root_key, {}).get(list_key, [])
    base_dir = path.parent
    return [base_dir / rel for rel in refs]


def validate_file(path: Path, schema_name: str) -> list[str]:
    errors = []
    data = load_yaml(path)
    if data is None:
        return [f"{path}: File is empty or invalid."]

    validator = make_validator(schema_name)
    for err in validator.iter_errors(data):
        loc = " -> ".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{path}: [{loc}] {err.message}")
    return errors


def validate_list_items(path: Path, schema_name: str, list_key: str) -> list[str]:
    """Validates each item in data[list_key] against schema_name (item-level
    schema, not a wrapper)."""
    errors = []
    data = load_yaml(path)
    if data is None:
        return [f"{path}: File is empty or invalid."]

    validator = make_validator(schema_name)
    for item in data.get(list_key, []):
        for err in validator.iter_errors(item):
            key = item.get("id") or item.get("item_id", "?")
            errors.append(f"{path}: {list_key} '{key}': {err.message}")
    return errors


def collect_element_ids() -> dict[str, set[str]]:
    """Loads all element catalogs and returns a mapping of list_key -> set
    of known IDs. Missing catalog files are silently skipped."""
    ids: dict[str, set[str]] = {}
    for filename, (_schema_name, list_key) in ELEMENT_CATALOGS.items():
        catalog_file = ELEMENTS_DIR / filename
        if catalog_file.exists():
            data = load_yaml(catalog_file)
            if data:
                ids[list_key] = {
                    item.get("id") for item in data.get(list_key, []) if item.get("id")
                }
    return ids


def validate_element_catalog(path: Path, schema_name: str, list_key: str) -> list[str]:
    errors = []
    data = load_yaml(path)
    if data is None:
        return [f"{path}: File is empty or invalid."]
    validator = make_validator(schema_name)
    for item in data.get(list_key, []):
        for err in validator.iter_errors(item):
            errors.append(f"{path}: {list_key} '{item.get('id', '?')}': {err.message}")
    return errors


def check_item_refs(path: Path, category_data: dict, element_ids: dict[str, set[str]]) -> list[str]:
    """Checks items.yaml's default_uom/hazmat_classes against element
    catalogs, and that every item resolves a default_uom (own field or
    inherited from category.default_attributes)."""
    errors: list[str] = []
    data = load_yaml(path)
    if not data:
        return errors

    uom_ids = element_ids.get("uom_types", set())
    hazmat_ids = element_ids.get("hazmat_classes", set())
    category_defaults = category_data.get("category", {}).get("default_attributes") or {}
    category_default_uom = category_defaults.get("default_uom")
    category_condition = category_defaults.get("storage_condition")
    condition_ids = element_ids.get("storage_conditions", set())

    for item in data.get("items", []):
        item_id = item.get("id", "?")
        uom = item.get("default_uom") or category_default_uom
        if not uom:
            errors.append(f"{path}: item '{item_id}': no default_uom set and category has no default_attributes.default_uom to inherit")
        elif uom_ids and uom not in uom_ids:
            errors.append(f"{path}: item '{item_id}': default_uom '{uom}' not found in elements/uom_types.yaml")

        for hz in item.get("hazmat_classes", []):
            if hazmat_ids and hz not in hazmat_ids:
                errors.append(f"{path}: item '{item_id}': hazmat_classes '{hz}' not found in elements/hazmat_classes.yaml")

        condition = item.get("storage_condition") or category_condition
        if condition and condition_ids and condition not in condition_ids:
            errors.append(f"{path}: item '{item_id}': storage_condition '{condition}' not found in elements/storage_conditions.yaml")

    return errors


def check_tracking(path: Path, category_data: dict, packaged_item_ids: set[str]) -> list[str]:
    """Checks each item's resolved tracking obligations:
    - expiry day fields are only set when expiry is tracked,
    - min_remaining_at_receipt_days does not exceed total_shelf_life_days
      (otherwise no fresh delivery could ever be accepted),
    - a serial-tracked item has a packaging uom_hierarchy, because serial
      numbers are per base unit (the hierarchy's first entry)."""
    errors: list[str] = []
    data = load_yaml(path)
    if not data:
        return errors

    category_tracking = (
        category_data.get("category", {}).get("default_attributes") or {}
    ).get("tracking")

    for item in data.get("items", []):
        item_id = item.get("id", "?")
        tracking = resolve_tracking(item, category_tracking)
        expiry = tracking["expiry"]
        day_fields = [f for f in EXPIRY_DAY_FIELDS if f in expiry]

        if not expiry.get("tracked") and day_fields:
            errors.append(
                f"{path}: item '{item_id}': tracking.expiry {', '.join(day_fields)} set but expiry is not tracked"
            )

        minimum = expiry.get("min_remaining_at_receipt_days")
        total = expiry.get("total_shelf_life_days")
        if minimum is not None and total is not None and minimum > total:
            errors.append(
                f"{path}: item '{item_id}': tracking.expiry.min_remaining_at_receipt_days ({minimum}) exceeds total_shelf_life_days ({total}) - no delivery could ever be accepted"
            )

        if tracking["serial"]["capture"] != "none" and item_id not in packaged_item_ids:
            errors.append(
                f"{path}: item '{item_id}': serial capture '{tracking['serial']['capture']}' needs a packaging uom_hierarchy in structure/packaging.yaml (serial numbers are per base unit)"
            )

    return errors


def check_item_owners(path: Path, category_data: dict, owner_ids: set[str] | None) -> list[str]:
    """Checks each item's resolved owner (own field, else category
    default_attributes.owner) against the company's declared owners.
    owner_ids None = category validated on its own, company unknown: the
    check is skipped. Empty set = company declares no owners (single-owner
    warehouse): no item may carry one. Non-empty = every item must
    resolve to one of them."""
    errors: list[str] = []
    if owner_ids is None:
        return errors
    data = load_yaml(path)
    if not data:
        return errors

    category = category_data.get("category", {})
    category_owner = (category.get("default_attributes") or {}).get("owner")
    if category_owner and category_owner not in owner_ids:
        errors.append(
            f"{path}: category '{category.get('id', '?')}': default_attributes.owner '{category_owner}' not declared in company.yaml owners"
        )

    for item in data.get("items", []):
        item_id = item.get("id", "?")
        owner = item.get("owner") or category_owner
        if not owner_ids:
            if owner:
                errors.append(
                    f"{path}: item '{item_id}': owner '{owner}' set but company.yaml declares no owners"
                )
        elif not owner:
            errors.append(
                f"{path}: item '{item_id}': no owner set and category has no default_attributes.owner, but company.yaml declares owners"
            )
        elif item.get("owner") and owner not in owner_ids:
            errors.append(
                f"{path}: item '{item_id}': owner '{owner}' not declared in company.yaml owners"
            )
    return errors


def check_packaging_refs(path: Path, item_ids: set[str], element_ids: dict[str, set[str]]) -> list[str]:
    """Checks packaging.yaml's item_id -> items.yaml, uom_hierarchy[].uom
    -> uom_types.yaml, and .packaging_material -> packaging_materials.yaml."""
    errors: list[str] = []
    data = load_yaml(path)
    if not data:
        return errors

    uom_ids = element_ids.get("uom_types", set())
    material_ids = element_ids.get("packaging_materials", set())

    for entry in data.get("packaging", []):
        item_id = entry.get("item_id", "?")
        if item_ids and item_id not in item_ids:
            errors.append(f"{path}: packaging item_id '{item_id}' not found in structure/items.yaml")

        for i, step in enumerate(entry.get("uom_hierarchy", [])):
            uom = step.get("uom")
            if uom and uom_ids and uom not in uom_ids:
                errors.append(f"{path}: packaging '{item_id}' uom_hierarchy[{i}]: uom '{uom}' not found in elements/uom_types.yaml")
            material = step.get("packaging_material")
            if material and material_ids and material not in material_ids:
                errors.append(f"{path}: packaging '{item_id}' uom_hierarchy[{i}]: packaging_material '{material}' not found in elements/packaging_materials.yaml")

            load_unit = step.get("load_unit_type")
            lu_ids = element_ids.get("load_unit_types", set())
            if load_unit and lu_ids and load_unit not in lu_ids:
                errors.append(f"{path}: packaging '{item_id}' uom_hierarchy[{i}]: load_unit_type '{load_unit}' not found in elements/load_unit_types.yaml")

            barcodes = step.get("barcodes", [])
            for barcode in barcodes:
                code = str(barcode.get("code", ""))
                if barcode.get("type") == "gtin" and code.isdigit() and not gtin_check_digit_ok(code):
                    errors.append(f"{path}: packaging '{item_id}' uom_hierarchy[{i}]: GTIN '{code}' has a wrong check digit")
            if sum(1 for b in barcodes if b.get("primary")) > 1:
                errors.append(f"{path}: packaging '{item_id}' uom_hierarchy[{i}]: more than one barcode marked primary")

    return errors


def check_load_unit_payload(path: Path, items_data: dict | None) -> list[str]:
    """For each packaging level with a load_unit_type: goods weight of the
    level (item weight x base units in that level) must not exceed the
    carrier's max_weight. Tare is not added - max_weight is the carrier's
    design load for goods (schemas/load-unit-type.schema.json). Skipped
    where the item has no weight or the carrier no max_weight."""
    errors: list[str] = []
    data = load_yaml(path)
    if not data:
        return errors
    catalog = load_yaml(ELEMENTS_DIR / "load_unit_types.yaml") or {}
    carriers = {c["id"]: c for c in catalog.get("load_unit_types", []) if c.get("id")}
    weights = {}
    for item in (items_data or {}).get("items", []):
        weight = item.get("weight")
        if weight and weight.get("unit") in MASS_TO_KG:
            weights[item.get("id")] = weight["value"] * MASS_TO_KG[weight["unit"]]

    for entry in data.get("packaging", []):
        item_id = entry.get("item_id", "?")
        base_units = 1
        for i, step in enumerate(entry.get("uom_hierarchy", [])):
            if i > 0:
                base_units *= step.get("quantity_of_previous", 1)
            carrier = carriers.get(step.get("load_unit_type"))
            if not carrier or item_id not in weights or not carrier.get("max_weight"):
                continue
            limit = carrier["max_weight"]["value"] * MASS_TO_KG.get(carrier["max_weight"]["unit"], 1.0)
            goods = weights[item_id] * base_units
            if goods > limit + 1e-9:
                errors.append(
                    f"{path}: packaging '{item_id}' uom_hierarchy[{i}] ({step.get('uom')}): goods weight {goods:g} kg "
                    f"({base_units} x {weights[item_id]:g} kg) exceeds load_unit_type '{carrier['id']}' max_weight {limit:g} kg"
                )
    return errors


def category_barcode_records(category_file: Path) -> list[dict]:
    """All barcodes of a category with each item's resolved owner (own
    field, else category default_attributes.owner, else None)."""
    category = (load_yaml(category_file) or {}).get("category", {})
    category_owner = (category.get("default_attributes") or {}).get("owner")
    item_owners: dict[str, str | None] = {}
    records: list[dict] = []
    imported = {p.name: p for p in collect_imports(category_file) if p.exists()}
    if "items.yaml" in imported:
        for item in (load_yaml(imported["items.yaml"]) or {}).get("items", []):
            item_owners[item.get("id")] = item.get("owner") or category_owner
    if "packaging.yaml" in imported:
        records = collect_barcodes(load_yaml(imported["packaging.yaml"]), item_owners, imported["packaging.yaml"])
    return records


def check_item_id_refs(path: Path, list_key: str, item_ids: set[str], extra_fields: list[str] = ()) -> list[str]:
    """Generic check for a file whose entries have item_id (+ optional
    extra id fields, e.g. substitute_item_id) referencing items.yaml."""
    errors: list[str] = []
    data = load_yaml(path)
    if not data:
        return errors

    for entry in data.get(list_key, []):
        for field in ("item_id", *extra_fields):
            ref = entry.get(field)
            if ref and item_ids and ref not in item_ids:
                errors.append(f"{path}: {list_key} '{entry.get('item_id', '?')}': {field} '{ref}' not found in structure/items.yaml")

    return errors


def validate_category_file(
    category_file: Path,
    element_ids: dict[str, set[str]] = {},
    owner_ids: set[str] | None = None,
) -> list[str]:
    """Validates a single category-level category.yaml and everything it
    imports. owner_ids = the company's declared owners when called from
    validate_company_file, None when the category is validated alone."""
    if not category_file.exists():
        return [f"category file missing: {category_file}"]

    all_errors = validate_file(category_file, "category.schema.json")
    category_data = load_yaml(category_file) or {}

    imports: dict[str, Path] = {}
    for imported in collect_imports(category_file):
        if not imported.exists():
            all_errors.append(f"{category_file}: imported file missing: {imported}")
            continue

        imports[imported.name] = imported
        name = imported.name
        if name == "items.yaml":
            all_errors += validate_list_items(imported, "item.schema.json", "items")
        elif name == "packaging.yaml":
            all_errors += validate_list_items(imported, "packaging.schema.json", "packaging")
        elif name == "sourcing.yaml":
            all_errors += validate_list_items(imported, "sourcing.schema.json", "sourcing")
        elif name == "lifecycle.yaml":
            all_errors += validate_list_items(imported, "lifecycle.schema.json", "lifecycle")
        else:
            data = load_yaml(imported)
            if data is None:
                all_errors.append(f"{imported}: File is empty or invalid.")

    item_ids: set[str] = set()
    if "items.yaml" in imports:
        all_errors += check_item_refs(imports["items.yaml"], category_data, element_ids)
        items_data = load_yaml(imports["items.yaml"]) or {}
        item_ids = {i.get("id") for i in items_data.get("items", []) if i.get("id")}

    packaged_item_ids: set[str] = set()
    if "packaging.yaml" in imports:
        all_errors += check_packaging_refs(imports["packaging.yaml"], item_ids, element_ids)
        all_errors += check_load_unit_payload(
            imports["packaging.yaml"], load_yaml(imports["items.yaml"]) if "items.yaml" in imports else None
        )
        packaging_data = load_yaml(imports["packaging.yaml"]) or {}
        packaged_item_ids = {
            p.get("item_id") for p in packaging_data.get("packaging", [])
            if p.get("item_id") and p.get("uom_hierarchy")
        }
    if "items.yaml" in imports:
        all_errors += check_tracking(imports["items.yaml"], category_data, packaged_item_ids)
        all_errors += check_item_owners(imports["items.yaml"], category_data, owner_ids)

    # Validated on its own (no company context): check barcode
    # uniqueness within this category. From validate_company_file the
    # same check runs once across all categories instead.
    if owner_ids is None:
        all_errors += find_duplicate_codes(category_barcode_records(category_file))
    if "sourcing.yaml" in imports:
        all_errors += check_item_id_refs(imports["sourcing.yaml"], "sourcing", item_ids)
    if "lifecycle.yaml" in imports:
        all_errors += check_item_id_refs(imports["lifecycle.yaml"], "lifecycle", item_ids, extra_fields=["substitute_item_id"])

    return all_errors


def validate_company_file(company_file: Path, element_ids: dict[str, set[str]] = {}) -> list[str]:
    """Validates a company.yaml and cascades into every category it lists."""
    all_errors = validate_file(company_file, "company.schema.json")

    owners = (load_yaml(company_file) or {}).get("company", {}).get("owners") or []
    owner_list = [o.get("id") for o in owners if o.get("id")]
    duplicates = sorted({o for o in owner_list if owner_list.count(o) > 1})
    if duplicates:
        all_errors.append(f"{company_file}: duplicate owner ids: {duplicates}")
    owner_ids = set(owner_list)

    barcode_records: list[dict] = []
    for category_file in collect_relative_refs(company_file, "company", "categories"):
        all_errors += validate_category_file(category_file, element_ids, owner_ids)
        if category_file.exists():
            barcode_records += category_barcode_records(category_file)

    # Barcodes are unique per owner across the whole company - the same
    # GTIN may exist once per owner (Variante A: same goods of two owners
    # are two items).
    all_errors += find_duplicate_codes(barcode_records)

    return all_errors


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(argv) != 2:
        print("Usage: python tools/validate.py <path-to-company|category.yaml>")
        return 2

    target_file = Path(argv[1]).resolve()
    if not target_file.exists():
        print(f"File not found: {target_file}")
        return 2

    all_errors: list[str] = []

    for filename, (schema_name, list_key) in ELEMENT_CATALOGS.items():
        catalog_file = ELEMENTS_DIR / filename
        if catalog_file.exists():
            all_errors += validate_element_catalog(catalog_file, schema_name, list_key)

    element_ids = collect_element_ids()

    data = load_yaml(target_file)
    if data is None:
        all_errors.append(f"{target_file}: File is empty or invalid.")
    elif "company" in data:
        all_errors += validate_company_file(target_file, element_ids)
    elif "category" in data:
        all_errors += validate_category_file(target_file, element_ids)
    else:
        all_errors.append(
            f"{target_file}: unrecognized root key (expected one of "
            f"'company', 'category')."
        )

    if all_errors:
        print(f"❌ {len(all_errors)} validation errors found:\n")
        for e in all_errors:
            print(f"  - {e}")
        return 1

    print("✅ Validation successful.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
