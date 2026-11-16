"""Tests for the sensor entities (values, state classes and unique IDs)."""

from datetime import date, datetime

import pytest


class FakeEntry:
    def __init__(self, entry_id="abc123"):
        self.entry_id = entry_id


class FakeCoordinator:
    def __init__(self, data, entry_id="abc123"):
        self.data = data
        self.config_entry = FakeEntry(entry_id)


@pytest.fixture
def make_data(data_module):
    def _make(points=None, bill=None, peak=0.32, offpeak=0.16, plan=None):
        usage = data_module.summarise(points or [])
        return data_module.ContactEnergyData(
            usage=usage,
            rates=data_module.Rates(peak=peak, offpeak=offpeak, source="bill"),
            plan=plan or {},
            bill=bill or {},
            account_id="ACC1",
            contract_id="CON1",
        )

    return _make


def _point(data_module, hour, kwh, offpeak=False, cost=0.0, day=1):
    return data_module.UsagePoint(
        start=datetime(2026, 9, day, hour, tzinfo=data_module.NZ_TZ), kwh=kwh, cost=cost, offpeak=offpeak
    )


ALL_SENSORS = [
    ("ContactEnergyUsageSensor", "abc123_usage"),
    ("ContactEnergyCurrentPriceSensor", "abc123_current_price"),
    ("ContactEnergyPeakCostSensor", "abc123_peak_cost"),
    ("ContactEnergyOffPeakCostSensor", "abc123_offpeak_cost"),
    ("ContactEnergyPeakRateSensor", "abc123_peak_rate"),
    ("ContactEnergyOffPeakRateSensor", "abc123_offpeak_rate"),
    ("ContactEnergyOffPeakPeriodSensor", "abc123_offpeak_period"),
    ("ContactEnergyNextBillDateSensor", "contact_energy_abc123_next_bill_date"),
    ("ContactEnergyNextBillAmountSensor", "contact_energy_abc123_next_bill_amount"),
]


class TestUniqueIdsAndDevice:
    """Unique IDs must never change, or existing installs get orphaned entities."""

    @pytest.mark.parametrize(("class_name", "unique_id"), ALL_SENSORS)
    def test_unique_id_and_device_grouping(self, sensor_module, make_data, class_name, unique_id):
        sensor = getattr(sensor_module, class_name)(FakeCoordinator(make_data()))
        assert sensor._attr_unique_id == unique_id
        assert sensor._attr_has_entity_name is True
        assert sensor._attr_device_info["identifiers"] == {("contact_energy", "abc123")}

    def test_device_model_comes_from_plan(self, sensor_module, make_data):
        data = make_data(plan={"plan_name": "Good Nights", "plan_id": "RGN01"})
        sensor = sensor_module.ContactEnergyUsageSensor(FakeCoordinator(data))
        assert sensor._attr_device_info["model"] == "Good Nights"
        assert sensor._attr_device_info["sw_version"] == "RGN01"


class TestStateClasses:
    """Rolling-window totals must not be TOTAL (HA reads drops as negative usage)."""

    @pytest.mark.parametrize(
        "class_name",
        [
            "ContactEnergyUsageSensor",
            "ContactEnergyPeakCostSensor",
            "ContactEnergyOffPeakCostSensor",
            "ContactEnergyNextBillAmountSensor",
        ],
    )
    def test_no_state_class(self, sensor_module, class_name):
        assert getattr(getattr(sensor_module, class_name), "_attr_state_class", None) is None

    def test_current_price_is_measurement_without_monetary_class(self, sensor_module):
        cls = sensor_module.ContactEnergyCurrentPriceSensor
        assert cls._attr_state_class == "measurement"
        assert getattr(cls, "_attr_device_class", None) is None
        assert cls._attr_native_unit_of_measurement == "NZD/kWh"


