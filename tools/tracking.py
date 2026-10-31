"""
Field-by-field merge of an item's tracking obligations with its
category's default_attributes.tracking. Lives in its own module because
both tools/compile.py (writes the resolved values into the artifact) and
tools/validate.py (checks the resolved values) need the identical merge -
a second copy could drift.
"""

TRACKING_DEFAULTS = {
    "lot": "none",
    "expiry": {"tracked": False},
    "serial": {"capture": "none"},
}
EXPIRY_DAY_FIELDS = ("min_remaining_at_receipt_days", "total_shelf_life_days")


def resolve_tracking(item: dict, category_tracking: dict | None) -> dict:
    """Merges tracking obligations field by field: item value, else
    category.default_attributes.tracking value, else TRACKING_DEFAULTS.
    Nested objects (expiry, serial) merge per sub-field, so an item can
    override only expiry.min_remaining_at_receipt_days and still inherit
    expiry.tracked. Shared by validate.py (checks) and compile.py
    (artifact), so both see the same resolved values."""
    own = item.get("tracking") or {}
    inherited = category_tracking or {}
    resolved: dict = {}
    for key, default in TRACKING_DEFAULTS.items():
        if isinstance(default, dict):
            resolved[key] = {**default, **(inherited.get(key) or {}), **(own.get(key) or {})}
        else:
            resolved[key] = own.get(key, inherited.get(key, default))

    # An item that switches expiry off must not keep the category's day
    # fields: they would only describe a date it no longer carries. Day
    # fields the item sets itself stay, so check_tracking can flag them.
    own_expiry = own.get("expiry") or {}
    if own_expiry.get("tracked") is False:
        for field in EXPIRY_DAY_FIELDS:
            if field not in own_expiry:
                resolved["expiry"].pop(field, None)
    return resolved
