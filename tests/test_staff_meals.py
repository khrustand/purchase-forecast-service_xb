from unittest import TestCase
from src.domain.staff_meals import staff_meal_allowed,eligible_staff_demand
from src.domain.traffic import allocate_staff


class StaffMealTests(TestCase):
    def test_excluded_foods_get_no_staff_reserve_but_five_meals_remain(self):
        demand={'онигири краб':100,'темаки цыпленок':100,'суп':4,'каша рисовая':3}
        balance={}
        for _ in range(14):
            result=allocate_staff(eligible_staff_demand(demand),5,balance)
            self.assertEqual(result['онигири краб'],0)
            self.assertEqual(result['темаки цыпленок'],0)
            self.assertEqual(sum(result.values()),5)

    def test_names_with_codes_and_marks(self):
        self.assertFalse(staff_meal_allowed(' *282024 Онигири краб 0,120'))
        self.assertFalse(staff_meal_allowed('Темаки краб 0,140'))
        self.assertTrue(staff_meal_allowed('Блины с творогом'))
        self.assertTrue(staff_meal_allowed('Суп крем грибной'))
