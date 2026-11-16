from __future__ import annotations

from dataclasses import dataclass
from math import ceil


def is_culinary_category(category: str) -> bool:
    normalized = ' '.join(category.casefold().replace('ё', 'е').split())
    return normalized.startswith('кулинария') or normalized in {
        'супы', 'горячее', 'салаты', 'завтраки', 'роллы',
    }


@dataclass(frozen=True)
class CulinaryMenuItem:
    sku: str
    name: str
    category: str
    order_multiple: int
    unit_cost: float
    shelf_life_days: int


@dataclass(frozen=True)
class CulinarySalesPeriod:
    sku: str
    sold_quantity: int
    waste_quantity: int = 0


@dataclass(frozen=True)
class CulinaryStock:
    sku: str
    quantity: int


@dataclass(frozen=True)
class CulinaryOrderRecommendation:
    sku: str
    name: str
    category: str
    forecast_quantity: int
    stock_quantity: int
    safety_stock: int
    recommended_quantity: int
    estimated_cost: float
    review_reason: str


def recommend_culinary_orders(
    menu: list[CulinaryMenuItem],
    sales_periods: list[CulinarySalesPeriod],
    stocks: list[CulinaryStock],
    forecast_periods: int = 2,
    safety_rate: float = 0.15,
) -> list[CulinaryOrderRecommendation]:
    if forecast_periods <= 0:
        raise ValueError("Горизонт прогноза должен быть больше нуля")
    if safety_rate < 0:
        raise ValueError("Страховой запас не может быть отрицательным")

    sales_by_sku = _group_sales(sales_periods)
    stock_by_sku = {stock.sku: stock.quantity for stock in stocks}
    recommendations: list[CulinaryOrderRecommendation] = []

    for item in menu:
        recent_sales = sales_by_sku.get(item.sku, [])
        average_sales = _average(recent_sales)
        forecast_quantity = ceil(average_sales * forecast_periods)
        safety_stock = ceil(forecast_quantity * safety_rate)
        stock_quantity = stock_by_sku.get(item.sku, 0)
        raw_order = max(0, forecast_quantity + safety_stock - stock_quantity)
        recommended_quantity = _round_up(raw_order, item.order_multiple)
        review_reason = _review_reason(item, recent_sales, forecast_quantity, stock_quantity)

        recommendations.append(
            CulinaryOrderRecommendation(
                sku=item.sku,
                name=item.name,
                category=item.category,
                forecast_quantity=forecast_quantity,
                stock_quantity=stock_quantity,
                safety_stock=safety_stock,
                recommended_quantity=recommended_quantity,
                estimated_cost=recommended_quantity * item.unit_cost,
                review_reason=review_reason,
            )
        )

    return sorted(
        recommendations,
        key=lambda recommendation: (
            recommendation.category,
            recommendation.name,
        ),
    )


def _group_sales(sales_periods: list[CulinarySalesPeriod]) -> dict[str, list[int]]:
    grouped: dict[str, list[int]] = {}
    for period in sales_periods:
        if period.sold_quantity < 0:
            raise ValueError("Продажи не могут быть отрицательными")
        if period.waste_quantity < 0:
            raise ValueError("Списания не могут быть отрицательными")
        grouped.setdefault(period.sku, []).append(period.sold_quantity + period.waste_quantity)
    return grouped


def _average(values: list[int]) -> float:
    if not values:
        return 0
    return sum(values) / len(values)


def _round_up(value: int, multiple: int) -> int:
    if multiple <= 0:
        raise ValueError("Кратность заказа должна быть больше нуля")
    if value == 0:
        return 0
    return ceil(value / multiple) * multiple


def _review_reason(
    item: CulinaryMenuItem,
    recent_sales: list[int],
    forecast_quantity: int,
    stock_quantity: int,
) -> str:
    if not recent_sales:
        return "нет истории продаж"
    if item.shelf_life_days <= 2 and stock_quantity > forecast_quantity:
        return "риск списаний"
    if stock_quantity < ceil(forecast_quantity * 0.25):
        return "риск нехватки"
    return "расчет по истории"
