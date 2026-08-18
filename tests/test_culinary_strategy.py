from unittest import TestCase

from scripts.analyze_culinary_strategy import build_daily_menu, daily_menu_summary


class CulinaryStrategyTests(TestCase):
    def test_daily_menu_prefers_items_without_high_waste_risk(self) -> None:
        recommendations = [
            {
                "category": "Супы",
                "name": "Суп рискованный",
                "order_for_2_days": 2,
                "sales_june_july": 200,
                "waste_count": 12,
                "waste_risk": "высокий риск списаний",
                "shelf_life_days": 3,
                "shelf_life_risk": "срок покрывает горизонт заказа",
                "menu_score": 300,
                "strategy": "заказывать реже или исключить из ежедневной витрины",
            },
            {
                "category": "Супы",
                "name": "Суп стабильный",
                "order_for_2_days": 2,
                "sales_june_july": 100,
                "waste_count": 0,
                "waste_risk": "списаний не найдено",
                "shelf_life_days": 3,
                "shelf_life_risk": "срок покрывает горизонт заказа",
                "menu_score": 100,
                "strategy": "держать регулярно, контролировать остаток каждый заказ",
            },
        ]

        menu = build_daily_menu(recommendations)

        by_name = {item["name"]: item for item in menu}

        self.assertEqual(by_name["Суп стабильный"]["menu_role"], "основная витрина")
        self.assertEqual(
            by_name["Суп рискованный"]["menu_role"],
            "резерв: только если не хватает безопасных позиций",
        )

    def test_daily_menu_summary_shows_shortfall_and_high_risk_count(self) -> None:
        summary = daily_menu_summary(
            [
                {
                    "category": "Супы",
                    "waste_risk": "высокий риск списаний",
                }
            ]
        )

        self.assertEqual(summary["target_total"], 34)
        self.assertEqual(summary["actual_total"], 1)
        self.assertEqual(summary["shortfall"], 33)
        self.assertEqual(summary["high_risk_count"], 1)
