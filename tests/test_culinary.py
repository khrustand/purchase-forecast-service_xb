from unittest import TestCase

from src.domain.culinary import (
    CulinaryMenuItem,
    CulinarySalesPeriod,
    CulinaryStock,
    recommend_culinary_orders,
)


class CulinaryOrderTests(TestCase):
    def test_recommends_order_from_recent_sales_and_stock(self) -> None:
        recommendations = recommend_culinary_orders(
            menu=[
                CulinaryMenuItem("lunch", "Обед с курицей", "Обеды", 5, 140, 2),
                CulinaryMenuItem("salad", "Салат Цезарь", "Салаты", 4, 115, 2),
            ],
            sales_periods=[
                CulinarySalesPeriod("lunch", 30, 2),
                CulinarySalesPeriod("lunch", 34, 1),
                CulinarySalesPeriod("salad", 18),
                CulinarySalesPeriod("salad", 20),
            ],
            stocks=[
                CulinaryStock("lunch", 10),
                CulinaryStock("salad", 35),
            ],
            forecast_periods=2,
            safety_rate=0.1,
        )

        lunch = next(item for item in recommendations if item.sku == "lunch")
        salad = next(item for item in recommendations if item.sku == "salad")

        self.assertEqual(lunch.forecast_quantity, 67)
        self.assertEqual(lunch.safety_stock, 7)
        self.assertEqual(lunch.recommended_quantity, 65)
        self.assertEqual(lunch.review_reason, "риск нехватки")
        self.assertEqual(salad.recommended_quantity, 8)
        self.assertEqual(salad.review_reason, "расчет по истории")

    def test_marks_missing_history_for_review(self) -> None:
        recommendations = recommend_culinary_orders(
            menu=[CulinaryMenuItem("roll", "Ролл с курицей", "Роллы", 4, 130, 2)],
            sales_periods=[],
            stocks=[],
        )

        self.assertEqual(recommendations[0].review_reason, "нет истории продаж")
