"""Tests for fetching and statistics writing in coordinator.py."""

import asyncio
from datetime import datetime, timedelta

import pytest


class FakeApi:
    """Stands in for ContactEnergyApi; returns canned days.

    range_mode controls get_usage_range(): "ok" returns every day in the
    range, "first_day_only" mimics an API that ignores `to`, "error" fails.
    """

    def __init__(self, auth_error_cls, responses=None, logged_in=True, range_mode="ok"):
        self._auth_error_cls = auth_error_cls
        self.responses = responses or {}
        self.logged_in = logged_in
        self.range_mode = range_mode
        self.authenticate_calls = 0
        self.expire_token_once = False
        self.reject_login = False
        self.requested = []
        self.range_requests = []

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

    def get_usage_range(self, start, end):
        self.range_requests.append((start.isoformat(), end.isoformat()))
        if self.range_mode == "error":
            return False
        out = []
        day = start
        while day <= end:
            out.extend(self.responses.get(day.isoformat(), []))
            if self.range_mode == "first_day_only":
                break
            day += timedelta(days=1)
        return out


class FakeHass:
    def __init__(self, is_running=True):
        self.is_running = is_running

    async def async_add_executor_job(self, func, *args):
        return func(*args)


RUNNING_HASS = FakeHass()


def _coordinator(coordinator_module, api):
    coordinator = coordinator_module.ContactEnergyCoordinator.__new__(
        coordinator_module.ContactEnergyCoordinator
    )
    coordinator.api = api
    coordinator.hass = FakeHass()
    coordinator._range_supported = None
    coordinator._progress_listeners = set()
    coordinator.import_state = {"status": "idle", "progress": 0}
    coordinator.statistics_lock = asyncio.Lock()
    coordinator.history_range = None
    return coordinator


def _api_module(coordinator_module):
    return __import__(f"{coordinator_module.__package__}.api", fromlist=["x"])


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


def _responses(coordinator_module, days_ago):
    out = {}
    for n in days_ago:
        day = _nz_day(coordinator_module, n)
        out[day.isoformat()] = _raw_day(day, [(8, 1.0), (20, 2.0)])
    return out


class TestFetchPoints:
    def test_first_multi_day_fetch_is_checked_day_by_day(self, coordinator_module):
        api = FakeApi(_api_module(coordinator_module).ContactEnergyAuthError, _responses(coordinator_module, [1, 2, 3]))
        coordinator = _coordinator(coordinator_module, api)

        points = coordinator.fetch_points(3)

        assert api.requested == [_nz_day(coordinator_module, n).isoformat() for n in (3, 2, 1)]
        assert len(api.range_requests) == 1
        assert coordinator._range_supported is True
        assert len(points) == 6

    def test_uses_range_requests_once_confirmed(self, coordinator_module):
        api = FakeApi(_api_module(coordinator_module).ContactEnergyAuthError, _responses(coordinator_module, range(1, 15)))
        coordinator = _coordinator(coordinator_module, api)
        coordinator._range_supported = True

        points = coordinator.fetch_points(14)

        assert api.requested == []
        assert len(api.range_requests) == 2  # two 7-day chunks
        assert len(points) == 28

    def test_falls_back_to_day_by_day_when_range_is_ignored(self, coordinator_module):
        api = FakeApi(
            _api_module(coordinator_module).ContactEnergyAuthError,
            _responses(coordinator_module, range(1, 15)),
            range_mode="first_day_only",
        )
        coordinator = _coordinator(coordinator_module, api)

        points = coordinator.fetch_points(14)

        assert coordinator._range_supported is False
        assert len(api.range_requests) == 1  # only the check
        assert len(api.requested) == 14
        assert len(points) == 28

    def test_failed_range_request_falls_back_for_that_chunk(self, coordinator_module):
        api = FakeApi(
            _api_module(coordinator_module).ContactEnergyAuthError,
            _responses(coordinator_module, range(1, 8)),
            range_mode="error",
        )
        coordinator = _coordinator(coordinator_module, api)
        coordinator._range_supported = True

        points = coordinator.fetch_points(7)

        assert len(api.requested) == 7
        assert len(points) == 14

    def test_logs_in_again_when_token_expires_mid_fetch(self, coordinator_module):
        """Regression: an expired token used to stop all updates until a restart."""
        day = _nz_day(coordinator_module, 1)
        api = FakeApi(
            _api_module(coordinator_module).ContactEnergyAuthError,
            {day.isoformat(): _raw_day(day, [(8, 1.5)])},
        )
        api.expire_token_once = True
        coordinator = _coordinator(coordinator_module, api)

        points = coordinator.fetch_points(1)

        assert api.authenticate_calls == 1
        assert [p.kwh for p in points] == [1.5]

    def test_wrong_password_raises_auth_error(self, coordinator_module):
        api_mod = _api_module(coordinator_module)
        api = FakeApi(api_mod.ContactEnergyAuthError, logged_in=False)
        api.reject_login = True
        coordinator = _coordinator(coordinator_module, api)

        with pytest.raises(api_mod.ContactEnergyAuthError):
            coordinator.fetch_points(1)


class TestDateChunks:
    def test_chunks_cover_range_exactly(self, coordinator_module):
        start = datetime(2026, 1, 1).date()
        end = datetime(2026, 1, 16).date()
        chunks = coordinator_module.date_chunks(start, end, 7)
        assert [(a.day, b.day) for a, b in chunks] == [(1, 7), (8, 14), (15, 16)]


