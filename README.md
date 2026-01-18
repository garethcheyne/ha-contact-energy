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

**Version:** v2026.01.18.1

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

## 📊 Sensors and Data

---

## 📊 Sensors and Data

| `sensor.contact_energy_energy_usage` | Total cumulative energy usage | kWh | Every 3 hours |

### Sensor Attributes

The sensor provides rich attributes with additional information:

| Attribute | Description | Example |
|-----------|-------------|---------|
| `account_id` | Your Contact Energy account ID | `502023369` |
| `contract_id` | Your contract ID | `1351884555` |
| `last_daily_cost` | Cost of the most recent day with data | `$9.83` |
| `plan_name` | Your current energy plan | `Good Charge` |
| `plan_id` | Plan identifier | `RGCHO00` |
| `campaign` | Campaign description | `Good Charge` |
| `contract_start_date` | Contract start date | `2025-09-17` |
| `contract_end_date` | Contract end date | `9999-12-31` |
| `prompt_payment_discount` | Prompt payment discount percentage | `0%` |
| `service_type` | Service type | `Electricity` |

---

## 📈 Energy Dashboard Integration

This integration creates **external statistics** that seamlessly integrate with Home Assistant's Energy Dashboard:

### Available Statistics

| Statistic ID | Description | Use Case |
|--------------|-------------|----------|
| `contact_energy:energy_consumption` | Total energy consumption with hourly granularity | Track overall energy usage patterns |
| `contact_energy:free_energy_consumption` | Free/off-peak energy consumption | Monitor savings from off-peak usage |

### How to Add to Energy Dashboard

1. Navigate to **Settings** → **Dashboards** → **Energy**
2. Click **Add Consumption** in the Electricity section
3. Select `contact_energy:energy_consumption` from the dropdown
4. Optionally add `contact_energy:free_energy_consumption` to track off-peak usage separately

### Hourly Data

The integration fetches **hourly energy usage data** from Contact Energy's API. Each hour's consumption is stored as a separate data point with:
- ⏰ Timestamp (hourly precision)
- ⚡ Energy consumed (kWh)
- 💵 Cost (NZD)
- 🌙 Off-peak indicator

This hourly granularity allows the Energy Dashboard to display detailed consumption patterns throughout the day.

---

## ⚠️ Data Availability
---

## ⚠️ Data Availability

Contact Energy usage data is typically **delayed by 1-2 days**. This is a limitation of Contact Energy's API, not this integration.

- ✅ **Expected:** No data for yesterday or today
- ✅ **Normal:** Data available from 2-3 days ago onwards

## 🔧 API Documentation

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

---

## 📝 Changelog

### v2026.01.18

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
