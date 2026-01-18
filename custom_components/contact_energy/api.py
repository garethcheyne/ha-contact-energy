"""Contact Energy API."""

import logging
import requests

_LOGGER = logging.getLogger(__name__)


class ContactEnergyApi:
    """Class for Contact Energy API."""

    def __init__(self, email, password):
        """Initialise Contact Energy API."""
        self._api_token = ""
        self._contractId = ""
        self._accountId = ""
        self._premiseId = ""
        self._plan_details = {}
        self._url_base = "https://api.contact-digital-prod.net"
        # Contact Energy uses different API keys for different endpoints
        self._api_key_login = "IHUNZ1q6Ny97U9uS5iztj6UKsOBhJ3eD72LQUizO"  # For login
        self._api_key_data = "wg8mXRp7kQ82aOT7mTkzl9fsULf1sEcu7WMGtn6C"  # For customer/usage data
        self._email = email
        self._password = password

    def login(self):
        """Login to the Contact Energy API."""
        headers = {"x-api-key": self._api_key_login}
        data = {"username": self._email, "password": self._password}
        
        try:
            response = requests.post(
                self._url_base + "/login/v2", 
                json=data, 
                headers=headers,
                timeout=30
            )
            
            if response.status_code == requests.codes.ok:
                json_result = response.json()
                self._api_token = json_result["token"]
                _LOGGER.debug("Logged in successfully")
                
                # Get account info after login
                if self.get_accounts():
                    # Get plan details
                    self.get_plan_details()
                    return True
                return False
            else:
                _LOGGER.error(
                    "Failed to login - check credentials. Status: %s, Response: %s",
                    response.status_code,
                    response.text,
                )
                return False
        except requests.exceptions.RequestException as e:
            _LOGGER.error("Login request failed: %s", e)
            return False

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
                _LOGGER.error(
                    "Failed to fetch usage data for %s: %s", 
                    date_str, 
                    response.text
                )
                return False
        except requests.exceptions.RequestException as e:
            _LOGGER.error("Get usage request failed for %s: %s", date_str, e)
            return False
