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
| `owner` | A stock owner declared in `company.yaml` `owners` (`id`, `name`). Referenced by `item.owner` / `category.default_attributes.owner`, and by `Allocation-as-Code` `applies_to.owner`. See "Stock Owners". |
| `item` | A single article/SKU's physical master facts (`structure/items.yaml`): id, description, dimensions, weight, `hazmat_classes` (references `elements/hazmat_classes.yaml`), `default_uom`. `default_uom` may be omitted to inherit the category's `default_attributes.default_uom` - `tools/compile.py` resolves this; `tools/validate.py` errors if neither is set. |
| `tracking` | An item's lot, expiry and serial obligations (`schemas/tracking.schema.json`, on the item and on `category.default_attributes.tracking`). `lot`: `none` / `optional` (captured when the supplier provides one) / `required`. `expiry.tracked`, `expiry.min_remaining_at_receipt_days` (minimum remaining shelf life to accept a delivery), `expiry.total_shelf_life_days` (derive the expiry date from a production date). `serial.capture`: `none` / `outbound` (goods issue only) / `always` (from goods receipt on); serial numbers are per base unit, the first entry of the item's `uom_hierarchy`. Modeled after myWMS `ItemData` (`lotMandatory`, `bestBeforeMandatory`, `shelflife`, `serialNoRecordType`). |
| `packaging` | One item's `each → case → pallet` conversion hierarchy (`structure/packaging.yaml`), ordered smallest-to-largest. Each step's `quantity_of_previous` is how many of the prior uom make up one of this uom; `packaging_material` references `elements/packaging_materials.yaml`. |
| `barcode` | A code on one packaging level (`uom_hierarchy[].barcodes`): `code`, `type` (`gtin` = GS1 GTIN-8/12/13/14 with verified check digit, `internal` = any owner- or warehouse-assigned code), optional `primary` (at most one per level). Scanning a code identifies item **and** packaging level, so the quantity follows from the hierarchy. Unique per stock owner across the whole company (single-owner company: across the company) - the same GTIN may exist once per owner, because the same goods of two owners are two items. Modeled after myWMS `ItemDataNumber`. |
| `load_unit_type` | A carrier (`elements/load_unit_types.yaml`): dimensions of the empty carrier, `max_weight` (design load for goods, without tare), `tare_weight`, `stackable`, `volume`. Referenced by `uom_hierarchy[].load_unit_type` - the carrier a packaging level is built on, which gives the item's default load unit per level; `tools/validate.py` checks the level's goods weight (item weight x base units) against `max_weight`. Owned here; `Topology-as-Code` keeps a pinned copy. |
| `storage_condition` | A storage condition class (`elements/storage_conditions.yaml`: `ambient`, `chilled`, `frozen`) with a temperature range in °C. Set on the item or inherited from `category.default_attributes.storage_condition`; omitted on both = no requirement. `Topology-as-Code` storage types reference the same ids (pinned copy) so putaway can match item and zone. |

## Process Rules

| Term | Meaning |
|---|---|
| `sourcing` rule | Preferred/alternate supplier(s) for an item, lead time, minimum order quantity (`strategies/sourcing.yaml`). Independent of packaging/UOM facts - same structure-vs-strategies separation used elsewhere in this family. |
| `lifecycle` rule | An item's status (`active`/`seasonal`/`discontinued`), optional recurring `season_window` (required when `seasonal`), and optional `substitute_item_id` offered when the item is unavailable (`strategies/lifecycle.yaml`). |

## Inheritance (`default_attributes`)

`category.default_attributes` carries values every item in that category
inherits unless it sets its own - the same pattern
`Topology-as-Code`'s `storage_type.default_attributes` →
`storage_point` exceptions uses. Three attributes are modeled this way:

- `default_uom`: `tools/compile.py` performs the merge (item's own value
  wins, falls back to the category's); `tools/validate.py` only checks
  that *some* value resolves.
- `tracking`: merged field by field, nested objects per sub-field - an
  item can override `expiry.min_remaining_at_receipt_days` alone and
  still inherit `expiry.tracked`. Unset fields fall back to `lot: none`,
  `expiry.tracked: false`, `serial.capture: none`. An item that sets
  `expiry.tracked: false` drops the category's inherited day values.
  Because `tools/validate.py` must check the *resolved* values (e.g.
  receipt minimum not above shelf life), the merge lives in one shared
  module, `tools/tracking.py`, used by both `compile.py` and
  `validate.py` - a second copy could drift.
- `owner`: item's own value wins, falls back to the category's
  `default_attributes.owner`; `tools/compile.py` writes the resolved
  owner into the artifact.

## Stock Owners

A company operates the warehouse; `owners` in `company.yaml` lists whose
stock it stores (e.g. the customers of a 3PL). Decided model: **each item
belongs to exactly one owner** (same as myWMS `ItemData.client`). The
same physical goods of two owners are two items, possibly with the same
GTIN. Lot, expiry and serial obligations therefore differ per owner
without extra logic.

| Company declares owners? | Items |
|---|---|
| No (single-owner warehouse) | carry no owner - nothing to configure |
| Yes | every item resolves to exactly one declared owner (own field or category default) |

`tools/validate.py` checks this when validating from `company.yaml`; a
category validated on its own skips it, because the owner list lives on
the company. Owner-specific search and putaway rules, owner-dedicated
zones and the no-mixing constraint live in `Allocation-as-Code`
(`applies_to.owner`, `allow_mixed_owners`). That stock of one owner is
never allocated to another owner's order is a runtime invariant, not
configuration.

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
