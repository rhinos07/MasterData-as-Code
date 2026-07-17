# Entity Glossary

## Organizational Hierarchy

| Term | Meaning |
|---|---|
| `company` | Top-level tenant/organization (`company.yaml`). Lists one or more `category` files. |
| `category` | A product category/family belonging to a company (`category.yaml`). Imports its own `structure/` and `strategies/`, and carries `default_attributes` items inherit unless they override them. |

A company can have multiple categories, and each category groups one or
more items - **Company → Category → Item**. `tools/validate.py` accepts
a path at either level and cascades validation downward automatically.

## Structure

| Term | Meaning |
|---|---|
| `item` | A single article/SKU's physical master facts (`structure/items.yaml`): id, description, dimensions, weight, `hazmat_classes` (references `elements/hazmat_classes.yaml`), `default_uom`. `default_uom` may be omitted to inherit the category's `default_attributes.default_uom` - `tools/compile.py` resolves this; `tools/validate.py` errors if neither is set. |
| `packaging` | One item's `each → case → pallet` conversion hierarchy (`structure/packaging.yaml`), ordered smallest-to-largest. Each step's `quantity_of_previous` is how many of the prior uom make up one of this uom; `packaging_material` references `elements/packaging_materials.yaml`. |

## Process Rules

| Term | Meaning |
|---|---|
| `sourcing` rule | Preferred/alternate supplier(s) for an item, lead time, minimum order quantity (`strategies/sourcing.yaml`). Independent of packaging/UOM facts - same structure-vs-strategies separation used elsewhere in this family. |
| `lifecycle` rule | An item's status (`active`/`seasonal`/`discontinued`), optional recurring `season_window` (required when `seasonal`), and optional `substitute_item_id` offered when the item is unavailable (`strategies/lifecycle.yaml`). |

## Inheritance (`default_attributes`)

`category.default_attributes` carries values every item in that category
inherits unless it sets its own - the same pattern
`Topology-as-Code`'s `storage_type.default_attributes` →
`storage_point` exceptions uses. Currently only `default_uom` is
modeled this way; `tools/compile.py` performs the actual merge (item's
own value wins, falls back to the category's). `tools/validate.py` only
checks that *some* value resolves - it does not perform the merge
itself, mirroring how `Topology-as-Code` keeps merge logic in
`compile.py`, not `validate.py`.

## Cross-Repo References

| Field | References |
|---|---|
| `OrderOrchestration-as-Code`'s `material_request.item_id` | This repo's `structure/items.yaml` `id` |
| `Allocation-as-Code`'s `search_rule.applies_to.category`/`item_id` | This repo's `category.id` / `structure/items.yaml` `id` |
| `structure/packaging.yaml`'s `item_id` | This repo's own `structure/items.yaml` `id` (same category) |

None of these are cross-checked by any repo's `tools/validate.py` - same
category of gap every sibling repo already has against every other one
(see each repo's own README "Open Validation Gaps"/"Next Steps"). Only
`WMS-POC` has, so far, implemented an actual cross-repo check (target-id
reachability against `Topology-as-Code`) - see its README "Findings".

## What This Repo Is Not

It does not track live inventory, stock levels, or batch/lot instances -
that's runtime state in the WMS/ERP (here, KCC). It does not define
warehouse structure or movement rules (`Topology-as-Code`). It does not
define how an order gets split or which workflow that triggers
(`OrderOrchestration-as-Code`). It does not define how a stock search is
configured (`Allocation-as-Code`). This repo only defines what an item
*is* - its physical facts, how it's packaged/converted between units,
and the (slower-changing) business rules for sourcing and lifecycle
state. Analogous to Terraform: the code describes the item's master
facts, not any single unit's current stock position.
