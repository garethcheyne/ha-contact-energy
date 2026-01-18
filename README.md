# Contact Energy Integration for Home Assistant

<p align="center">
  <img src="https://github.com/home-assistant/brands/blob/master/custom_integrations/contact_energy/logo.png" alt="Contact Energy" width="200"/>
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

**Version:** v2026.01.19.01

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

### Option 1: HACS (Recommended)

1. Ensure [HACS](https://hacs.xyz/docs/setup/download) is installed in your Home Assistant instance
2. Click the button below to add this repository to HACS:
   
   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=garethcheyne&repository=ha-contact-energy&category=integration)
   
3. Search for "Contact Energy" in HACS
4. Click **Download** to install the integration
5. **Restart Home Assistant**

### Option 2: Manual Installation

1. Download the latest release from the [releases page](https://github.com/garethcheyne/ha-contact-energy/releases)
2. Extract the contents
3. Copy the `custom_components/contact_energy` folder to your Home Assistant's `config/custom_components/` directory
4. **Restart Home Assistant**

---

## ⚙️ Configuration

3. Search for **"Contact Energy"**
4. Enter your Contact Energy account credentials:
   
   | Field | Description |
   |-------|-------------|
   | **Email** | Your Contact Energy account email address |
   | **Password** | Your Contact Energy account password |
   | **Usage Days** | Number of days of historical data to fetch (1-30, default: 10) |

5. Click **Submit** - your credentials will be validated before saving
6. The integration will immediately fetch your historical usage data and add it to Home Assistant

### Legacy YAML Configuration (Deprecated)

> ⚠️ **Note:** YAML configuration is deprecated. Please use the UI configuration method above.

<details>
<summary>Click to expand YAML configuration</summary>

For older versions, add the following to your `configuration.yaml`:

```yaml
sensor:
  - platform: contact_energy
    email: your-email@example.com
    password: your-password
    usage_days: 10  # Optional, default: 10
```

</details>

---

## ⚙️ Configuration

The integration is configured through Home Assistant's UI:

### Configuration Options

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| **Email** | Yes | string | - | Your Contact Energy account email |
| **Password** | Yes | password | - | Your Contact Energy account password |
| **Usage Days** | No | integer (1-30) | 10 | Number of days of historical data to fetch |
| **Peak Rate** | No | decimal (0.01-5.0) | Auto-detect | Peak rate override (NZD/kWh) - leave empty to fetch from API |
| **Off-Peak Rate** | No | decimal (0.0-5.0) | Auto-detect | Off-peak rate override (NZD/kWh) - leave empty to fetch from API |

### Rate Configuration

The integration supports **three modes** for rate configuration:

1. **API Auto-Detection (Recommended)** - Leave rate fields empty
   - Fetches rates automatically from your bill API
   - Updates based on your actual plan pricing
   - Example: `Peak: $0.327/kWh, Off-Peak: $0.161/kWh`

2. **Manual Override** - Enter specific values
   - Use when you want to override API-detected rates
   - Useful for custom calculations or testing
   - Example: `Peak: $0.35/kWh, Off-Peak: $0.20/kWh`

3. **Default Fallback** - If API fails and no override provided
   - Peak: $0.30/kWh
   - Off-Peak: $0.15/kWh

**Priority:** Manual Override > API Auto-Detection > Default Fallback

---

## 📊 Sensors and Data

This integration creates **7 sensors** for comprehensive energy monitoring:

### Sensor Entities

#### 1. **Energy Usage Sensor**
- **Entity ID:** `sensor.contact_energy_usage`
- **Unit:** kWh
- **Update Frequency:** Every 3 hours
- **Description:** Total cumulative energy consumption
- **Example Value:** `26.64 kWh`

**Attributes:**
```yaml
account_id: "502023369"
contract_id: "1351884555"
plan_name: "Good Charge"
plan_id: "RGCHO00"
campaign: "Good Charge"
benefit_group: "Good Charge"
contract_start: "2025-09-17"
contract_end: "9999-12-31"
ppd_percentage: "0%"
service_type: "Electricity"
peak_kwh: 15.63
offpeak_kwh: 11.01
peak_rate: 0.327
offpeak_rate: 0.161
daily_charge: 2.885
```

#### 2. **Current Price Sensor**
- **Entity ID:** `sensor.contact_energy_current_price`
- **Unit:** NZD/kWh
- **Update Frequency:** Real-time (changes based on time of day)
- **Description:** Current electricity rate (peak or off-peak)
- **Example Value:** `$0.3270/kWh` (during 7AM-9PM) or `$0.1610/kWh` (during 9PM-7AM)
- **Use Case:** Energy Dashboard cost tracking

**Attributes:**
```yaml
current_period: "Peak (7AM - 9PM)"  # or "Off-Peak (9PM - 7AM)"
peak_rate: 0.327
offpeak_rate: 0.161
rate_source: "API-Fetched"  # or "Manual-Override" or "Default"
```

#### 3. **Peak Cost Sensor**
- **Entity ID:** `sensor.contact_energy_peak_cost`
- **Unit:** NZD
- **Update Frequency:** Every 3 hours
- **Description:** Total cost of peak energy consumption
- **Calculation:** `peak_kwh × peak_rate`
- **Example Value:** `$5.11 NZD`

**Attributes:**
```yaml
peak_kwh: 15.63
peak_rate: 0.327
peak_cost: 5.11
```

#### 4. **Off-Peak Cost Sensor**
- **Entity ID:** `sensor.contact_energy_offpeak_cost`
- **Unit:** NZD
- **Update Frequency:** Every 3 hours
- **Description:** Total cost of off-peak energy consumption
- **Calculation:** `offpeak_kwh × offpeak_rate`
- **Example Value:** `$1.77 NZD`

**Attributes:**
```yaml
offpeak_kwh: 11.01
offpeak_rate: 0.161
offpeak_cost: 1.77
```

#### 5. **Off-Peak Period Sensor**
- **Entity ID:** `sensor.contact_energy_offpeak_period`
- **Unit:** -
- **Update Frequency:** On startup
- **Description:** Time range for off-peak pricing
- **Example Value:** `21:00 - 07:00` or `9PM - 7AM`

**Attributes:**
```yaml
start_time: "21:00"
end_time: "07:00"
duration_hours: 10
```

#### 6. **Next Bill Date Sensor**
- **Entity ID:** `sensor.contact_energy_next_bill_date`
- **Unit:** -
- **Device Class:** Date
- **Update Frequency:** Every 3 hours
- **Description:** Next bill due date
- **Example Value:** `2026-02-17`

**Attributes:**
```yaml
billing_start: "2026-01-18"
billing_end: "2026-02-17"
```

#### 7. **Next Bill Amount Sensor**
- **Entity ID:** `sensor.contact_energy_next_bill_amount`
- **Unit:** NZD
- **Device Class:** Monetary
- **Update Frequency:** Every 3 hours
- **Description:** Estimated next bill amount
- **Example Value:** `$145.32 NZD`

**Attributes:**
```yaml
billing_period: "30 days"
peak_cost: 95.50
offpeak_cost: 34.82
daily_charges: 15.00
```

---

## 📈 Energy Dashboard Integration

This integration creates **external statistics** that seamlessly integrate with Home Assistant's Energy Dashboard:

### Available Statistics

| Statistic ID | Description | Use Case |
|--------------|-------------|----------|
| `contact_energy:energy_consumption` | Total energy consumption with hourly granularity | Track overall energy usage patterns |
| `contact_energy:peak_consumption` | Peak period consumption only | Monitor daytime usage |
| `contact_energy:offpeak_consumption` | Off-peak period consumption only | Monitor nighttime/off-peak usage |

### How to Add to Energy Dashboard

1. Navigate to **Settings** → **Dashboards** → **Energy**
2. Click **Add Consumption** in the Electricity section
3. Select `sensor.contact_energy_current_price` for **Use an entity with current price**
4. Optionally add individual statistics:
   - `contact_energy:energy_consumption` - Total consumption
   - `contact_energy:peak_consumption` - Peak hours only
   - `contact_energy:offpeak_consumption` - Off-peak hours only

### Hourly Data Structure

The integration stores **hourly statistics** with the following data:

```python
StatisticData(
    start=datetime(2026, 1, 16, 0, 0),  # Hour start
    state=1.15,                          # kWh consumed
    sum=cumulative_total                 # Running total
)
```

**Example Hour:**
```yaml
timestamp: "2026-01-16T00:00:00+13:00"
energy: 1.15 kWh
cost: $0.185 NZD
period: "Off-Peak"
rate: $0.161/kWh
```
- 🌙 Off-peak indicator

This hourly granularity allows the Energy Dashboard to display detailed consumption patterns throughout the day.

---

## ⚠️ Data Availability

Contact Energy usage data is typically **delayed by 1-2 days**. This is a limitation of Contact Energy's API, not this integration.

- ✅ **Expected:** No data for yesterday or today
- ✅ **Normal:** Data available from 2-3 days ago onwards

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

None currently known. Please [report any issues](https://github.com/garethcheyne/ha-contact-energy/issues) you encounter.

---

## 🤝 Contributing

Your support and contributions are welcome! Here's how you can help:

- 🐛 [Report bugs](https://github.com/garethcheyne/ha-contact-energy/issues/new?template=bug_report.md)
- 💡 [Request features](https://github.com/garethcheyne/ha-contact-energy/issues/new?template=feature_request.md)
- 🔧 [Submit pull requests](https://github.com/garethcheyne/ha-contact-energy/pulls)
- ⭐ Star this repository if you find it useful!

---

## 📝 Changelog

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
