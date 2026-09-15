# Changelog

All notable changes to this project are documented in this file.

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

## Original v2026.01.18 (Initial Fork)

- Added UI-based configuration (Config Flow) with credential validation before saving.
- Sensor reports actual state values with cost tracking in attributes.
- Modernized codebase with async patterns and device registry support.
