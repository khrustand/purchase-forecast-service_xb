from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BodyProfile:
    sex: str
    age_years: int
    height_cm: float
    weight_kg: float | None = None
    waist_cm: float | None = None

    def height_m(self) -> float:
        if self.height_cm <= 0:
            raise ValueError("height_cm must be greater than zero")
        return self.height_cm / 100

    def bmi(self) -> float | None:
        if self.weight_kg is None:
            return None
        if self.weight_kg <= 0:
            raise ValueError("weight_kg must be greater than zero")
        return self.weight_kg / (self.height_m() ** 2)

    def waist_to_height_ratio(self) -> float | None:
        if self.waist_cm is None:
            return None
        if self.waist_cm <= 0:
            raise ValueError("waist_cm must be greater than zero")
        return self.waist_cm / self.height_cm


@dataclass(frozen=True)
class BodyTargets:
    healthy_bmi_min: float = 18.5
    healthy_bmi_max: float = 24.9
    planning_bmi_min: float = 22.0
    planning_bmi_max: float = 24.0
    healthy_waist_to_height_min: float = 0.40
    healthy_waist_to_height_max: float = 0.49
    risk_waist_to_height_threshold: float = 0.50

    def healthy_weight_range(self, height_cm: float) -> tuple[float, float]:
        return _weight_range_for_bmi(height_cm, self.healthy_bmi_min, self.healthy_bmi_max)

    def planning_weight_range(self, height_cm: float) -> tuple[float, float]:
        return _weight_range_for_bmi(height_cm, self.planning_bmi_min, self.planning_bmi_max)

    def healthy_waist_range(self, height_cm: float) -> tuple[float, float]:
        if height_cm <= 0:
            raise ValueError("height_cm must be greater than zero")
        return (
            height_cm * self.healthy_waist_to_height_min,
            height_cm * self.healthy_waist_to_height_max,
        )

    def waist_risk_threshold_cm(self, height_cm: float) -> float:
        if height_cm <= 0:
            raise ValueError("height_cm must be greater than zero")
        return height_cm * self.risk_waist_to_height_threshold


def _weight_range_for_bmi(height_cm: float, min_bmi: float, max_bmi: float) -> tuple[float, float]:
    if height_cm <= 0:
        raise ValueError("height_cm must be greater than zero")
    if min_bmi <= 0 or max_bmi <= 0:
        raise ValueError("BMI bounds must be greater than zero")
    if min_bmi > max_bmi:
        raise ValueError("min_bmi must not be greater than max_bmi")

    height_m = height_cm / 100
    return (min_bmi * height_m**2, max_bmi * height_m**2)
