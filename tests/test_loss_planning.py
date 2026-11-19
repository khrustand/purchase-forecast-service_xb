from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from src.app.loss_planning import monthly_loss_plan
from src.infrastructure.loss_plans import load_loss_plans, save_loss_plan
from src.infrastructure.report_analytics import loss_group_totals


class MonthlyLossPlanningTests(TestCase):
    def test_saved_budget_is_month_specific_and_uses_known_loss(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'plan.json'
            save_loss_plan(path, '2026-12', '5 000 000', '1800,50')
            save_loss_plan(path, '2027-01', '6 000 000')
            with self.assertRaises(ValueError):
                save_loss_plan(path, '2026-12', 'NaN')
            self.assertEqual(len(load_loss_plans(path)), 2)
            with patch('src.app.loss_planning.loss_plan_path', return_value=path):
                plan = monthly_loss_plan(date(2026, 12, 1), [], [], {})
            self.assertEqual(plan['budget_left'], 100_000)
            self.assertEqual(plan['projected_loss'], 1800.50)

    def test_summary_accounts_deduplicate_and_exclude_food_for_staff(self):
        rows = [
            ['Дата', '№  документа', 'Сумма, р.', 'Счет списания', 'Проведен'],
            ['01.10.2026', '1', '42', 'Списание слойка', 'Да'],
            ['01.10.2026', '2', '11', 'Кулинария сотрудникам', 'Да'],
            ['01.10.2026', '3', '20', 'Списание хлеб', 'Нет'],
        ]
        with patch('src.infrastructure.report_analytics.read_xlsx', return_value=rows):
            results = loss_group_totals([], [Path('a.xlsx'), Path('b.xlsx')], date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(sum(row['waste_cost'] for row in results.values()), 42)
        self.assertEqual(results['bakery']['waste_days'], 1)
