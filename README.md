# Contact Energy integration for Home Assistant

View your energy usage from Contact Energy (New Zealand).

**Version:** v2026.01.18

> **Note:** This is a fork of the original [ha-contact-energy](https://github.com/codyc1515/ha-contact-energy) integration by [@codyc1515](https://github.com/codyc1515). Credit to them for the original implementation.

## Features
- View historical energy usage (updated every 3 hours)
- Track energy costs
- Separate tracking for free/off-peak energy
- Integration with Home Assistant Energy Dashboard
- UI-based configuration with credential validation

## Installation

### HACS (recommended)
1. [Install HACS](https://hacs.xyz/docs/setup/download), if you did not already
2. [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=garethcheyne&repository=ha-contact-energy&category=integration)
3. Install the Contact Energy integration
4. Restart Home Assistant

### Manual Installation
Copy the `custom_components/contact_energy` folder to your Home Assistant's `config/custom_components/` directory.

## Configuration

### UI Setup (v2026.01.18+)
1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for **Contact Energy**
4. Enter your Contact Energy account credentials:
   - **Email**: Your Contact Energy login email
   - **Password**: Your Contact Energy password
   - **Usage Days**: Number of days of history to fetch (default: 10)
5. Click **Submit** - your credentials will be validated before saving

### Legacy YAML Configuration
For older versions, add the following to your `configuration.yaml`:

```yaml
sensor:
  - platform: contact_energy
    email: your-email@example.com
    password: your-password
    usage_days: 10  # Optional, default: 10
```

## Sensors

| Sensor | Description |
|--------|-------------|
| `sensor.contact_energy_energy_usage` | Total energy usage (kWh) |

### Attributes
- `account_id`: Your Contact Energy account ID
- `contract_id`: Your contract ID
- `last_daily_cost`: Cost of the most recent day with data

## Energy Dashboard
This integration creates external statistics that can be used in the Home Assistant Energy Dashboard:
- `contact_energy:energy_consumption` - Total energy consumption
- `contact_energy:free_energy_consumption` - Free/off-peak energy consumption

## Data Availability
Contact Energy usage data is typically delayed by 1-2 days. This is a limitation of Contact Energy's API, not this integration.

## Known Issues
None known.

## Contributing
Your support is welcomed. Please open issues or pull requests on GitHub.

## Changelog

### v2026.01.18
- Added UI-based configuration (Config Flow)
- Credential validation before saving
- Improved sensor with actual state values
- Added cost tracking in sensor attributes
- Modernized codebase with async patterns
- Added device registry support
