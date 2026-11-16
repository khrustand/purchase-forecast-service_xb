from datetime import date, timedelta
from unittest import TestCase

from src.domain.demand_planning import demand_samples, plan_demand, distribute_quantity


class DemandPlanningTests(TestCase):
    def setUp(self):
        self.target = date(2026, 11, 17)
        self.history = {self.target - timedelta(weeks=i): q for i, q in enumerate([1, 3, 8], 1)}

    def test_reserve_and_staff_without_batch_rounding(self):
        plan = plan_demand(self.history, [self.target], self.target, [1], [1], 10, 9)
        self.assertEqual(plan['quantity'], 2)
        self.assertEqual(plan['guest_quantity'], 1)
        self.assertEqual(plan['economic_quantity'], 1)
        self.assertEqual(plan['availability_cost'], 0)
        self.assertTrue(plan['limited_by_profit'])
        self.assertEqual(plan['service_quantity'], 8)
        self.assertGreater(plan['stockout_probability'], .15)
        self.assertGreater(plan['alternatives'][1]['expected_remaining'], 0)

    def test_missing_economics_is_not_zero_cost_or_invented_profit(self):
        plan = plan_demand(self.history, [self.target], self.target, [0], [1])
        self.assertEqual(plan['quantity'], 8)
        self.assertIsNone(plan['economic_quantity'])
        self.assertIsNone(plan['expected_remaining_cost'])
        self.assertIsNone(plan['expected_profit'])

    def test_staff_cost_deducted_once_and_never_counted_as_waste(self):
        history = {self.target - timedelta(weeks=i): 4 for i in range(1, 5)}
        plan = plan_demand(history, [self.target], self.target, [2], [1], 100, 40)
        self.assertEqual(plan['quantity'], 6)
        self.assertEqual(plan['expected_profit'], 160)
        self.assertEqual(plan['expected_remaining_cost'], 0)

    def test_economic_quantity_matches_integer_profit_maximum(self):
        for factor in (.5, .8, 1, 1.3):
            plan = plan_demand(self.history, [self.target], self.target, [0], [factor], 100, 75, .1)
            values = [q * factor for q in [1, 3, 8]]
            weights = [1, .85, .85 ** 2]
            profits = {q: sum(min(q, d) * 100 * w for d, w in zip(values, weights)) / sum(weights) - 75 * q for q in range(12)}
            best = max(profits, key=lambda q: (profits[q], -q))
            self.assertEqual(plan['economic_quantity'], best)

    def test_future_values_excluded_and_observed_zero_retained(self):
        history = {self.target - timedelta(weeks=i): 0 for i in range(1, 4)}
        history[self.target] = 1000
        plan = plan_demand(history, [self.target], self.target, [1], [1])
        self.assertEqual(plan['quantity'], 1)
        self.assertEqual(plan['expected_demand'], 0)
        self.assertIsNone(plan_demand({}, [self.target], self.target, [0], [1])['quantity'])

    def test_missing_days_not_assumed_to_be_zero(self):
        samples, basis = demand_samples({self.target - timedelta(days=1): 7}, [self.target], self.target)
        self.assertEqual(samples, [[7]])
        self.assertIn('разреженная', basis)

    def test_sensitivity_is_conditional_and_does_not_increase_plan(self):
        plan = plan_demand(self.history, [self.target], self.target, [0], [1], 100, 30)
        scenario = plan['sensitivity'][1]
        self.assertEqual(scenario['demand_uplift_percent'], 20)
        self.assertGreaterEqual(scenario['stockout_probability'], plan['stockout_probability'])
        self.assertLessEqual(scenario['expected_remaining'], plan['expected_remaining'])

    def test_whole_windows_keep_interday_relationship(self):
        friday = date(2026, 11, 20)
        days = [friday + timedelta(days=i) for i in range(3)]
        history = {}
        for week, values in enumerate(([5, 1, 0], [1, 5, 0], [2, 4, 0]), 1):
            for offset, value in enumerate(values):
                history[friday - timedelta(weeks=week) + timedelta(days=offset)] = value
        samples, _ = demand_samples(history, days, friday)
        self.assertEqual(samples, [[5, 1, 0], [1, 5, 0], [2, 4, 0]])
        plan = plan_demand(history, days, friday, [1, 0, 1], [1, 1, 1], 100, 40)
        self.assertEqual(plan['quantity'], 8)
        self.assertEqual(sum(d['quantity'] for d in plan['daily']), 8)

    def test_trial_does_not_claim_estimated_risk_or_profit(self):
        plan = plan_demand({}, [self.target], self.target, [0], [1], trial_quantity=3)
        self.assertEqual(plan['quantity'], 3)
        self.assertIsNone(plan['stockout_probability'])
        self.assertIsNone(plan['expected_profit'])

    def test_allocation_exact_and_validation(self):
        self.assertEqual(distribute_quantity(7, [2, 1, 0]), [5, 2, 0])
        for level in (0, 1, -1):
            with self.assertRaises(ValueError):
                plan_demand(self.history, [self.target], self.target, [0], [1], service_level=level)

    def test_reserve_can_increase_quantity_within_explicit_profit_budget(self):
        history = {self.target - timedelta(weeks=i): q for i, q in enumerate([2, 2, 3, 3, 4, 4, 5, 6], 1)}
        plan = plan_demand(history, [self.target], self.target, [0], [1], 100, 40)
        self.assertGreater(plan['guest_quantity'], plan['economic_quantity'])
        self.assertGreater(plan['availability_cost'], 0)
        self.assertLessEqual(plan['availability_cost'], plan['availability_cost_limit'] + .01)
        no_buffer = plan_demand(history, [self.target], self.target, [0], [1], 100, 40, profit_tolerance=0)
        self.assertEqual(no_buffer['guest_quantity'], no_buffer['economic_quantity'])
