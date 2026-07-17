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

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas"
ELEMENTS_DIR = REPO_ROOT / "elements"

ELEMENT_CATALOGS = {
    "uom_types.yaml": ("uom-type.schema.json", "uom_types"),
    "packaging_materials.yaml": ("packaging-material.schema.json", "packaging_materials"),
    "hazmat_classes.yaml": ("hazmat-class.schema.json", "hazmat_classes"),
}


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
    category_default_uom = (category_data.get("category", {}).get("default_attributes") or {}).get("default_uom")

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

    return errors


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


def validate_category_file(category_file: Path, element_ids: dict[str, set[str]] = {}) -> list[str]:
    """Validates a single category-level category.yaml and everything it imports."""
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

    if "packaging.yaml" in imports:
        all_errors += check_packaging_refs(imports["packaging.yaml"], item_ids, element_ids)
    if "sourcing.yaml" in imports:
        all_errors += check_item_id_refs(imports["sourcing.yaml"], "sourcing", item_ids)
    if "lifecycle.yaml" in imports:
        all_errors += check_item_id_refs(imports["lifecycle.yaml"], "lifecycle", item_ids, extra_fields=["substitute_item_id"])

    return all_errors


def validate_company_file(company_file: Path, element_ids: dict[str, set[str]] = {}) -> list[str]:
    """Validates a company.yaml and cascades into every category it lists."""
    all_errors = validate_file(company_file, "company.schema.json")

    for category_file in collect_relative_refs(company_file, "company", "categories"):
        all_errors += validate_category_file(category_file, element_ids)

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
