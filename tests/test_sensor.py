"""Tests for the sensor aggregation/hold-last-good-value logic.

conftest.py stubs the `homeassistant` package and loads sensor.py via
importlib (see the `sensor_module` fixture there), so this module runs
the *actual* integration code against fakes rather than a real HA
instance or the real Contact Energy API.
"""

from datetime import datetime, timedelta

import pytest


class FakeConfigEntry:
    def __init__(self, entry_id="test_entry"):
        self.entry_id = entry_id
        self.data = {}


class FakeApi:
    """Stands in for ContactEnergyApi.

    Tests control get_usage() directly instead of mocking HTTP, since
    HTTP behaviour is already covered in test_api.py.
    """

    def __init__(self, daily_responses: dict):
        """Store a {date_key: response} map for get_usage() to return.

        `daily_responses` maps "YYYY-M-D" -> response (list of points,
        or False/[] to simulate "no data for this day").
        """
        self._api_token = "tok"
        self._plan_details = {}
        self._bill_details = {}
        self._accountId = "ACC1"
        self._contractId = "CON1"
        self._daily_responses = daily_responses
        self.login_called = False

    def login(self):
        self.login_called = True
        return True

    def get_usage(self, year, month, day):
        key = f"{year}-{int(month)}-{int(day)}"
        return self._daily_responses.get(key, False)


def _point(days_ago: int, hour: int, value: float, offpeak: bool, dollar: float = None):
    day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=days_ago
    )
    ts = day.replace(hour=hour)
    return {
        "date": ts.strftime("%Y-%m-%dT%H:%M:%S.%f+13:00"),
        "value": str(value),
        "dollarValue": str(dollar if dollar is not None else value * 0.3),
        "offpeakValue": "1" if offpeak else "0",
    }


def _responses_for_days_ago(days_ago_list, points_per_day):
    """Build the {date_key: [points]} map get_usage() will be queried with.

    `days_ago_list` is the list of "days ago" offsets to populate.
    """
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    out = {}
    for days_ago in days_ago_list:
        day = today - timedelta(days=days_ago)
        key = f"{day.year}-{day.month}-{day.day}"
        out[key] = points_per_day(days_ago)
    return out


class TestUsageSensorHoldsLastGoodValue:
    """Regression tests for the original bug.

    An empty fetch window used to silently overwrite a real reading with 0.0.
    """

    def test_holds_previous_value_when_no_data_returned(self, sensor_module):
        entry = FakeConfigEntry()
        api = FakeApi(daily_responses={})  # every day comes back False
        s = sensor_module.ContactEnergyUsageSensor(entry, api, usage_days=3)
        s._attr_native_value = 386.18  # simulate a previously-successful reading

        s._update()

        assert s._attr_native_value == 386.18, (
            "an empty fetch window must not overwrite the last good value"
        )

    def test_updates_value_when_data_is_available(self, sensor_module):
        entry = FakeConfigEntry()
        responses = _responses_for_days_ago(
            [1, 2, 3],
            lambda d: [_point(d, 8, 1.5, offpeak=False), _point(d, 23, 0.5, offpeak=True)],
        )
        api = FakeApi(daily_responses=responses)
        s = sensor_module.ContactEnergyUsageSensor(entry, api, usage_days=3)
        s._attr_native_value = 0.0
        s.hass = object()  # normally injected by the HA entity platform

        s._update()

        # 3 days * (1.5 peak + 0.5 offpeak) = 6.0 kWh total
        assert s._attr_native_value == pytest.approx(6.0)

    def test_partial_window_still_updates_with_whatever_data_exists(self, sensor_module):
        """Only some days in the window have data (e.g. API lag on the most recent day).

        The sensor should still aggregate what it got rather than
        treating a partial result as "no data".
        """
        entry = FakeConfigEntry()
        responses = _responses_for_days_ago(
            [2, 3],  # day "1" (most recent) deliberately missing
            lambda d: [_point(d, 8, 2.0, offpeak=False)],
        )
        api = FakeApi(daily_responses=responses)
        s = sensor_module.ContactEnergyUsageSensor(entry, api, usage_days=3)
        s._attr_native_value = 0.0
        s.hass = object()  # normally injected by the HA entity platform

        s._update()

        assert s._attr_native_value == pytest.approx(4.0)


