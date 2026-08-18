from unittest import TestCase

from src.domain.body_profile import BodyProfile, BodyTargets


class BodyProfileTests(TestCase):
    def test_calculates_bmi_for_baseline_profile(self) -> None:
        profile = BodyProfile(sex="male", age_years=30, height_cm=176.4, weight_kg=80.3)

        self.assertAlmostEqual(profile.bmi(), 25.8, places=1)

    def test_calculates_target_ranges_for_average_height(self) -> None:
        targets = BodyTargets()

        healthy_min, healthy_max = targets.healthy_weight_range(176.4)
        planning_min, planning_max = targets.planning_weight_range(176.4)
        waist_min, waist_max = targets.healthy_waist_range(176.4)

        self.assertAlmostEqual(healthy_min, 57.6, places=1)
        self.assertAlmostEqual(healthy_max, 77.5, places=1)
        self.assertAlmostEqual(planning_min, 68.5, places=1)
        self.assertAlmostEqual(planning_max, 74.7, places=1)
        self.assertAlmostEqual(waist_min, 70.6, places=1)
        self.assertAlmostEqual(waist_max, 86.4, places=1)
        self.assertAlmostEqual(targets.waist_risk_threshold_cm(176.4), 88.2, places=1)

    def test_calculates_waist_to_height_ratio(self) -> None:
        profile = BodyProfile(sex="male", age_years=30, height_cm=176.4, waist_cm=86)

        self.assertAlmostEqual(profile.waist_to_height_ratio(), 0.49, places=2)
