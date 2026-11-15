"""Constants for the Contact Energy integration."""

from datetime import timedelta

DOMAIN = "contact_energy"

CONF_USAGE_DAYS = "usage_days"
CONF_PEAK_RATE = "peak_rate"
CONF_OFFPEAK_RATE = "offpeak_rate"
CONF_CONFIG_ENTRY_ID = "config_entry_id"

DEFAULT_USAGE_DAYS = 10
DEFAULT_PEAK_RATE = 0.30
DEFAULT_OFFPEAK_RATE = 0.15

UPDATE_INTERVAL = timedelta(hours=3)

# External statistics shown in the Energy Dashboard. Keep these IDs stable:
# existing installs already have history recorded under them.
STATISTIC_PEAK = f"{DOMAIN}:energy_consumption"
STATISTIC_OFFPEAK = f"{DOMAIN}:free_energy_consumption"
