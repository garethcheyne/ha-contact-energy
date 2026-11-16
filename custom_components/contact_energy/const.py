"""Constants for the Contact Energy integration."""

from datetime import timedelta

DOMAIN = "contact_energy"

CONF_USAGE_DAYS = "usage_days"
CONF_PEAK_RATE = "peak_rate"
CONF_OFFPEAK_RATE = "offpeak_rate"
CONF_CONFIG_ENTRY_ID = "config_entry_id"
CONF_HISTORY_DAYS = "history_days"  # history to import when first set up
CONF_INITIAL_HISTORY_DONE = "initial_history_done"
CONF_CLEAR_EXISTING = "clear_existing"

DEFAULT_USAGE_DAYS = 10
DEFAULT_HISTORY_DAYS = 90
# Upper limit for one import. Imports stop early once Contact has no older
# data (HISTORY_EMPTY_STOP_DAYS empty days in a row after finding data).
MAX_HISTORY_DAYS = 1095
HISTORY_EMPTY_STOP_DAYS = 14
# Days per usage request when Contact accepts multi-day requests.
FETCH_CHUNK_DAYS = 7
DEFAULT_PEAK_RATE = 0.30
DEFAULT_OFFPEAK_RATE = 0.15

UPDATE_INTERVAL = timedelta(hours=3)

# External statistics shown in the Energy Dashboard. Keep these IDs stable:
# existing installs already have history recorded under them.
STATISTIC_PEAK = f"{DOMAIN}:energy_consumption"
STATISTIC_OFFPEAK = f"{DOMAIN}:free_energy_consumption"
# Hourly cost as charged by Contact (their `dollarValue`), for the
# Energy Dashboard's "use an entity tracking the total costs" option.
STATISTIC_PEAK_COST = f"{DOMAIN}:energy_cost"
STATISTIC_OFFPEAK_COST = f"{DOMAIN}:free_energy_cost"
ALL_STATISTIC_IDS = (STATISTIC_PEAK, STATISTIC_OFFPEAK, STATISTIC_PEAK_COST, STATISTIC_OFFPEAK_COST)

CURRENCY = "NZD"
