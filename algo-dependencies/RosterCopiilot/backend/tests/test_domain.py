"""Domain model validation tests."""
from datetime import date

import pytest
from pydantic import ValidationError

from app.domain import (
    Gender,
    GenderRequirement,
    Period,
    ScheduleParams,
    ServiceCode,
    WeekPattern,
)


class TestWeekPattern:
    def test_weekly_matches_everything(self):
        assert WeekPattern().matches(date(2026, 6, 8))
        assert WeekPattern().matches(date(2026, 6, 29))

    def test_weeks_of_month_uses_occurrence_counting(self):
        p = WeekPattern.parse("1,3")
        assert p.matches(date(2026, 6, 1))    # 1st Monday
        assert not p.matches(date(2026, 6, 8))  # 2nd Monday
        assert p.matches(date(2026, 6, 15))   # 3rd Monday
        assert not p.matches(date(2026, 6, 22))

    def test_month_parity(self):
        odd = WeekPattern.parse("單月")
        even = WeekPattern.parse("雙月")
        assert odd.matches(date(2026, 5, 4)) and not odd.matches(date(2026, 6, 1))
        assert even.matches(date(2026, 6, 1)) and not even.matches(date(2026, 5, 4))

    def test_overlap_detection(self):
        assert not WeekPattern.parse("1,3").overlaps(WeekPattern.parse("2,4"))
        assert WeekPattern.parse("1,3").overlaps(WeekPattern.parse("3"))
        assert WeekPattern().overlaps(WeekPattern.parse("2,4"))
        assert not WeekPattern.parse("單月").overlaps(WeekPattern.parse("雙月"))

    def test_invalid_pattern_rejected(self):
        with pytest.raises(ValueError):
            WeekPattern.parse("garbage")
        with pytest.raises(ValidationError):
            WeekPattern(kind="weeks_of_month", weeks=[7], raw="7")


class TestScheduleParams:
    def test_week_start_must_be_monday(self):
        with pytest.raises(ValidationError):
            ScheduleParams(week_start=date(2026, 6, 9))  # a Tuesday
        assert ScheduleParams(week_start=date(2026, 6, 8)).week_start.weekday() == 0


class TestDatasetShape:
    def test_dataset_counts(self, dataset):
        assert len(dataset.employees) == 52
        assert len(dataset.elders) >= 300
        assert len(dataset.fixed_services) > 300
        assert len(dataset.escort_requests) >= 30
        assert dataset.params.week_start.weekday() == 0

    def test_generator_is_deterministic(self, dataset):
        from app.mockdata import generate_dataset
        again = generate_dataset(dataset.seed)
        assert again.model_dump() == dataset.model_dump()

    def test_different_seed_differs(self, dataset):
        from app.mockdata import generate_dataset
        other = generate_dataset(seed=7)
        assert other.model_dump() != dataset.model_dump()

    def test_edge_case_actors_present(self, dataset):
        workers = dataset.employee_map()
        assert workers["W001"].display_name == "娥"
        assert workers["W003"].gender == Gender.MALE
        assert ServiceCode.BATH in workers["W003"].skills
        exclusive = [e for e in dataset.elders if e.exclusive_worker_id == "W001"]
        assert len(exclusive) >= 3
        unknown_gender = [e for e in dataset.elders if e.gender is None]
        assert unknown_gender, "data-gap elder must exist"
        gaps = [r for r in dataset.escort_requests
                if r.gender_requirement == GenderRequirement.UNKNOWN]
        assert gaps, "data-gap escort must exist"

    def test_escort_week_has_over_and_under_baseline_days(self, dataset):
        from collections import Counter
        c = Counter((r.service_date.isoweekday(), r.period) for r in dataset.escort_requests)
        assert c[(3, Period.AM)] >= 5   # Wednesday AM over nominal baseline 4
        assert c[(4, Period.AM)] < 4    # Thursday AM under baseline (incl. data-gap case)
