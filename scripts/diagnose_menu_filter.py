from __future__ import annotations

from collections import Counter
from datetime import date

from src.app.web_server import (
    DEFAULT_MENU_STATE_PATH,
    DEFAULT_PREVIOUS_ORDERS_DIR,
    DEFAULT_SALES_PATH,
    build_culinary_strategy_payload,
    build_menu_coverage,
)
from src.domain.menu_catalog import (
    apply_menu_state,
    build_menu_catalog,
    enabled_menu_names,
    load_menu_state,
)
from scripts.analyze_culinary_strategy import extract_items, normalize_name, read_xlsx


def main() -> int:
    menu_state = load_menu_state(DEFAULT_MENU_STATE_PATH)
    menu = apply_menu_state(build_menu_catalog(DEFAULT_PREVIOUS_ORDERS_DIR), menu_state)
    enabled = enabled_menu_names(menu)
    own = {item.normalized_name for item in menu if item.own_production}
    disabled = {item.normalized_name for item in menu if not item.enabled}
    strategy = build_culinary_strategy_payload()
    if strategy is None:
        print("NO_STRATEGY")
        return 1
    period_start, period_end = str(strategy["period"]).split("..", 1)
    sales_items = extract_items(
        read_xlsx(DEFAULT_SALES_PATH),
        date.fromisoformat(period_start),
        date.fromisoformat(period_end),
    )
    coverage = build_menu_coverage(sales_items, menu)

    print("MENU_DIR", DEFAULT_PREVIOUS_ORDERS_DIR)
    print("MENU_TOTAL", len(menu))
    print("MENU_ENABLED_FOR_ORDER", len(enabled))
    print("MENU_OWN_PRODUCTION", len(own))
    print("MENU_DISABLED", len(disabled))
    print("SALES_SKU_TOTAL", len(sales_items))
    print("SALES_IN_MENU_QTY", coverage["in_menu"]["quantity"])
    print("SALES_OWN_QTY", coverage["own_production"]["quantity"])
    print("SALES_OUTSIDE_MENU_QTY", coverage["outside_menu"]["quantity"])
    print("SALES_DISABLED_QTY", coverage["disabled"]["quantity"])
    print("CURRENT_ORDER_TOTAL", strategy["future_orders"][0]["total_quantity"])
    print("CURRENT_ORDER_ROWS", len(strategy["future_orders"][0]["rows"]))
    print("CURRENT_ORDER_NAMES", "; ".join(item["name"] for item in strategy["future_orders"][0]["rows"][:20]))

    by_type = Counter("own" if item.own_production else "supplier" for item in menu)
    print("MENU_TYPE_COUNTS", dict(by_type))

    print("TOP_OWN_SALES")
    for row in coverage["own_production"]["rows"][:20]:
        print(row["quantity"], row["name"])

    print("TOP_OUTSIDE_MENU_SALES")
    for row in coverage["outside_menu"]["rows"][:20]:
        print(row["quantity"], row["name"])

    print("SUPPLIER_MENU_ITEMS")
    for item in menu:
        if not item.own_production:
            print(item.times_ordered, item.average_order_quantity, item.name)

    print("OWN_MENU_ITEMS")
    for item in menu:
        if item.own_production:
            print(item.times_ordered, item.average_order_quantity, item.name)

    print("MENU_ITEMS_WITH_MATCHING_SALES")
    sales_names = {normalize_name(item.name) for item in sales_items}
    for item in menu:
        if item.normalized_name in sales_names:
            print("own" if item.own_production else "supplier", item.name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
