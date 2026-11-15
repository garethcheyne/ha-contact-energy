# Contact Energy Integration for Home Assistant

<p align="center">
  <img src="https://raw.githubusercontent.com/garethcheyne/ha-contact-energy/main/contact-logo-d.svg" alt="Contact Energy" width="200"/>
</p>

<p align="center">
  <strong>Monitor your energy usage and costs from Contact Energy (New Zealand)</strong>
</p>

<p align="center">
  <a href="https://github.com/garethcheyne/ha-contact-energy/releases">
    <img src="https://img.shields.io/github/v/release/garethcheyne/ha-contact-energy" alt="Release"/>
  </a>
  <a href="https://github.com/garethcheyne/ha-contact-energy/issues">
    <img src="https://img.shields.io/github/issues/garethcheyne/ha-contact-energy" alt="Issues"/>
  </a>
  <a href="https://github.com/garethcheyne/ha-contact-energy/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/garethcheyne/ha-contact-energy" alt="License"/>
  </a>
</p>

---

## 📋 Overview

This Home Assistant custom integration connects to Contact Energy's API to provide real-time monitoring of your electricity usage and costs. Perfect for New Zealand homes wanting to track their energy consumption through Home Assistant's powerful Energy Dashboard.

**Version:** v2026.11.16.01

