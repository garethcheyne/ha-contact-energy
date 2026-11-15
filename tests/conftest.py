"""Lightweight stand-ins for the `homeassistant` symbols the integration imports.

We deliberately do NOT install the real `homeassistant` package for these
tests: it's a huge dependency just to exercise data-aggregation logic. These
stubs give the integration modules exactly the surface area they touch, so
the *actual* integration code runs unmodified against them.

If a future change starts using more of the HA API, extend these stubs (or
switch to pytest-homeassistant-custom-component) rather than papering over
an ImportError.
"""

import importlib
import sys
import types
from pathlib import Path
from typing import Generic, TypeVar

import pytest

COMPONENT_DIR = Path(__file__).parent.parent / "custom_components" / "contact_energy"
# api.py and data.py have no relative imports, so they can also be loaded as
# plain top-level modules (test_api.py and test_data.py do this).
sys.path.insert(0, str(COMPONENT_DIR))

PACKAGE = "_contact_energy_test_pkg"

_T = TypeVar("_T")


class FakeRecorder:
    """Records what the integration asks the recorder to do."""

    def __init__(self):
        self.cleared = []
        self.blocked = 0

    async def async_block_till_done(self):
        self.blocked += 1

    async def async_add_executor_job(self, func, *args):
        return func(*args)

    def async_clear_statistics(self, statistic_ids):
        self.cleared.append(list(statistic_ids))


class FakeStatisticsStore:
    """Backs the stubbed recorder statistics functions."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.rows = {}  # statistic_id -> list of {"start": ts, "sum": x}
        self.imports = []  # (metadata, [StatisticData])

    def get_last_statistics(self, hass, number, statistic_id, convert_units, types_):
        rows = sorted(self.rows.get(statistic_id, []), key=lambda r: r["start"])
        return {statistic_id: rows[-number:]} if rows else {}

    def statistics_during_period(self, hass, start, end, ids, period, units, types_):
        out = {}
        for statistic_id in ids:
            rows = [
                r
                for r in sorted(self.rows.get(statistic_id, []), key=lambda r: r["start"])
                if start.timestamp() <= r["start"] < end.timestamp()
            ]
            if rows:
                out[statistic_id] = rows
        return out

    def async_add_external_statistics(self, hass, metadata, stats):
        self.imports.append((metadata, stats))


RECORDER = FakeRecorder()
STATISTICS = FakeStatisticsStore()


def _module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    return mod


def _install_ha_stubs() -> None:
    if "homeassistant" in sys.modules:
        return  # already stubbed (or the real thing is installed) - leave it alone

    class HomeAssistant:
        pass

    def callback(func):
        return func

    class ConfigEntry(Generic[_T]):
        pass

    class UnitOfEnergy:
        KILO_WATT_HOUR = "kWh"

    class SensorDeviceClass:
        ENERGY = "energy"
        MONETARY = "monetary"
        DATE = "date"

    class SensorStateClass:
        TOTAL = "total"
        MEASUREMENT = "measurement"

    class SensorEntity:
        pass

    class StatisticData(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    class StatisticMetaData(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    class StatisticMeanType:
        NONE = 0
        ARITHMETIC = 1
        CIRCULAR = 2

    class DeviceEntryType:
        SERVICE = "service"

    class DeviceInfo(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    class AddEntitiesCallback:
        pass

    class DataUpdateCoordinator(Generic[_T]):
        def __init__(self, hass, logger, *, config_entry=None, name="", update_interval=None):
            self.hass = hass
            self.config_entry = config_entry
            self.name = name
            self.update_interval = update_interval
            self.data = None

    class CoordinatorEntity(Generic[_T]):
        def __init__(self, coordinator):
            self.coordinator = coordinator

    class UpdateFailed(Exception):
        pass

    class ConfigEntryAuthFailed(Exception):
        pass

    class EnergyConverter:
        UNIT_CLASS = "energy"

    def async_track_time_change(hass, action, **kwargs):
        return lambda: None

    _module("homeassistant")
    _module("homeassistant.core", HomeAssistant=HomeAssistant, callback=callback)
    _module("homeassistant.config_entries", ConfigEntry=ConfigEntry)
    _module("homeassistant.const", UnitOfEnergy=UnitOfEnergy)
    _module("homeassistant.exceptions", ConfigEntryAuthFailed=ConfigEntryAuthFailed)
    _module("homeassistant.components")
    _module(
        "homeassistant.components.sensor",
        SensorDeviceClass=SensorDeviceClass,
        SensorStateClass=SensorStateClass,
        SensorEntity=SensorEntity,
    )
    _module("homeassistant.components.recorder", get_instance=lambda hass: RECORDER)
    _module(
        "homeassistant.components.recorder.models",
        StatisticData=StatisticData,
        StatisticMeanType=StatisticMeanType,
        StatisticMetaData=StatisticMetaData,
    )
    _module(
        "homeassistant.components.recorder.statistics",
        async_add_external_statistics=STATISTICS.async_add_external_statistics,
        get_last_statistics=STATISTICS.get_last_statistics,
        statistics_during_period=STATISTICS.statistics_during_period,
    )
    _module("homeassistant.helpers")
    _module(
        "homeassistant.helpers.device_registry",
        DeviceEntryType=DeviceEntryType,
        DeviceInfo=DeviceInfo,
    )
    _module("homeassistant.helpers.entity_platform", AddEntitiesCallback=AddEntitiesCallback)
    _module("homeassistant.helpers.event", async_track_time_change=async_track_time_change)
    _module(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=DataUpdateCoordinator,
        CoordinatorEntity=CoordinatorEntity,
        UpdateFailed=UpdateFailed,
    )
    _module("homeassistant.util")
    _module("homeassistant.util.unit_conversion", EnergyConverter=EnergyConverter)


_install_ha_stubs()


def _load_package():
    """Make the integration importable as a package without running __init__.py.

    __init__.py wires up config entries and services, which would need far
    more of Home Assistant stubbed; the modules under test don't need it.
    """
    pkg = types.ModuleType(PACKAGE)
    pkg.__path__ = [str(COMPONENT_DIR)]
    sys.modules[PACKAGE] = pkg
    return pkg


_load_package()


@pytest.fixture(scope="session")
def sensor_module():
    return importlib.import_module(f"{PACKAGE}.sensor")


@pytest.fixture(scope="session")
def coordinator_module():
    return importlib.import_module(f"{PACKAGE}.coordinator")


@pytest.fixture(scope="session")
def data_module():
    return importlib.import_module(f"{PACKAGE}.data")


@pytest.fixture
def statistics_store():
    STATISTICS.reset()
    return STATISTICS


@pytest.fixture
def fake_recorder():
    RECORDER.cleared.clear()
    RECORDER.blocked = 0
    return RECORDER
