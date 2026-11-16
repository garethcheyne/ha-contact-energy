# Changelog

All notable changes to this project are documented in this file.

## v2026.11.16.01

Requires Home Assistant 2025.11 or newer.

### Added

- **Real costs in the Energy Dashboard.** New hourly statistics `contact_energy:energy_cost` (peak) and `contact_energy:free_energy_cost` (off-peak) carry the cost Contact reports for each hour (`dollarValue`, in NZD). Choose them under **Use an entity tracking the total costs**, and the dashboard shows what Contact actually charged instead of a flat-rate estimate. The daily fixed charge isn't included. The import action backfills them too, and `clear_existing` clears them along with usage.

### Fixed

- **Energy Dashboard showed no usage.** Statistics were written without the running total (`sum`) that the Energy Dashboard reads. Earlier versions wrote a sum but restarted it at 0 on every update, which caused negative spikes. Each update now carries the sum on from the last hour already stored. **After upgrading, run `contact_energy.import_historical_data` once with `clear_existing: true` and `confirm_clear: "yes"` to rebuild the history.**
- **Home Assistant 2026.11 compatibility.** Statistics metadata uses `mean_type` instead of the deprecated `has_mean`, and sets `unit_class`.
- **Options dialog crashed.** It assigned `self.config_entry`, which current Home Assistant no longer allows, and its methods were defined twice. Options were also saved where the integration never read them. Options now apply and reload the integration.
- **The "clear existing" import crashed** because it awaited a function that isn't async.
- **A failed login at startup was permanent.** A wrong password now starts Home Assistant's re-authentication flow. A network outage makes Home Assistant retry setup. The setup form now says "cannot connect" for network problems instead of "invalid password".
- **Current Price could be up to 3 hours stale** and was guessed from usage two days earlier. It now uses the detected off-peak window and updates at the top of every hour.
- **Wrong sensor classes.** Energy Usage, Peak Cost, Off-Peak Cost and Next Bill Amount had `state_class: total`, but they are rolling or point-in-time values, so Home Assistant recorded every drop as negative usage. They no longer have a state class. Current Price no longer combines `monetary` with `measurement`, which Home Assistant rejected.
- Bill and plan details were only refreshed when logging in; they now refresh on every update.
- Next Bill Date could be set to a string, which a date sensor rejects.
- Dates are worked out in New Zealand time rather than the host's time zone.

### Changed

- All sensors share one `DataUpdateCoordinator` fetch, about 3× fewer API calls per update.
- Hours with 0 kWh are now recorded. Both statistics series get a row every hour, so they have no gaps.
- The import and export actions are registered once, accept `config_entry_id` when several accounts are set up, return a summary, and raise proper errors instead of only logging.
- Translations added for the setup, re-authentication, options and action forms (`translations/en.json`).
- Rate overrides apply independently, and an off-peak override of `0` is respected.

### Marketplace

- `manifest.json`: added `integration_type`, `categories` and `connectivity`, and removed the unsupported `icon` key.
- `hacs.json`: added the minimum Home Assistant version (`2025.11.0`).
- README installation instructions updated for the Home Assistant Marketplace.

### Development

- Tests cover the new parsing, running-sum and coordinator logic (83 tests).
- `ruff` config updated for current ruff; CI uses Python 3.13. The dev container uses Python 3.14 and Home Assistant 2026.11.1. The release workflow strips the `v` from the tag when setting the manifest version.

---

## v2026.09.16.02

### Fixed

- Integration logo not displaying in Home Assistant/HACS. `icon.png` and `icon@2x.png` were sitting directly in `custom_components/contact_energy/`, but HA 2026.3+ only picks up local brand images from a `brand/` subdirectory. Moved both files to `custom_components/contact_energy/brand/`.

---

## v2026.09.16.01

### Security

- Removed debug `print()` statements in `api.py` that leaked the full login response (including the session token itself) and full bill details to stdout/Home Assistant's logs on every login and bill fetch.