class TestHistoryImport:
    def test_stops_when_contact_runs_out_of_data(
        self, coordinator_module, statistics_store, fake_recorder
    ):
        """Data exists for the last 20 days only; a 365-day import stops early."""
        api = FakeApi(_api_module(coordinator_module).ContactEnergyAuthError, _responses(coordinator_module, range(1, 21)))
        coordinator = _coordinator(coordinator_module, api)
        coordinator._range_supported = True
        progress = []
        coordinator.async_add_progress_listener(progress.append)

        summary = asyncio.run(coordinator._async_import(365, clear=False))

        assert summary["days_imported"] == 20
        assert summary["hours_imported"] == 40
        assert summary["contact_history_starts"] == _nz_day(coordinator_module, 20).isoformat()
        assert summary["oldest"] == _nz_day(coordinator_module, 20).isoformat()
        # 20 days of data + 14 empty days, fetched a week at a time: 5 chunks, not 53.
        assert len(api.range_requests) == 5
        assert progress == sorted(progress) and progress[-1] < 1
        assert {m["statistic_id"] for m, _ in statistics_store.imports} >= {
            "contact_energy:energy_consumption"
        }

    def test_full_range_when_data_goes_back_further(
        self, coordinator_module, statistics_store, fake_recorder
    ):
        api = FakeApi(_api_module(coordinator_module).ContactEnergyAuthError, _responses(coordinator_module, range(1, 40)))
        coordinator = _coordinator(coordinator_module, api)
        coordinator._range_supported = True

        summary = asyncio.run(coordinator._async_import(14, clear=True))

        assert summary["days_imported"] == 14
        assert summary["contact_history_starts"] is None
        assert summary["cleared_existing"] is True
        assert fake_recorder.cleared  # statistics cleared before the import

    def test_no_data_raises(self, coordinator_module, statistics_store, fake_recorder):
        api = FakeApi(_api_module(coordinator_module).ContactEnergyAuthError, {})
        coordinator = _coordinator(coordinator_module, api)
        coordinator._range_supported = True
        exceptions = __import__("homeassistant.exceptions", fromlist=["x"])

        with pytest.raises(exceptions.HomeAssistantError):
            asyncio.run(coordinator._async_import(7, clear=False))


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
        asyncio.run(coordinator_module.async_write_statistics(RUNNING_HASS, points))

        units = {}
        for metadata, _ in statistics_store.imports:
            assert metadata["mean_type"] == 0
            assert "has_mean" not in metadata
            assert metadata["has_sum"] is True
            units[metadata["statistic_id"]] = (metadata["unit_of_measurement"], metadata["unit_class"])
        assert units == {
            "contact_energy:energy_consumption": ("kWh", "energy"),
            "contact_energy:free_energy_consumption": ("kWh", "energy"),
            "contact_energy:energy_cost": ("NZD", None),
            "contact_energy:free_energy_cost": ("NZD", None),
        }

    def test_cost_series_carry_contact_dollar_values(
        self, coordinator_module, data_module, statistics_store, fake_recorder
    ):
        """Costs come from Contact's per-hour dollarValue, split peak/off-peak."""
        start = self._start(data_module)
        points = [
            data_module.UsagePoint(start=start, kwh=2.0, cost=0.65, offpeak=False),
            data_module.UsagePoint(start=start + timedelta(hours=1), kwh=1.0, cost=0.0, offpeak=True),
            data_module.UsagePoint(start=start + timedelta(hours=2), kwh=1.0, cost=0.33, offpeak=False),
        ]
        statistics_store.rows["contact_energy:energy_cost"] = [
            {"start": (start - timedelta(hours=1)).timestamp(), "sum": 10.0},
        ]

        asyncio.run(coordinator_module.async_write_statistics(RUNNING_HASS, points))

        rows = {m["statistic_id"]: r for m, r in statistics_store.imports}
        assert [r["sum"] for r in rows["contact_energy:energy_cost"]] == pytest.approx([10.65, 10.65, 10.98])
        assert [r["sum"] for r in rows["contact_energy:free_energy_cost"]] == [0.0, 0.0, 0.0]

    def test_first_import_starts_at_zero(
        self, coordinator_module, data_module, statistics_store, fake_recorder
    ):
        points = self._points(data_module, self._start(data_module), [1.0, 2.0])
        asyncio.run(coordinator_module.async_write_statistics(RUNNING_HASS, points))

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

        asyncio.run(coordinator_module.async_write_statistics(RUNNING_HASS, points))

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

        asyncio.run(coordinator_module.async_write_statistics(RUNNING_HASS, points))

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

        asyncio.run(coordinator_module.async_write_statistics(RUNNING_HASS, points, reset=True))

        _, peak_rows = statistics_store.imports[0]
        assert [r["sum"] for r in peak_rows] == [1.0]


class TestStartupDoesNotWaitForRecorder:
    def test_no_recorder_wait_while_home_assistant_is_starting(
        self, coordinator_module, data_module, statistics_store, fake_recorder
    ):
        """Regression: waiting for the recorder during startup deadlocked setup.

        The recorder doesn't commit until startup finishes, so setup hung
        until Home Assistant's startup timeout and the entry failed to load.
        """
        start = datetime(2026, 9, 1, 0, tzinfo=data_module.NZ_TZ)
        points = [data_module.UsagePoint(start=start, kwh=1.0, cost=0.1, offpeak=False)]

        asyncio.run(coordinator_module.async_write_statistics(FakeHass(is_running=False), points))

        assert fake_recorder.blocked == 0
        assert statistics_store.imports  # still written

    def test_waits_for_recorder_once_running(
        self, coordinator_module, data_module, statistics_store, fake_recorder
    ):
        start = datetime(2026, 9, 1, 0, tzinfo=data_module.NZ_TZ)
        points = [data_module.UsagePoint(start=start, kwh=1.0, cost=0.1, offpeak=False)]

        asyncio.run(coordinator_module.async_write_statistics(FakeHass(is_running=True), points))

        assert fake_recorder.blocked >= 1