> **Attribution:** This is a fork of the original [ha-contact-energy](https://github.com/codyc1515/ha-contact-energy) integration by [@codyc1515](https://github.com/codyc1515). Credit to them for the original implementation.

---

## ✨ Features

- 🔌 **Hourly Energy Usage** - Detailed consumption data updated every 3 hours
- 💰 **Cost Tracking** - Real-time cost monitoring for your energy usage
- 🌙 **Off-Peak Detection** - Separate tracking for free/off-peak energy periods  
- 📊 **Energy Dashboard Integration** - Seamless integration with Home Assistant's Energy Dashboard
- 📱 **Plan Information** - View your current energy plan details and contract information
- ⚙️ **UI Configuration** - Easy setup through Home Assistant's UI with credential validation
- 📈 **Historical Data** - Fetch up to 30 days of historical usage data

---

## 📦 Installation

Requires **Home Assistant 2025.11 or newer**.

### Option 1: Home Assistant Marketplace (recommended)

From Home Assistant 2026.11 the Marketplace (which replaced HACS) is built in.

1. Click the button below to open this repository in your Marketplace (it also works with HACS):

   [![Open your Home Assistant instance and open this repository in the Marketplace.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=garethcheyne&repository=ha-contact-energy&category=integration)

   Or go to **Settings → Marketplace**, open the menu, choose **Custom repositories**, and add `https://github.com/garethcheyne/ha-contact-energy` as an **Integration**.
2. Install **Contact Energy**.
3. **Restart Home Assistant**.

If you are on Home Assistant 2025.11 – 2026.10 with HACS, add the same URL as a HACS custom repository instead.

### Option 2: Manual installation

1. Download the latest release from the [releases page](https://github.com/garethcheyne/ha-contact-energy/releases).
2. Copy the `custom_components/contact_energy` folder into your Home Assistant `config/custom_components/` folder.
3. **Restart Home Assistant**.

---

## ⚙️ Configuration

1. Go to **Settings → Devices & services → Add integration**.
2. Search for **Contact Energy**.
3. Sign in with your Contact Energy email and password. They are checked before anything is saved.

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| **Email** | Yes | - | Your Contact Energy account email |
| **Password** | Yes | - | Your Contact Energy account password |
| **Usage window (days)** | No | 10 | How many recent days to fetch on each update (1-30) |
| **Peak rate override** | No | From your bill | NZD/kWh |
| **Off-peak rate override** | No | From your bill | NZD/kWh (use `0` for free-hours plans) |

You can change the usage window and rate overrides later with **Configure** on the integration. Clear a rate field to go back to the rate on your bill. If Contact stops accepting your saved password, Home Assistant asks you to sign in again.

YAML configuration is not supported.

### Rates

Each rate is chosen in this order:

1. **Your override**, if you entered one.
2. **The rate on your current bill** (for example peak `$0.327/kWh`, off-peak `$0.161/kWh`).
3. **Defaults** of `$0.30/kWh` peak and `$0.15/kWh` off-peak, if the bill can't be read.

The `rate_source` attribute on **Current Price** shows which one is in use.

---

## 📊 Sensors and Data

The integration adds one **Contact Energy** device with 7 sensors. Data is fetched every 3 hours, with one request per day of the usage window shared by all sensors.

| Sensor | Example | Notes |
|--------|---------|-------|
| **Energy Usage** | `26.64 kWh` | Total usage over the usage window. Attributes: account and contract IDs, plan details, `last_daily_usage`, `last_daily_cost`, `last_data_date`, `peak_usage`, `offpeak_usage`. |
| **Current Price** | `0.3270 NZD/kWh` | The rate for the current hour, re-checked at the top of every hour. Attributes: `peak_rate`, `offpeak_rate`, `current_period`, `rate_source`. |
| **Peak Cost** | `5.11 NZD` | Peak usage in the window × peak rate. |
| **Off-Peak Cost** | `1.77 NZD` | Off-peak usage in the window × off-peak rate. |
| **Off-Peak Period** | `21:00 - 07:00` | Off-peak hours (NZ time) detected from your most recent usage. |
| **Next Bill Date** | `2026-12-17` | |
| **Next Bill Amount** | `145.32 NZD` | |

**Energy Usage**, **Peak Cost** and **Off-Peak Cost** are rolling totals over the usage window, so they rise and fall as days move in and out of it. For that reason they have no state class and aren't offered as Energy Dashboard sources. Use the statistics below for the dashboard.

> **Upgrading from an earlier version?** Home Assistant may show a repair saying these sensors no longer have a state class. Choose to delete their old long-term statistics; they were not meaningful.

If Contact's API returns no data at all for an update, the sensors keep their last values instead of dropping to zero.

---

## 📈 Energy Dashboard Integration

The integration writes hourly **external statistics** for the Energy Dashboard:

| Statistic ID | Name | Contains |
|--------------|------|----------|
| `contact_energy:energy_consumption` | Contact Energy | Peak-time usage (kWh) |
| `contact_energy:free_energy_consumption` | Contact Energy Free | Off-peak / free-hours usage (kWh) |
| `contact_energy:energy_cost` | Contact Energy Cost | What Contact charged for peak-time usage (NZD) |
| `contact_energy:free_energy_cost` | Contact Energy Free Cost | What Contact charged for off-peak usage (NZD) |

The cost statistics use the cost Contact reports for each hour, so the dashboard shows your actual usage charges rather than an estimate from a flat rate. They don't include the daily fixed charge.

### Adding them to the Energy Dashboard

1. Go to **Settings → Dashboards → Energy**.
2. Under **Electricity grid**, choose **Add consumption** and pick **Contact Energy**.
3. For cost, choose **Use an entity tracking the total costs** and pick **Contact Energy Cost**.
4. Add **Contact Energy Free** the same way, with **Contact Energy Free Cost** as its cost.

If you prefer estimated costs, choose **Use an entity with current price** and pick the **Current Price** sensor instead.

Each hourly row holds that hour's value and a running total (`sum`), which is what the Energy Dashboard reads. Every update rewrites the usage window and carries the running total on from the last stored hour, so re-fetched days don't cause spikes. To fill in costs for earlier months, run the import action below.

> **Energy Dashboard empty or showing spikes after upgrading?** Versions up to v2026.09.16.02 wrote statistics without running totals. Run the import action once with `clear_existing: true` (see below) to rebuild the history.

---

## ⚠️ Data Availability

Contact Energy usage data is typically **delayed by 1-2 days**. This is a limitation of Contact Energy's API, not this integration.

- ✅ **Expected:** No data for yesterday or today
- ✅ **Normal:** Data available from 2-3 days ago onwards

### Importing Historical Data

Use the `contact_energy.import_historical_data` action (**Developer tools → Actions**) to load older usage into the Energy Dashboard.

**Add history:**
```yaml
action: contact_energy.import_historical_data
data:
  days: 90  # 1-365, default 90
```

**Rebuild history from scratch** (deletes all existing Contact Energy statistics first):
```yaml
action: contact_energy.import_historical_data
data:
  days: 365
  clear_existing: true
  confirm_clear: "yes"  # required with clear_existing
```

If you have more than one Contact Energy account set up, add `config_entry_id` to choose the account. The action returns the number of hours imported, and reports an error if Contact can't be reached or returns no data.

### Exporting Historical Data

To export all historical data for analysis or plotting in external tools (Excel, Python, R, etc.):

**Developer tools → Actions:**
```yaml
action: contact_energy.export_historical_data
data:
  days: 30  # 1-365, default 30
```

This will:
1. Fetch up to 365 days of hourly data from Contact Energy
2. Write it to `/config/contact_energy_export.csv`
3. Return (and log) a summary: hours, total/peak/off-peak kWh and total cost

**CSV Format:**
```csv
timestamp,date,hour,kwh,cost_nzd,is_offpeak,offpeak_kwh,peak_kwh
2026-01-15 00:00:00,2026-01-15,0,1.15,0.185,1,1.15,0.00
2026-01-15 01:00:00,2026-01-15,1,0.98,0.158,1,0.98,0.00
2026-01-15 07:00:00,2026-01-15,7,2.34,0.765,0,0.00,2.34
```

**Use Cases:**
- Create custom visualizations in Excel, Tableau, or Power BI
- Analyze usage patterns with Python (pandas, matplotlib)
- Calculate custom statistics or forecasts
- Backup historical data before making changes
- Share data with energy consultants

**Example Python Plot:**
```python
import pandas as pd
import matplotlib.pyplot as plt

# Load exported data
df = pd.read_csv('/config/contact_energy_export.csv')
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Plot daily consumption
daily = df.groupby('date')['kwh'].sum()
daily.plot(kind='bar', title='Daily Energy Consumption', ylabel='kWh')
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()

# Plot hourly pattern (average by hour of day)
hourly_avg = df.groupby('hour')['kwh'].mean()
hourly_avg.plot(kind='line', title='Average Hourly Consumption', ylabel='kWh', xlabel='Hour')
plt.show()
```

---

## 🔧 API Documentation

This integration uses Contact Energy's REST API. The integration automatically handles authentication and data retrieval.

<details>
1. **Login** - Authenticate with email/password to receive a session token
2. **Get Accounts** - Retrieve account and contract IDs
3. **Get Plan Details** - Fetch current energy plan information
4. **Get Usage** - Retrieve hourly consumption data

### API Endpoints

**Base URL:** `https://api.contact-digital-prod.net`

#### Login
```
POST /login/v2
Headers: x-api-key: {API_KEY}
Body: {"username": "email@example.com", "password": "password"}
Response: {"token": "...", "segment": "RESI", "bp": "..."}
```
Returns an authentication token for subsequent requests.

#### Get Accounts
```
GET /customer/v2?fetchAccounts=true
Headers: 
  x-api-key: {API_KEY}
  session: {TOKEN}
Response: {
  "accounts": [{
    "id": "account_id",
    "contracts": [{"contractId": "contract_id", "premiseId": "..."}]
  }]
}
```
Retrieves account and contract IDs needed for usage queries.

#### Get Plan Details
```
GET /panel-plans/v2?ba={ACCOUNT_ID}
Headers:
  x-api-key: {API_KEY}
  session: {TOKEN}
Response: {
  "premises": [{
    "services": [{
      "planDetails": {
        "externalPlanDescription": "Good Charge",
        "campaignDesc": "...",
        "ppdPercentage": "0%",
        ...
      }
    }]
  }]
}
```
Fetches detailed plan and pricing information.

#### Get Usage Data
```
POST /usage/v2/{CONTRACT_ID}?ba={ACCOUNT_ID}&interval=hourly&from=YYYY-MM-DD&to=YYYY-MM-DD
Headers:
  x-api-key: {API_KEY}
  session: {TOKEN}
Response: [
  {
    "date": "2026-01-15T00:00:00.000+13:00",
    "value": 1.11,                    // kWh consumed
    "dollarValue": 0.299,             // Cost (NZD)
    "offpeakValue": 1.11,             // Off-peak kWh (0.00 if peak)
    "unit": "kWh",
    "timeZone": "Pacific/Auckland"
  },
  // ... 23 more hourly records
]
```

### Data Processing

The integration:
1. **Fetches hourly data** for the configured number of days (default: 10 days)
2. **Processes each hourly record** and tracks:
   - Total energy consumption (cumulative)
   - Free/off-peak energy (when `offpeakValue` > 0)
   - Costs (`dollarValue` field)
3. **Creates external statistics** for Home Assistant Energy Dashboard with:
   - Timestamp from `date` field
   - Running sum of consumption
   - Separate tracking for free energy

### Off-Peak Detection

Energy is classified as "free" or off-peak when `offpeakValue` > 0. During peak times, `offpeakValue` is `0.00` and all energy is charged at standard rates.

</details>

---

## 🐛 Known Issues

- Contact Energy usage data is usually 1-2 days behind.
- Off-peak hours are inferred from your recent usage. If the latest day has no off-peak hours, the most recent day that does is used.

Please [report any other issues](https://github.com/garethcheyne/ha-contact-energy/issues) you encounter.

---

## 🤝 Contributing

Your support and contributions are welcome! Here's how you can help:

- 🐛 [Report bugs](https://github.com/garethcheyne/ha-contact-energy/issues/new?template=bug_report.md)
- 💡 [Request features](https://github.com/garethcheyne/ha-contact-energy/issues/new?template=feature_request.md)
- 🔧 [Submit pull requests](https://github.com/garethcheyne/ha-contact-energy/pulls)
- ⭐ Star this repository if you find it useful!

### Running the tests

The test suite mocks the HTTP layer and the `homeassistant` symbols the integration uses, so it never hits the real Contact Energy API and doesn't require installing Home Assistant itself:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r tests/requirements_test.txt
pytest tests/ -v
```

`ruff check .` (see `.ruff.toml`) is run in CI alongside the test suite - please run both before opening a PR.

---

## 📝 Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full history. Latest release:

### v2026.11.16.01

**Energy Dashboard, Home Assistant 2026.11 and Marketplace update**

- 📈 **Energy Dashboard fixed:** statistics now include running totals that carry on correctly between updates. Run the import action once with `clear_existing: true` to rebuild old history.
- 🔧 **Home Assistant 2026.11 ready:** statistics use `mean_type` and `unit_class`, and the options dialog works again.
- 🔐 **Re-authentication:** a changed password now asks you to sign in again instead of the integration silently failing. Network outages at startup are retried automatically.
- ⚡ **One shared fetch** per update instead of one per sensor (about 3× fewer API calls).
- 💵 **Real costs in the Energy Dashboard:** new `contact_energy:energy_cost` and `contact_energy:free_energy_cost` statistics carry what Contact charged for each hour.
- 💲 **Current Price** now switches at the right hour.
- 🛒 Marketplace-ready manifest, plus translations for the setup, options and action forms.

---

### v2026.09.16.02

**Bug Fixes**

- Integration logo not displaying in Home Assistant/HACS. Local brand images (`icon.png`, `icon@2x.png`) must live in a `brand/` subdirectory under `custom_components/contact_energy/` per HA 2026.3+ requirements - moved them there from the integration root.

---

### v2026.09.16.01

**Security & Reliability Fixes**

#### 🔒 Security
- Removed debug `print()` statements in `api.py` that leaked the full login response - including the session token - and bill details to Home Assistant's logs.

#### 🐛 Bug Fixes
- **Sensors no longer overwrite good data with zero.** `Energy Usage`, `Peak Cost`, and `Off-Peak Cost` used to silently reset to `0.0` whenever Contact's API returned no data for the entire polling window (temporary lag, rate limiting), wiping out the last real reading. They now hold the last known good value until the next successful fetch.
- **Expired session tokens no longer kill the integration until restart.** The API client never cleared `_api_token` after an auth failure, so once a session expired, every sensor's re-login guard stayed permanently false and all requests failed silently. A 401/403 now clears the token so the next update cycle re-authenticates automatically.
- `Next Bill Date` / `Next Bill Amount` sensors now correctly group under the "Contact Energy" device tile in the UI (previously missing `has_entity_name`/device info). Existing entity IDs are unaffected.

#### 🧪 Testing
- Added a `pytest` suite (`tests/`) covering the API client and sensor aggregation logic, including regression tests for both bugs above. Runs in CI on every push/PR via `.github/workflows/test.yml`.

---

### v2026.01.19.01

**Major Feature Update - Automatic Rate Detection & Enhanced Sensors**

#### 🆕 New Features
- 🤖 **Automatic Rate Detection** - Fetches peak/off-peak rates directly from your bill API
  - Intelligent time range parsing (e.g., "9PM - 7AM" detected as off-peak)
  - Works with any plan's time periods (not hardcoded)
  - Converts cents to dollars automatically (32.700 cents → $0.327/kWh)
- 🎛️ **User Rate Override** - Optional manual rate configuration
  - Priority: User Override > API Rates > Defaults
  - Leave fields empty for automatic detection
- 📅 **Next Bill Date Sensor** - Shows when your next bill is due
- 💵 **Next Bill Amount Sensor** - Displays estimated next bill amount
- 🏷️ **Enhanced Device Info** - Device now shows:
  - Model: Your plan name (e.g., "Good Charge")
  - Software Version: Plan ID (e.g., "RGCHO00")
  - Configuration URL: Link to Contact Energy My Account

#### 🔧 Improvements
- ✅ **Fixed Historical Data** - Statistics now properly spread across actual dates/hours
  - Each hour appears on its correct timestamp (not lumped on one date)
  - Includes both `state` (hourly value) and `sum` (cumulative)
- ✅ **Business Partner Extraction** - Now correctly extracted from login response
- ✅ **7 Total Sensors** - Complete energy monitoring suite:
  1. Energy Usage (with hourly statistics)
  2. Current Price (for Energy Dashboard)
  3. Peak Cost
  4. Off-Peak Cost
  5. Off-Peak Period
  6. Next Bill Date (NEW)
  7. Next Bill Amount (NEW)

#### 📚 Documentation
- Complete sensor documentation with examples and attributes
- Rate configuration modes explained
- Device info customization documented

---

### v2026.01.18.02

**Major Update - Improved Authentication & Features**

#### 🔒 Authentication Improvements
- ✅ Updated to use Contact Energy's current API keys
- ✅ Fixed authentication flow to match official web interface
- 🆕 **Plan Details** - Sensor now includes your energy plan information as attributes
  - Plan name and campaign details
  - Contract start/end dates
  - Prompt payment discount percentage
  - Service type information
- 🆕 **Premise ID Tracking** - Now stores and tracks premise IDs for future enhancements

#### 🐛 Bug Fixes
- Fixed API header usage (using correct `session` header instead of mixed approaches)
- Improved response handling for missing or delayed data
- Better logging for troubleshooting authentication issues

#### 📚 Documentation
- Comprehensive API documentation with all endpoints
- Better formatted README with logo and badges
- Detailed explanation of hourly statistics and Energy Dashboard integration
- Clear data availability expectations

---

#### Previous Versions

<details>
<summary>View older changelog entries</summary>

### Original v2026.01.18 (Initial Fork)
- Added UI-based configuration (Config Flow)
- Credential validation before saving
- Improved sensor with actual state values
- Added cost tracking in sensor attributes
- Modernized codebase with async patterns
- Added device registry support

</details>

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- Original integration by [@codyc1515](https://github.com/codyc1515)
- Contact Energy for providing API access
- Home Assistant community for ongoing support

---

<p align="center">
  Made with ❤️ for the Home Assistant community
</p>
