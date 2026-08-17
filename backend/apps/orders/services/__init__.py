"""Order and quote use cases.

Re-exported here so callers keep importing `apps.orders.services`.
"""

from apps.orders.services.orders import (
    apply_discount,
    cancel_order,
    get_order_for_tenant,
    next_order_number,
    place_order,
    transition_order,
)
from apps.orders.services.quotes import (
    build_addon_quote,
    build_quote,
    claim_quote,
    get_quote_for_request,
)

__all__ = [
    "build_quote",
    "build_addon_quote",
    "claim_quote",
    "get_quote_for_request",
    "place_order",
    "transition_order",
    "cancel_order",
    "apply_discount",
    "get_order_for_tenant",
    "next_order_number",
]
