#!/usr/bin/env python3
"""
Resolves each item's default_uom (own value, or inherited from the
category's default_attributes) into a flat, concrete items artifact.
Run tools/validate.py first; this script assumes schema-valid input.

Usage:
    python tools/compile.py customers/example_customer/categories/beverages/category.yaml --output build/items.yaml
"""

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import collect_imports, load_yaml  # noqa: E402

# Versioned independently of the source api_version: a consumer of the
# compiled artifact is affected by changes to the artifact's own shape, not
# by every change to the authoring schemas. Same split Topology-as-Code
# makes between api_version and artifact_api_version.
ARTIFACT_API_VERSION = "masterdata-as-code/artifact-v1"


def compile_category(category_file: Path) -> list[dict]:
    category_data = load_yaml(category_file)["category"]
    category_default_uom = (category_data.get("default_attributes") or {}).get("default_uom")

    items: list[dict] = []
    for imported in collect_imports(category_file):
        if imported.name != "items.yaml":
            continue
        for item in (load_yaml(imported) or {}).get("items", []):
            compiled = dict(item)
            compiled["default_uom"] = item.get("default_uom") or category_default_uom
            compiled["category"] = category_data["id"]
            items.append(compiled)

    return items


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("category_file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv[1:])

    items = compile_category(args.category_file)
    source_api_version = load_yaml(args.category_file)["api_version"]

    artifact = {
        "api_version": source_api_version,
        "artifact_api_version": ARTIFACT_API_VERSION,
        "items": items,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        yaml.dump(artifact, f, sort_keys=False, allow_unicode=True)

    print(f"✅ Wrote {len(items)} compiled item(s) to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