### Fixed

- **Sensors no longer overwrite good data with a false zero.** `ContactEnergyUsageSensor`, `ContactEnergyPeakCostSensor`, and `ContactEnergyOffPeakCostSensor` recompute their totals from scratch on every poll by re-fetching each day in the usage window. If Contact's API returned no data for *every* day in that window (temporary lag, rate limiting, an expired token), the running sums stayed at `0.0` and were written straight into the sensor state, wiping out the last real reading. All three now detect an entirely empty fetch window and hold the previous value instead.
- **Expired session tokens no longer kill the integration until Home Assistant is restarted.** `ContactEnergyApi._api_token` was only ever set on a successful login and never cleared afterwards. Once the token expired server-side, every authenticated request (`get_usage`, `get_accounts`, `get_plan_details`, `get_bill_details`) started returning `False` - but since the sensors' `if not self._api._api_token: login()` guard only fires when the token is falsy, and the stale token was still a non-empty string, no sensor ever attempted to log in again. A 401/403 response now clears `_api_token`, so the next update cycle re-authenticates automatically.
- `ContactEnergyNextBillDateSensor` and `ContactEnergyNextBillAmountSensor` were missing `_attr_has_entity_name` and `_attr_device_info`, so they appeared outside the "Contact Energy" device tile in the Home Assistant UI instead of grouped with the other five sensors. Fixed without changing their `unique_id`, so existing installs pick up the fix in place rather than getting orphaned duplicate entities.
- Removed the unused `usage_days` constructor parameter from both bill sensors (it was accepted but never read).

### Added

- `tests/` - a `pytest` suite covering `api.py` (login, auth-failure token clearing, usage-data parsing, bill-rate parsing) and `sensor.py` (the hold-last-good-value regression cases, device-grouping). Runs against mocked HTTP responses and a lightweight stub of the `homeassistant` package - no live Contact Energy account or full Home Assistant install required. See the "Running the tests" section in `README.md`.
- `.github/workflows/test.yml` - runs the test suite in CI on every push/PR to `main`.
- `tests/requirements_test.txt` - pinned test dependencies (`pytest`, `pytest-asyncio`, `requests-mock`).

### Known limitations (not yet fixed)

- `ContactEnergyUsageSensor`, `ContactEnergyPeakCostSensor`, and `ContactEnergyOffPeakCostSensor` still each independently re-fetch the same days of usage data from Contact's API on every update cycle, just to compute different aggregates from identical underlying data - roughly 3x the necessary API traffic. Consolidating this into a single shared fetch (e.g. a `DataUpdateCoordinator`) is a planned follow-up.

---

## v2026.01.19.01

**Major Feature Update - Automatic Rate Detection & Enhanced Sensors**

### Added
- Automatic peak/off-peak rate detection from the bill API, with intelligent time-range parsing (e.g. "9PM - 7AM" detected as off-peak) and cents-to-dollars conversion.
- Optional manual rate override (priority: User Override > API Rates > Defaults).
- `Next Bill Date` and `Next Bill Amount` sensors.
- Enhanced device info: model set to the plan name, software version set to the plan ID, configuration URL linking to Contact Energy's My Account.

### Fixed
- Historical statistics now spread across their actual dates/hours instead of being lumped onto one date.
- Business partner ID now correctly extracted from the login response.

---

## v2026.01.18.02

**Major Update - Improved Authentication & Features**

### Changed
- Updated to Contact Energy's current API keys and authentication flow.
- Sensor now includes plan details (name, campaign, contract dates, prompt payment discount, service type) as attributes.
- Premise ID is now stored for future use.

### Fixed
- Corrected API header usage (`session` header instead of a mixed approach).
- Improved handling of missing/delayed API responses.
- Better logging for authentication troubleshooting.

---

## v2026.01.18

- Added UI-based configuration (Config Flow) with credential validation before saving.
- Sensor reports actual state values with cost tracking in attributes.
- Modernized codebase with async patterns and device registry support.
