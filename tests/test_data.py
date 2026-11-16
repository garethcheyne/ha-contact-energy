"""Tests for the pure parsing/aggregation helpers in data.py."""

from datetime import date, datetime, timedelta

import pytest

from data import (  # noqa: E402 - conftest puts the component dir on sys.path
    NZ_TZ,
    UsagePoint,
    choose_usage,
    cumulative_statistics,
    detect_offpeak_window,
    is_offpeak_hour,
    parse_bill_date,
    parse_points,
    resolve_rates,
    summarise,
)


def _raw(day: str, hour: int, value, offpeak=False, dollar="0.10", offset="+13:00"):
    return {
        "date": f"{day}T{hour:02d}:00:00.000{offset}",
        "value": value,
        "dollarValue": dollar,
        "offpeakValue": str(value) if offpeak else "0",
    }


def _point(day: date, hour: int, kwh: float, offpeak=False, cost=0.0):
    return UsagePoint(
        start=datetime(day.year, day.month, day.day, hour, tzinfo=NZ_TZ),
        kwh=kwh,
        cost=cost,
        offpeak=offpeak,
    )


class TestParsePoints:
    def test_parses_values_cost_and_offpeak_flag(self):
        points = parse_points(
            [_raw("2026-09-01", 8, "1.5", dollar="0.49"), _raw("2026-09-01", 22, "0.5", offpeak=True)]
        )
        assert [(p.start.hour, p.kwh, p.cost, p.offpeak) for p in points] == [
            (8, 1.5, 0.49, False),
            (22, 0.5, 0.10, True),
        ]
        assert points[0].start.utcoffset() == timedelta(hours=13)

    def test_keeps_zero_usage_hours(self):
        """Zero-kWh hours used to be dropped, leaving gaps in the statistics."""
        assert [p.kwh for p in parse_points([_raw("2026-09-01", 3, "0")])] == [0.0]

    def test_skips_unpublished_and_malformed_points(self):
        raw = [
            _raw("2026-09-01", 1, None),
            _raw("2026-09-01", 2, ""),
            {"date": "not a date", "value": "1"},
            {"value": "1"},
            "junk",
        ]
        assert parse_points(raw) == []

    def test_handles_none_and_false(self):
        assert parse_points(None) == []
        assert parse_points([]) == []


class TestOffPeakWindow:
    def test_window_that_wraps_midnight(self):
        day = date(2026, 9, 1)
        points = [_point(day, h, 1, offpeak=h >= 21 or h < 7) for h in range(24)]
        assert detect_offpeak_window(points) == (21, 7)

    def test_window_within_one_day(self):
        day = date(2026, 9, 1)
        points = [_point(day, h, 1, offpeak=9 <= h < 17) for h in range(24)]
        assert detect_offpeak_window(points) == (9, 17)

    def test_window_ending_at_midnight(self):
        day = date(2026, 9, 1)
        points = [_point(day, h, 1, offpeak=h >= 21) for h in range(24)]
        assert detect_offpeak_window(points) == (21, 0)

    def test_no_offpeak_hours(self):
        assert detect_offpeak_window([_point(date(2026, 9, 1), 8, 1)]) is None

    @pytest.mark.parametrize(
        ("hour", "window", "expected"),
        [
            (22, (21, 7), True),
            (3, (21, 7), True),
            (7, (21, 7), False),
            (12, (21, 7), False),
            (9, (9, 17), True),
            (17, (9, 17), False),
            (23, (21, 0), True),
            (0, (21, 0), False),
            (5, None, False),
            (5, (0, 0), True),
        ],
    )
    def test_is_offpeak_hour(self, hour, window, expected):
        assert is_offpeak_hour(hour, window) is expected


