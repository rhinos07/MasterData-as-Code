# MasterData-as-Code

MasterData-as-Code: declarative, version-controlled description of
**item/article master data** - physical attributes, packaging/UOM
hierarchy, sourcing and lifecycle rules - as YAML, validated via CI.
This is the foundation the sibling repos below reference by item id.

## Related Projects

Part of a family of sibling "-as-Code" repos sharing the same declarative
pattern (JSON Schema validation, `structure/` vs. `strategies/`,
`elements/` catalogs):

| Repo | Covers |
|---|---|
| [`Topology-as-Code`](https://github.com/rhinos07/Topology-as-Code) | Physical warehouse structure, material-flow communication, movement/replenishment rules |
| [`OrderOrchestration-as-Code`](https://github.com/rhinos07/OrderOrchestration-as-Code) | How incoming orders are split, and which downstream workflow each split triggers |
| **MasterData-as-Code** (this repo) | Item/article master data, packaging/UOM hierarchy, sourcing & lifecycle rules |
| [`Allocation-as-Code`](https://github.com/rhinos07/Allocation-as-Code) | Stock-search configuration: search-zone sequence, selection strategy, constraints |

`Topology-as-Code`'s `elements/load_unit_types.yaml` is conceptually
packaging master data and a candidate to eventually move here (see
"Shared Vocabulary" below); all three sibling repos reference item/
category ids owned by this repo -
`OrderOrchestration-as-Code`'s `material_request.item_id`, and now also
`Allocation-as-Code`'s `search_rule.applies_to.category`/`item_id`.

## Core Principle

| Layer | What | Change Frequency | Who Changes It |
|---|---|---|---|
| `elements/` | Reusable catalogs (UOM types, packaging materials, hazmat classes) | very rarely | Architect/Compliance |
| `customers/<customer>/company.yaml` | Tenant/organization identity | very rarely (onboarding/offboarding) | Admin |
| `customers/<customer>/categories/<category>/category.yaml` | Product category/family identity | rarely | Merchandising Admin |
| `.../categories/<category>/structure/` | Item master: physical attributes, packaging/UOM hierarchy | rarely (per new item, shape is stable) | Merchandising, strict review |
| `.../categories/<category>/strategies/` | Sourcing and lifecycle rules | frequently | Procurement / Merchandising Ops, lenient review |

A company can have multiple product categories, and each category groups
one or more items - **Company → Category → Item**. A category also
carries shared `default_attributes` that individual items inherit unless
overridden (same pattern as `Topology-as-Code`'s `storage_type.default_attributes`
→ `storage_point` exceptions). This mirrors the same principle both
sibling repos use: a stable identity layer, then a `structure/` vs.
`strategies/` split by change frequency and reviewer.

**What this repo is not**: it does not track live inventory, stock
levels, or batch/lot instances (that's runtime state in the WMS/ERP -
here, KCC). It does not define warehouse structure or movement rules
(that's `Topology-as-Code`). It does not define how an order gets split
or which workflow that triggers (that's `OrderOrchestration-as-Code`).
This repo only defines: what an item *is* - its physical facts, how it's
packaged/converted between units, and the (slower-changing) business
rules for sourcing and lifecycle state. Analogous to Terraform: the code
describes the item's master facts, not any single unit's current stock
position.

## Repo Structure

```
master-data-definitions/
├── schemas/                  # JSON Schema for validating all YAML files
├── elements/                 # Reusable templates and catalogs
│   ├── uom_types.yaml               # Each/case/pallet/… base unit definitions
│   ├── packaging_materials.yaml     # Carton/tote/pallet carrier definitions
│   └── hazmat_classes.yaml          # Hazardous material / compliance classifications
├── customers/
│   └── <customer>/                          # = Company
│       ├── company.yaml                     # Top level, lists categories (and partners, see below)
│       └── categories/
│           └── <category>/                  # = Product category/family
│               ├── category.yaml            # Imports structure/strategies below
│               ├── structure/                       # Item facts (stable)
│               │   ├── items.yaml                   # Item master: id, dimensions, weight, hazmat class
│               │   └── packaging.yaml               # UOM/packaging hierarchy: each -> case -> pallet
│               └── strategies/                       # Process rules (changes often)
│                   ├── sourcing.yaml                 # Preferred/alternate supplier per item, lead times
│                   └── lifecycle.yaml                # Seasonal windows, active/discontinued, substitution
├── tools/
│   ├── validate.py          # Validation script (schema + consistency checks)
│   └── compile.py           # Expands any generator syntax into concrete
│                             #   item/UOM instances (build/ output)
├── docs/
│   └── entity-glossary.md
└── .github/workflows/validate.yaml   # CI pipeline
```

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Validates a company.yaml or category.yaml - cascades down to every
# category/item it references
python tools/validate.py customers/example_customer/company.yaml

# Expand any generator syntax into concrete item/packaging instances
# for one specific category
python tools/compile.py customers/example_customer/categories/beverages/category.yaml --output build/items.yaml
```

## Examples

- `customers/example_customer/categories/beverages/` - one category,
  four items: `ITEM_001`/`ITEM_002` (plain each→case→pallet hierarchy,
  `default_uom` inherited from the category's `default_attributes`),
  `ITEM_003` (seasonal - `strategies/lifecycle.yaml`'s `season_window`,
  substituted by `ITEM_002` out of season; also the item
  `Allocation-as-Code`'s `SEARCH_ITEM_003_FEFO` rule scopes to, since its
  short shelf life is exactly why that rule needs `FEFO`), and
  `ITEM_004` (hazmat-classified, case-only - `default_uom: "case"`
  overrides the category default). `ITEM_001`-`ITEM_003` are the same
  item ids `WMS-POC`'s scenarios and `Allocation-as-Code`'s examples
  already use, kept consistent on purpose rather than inventing new ids
  per repo.

## Core Concepts (Quick Reference)

- **category** — a product family/group (e.g. `beverages`,
  `electronics`) that items belong to; carries `default_attributes`
  items inherit unless they override them.
- **item** — a single article/SKU: id, description, physical dimensions,
  weight, `hazmat_classes` (references `elements/hazmat_classes.yaml`),
  default UOM.
- **packaging hierarchy / UOM conversion** — how many `each` per `case`,
  `case` per `pallet`, etc. for an item - referenced by
  `Topology-as-Code`'s `replenishment_strategy.unit_conversion` and by
  `OrderOrchestration-as-Code`'s split rules (e.g. "only split at case
  boundaries").
- **sourcing rule** — preferred and alternate supplier(s) for an item,
  lead times, minimum order quantities. Independent of packaging/UOM
  facts - same separation of concerns as structure vs. strategies
  elsewhere in this family of repos.
- **lifecycle rule** — seasonal availability windows, active →
  discontinued transitions, substitute-item rules for when an item goes
  out of stock/end-of-life.

Full glossary: [`docs/entity-glossary.md`](docs/entity-glossary.md)

## Shared Vocabulary with Topology-as-Code

`Topology-as-Code` already has an `elements/load_unit_types.yaml`
catalog (`pallet_euro`, `carton`, `autostore_bin`, `order_tote`, …)
describing physical carrier dimensions - conceptually this is packaging
*master data*, not warehouse structure. Once this repo exists, decide
whether `load_unit_types.yaml` should move here (and `Topology-as-Code`
references it) or stay duplicated. **Don't solve this prematurely** -
the two catalogs can drift apart safely for a while; only extract/merge
once real duplication actually causes pain.

## Open Scoping Question

Should trading-partner master data (customers, suppliers) live in this
repo alongside item master data, or in its own repo? Real-world MDM
often splits these (different owning teams - Procurement owns supplier
master, Sales/Credit owns customer master, Merchandising owns item
master). This README assumes item master only; if partners join later,
consider `customers/<customer>/partners/` as a parallel top-level
sibling to `categories/`, or a fully separate repo - same
separate-owners/separate-lifecycle reasoning used to keep
`OrderOrchestration-as-Code` and `Topology-as-Code` apart.

## Next Steps for This Repo

- [x] ~~Define `schemas/category.schema.json`, `schemas/item.schema.json`,
      `schemas/packaging.schema.json`~~ - done, plus `sourcing.schema.json`,
      `lifecycle.schema.json`, and the three `elements/` catalog schemas.
- [x] ~~Build `customers/example_customer/` with a worked category +
      items~~ - `categories/beverages/` with 4 items, see "Examples".
- [x] ~~`tools/validate.py` / `tools/compile.py`~~ - done. `compile.py`
      is intentionally small: it only resolves `default_uom` inheritance
      (item's own value, falling back to the category's
      `default_attributes.default_uom`) into a flat items artifact -
      there's no generator syntax to expand here, unlike
      `Topology-as-Code`'s `storage_point_generator`.
- [ ] Decide the shared-vocabulary question above (`load_unit_types.yaml`
      location) and the open scoping question (partners)
- [ ] Cross-check `OrderOrchestration-as-Code`'s `material_request.item_id`
      and `Allocation-as-Code`'s `search_rule.applies_to.category`/
      `item_id` against this repo's real ids - same category of gap
      every sibling repo already has against every other one (not
      implemented in any repo's own `tools/validate.py`; see
      `docs/entity-glossary.md` "Cross-Repo References"). `WMS-POC` is
      the one place in this family that has actually implemented a
      cross-repo check so far (target-id reachability against
      `Topology-as-Code`) - extending it to item ids would be the
      natural next step, not a change to this repo.

### Out of Scope (By Design)

- **Runtime state**: live stock levels, batch/lot instances, current
  inventory positions - these live in the WMS/ERP runtime database
  (KCC), not here.
- **Order structure and splitting**: that's `OrderOrchestration-as-Code`.
- **Warehouse structure and movement rules**: physical layout,
  storage_types, `movement_rules.yaml` - that's `Topology-as-Code`.
  This repo defines what an item *is*; where it's physically stored and
  how it moves is `Topology-as-Code`'s concern.
- **Pricing, promotions, tax classification** - commercial master data
  usually owned by a separate Pricing/Finance domain, not modeled here
  unless you decide otherwise.
