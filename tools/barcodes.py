"""
Barcode helpers shared by tools/validate.py and the tests: the GS1 GTIN
check digit and the collection of all codes of a category with their
resolved owner, so uniqueness can be checked per owner across a company.
"""

from pathlib import Path


def gtin_check_digit_ok(code: str) -> bool:
    """GS1 mod-10 check for GTIN-8/12/13/14: from the right, the digits
    before the check digit are weighted 3, 1, 3, 1, ...; the check digit
    brings the weighted sum to a multiple of 10."""
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in code]
    body, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def collect_barcodes(packaging_data: dict, item_owners: dict[str, str | None], source: Path) -> list[dict]:
    """Flattens packaging.yaml barcodes into records
    {code, owner, item_id, uom, source}; owner None = single-owner company."""
    records = []
    for entry in (packaging_data or {}).get("packaging", []):
        item_id = entry.get("item_id", "?")
        for step in entry.get("uom_hierarchy", []):
            for barcode in step.get("barcodes", []):
                records.append({
                    "code": barcode.get("code"),
                    "owner": item_owners.get(item_id),
                    "item_id": item_id,
                    "uom": step.get("uom"),
                    "source": source,
                })
    return records


def find_duplicate_codes(records: list[dict]) -> list[str]:
    """One message per (owner, code) used more than once - on two items or
    on two packaging levels of the same item."""
    seen: dict[tuple, dict] = {}
    errors = []
    for record in records:
        key = (record["owner"], record["code"])
        first = seen.get(key)
        if first is None:
            seen[key] = record
            continue
        scope = f"owner '{record['owner']}'" if record["owner"] else "the company"
        errors.append(
            f"{record['source']}: barcode '{record['code']}' on {record['item_id']}/{record['uom']} "
            f"already used on {first['item_id']}/{first['uom']} within {scope}"
        )
    return errors