class TestSummarise:
    def test_totals_and_latest_day(self):
        d1, d2 = date(2026, 9, 1), date(2026, 9, 2)
        points = [
            _point(d1, 8, 2.0, cost=0.6),
            _point(d1, 22, 1.0, offpeak=True, cost=0.1),
            _point(d2, 8, 3.0, cost=0.9),
            _point(d2, 22, 0.5, offpeak=True, cost=0.05),
        ]
        summary = summarise(points)
        assert summary.peak_kwh == pytest.approx(5.0)
        assert summary.offpeak_kwh == pytest.approx(1.5)
        assert summary.total_kwh == pytest.approx(6.5)
        assert summary.latest_day == d2
        assert summary.latest_day_kwh == pytest.approx(3.5)
        assert summary.latest_day_cost == pytest.approx(0.95)
        assert summary.offpeak_window == (22, 23)
        assert (summary.period_start, summary.period_end, summary.days) == (d1, d2, 2)
        assert summary.peak_cost == pytest.approx(1.5)
        assert summary.offpeak_cost == pytest.approx(0.15)
        assert summary.has_cost is True

    def test_has_cost_false_when_contact_reports_no_costs(self):
        summary = summarise([_point(date(2026, 9, 1), 8, 2.0, cost=0.0)])
        assert summary.has_cost is False

    def test_latest_day_skips_trailing_all_zero_day(self):
        d1, d2 = date(2026, 9, 1), date(2026, 9, 2)
        summary = summarise([_point(d1, 8, 2.0), _point(d2, 8, 0.0)])
        assert summary.latest_day == d1

    def test_empty_returns_none(self):
        assert summarise([]) is None

    def test_choose_usage_holds_last_good_value(self):
        """Regression: an empty fetch window used to overwrite real readings with 0."""
        previous = summarise([_point(date(2026, 9, 1), 8, 2.0)])
        assert choose_usage(previous, None) is previous
        latest = summarise([_point(date(2026, 9, 2), 8, 1.0)])
        assert choose_usage(previous, latest) is latest
        assert choose_usage(None, None) is None


class TestCumulativeStatistics:
    def test_sums_carry_on_from_base_and_split_series(self):
        """Regression: sums were missing entirely, so the Energy Dashboard showed nothing."""
        day = date(2026, 9, 1)
        points = [_point(day, 8, 1.0), _point(day, 9, 2.0), _point(day, 22, 0.5, offpeak=True)]

        peak = cumulative_statistics(points, offpeak=False, base_sum=100.0)
        offpeak = cumulative_statistics(points, offpeak=True, base_sum=10.0)

        assert [(r["state"], r["sum"]) for r in peak] == [(1.0, 101.0), (2.0, 103.0), (0.0, 103.0)]
        assert [(r["state"], r["sum"]) for r in offpeak] == [(0.0, 10.0), (0.0, 10.0), (0.5, 10.5)]

    def test_cost_series_uses_cost_field(self):
        day = date(2026, 9, 1)
        points = [_point(day, 8, 1.0, cost=0.33), _point(day, 22, 0.5, offpeak=True, cost=0.0)]
        rows = cumulative_statistics(points, offpeak=False, base_sum=5.0, value="cost")
        assert [(r["state"], r["sum"]) for r in rows] == [(0.33, 5.33), (0.0, 5.33)]

    def test_rows_are_in_time_order(self):
        day = date(2026, 9, 1)
        rows = cumulative_statistics(
            [_point(day, 9, 2.0), _point(day, 8, 1.0)], offpeak=False, base_sum=0
        )
        assert [r["start"].hour for r in rows] == [8, 9]
        assert rows[-1]["sum"] == 3.0


class TestResolveRates:
    BILL = {"peak_rate": 0.327, "offpeak_rate": 0.161}

    def test_bill_rates_used_by_default(self):
        rates = resolve_rates(None, None, self.BILL, 0.30, 0.15)
        assert (rates.peak, rates.offpeak, rates.source) == (0.327, 0.161, "bill")

    def test_overrides_apply_independently(self):
        rates = resolve_rates(0.25, None, self.BILL, 0.30, 0.15)
        assert (rates.peak, rates.offpeak, rates.source) == (0.25, 0.161, "configured")

    def test_zero_offpeak_override_is_respected(self):
        """Free-hours plans need an off-peak override of exactly 0."""
        rates = resolve_rates(None, 0.0, self.BILL, 0.30, 0.15)
        assert rates.offpeak == 0.0

    def test_defaults_when_bill_has_no_rates(self):
        rates = resolve_rates(None, None, {}, 0.30, 0.15)
        assert (rates.peak, rates.offpeak, rates.source) == (0.30, 0.15, "default")


class TestParseBillDate:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2026-02-17T00:00:00+13:00", date(2026, 2, 17)),
            ("2026-02-17T00:00:00Z", date(2026, 2, 17)),
            ("2026-02-17", date(2026, 2, 17)),
            ("", None),
            (None, None),
            ("soon", None),
        ],
    )
    def test_parse(self, value, expected):
        assert parse_bill_date(value) == expected