class TestValues:
    def test_usage_and_costs(self, sensor_module, data_module, make_data):
        points = [_point(data_module, 8, 2.0), _point(data_module, 22, 5.0, offpeak=True)]
        coordinator = FakeCoordinator(make_data(points, peak=0.32, offpeak=0.16))

        assert sensor_module.ContactEnergyUsageSensor(coordinator).native_value == 7.0
        assert sensor_module.ContactEnergyPeakCostSensor(coordinator).native_value == pytest.approx(0.64)
        assert sensor_module.ContactEnergyOffPeakCostSensor(coordinator).native_value == pytest.approx(0.8)
        assert sensor_module.ContactEnergyOffPeakPeriodSensor(coordinator).native_value == "22:00 - 23:00"

    def test_costs_use_what_contact_charged(self, sensor_module, data_module, make_data):
        """Contact's per-hour charges win over the flat-rate estimate."""
        points = [
            _point(data_module, 8, 2.0, cost=0.70, day=1),
            _point(data_module, 22, 5.0, offpeak=True, cost=0.75, day=3),
        ]
        coordinator = FakeCoordinator(make_data(points, peak=0.32, offpeak=0.16))

        peak = sensor_module.ContactEnergyPeakCostSensor(coordinator)
        offpeak = sensor_module.ContactEnergyOffPeakCostSensor(coordinator)

        assert peak.native_value == 0.70
        assert offpeak.native_value == 0.75
        assert peak.extra_state_attributes == {
            "period_start": "2026-09-01",
            "period_end": "2026-09-03",
            "days": 3,
            "kwh": 2.0,
            "rate": "$0.3200/kWh",
            "cost_source": "contact",
            "estimated_cost": 0.64,
            "peak_energy": "2.00 kWh",
        }
        assert offpeak.extra_state_attributes["cost_source"] == "contact"
        assert offpeak.extra_state_attributes["estimated_cost"] == 0.8

    def test_costs_fall_back_to_estimate_without_contact_costs(
        self, sensor_module, data_module, make_data
    ):
        points = [_point(data_module, 8, 2.0), _point(data_module, 22, 5.0, offpeak=True)]
        coordinator = FakeCoordinator(make_data(points, peak=0.32, offpeak=0.16))
        sensor = sensor_module.ContactEnergyPeakCostSensor(coordinator)
        assert sensor.native_value == pytest.approx(0.64)
        assert sensor.extra_state_attributes["cost_source"] == "estimated"

    def test_rate_sensors(self, sensor_module, make_data):
        coordinator = FakeCoordinator(make_data(peak=0.327, offpeak=0.161))
        peak = sensor_module.ContactEnergyPeakRateSensor(coordinator)
        offpeak = sensor_module.ContactEnergyOffPeakRateSensor(coordinator)
        assert (peak.native_value, offpeak.native_value) == (0.327, 0.161)
        assert peak._attr_native_unit_of_measurement == "NZD/kWh"
        assert peak._attr_state_class == "measurement"
        assert peak.extra_state_attributes == {"rate_source": "bill"}

    def test_usage_sensor_shows_period(self, sensor_module, data_module, make_data):
        points = [_point(data_module, 8, 2.0, day=1), _point(data_module, 8, 1.0, day=2)]
        sensor = sensor_module.ContactEnergyUsageSensor(FakeCoordinator(make_data(points)))
        attributes = sensor.extra_state_attributes
        assert (attributes["period_start"], attributes["period_end"], attributes["days"]) == (
            "2026-09-01",
            "2026-09-02",
            2,
        )

    def test_values_are_unknown_before_any_usage(self, sensor_module, make_data):
        coordinator = FakeCoordinator(make_data())
        assert sensor_module.ContactEnergyUsageSensor(coordinator).native_value is None
        assert sensor_module.ContactEnergyPeakCostSensor(coordinator).native_value is None
        assert sensor_module.ContactEnergyOffPeakPeriodSensor(coordinator).native_value is None

    def test_current_price_follows_the_offpeak_window(
        self, sensor_module, data_module, make_data, monkeypatch
    ):
        points = [_point(data_module, h, 1.0, offpeak=h >= 21 or h < 7) for h in range(24)]
        sensor = sensor_module.ContactEnergyCurrentPriceSensor(
            FakeCoordinator(make_data(points, peak=0.32, offpeak=0.0))
        )

        class FakeDatetime(datetime):
            hour_now = 12

            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 9, 2, cls.hour_now, tzinfo=tz)

        monkeypatch.setattr(sensor_module, "datetime", FakeDatetime)
        assert sensor.native_value == 0.32
        FakeDatetime.hour_now = 23
        assert sensor.native_value == 0.0
        assert sensor.extra_state_attributes["current_period"] == "off-peak"

    def test_bill_sensors(self, sensor_module, make_data):
        coordinator = FakeCoordinator(
            make_data(bill={"next_bill_date": "2026-09-17T00:00:00+13:00", "next_bill_amount": 615.674})
        )
        assert sensor_module.ContactEnergyNextBillDateSensor(coordinator).native_value == date(2026, 9, 17)
        assert sensor_module.ContactEnergyNextBillAmountSensor(coordinator).native_value == 615.67

    def test_bill_sensors_without_bill(self, sensor_module, make_data):
        coordinator = FakeCoordinator(make_data())
        assert sensor_module.ContactEnergyNextBillDateSensor(coordinator).native_value is None
        assert sensor_module.ContactEnergyNextBillAmountSensor(coordinator).native_value is None
