"""Contact Energy API."""

import logging
import re
import requests

_LOGGER = logging.getLogger(__name__)

AUTH_ERROR_STATUS_CODES = (401, 403)
# Status codes the login endpoint uses for a wrong email or password.
LOGIN_REJECTED_STATUS_CODES = (400, 401)


class ContactEnergyError(Exception):
    """Base error for the Contact Energy API."""


class ContactEnergyAuthError(ContactEnergyError):
    """Contact Energy rejected the credentials."""


class ContactEnergyConnectionError(ContactEnergyError):
    """Contact Energy could not be reached or returned an unexpected response."""


class ContactEnergyApi:
    """Class for Contact Energy API."""

    def __init__(self, email, password):
        """Initialise Contact Energy API."""
        self._api_token = ""
        self._contractId = ""
        self._accountId = ""
        self._premiseId = ""
        self._businessPartner = ""
        self._plan_details = {}
        self._bill_details = {}
        self._url_base = "https://api.contact-digital-prod.net"
        # Contact Energy uses different API keys for different endpoints
        self._api_key_login = "IHUNZ1q6Ny97U9uS5iztj6UKsOBhJ3eD72LQUizO"  # For login
        self._api_key_data = "wg8mXRp7kQ82aOT7mTkzl9fsULf1sEcu7WMGtn6C"  # For customer/usage data
        self._email = email
        self._password = password

    def _clear_token_on_auth_failure(self, response, context: str) -> None:
        """Clear the stored session token if the API reports it as invalid.

        Without this, an expired token stays truthy forever, the
        `if not self._api_token: login()` guards in the sensors never
        fire again, and every subsequent request silently fails until
        Home Assistant is restarted.
        """
        if response.status_code in AUTH_ERROR_STATUS_CODES:
            _LOGGER.warning(
                "Session token rejected (%s) during %s - clearing it so the "
                "next update triggers a fresh login",
                response.status_code,
                context,
            )
            self._api_token = ""

    @property
    def is_logged_in(self) -> bool:
        """Return True while a session token is held."""
        return bool(self._api_token)

    @property
    def account_id(self) -> str:
        """Return the Contact Energy account ID."""
        return self._accountId

    @property
    def contract_id(self) -> str:
        """Return the electricity contract ID."""
        return self._contractId

    @property
    def plan_details(self) -> dict:
        """Return the most recently fetched plan details."""
        return self._plan_details

    @property
    def bill_details(self) -> dict:
        """Return the most recently fetched bill details."""
        return self._bill_details

    def authenticate(self) -> None:
        """Log in and load the account, plan and bill details.

        Raises ContactEnergyAuthError when Contact rejects the credentials
        and ContactEnergyConnectionError for anything else, so callers can
        tell "ask the user for a new password" apart from "try again later".
        """
        self._api_token = ""
        headers = {"x-api-key": self._api_key_login}
        data = {"username": self._email, "password": self._password}

        try:
            response = requests.post(
                self._url_base + "/login/v2",
                json=data,
                headers=headers,
                timeout=30,
            )
        except requests.exceptions.RequestException as err:
            raise ContactEnergyConnectionError(f"Login request failed: {err}") from err

        if response.status_code in LOGIN_REJECTED_STATUS_CODES:
            raise ContactEnergyAuthError(
                f"Contact Energy rejected the email or password (HTTP {response.status_code})"
            )
        if response.status_code != requests.codes.ok:
            raise ContactEnergyConnectionError(
                f"Login failed with HTTP {response.status_code}"
            )

        try:
            json_result = response.json()
            token = json_result["token"]
        except (ValueError, KeyError, TypeError) as err:
            raise ContactEnergyConnectionError("Unexpected login response") from err

        self._api_token = token
        self._businessPartner = json_result.get("bp", "")
        _LOGGER.debug("Logged in successfully")

        if not self.get_accounts():
            raise ContactEnergyConnectionError("Could not load account details")

        # Plan and bill details are nice-to-have; failures are logged, not fatal.
        self.get_plan_details()
        self.get_bill_details()

    def login(self) -> bool:
        """Log in, returning True on success (see authenticate() for errors)."""
        try:
            self.authenticate()
        except ContactEnergyError as err:
            _LOGGER.error("%s", err)
            return False
        return True

    def get_accounts(self):
        """Get account and contract information."""
        headers = {"x-api-key": self._api_key_data, "session": self._api_token}

        try:
            response = requests.get(
                self._url_base + "/customer/v2?fetchAccounts=true",
                headers=headers,
                timeout=30
            )

            if response.status_code == requests.codes.ok:
                data = response.json()
                _LOGGER.debug("Retrieved accounts")

                # Extract account, contract, and premise IDs
                self._accountId = data["accounts"][0]["id"]
                self._contractId = data["accounts"][0]["contracts"][0]["contractId"]
                self._premiseId = data["accounts"][0]["contracts"][0].get("premiseId", "")

                return True
            else:
                self._clear_token_on_auth_failure(response, "get_accounts")
                _LOGGER.error("Failed to fetch customer accounts: %s", response.text)
                return False
        except (requests.exceptions.RequestException, KeyError, IndexError) as e:
            _LOGGER.error("Get accounts failed: %s", e)
            return False

    def get_plan_details(self):
        """Get plan details for the account."""
        if not self._accountId:
            _LOGGER.warning("Cannot get plan details without account ID")
            return False

        headers = {"x-api-key": self._api_key_data, "session": self._api_token}

        try:
            response = requests.get(
                self._url_base + f"/panel-plans/v2?ba={self._accountId}",
                headers=headers,
                timeout=30
            )

            if response.status_code == requests.codes.ok:
                data = response.json()
                _LOGGER.debug("Retrieved plan details")

                # Extract plan information
                if data.get("premises") and len(data["premises"]) > 0:
                    premise = data["premises"][0]
                    if premise.get("services") and len(premise["services"]) > 0:
                        service = premise["services"][0]
                        plan = service.get("planDetails", {})
                        contract = service.get("contract", {})

                        self._plan_details = {
                            "plan_name": plan.get("externalPlanDescription", "Unknown"),
                            "plan_id": plan.get("planId", ""),
                            "campaign": plan.get("campaignDesc", ""),
                            "benefit_group": plan.get("externalBenefitGroupDescription", ""),
                            "contract_start": contract.get("startDate", ""),
                            "contract_end": contract.get("endDate", ""),
                            "campaign_term": plan.get("campaignTermDescription", ""),
                            "ppd_percentage": plan.get("ppdPercentage", "0%"),
                            "one_off_credit": plan.get("oneOffCreditAmount", "$0.00"),
                            "early_termination_fee": plan.get("earlyTerminationFeeAmount", "$0.00"),
                            "service_type": service.get("serviceDescription", "Electricity"),
                        }
                        return True

                _LOGGER.warning("No plan details found in response")
                return False
            else:
                self._clear_token_on_auth_failure(response, "get_plan_details")
                _LOGGER.error("Failed to fetch plan details: %s", response.text)
                return False
        except (requests.exceptions.RequestException, KeyError) as e:
            _LOGGER.error("Get plan details failed: %s", e)
            return False

    def get_usage(self, year, month, day):
        """Get usage data for a specific day."""
        if not self._contractId or not self._accountId:
            _LOGGER.error("Cannot get usage without account and contract IDs")
            return False

        headers = {"x-api-key": self._api_key_data, "session": self._api_token}
        date_str = f"{year}-{month.zfill(2)}-{day.zfill(2)}"

        try:
            response = requests.post(
                f"{self._url_base}/usage/v2/{self._contractId}?ba={self._accountId}&interval=hourly&from={date_str}&to={date_str}",
                headers=headers,
                timeout=30
            )

            if response.status_code == requests.codes.ok:
                data = response.json()
                if not data:
                    _LOGGER.info(
                        "Fetched usage data for %s, but got nothing back (data may be delayed)",
                        date_str,
                    )
                return data if data else []
            else:
                self._clear_token_on_auth_failure(response, "get_usage")
                _LOGGER.error(
                    "Failed to fetch usage data for %s: %s",
                    date_str,
                    response.text
                )
                return False
        except requests.exceptions.RequestException as e:
            _LOGGER.error("Get usage request failed for %s: %s", date_str, e)
            return False

    def get_bill_details(self):
        """Get current bill details including rates and charges."""
        if not self._api_token or not self._accountId or not self._businessPartner:
            _LOGGER.warning("Cannot fetch bill details - missing credentials (token=%s, accountId=%s, bp=%s)",
                          bool(self._api_token), bool(self._accountId), bool(self._businessPartner))
            return False

        headers = {
            "session": self._api_token,
            "x-api-key": self._api_key_data,
        }

        try:
            # Get current bill
            response = requests.get(
                f"{self._url_base}/interactive-bill?ba={self._accountId}&bp={self._businessPartner}",
                headers=headers,
                timeout=30
            )

            if response.status_code == requests.codes.ok:
                bill_data = response.json()

                # Store for debugging
                self._last_bill_response = bill_data

                _LOGGER.debug("Bill API Response: %s", bill_data)

                # Extract rates from VariableCharges
                variable_charges = bill_data.get("VariableCharges", [])
                fixed_charges = bill_data.get("FixedCharges", [])

                self._bill_details = {
                    "peak_rate": 0.0,
                    "offpeak_rate": 0.0,
                    "peak_rate_cents": 0.0,
                    "offpeak_rate_cents": 0.0,
                    "daily_charge": 0.0,
                    "next_bill_date": bill_data.get("NextBillDate", ""),
                    "next_bill_amount": float(bill_data.get("TotalAmount", 0)),
                    "billing_start": bill_data.get("StartBillingPeriod", ""),
                    "billing_end": bill_data.get("EndBillingPeriod", ""),
                }

                # Parse variable charges for peak/off-peak rates
                for charge in variable_charges:
                    description = charge.get("Description", "")
                    price_str = charge.get("Price", "0")
                    currency_type = charge.get("CurrencyType", "cents").lower()

                    try:
                        price = float(price_str)
                    except (ValueError, TypeError):
                        _LOGGER.warning("Failed to parse price: %s", price_str)
                        continue

                    # Convert cents to dollars (e.g., 32.700 cents → $0.327)
                    if currency_type == "cents":
                        price = price / 100.0
                        _LOGGER.debug("Converted %s cents to $%.4f", price_str, price)

                    # Intelligently detect peak vs off-peak from description
                    # Look for time patterns like "9PM - 7AM" or "7AM - 9PM"
                    time_pattern = r'(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm))\s*[-–]\s*(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm))'
                    match = re.search(time_pattern, description)

                    is_offpeak = False
                    if match:
                        start_time_str = match.group(1).upper().strip()
                        end_time_str = match.group(2).upper().strip()

                        # Parse start and end times to 24-hour format for comparison
                        def parse_time_to_hour(time_str):
                            """Convert time string like '9PM' or '7AM' to 24-hour integer."""
                            time_str = time_str.upper().strip()
                            # Extract hour
                            hour_match = re.match(r'(\d{1,2})', time_str)
                            if not hour_match:
                                return None
                            hour = int(hour_match.group(1))
                            # Adjust for AM/PM
                            if 'PM' in time_str and hour != 12:
                                hour += 12
                            elif 'AM' in time_str and hour == 12:
                                hour = 0
                            return hour

                        start_hour = parse_time_to_hour(start_time_str)
                        end_hour = parse_time_to_hour(end_time_str)

                        if start_hour is not None and end_hour is not None:
                            # Off-peak typically spans midnight (start > end in 24h format)
                            # e.g., 9PM (21) - 7AM (7): 21 > 7 = off-peak
                            # Peak typically doesn't span midnight
                            # e.g., 7AM (7) - 9PM (21): 7 < 21 = peak
                            if start_hour > end_hour:
                                # Spans midnight - likely off-peak (night hours)
                                is_offpeak = True
                                _LOGGER.debug("Detected off-peak (spans midnight): %s - %s", start_time_str, end_time_str)
                            elif start_hour >= 19 or end_hour <= 9:
                                # Starts in evening or ends in morning - likely off-peak
                                is_offpeak = True
                                _LOGGER.debug("Detected off-peak (night hours): %s - %s", start_time_str, end_time_str)
                            else:
                                # Daytime hours - likely peak
                                is_offpeak = False
                                _LOGGER.debug("Detected peak (daytime hours): %s - %s", start_time_str, end_time_str)

                    # Store the rate based on detected type
                    if is_offpeak:
                        self._bill_details["offpeak_rate_cents"] = float(price_str)
                        self._bill_details["offpeak_rate"] = round(price, 4)
                        _LOGGER.info("Off-peak rate: %s cents = $%.4f/kWh (%s)", price_str, price, description)
                    else:
                        # If no time pattern detected or determined to be peak
                        # Only set peak rate if we found a time pattern or if peak rate not already set
                        if match or self._bill_details["peak_rate"] == 0.0:
                            self._bill_details["peak_rate_cents"] = float(price_str)
                            self._bill_details["peak_rate"] = round(price, 4)
                            _LOGGER.info("Peak rate: %s cents = $%.4f/kWh (%s)", price_str, price, description)

                # Parse fixed charges for daily charge
                for charge in fixed_charges:
                    if charge.get("LineItemType") == "ZCODLY":
                        daily_price = charge.get("Price", "0")
                        try:
                            daily_charge = float(daily_price)
                            self._bill_details["daily_charge"] = round(daily_charge, 3)
                            _LOGGER.info("Daily charge: $%.3f/day", daily_charge)
                        except (ValueError, TypeError):
                            _LOGGER.warning("Failed to parse daily charge: %s", daily_price)

                _LOGGER.info(
                    "Retrieved bill details - Peak: $%.4f/kWh, Off-peak: $%.4f/kWh, Daily: $%.3f",
                    self._bill_details["peak_rate"],
                    self._bill_details["offpeak_rate"],
                    self._bill_details["daily_charge"],
                )
                return True
            else:
                self._clear_token_on_auth_failure(response, "get_bill_details")
                _LOGGER.warning(
                    "Failed to fetch bill details: %s - %s",
                    response.status_code,
                    response.text[:200] if response.text else "No response"
                )
                return False
        except requests.exceptions.RequestException as e:
            _LOGGER.error("Get bill details request failed: %s", e)
            return False
        except (KeyError, ValueError, TypeError) as e:
            _LOGGER.error("Failed to parse bill details: %s", e)
            return False