class TestPeakCostSensorHoldsLastGoodValue:
    def test_holds_previous_value_when_no_data_returned(self, sensor_module):
        entry = FakeConfigEntry()
        api = FakeApi(daily_responses={})
        s = sensor_module.ContactEnergyPeakCostSensor(entry, api, usage_days=3, peak_rate=0.32)
        s._attr_native_value = 42.50

        s._update()

        assert s._attr_native_value == 42.50

    def test_computes_peak_only_cost(self, sensor_module):
        entry = FakeConfigEntry()
        responses = _responses_for_days_ago(
            [1],
            lambda d: [
                _point(d, 8, 2.0, offpeak=False),
                _point(d, 23, 5.0, offpeak=True),  # must be excluded
            ],
        )
        api = FakeApi(daily_responses=responses)
        s = sensor_module.ContactEnergyPeakCostSensor(entry, api, usage_days=1, peak_rate=0.32)

        s._update()

        assert s._peak_kwh == pytest.approx(2.0)
        assert s._attr_native_value == pytest.approx(0.64)


class TestOffPeakCostSensorHoldsLastGoodValue:
    def test_holds_previous_value_when_no_data_returned(self, sensor_module):
        entry = FakeConfigEntry()
        api = FakeApi(daily_responses={})
        s = sensor_module.ContactEnergyOffPeakCostSensor(
            entry, api, usage_days=3, offpeak_rate=0.16
        )
        s._attr_native_value = 12.34

        s._update()

        assert s._attr_native_value == 12.34

    def test_computes_offpeak_only_cost(self, sensor_module):
        entry = FakeConfigEntry()
        responses = _responses_for_days_ago(
            [1],
            lambda d: [
                _point(d, 8, 2.0, offpeak=False),  # must be excluded
                _point(d, 23, 5.0, offpeak=True),
            ],
        )
        api = FakeApi(daily_responses=responses)
        s = sensor_module.ContactEnergyOffPeakCostSensor(
            entry, api, usage_days=1, offpeak_rate=0.16
        )

        s._update()

        assert s._offpeak_kwh == pytest.approx(5.0)
        assert s._attr_native_value == pytest.approx(0.8)


class TestBillSensorsDeviceGrouping:
    """Regression tests for the entity-grouping fix.

    NextBillDate/Amount used to be missing has_entity_name/device_info,
    so they showed up outside the "Contact Energy" device tile in the HA
    UI. The unique_id must stay exactly as it was, or existing installs
    get an orphaned duplicate entity instead of the fix being picked up
    in place.
    """

    def test_next_bill_date_groups_under_contact_energy_device(self, sensor_module):
        entry = FakeConfigEntry(entry_id="abc123")
        api = FakeApi(daily_responses={})
        s = sensor_module.ContactEnergyNextBillDateSensor(entry, api)

        assert s._attr_has_entity_name is True
        assert s._attr_device_info["identifiers"] == {(sensor_module.DOMAIN, "abc123")}
        assert s._attr_unique_id == "contact_energy_abc123_next_bill_date"

    def test_next_bill_amount_groups_under_contact_energy_device(self, sensor_module):
        entry = FakeConfigEntry(entry_id="abc123")
        api = FakeApi(daily_responses={})
        s = sensor_module.ContactEnergyNextBillAmountSensor(entry, api)

        assert s._attr_has_entity_name is True
        assert s._attr_device_info["identifiers"] == {(sensor_module.DOMAIN, "abc123")}
        assert s._attr_unique_id == "contact_energy_abc123_next_bill_amount"

    def test_next_bill_amount_reads_from_bill_details(self, sensor_module):
        entry = FakeConfigEntry()
        api = FakeApi(daily_responses={})
        api._bill_details = {"next_bill_amount": 615.67}
        s = sensor_module.ContactEnergyNextBillAmountSensor(entry, api)

        s.update()

        assert s._attr_native_value == 615.67
