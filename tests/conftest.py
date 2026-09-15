"""Lightweight stand-ins for the handful of `homeassistant` symbols that `sensor.py` imports.

We deliberately do NOT install the real `homeassistant` package for these
tests: it's a huge dependency (and its compiled extras take a very long
time to build) just to exercise plain data-aggregation logic that happens
to live inside SensorEntity subclasses. These stubs give sensor.py exactly
the surface area it touches - nothing more - so the *actual* integration
code runs unmodified against them.

If a future change to sensor.py starts using more of the HA API, extend
these stubs (or switch to pytest-homeassistant-custom-component) rather
than papering over an ImportError.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

COMPONENT_DIR = Path(__file__).parent.parent / "custom_components" / "contact_energy"
# api.py has no relative imports, so it can be loaded as a plain top-level
# module (test_api.py does this directly).
sys.path.insert(0, str(COMPONENT_DIR))


def _install_ha_stubs() -> None:
    if "homeassistant" in sys.modules:
        return  # already stubbed (or the real thing is installed) - leave it alone

    ha = types.ModuleType("homeassistant")

    # homeassistant.core
    core = types.ModuleType("homeassistant.core")

    class HomeAssistant:  # noqa: D401 - stub
        pass

    core.HomeAssistant = HomeAssistant

    # homeassistant.config_entries
    config_entries = types.ModuleType("homeassistant.config_entries")

    class ConfigEntry:  # noqa: D401 - stub
        pass

    config_entries.ConfigEntry = ConfigEntry

    # homeassistant.const
    const = types.ModuleType("homeassistant.const")

    class UnitOfEnergy:
        KILO_WATT_HOUR = "kWh"

    const.UnitOfEnergy = UnitOfEnergy

    # homeassistant.components (namespace package)
    components = types.ModuleType("homeassistant.components")

    # homeassistant.components.sensor
    sensor_mod = types.ModuleType("homeassistant.components.sensor")

    class SensorDeviceClass:
        ENERGY = "energy"
        MONETARY = "monetary"
        DATE = "date"

    class SensorStateClass:
        TOTAL = "total"
        MEASUREMENT = "measurement"

    class SensorEntity:
        """Bare stub - see the module docstring for why this is a stub.

        The tests call `_update()` directly and read `_attr_native_value`
        off the instance, so none of the real SensorEntity property
        machinery is needed.
        """

    sensor_mod.SensorDeviceClass = SensorDeviceClass
    sensor_mod.SensorStateClass = SensorStateClass
    sensor_mod.SensorEntity = SensorEntity

    # homeassistant.components.recorder (+ .models, .statistics)
    recorder = types.ModuleType("homeassistant.components.recorder")
    recorder_models = types.ModuleType("homeassistant.components.recorder.models")

    class StatisticData:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class StatisticMetaData:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    recorder_models.StatisticData = StatisticData
    recorder_models.StatisticMetaData = StatisticMetaData

    recorder_statistics = types.ModuleType("homeassistant.components.recorder.statistics")

    def async_add_external_statistics(hass, metadata, stats):
        """No-op stub.

        Tests assert on the sensor's own aggregation, not on what gets
        pushed to the recorder.
        """

    recorder_statistics.async_add_external_statistics = async_add_external_statistics

    # homeassistant.helpers (+ .device_registry, .entity_platform)
    helpers = types.ModuleType("homeassistant.helpers")
    device_registry = types.ModuleType("homeassistant.helpers.device_registry")

    class DeviceEntryType:
        SERVICE = "service"

    class DeviceInfo(dict):
        """Real DeviceInfo is a TypedDict; a dict subclass is enough here."""

        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    device_registry.DeviceEntryType = DeviceEntryType
    device_registry.DeviceInfo = DeviceInfo

    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")

    class AddEntitiesCallback:  # noqa: D401 - stub
        pass

    entity_platform.AddEntitiesCallback = AddEntitiesCallback

    # Wire the package hierarchy together and register in sys.modules.
    ha.core = core
    ha.config_entries = config_entries
    ha.const = const
    ha.components = components
    components.sensor = sensor_mod
    components.recorder = recorder
    recorder.models = recorder_models
    recorder.statistics = recorder_statistics
    ha.helpers = helpers
    helpers.device_registry = device_registry
    helpers.entity_platform = entity_platform

    modules = {
        "homeassistant": ha,
        "homeassistant.core": core,
        "homeassistant.config_entries": config_entries,
        "homeassistant.const": const,
        "homeassistant.components": components,
        "homeassistant.components.sensor": sensor_mod,
        "homeassistant.components.recorder": recorder,
        "homeassistant.components.recorder.models": recorder_models,
        "homeassistant.components.recorder.statistics": recorder_statistics,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.device_registry": device_registry,
        "homeassistant.helpers.entity_platform": entity_platform,
    }
    sys.modules.update(modules)


_install_ha_stubs()


def _load_sensor_module():
    """Load sensor.py directly via importlib, bypassing the real __init__.py.

    custom_components/contact_energy/__init__.py pulls in a much bigger slice of Home Assistant
    (voluptuous service schemas, config_validation, recorder service
    calls) than sensor.py itself needs, purely to register HA services
    unrelated to what's under test here. Rather than stub all of that
    too, we give sensor.py's relative `from .const import DOMAIN` a
    synthetic parent package that only contains `const`.
    """
    package_name = "_contact_energy_test_pkg"

    pkg = types.ModuleType(package_name)
    pkg.__path__ = [str(COMPONENT_DIR)]
    sys.modules[package_name] = pkg

    const_spec = importlib.util.spec_from_file_location(
        f"{package_name}.const", COMPONENT_DIR / "const.py"
    )
    const_mod = importlib.util.module_from_spec(const_spec)
    sys.modules[f"{package_name}.const"] = const_mod
    const_spec.loader.exec_module(const_mod)

    sensor_spec = importlib.util.spec_from_file_location(
        f"{package_name}.sensor", COMPONENT_DIR / "sensor.py"
    )
    sensor_mod = importlib.util.module_from_spec(sensor_spec)
    sys.modules[f"{package_name}.sensor"] = sensor_mod
    sensor_spec.loader.exec_module(sensor_mod)
    return sensor_mod


@pytest.fixture(scope="session")
def sensor_module():
    return _load_sensor_module()
