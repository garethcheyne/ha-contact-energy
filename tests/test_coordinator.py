"""Tests for fetching and statistics writing in coordinator.py."""

import asyncio
from datetime import datetime, timedelta

import pytest


class FakeApi:
    """Stands in for ContactEnergyApi; get_usage() returns canned days."""

    def __init__(self, auth_error_cls, responses=None, logged_in=True):
        self._auth_error_cls = auth_error_cls
        self.responses = responses or {}
        self.logged_in = logged_in
        self.authenticate_calls = 0
        self.expire_token_once = False
        self.reject_login = False
        self.requested = []

    @property
    def is_logged_in(self):
        return self.logged_in

    def authenticate(self):
        self.authenticate_calls += 1
        if self.reject_login:
            raise self._auth_error_cls("bad password")
        self.logged_in = True

    def get_plan_details(self):
        return True

    def get_bill_details(self):
        return True

    def get_usage(self, year, month, day):
        key = f"{year}-{int(month):02d}-{int(day):02d}"
        self.requested.append(key)
        if self.expire_token_once:
            self.expire_token_once = False
            self.logged_in = False
            return False
        return self.responses.get(key, [])


def _coordinator(coordinator_module, api):
    coordinator = coordinator_module.ContactEnergyCoordinator.__new__(
        coordinator_module.ContactEnergyCoordinator
    )
    coordinator.api = api
    return coordinator


def _nz_day(coordinator_module, days_ago):
    return datetime.now(coordinator_module.NZ_TZ).date() - timedelta(days=days_ago)


def _raw_day(day, values):
    return [
        {
            "date": f"{day.isoformat()}T{hour:02d}:00:00.000+13:00",
            "value": str(value),
            "dollarValue": "0.1",
            "offpeakValue": "0",
        }
        for hour, value in values
    ]


class TestFetchPoints:
    def test_fetches_each_full_day_oldest_first(self, coordinator_module):
        api_mod = __import__(f"{coordinator_module.__package__}.api", fromlist=["x"])
        api = FakeApi(api_mod.ContactEnergyAuthError)
        coordinator = _coordinator(coordinator_module, api)

        coordinator.fetch_points(3)

        expected = [_nz_day(coordinator_module, n).isoformat() for n in (3, 2, 1)]
        assert api.requested == expected

    def test_logs_in_again_when_token_expires_mid_fetch(self, coordinator_module):
        """Regression: an expired token used to stop all updates until a restart."""
        api_mod = __import__(f"{coordinator_module.__package__}.api", fromlist=["x"])
        day = _nz_day(coordinator_module, 1)
        api = FakeApi(api_mod.ContactEnergyAuthError, {day.isoformat(): _raw_day(day, [(8, 1.5)])})
        api.expire_token_once = True
        coordinator = _coordinator(coordinator_module, api)

        points = coordinator.fetch_points(1)

        assert api.authenticate_calls == 1
        assert [p.kwh for p in points] == [1.5]

    def test_wrong_password_raises_auth_error(self, coordinator_module):
        api_mod = __import__(f"{coordinator_module.__package__}.api", fromlist=["x"])
        api = FakeApi(api_mod.ContactEnergyAuthError, logged_in=False)
        api.reject_login = True
        coordinator = _coordinator(coordinator_module, api)

        with pytest.raises(api_mod.ContactEnergyAuthError):
            coordinator.fetch_points(1)


class TestWriteStatistics:
    def _points(self, data_module, start, kwh_values):
        return [
            data_module.UsagePoint(start=start + timedelta(hours=i), kwh=kwh, cost=0, offpeak=False)
            for i, kwh in enumerate(kwh_values)
        ]

    def _start(self, data_module):
        return datetime(2026, 9, 1, 0, tzinfo=data_module.NZ_TZ)

    def test_metadata_uses_mean_type_and_unit_class(
        self, coordinator_module, data_module, statistics_store, fake_recorder
    ):
        points = self._points(data_module, self._start(data_module), [1.0])
        asyncio.run(coordinator_module.async_write_statistics(None, points))

        for metadata, _ in statistics_store.imports:
            assert metadata["mean_type"] == 0
            assert "has_mean" not in metadata
            assert metadata["unit_class"] == "energy"
            assert metadata["has_sum"] is True
        assert {m["statistic_id"] for m, _ in statistics_store.imports} == {
            "contact_energy:energy_consumption",
            "contact_energy:free_energy_consumption",
        }

    def test_first_import_starts_at_zero(
        self, coordinator_module, data_module, statistics_store, fake_recorder
    ):
        points = self._points(data_module, self._start(data_module), [1.0, 2.0])
        asyncio.run(coordinator_module.async_write_statistics(None, points))

        _, peak_rows = statistics_store.imports[0]
        assert [r["sum"] for r in peak_rows] == [1.0, 3.0]

    def test_continues_from_sum_stored_before_window(
        self, coordinator_module, data_module, statistics_store, fake_recorder
    ):
        """Re-importing an overlapping window must not restart the sum at 0."""
        start = self._start(data_module)
        stat = "contact_energy:energy_consumption"
        statistics_store.rows[stat] = [
            {"start": (start - timedelta(hours=1)).timestamp(), "sum": 50.0},
            {"start": start.timestamp(), "sum": 999.0},  # overlaps - must be ignored
            {"start": (start + timedelta(hours=1)).timestamp(), "sum": 999.0},
        ]
        points = self._points(data_module, start, [1.0, 2.0])

        asyncio.run(coordinator_module.async_write_statistics(None, points))

        _, peak_rows = statistics_store.imports[0]
        assert [r["sum"] for r in peak_rows] == [51.0, 53.0]
        assert fake_recorder.blocked >= 1

    def test_continues_from_latest_sum_when_window_is_newer(
        self, coordinator_module, data_module, statistics_store, fake_recorder
    ):
        start = self._start(data_module)
        stat = "contact_energy:energy_consumption"
        statistics_store.rows[stat] = [
            {"start": (start - timedelta(days=40)).timestamp(), "sum": 75.0},
        ]
        points = self._points(data_module, start, [1.0])

        asyncio.run(coordinator_module.async_write_statistics(None, points))

        _, peak_rows = statistics_store.imports[0]
        assert [r["sum"] for r in peak_rows] == [76.0]

    def test_reset_ignores_stored_sums(
        self, coordinator_module, data_module, statistics_store, fake_recorder
    ):
        start = self._start(data_module)
        statistics_store.rows["contact_energy:energy_consumption"] = [
            {"start": (start - timedelta(hours=1)).timestamp(), "sum": 50.0},
        ]
        points = self._points(data_module, start, [1.0])

        asyncio.run(coordinator_module.async_write_statistics(None, points, reset=True))

        _, peak_rows = statistics_store.imports[0]
        assert [r["sum"] for r in peak_rows] == [1.0]
