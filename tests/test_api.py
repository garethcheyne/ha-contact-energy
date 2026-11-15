"""Tests for ContactEnergyApi.

These tests mock the HTTP layer with requests_mock - they never hit the
real Contact Energy API. Run with:

    pip install -r tests/requirements_test.txt
    pytest tests/test_api.py -v
"""

import sys
from pathlib import Path

import pytest
import requests
import requests_mock

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "contact_energy"))

from api import (  # noqa: E402
    ContactEnergyApi,
    ContactEnergyAuthError,
    ContactEnergyConnectionError,
)

BASE = "https://api.contact-digital-prod.net"


@pytest.fixture
def api():
    return ContactEnergyApi("test@example.com", "hunter2")


def _login_ok(m, token="abc123", bp="BP001"):
    m.post(f"{BASE}/login/v2", json={"token": token, "bp": bp})


def _accounts_ok(m, account_id="ACC1", contract_id="CON1", premise_id="PREM1"):
    m.get(
        f"{BASE}/customer/v2?fetchAccounts=true",
        json={
            "accounts": [
                {
                    "id": account_id,
                    "contracts": [{"contractId": contract_id, "premiseId": premise_id}],
                }
            ]
        },
    )


def _plan_details_ok(m):
    m.get(
        requests_mock.ANY,
        additional_matcher=lambda r: r.path == "/panel-plans/v2",
        json={
            "premises": [
                {
                    "services": [
                        {
                            "planDetails": {
                                "externalPlanDescription": "Good Charge",
                                "planId": "RGCHO00",
                            },
                            "contract": {"startDate": "2025-09-17", "endDate": "9999-12-31"},
                            "serviceDescription": "Electricity",
                        }
                    ]
                }
            ]
        },
    )


def _bill_details_ok(m):
    m.get(
        requests_mock.ANY,
        additional_matcher=lambda r: r.path == "/interactive-bill",
        json={
            "TotalAmount": "615.67",
            "NextBillDate": "2026-09-17T00:00:00+13:00",
            "StartBillingPeriod": "2026-08-18T00:00:00+13:00",
            "EndBillingPeriod": "2026-09-17T00:00:00+13:00",
            "VariableCharges": [
                {"Description": "7AM - 9PM", "Price": "32.700", "CurrencyType": "cents"},
                {"Description": "9PM - 7AM", "Price": "16.100", "CurrencyType": "cents"},
            ],
            "FixedCharges": [
                {"LineItemType": "ZCODLY", "Price": "2.885"},
            ],
        },
    )


class TestLogin:
    def test_login_success_chains_account_plan_and_bill_lookups(self, api):
        with requests_mock.Mocker() as m:
            _login_ok(m, token="abc123")
            _accounts_ok(m)
            _plan_details_ok(m)
            _bill_details_ok(m)

            assert api.login() is True
            assert api._api_token == "abc123"
            assert api._accountId == "ACC1"
            assert api._contractId == "CON1"
            assert api._bill_details["peak_rate"] == pytest.approx(0.327)
            assert api._bill_details["offpeak_rate"] == pytest.approx(0.161)
            assert api._bill_details["daily_charge"] == pytest.approx(2.885)

    def test_login_bad_credentials_returns_false(self, api):
        with requests_mock.Mocker() as m:
            m.post(f"{BASE}/login/v2", status_code=401, text="invalid credentials")
            assert api.login() is False
            assert api._api_token == ""

    def test_login_network_error_returns_false(self, api):
        with requests_mock.Mocker() as m:
            m.post(f"{BASE}/login/v2", exc=requests.exceptions.ConnectionError)
            assert api.login() is False

    @pytest.mark.parametrize("status", [400, 401])
    def test_authenticate_rejected_credentials_raise_auth_error(self, api, status):
        with requests_mock.Mocker() as m:
            m.post(f"{BASE}/login/v2", status_code=status, text="invalid credentials")
            with pytest.raises(ContactEnergyAuthError):
                api.authenticate()

    def test_authenticate_network_error_raises_connection_error(self, api):
        """Network trouble must not be reported as a wrong password."""
        with requests_mock.Mocker() as m:
            m.post(f"{BASE}/login/v2", exc=requests.exceptions.ConnectionError)
            with pytest.raises(ContactEnergyConnectionError):
                api.authenticate()

    def test_authenticate_server_error_raises_connection_error(self, api):
        with requests_mock.Mocker() as m:
            m.post(f"{BASE}/login/v2", status_code=503, text="maintenance")
            with pytest.raises(ContactEnergyConnectionError):
                api.authenticate()

    def test_authenticate_fails_when_accounts_cannot_be_loaded(self, api):
        with requests_mock.Mocker() as m:
            _login_ok(m)
            m.get(f"{BASE}/customer/v2?fetchAccounts=true", status_code=500, text="oops")
            with pytest.raises(ContactEnergyConnectionError):
                api.authenticate()

    def test_login_does_not_leak_token_to_stdout(self, api, capsys):
        """Regression test: login() must not print the session token.

        It used to print() the full response straight to stdout/HA logs.
        """
        with requests_mock.Mocker() as m:
            _login_ok(m, token="super-secret-token")
            _accounts_ok(m)
            _plan_details_ok(m)
            _bill_details_ok(m)

            api.login()

        captured = capsys.readouterr()
        assert "super-secret-token" not in captured.out
        assert captured.out == ""


class TestTokenAutoClearOnAuthFailure:
    """Regression tests for the 'integration dies forever after token expiry' bug.

    Once the token expires, the stored token must be cleared so the next
    update logs in again.
    """

    def test_get_usage_clears_token_on_401(self, api):
        api._api_token = "stale-token"
        api._accountId = "ACC1"
        api._contractId = "CON1"

        with requests_mock.Mocker() as m:
            m.post(requests_mock.ANY, status_code=401, text="token expired")
            result = api.get_usage("2026", "9", "1")

        assert result is False
        assert api._api_token == ""

    def test_get_usage_clears_token_on_403(self, api):
        api._api_token = "stale-token"
        api._accountId = "ACC1"
        api._contractId = "CON1"

        with requests_mock.Mocker() as m:
            m.post(requests_mock.ANY, status_code=403, text="forbidden")
            api.get_usage("2026", "9", "1")

        assert api._api_token == ""

    def test_get_usage_keeps_token_on_server_error(self, api):
        """A transient 500 shouldn't force a re-login - only auth failures should."""
        api._api_token = "still-good-token"
        api._accountId = "ACC1"
        api._contractId = "CON1"

        with requests_mock.Mocker() as m:
            m.post(requests_mock.ANY, status_code=500, text="server error")
            api.get_usage("2026", "9", "1")

        assert api._api_token == "still-good-token"

    def test_get_accounts_clears_token_on_401(self, api):
        api._api_token = "stale-token"
        with requests_mock.Mocker() as m:
            m.get(requests_mock.ANY, status_code=401, text="token expired")
            api.get_accounts()
        assert api._api_token == ""

    def test_get_bill_details_clears_token_on_401(self, api):
        api._api_token = "stale-token"
        api._accountId = "ACC1"
        api._businessPartner = "BP001"
        with requests_mock.Mocker() as m:
            m.get(requests_mock.ANY, status_code=401, text="token expired")
            api.get_bill_details()
        assert api._api_token == ""


class TestGetUsage:
    def test_returns_false_without_account_or_contract_ids(self, api):
        assert api.get_usage("2026", "9", "1") is False

    def test_returns_empty_list_when_no_data_available_yet(self, api):
        api._api_token = "tok"
        api._accountId = "ACC1"
        api._contractId = "CON1"
        with requests_mock.Mocker() as m:
            # Contact's API returns a literal JSON `null` body when the
            # day's interval data hasn't been published yet.
            m.post(requests_mock.ANY, text="null", headers={"Content-Type": "application/json"})
            result = api.get_usage("2026", "9", "1")
        assert result == []

    def test_returns_hourly_data_points(self, api):
        api._api_token = "tok"
        api._accountId = "ACC1"
        api._contractId = "CON1"
        points = [
            {"date": "2026-09-01T00:00:00.000+13:00", "value": "0.5", "dollarValue": "0.08", "offpeakValue": "0.5"},
            {"date": "2026-09-01T08:00:00.000+13:00", "value": "1.2", "dollarValue": "0.39", "offpeakValue": "0"},
        ]
        with requests_mock.Mocker() as m:
            m.post(requests_mock.ANY, json=points)
            result = api.get_usage("2026", "9", "1")
        assert result == points

    def test_date_is_zero_padded(self, api):
        api._api_token = "tok"
        api._accountId = "ACC1"
        api._contractId = "CON1"
        with requests_mock.Mocker() as m:
            m.post(requests_mock.ANY, json=[])
            api.get_usage("2026", "9", "5")
        assert "from=2026-09-05&to=2026-09-05" in m.last_request.url


class TestGetBillDetailsRateParsing:
    def _api_ready(self, api):
        api._api_token = "tok"
        api._accountId = "ACC1"
        api._businessPartner = "BP001"
        return api

    def test_parses_peak_and_offpeak_rates_from_cents(self, api):
        self._api_ready(api)
        with requests_mock.Mocker() as m:
            _bill_details_ok(m)
            assert api.get_bill_details() is True
        assert api._bill_details["peak_rate"] == pytest.approx(0.327)
        assert api._bill_details["offpeak_rate"] == pytest.approx(0.161)

    def test_missing_credentials_short_circuits(self, api):
        # No token/account/businessPartner set.
        assert api.get_bill_details() is False

    def test_malformed_price_is_skipped_not_fatal(self, api):
        self._api_ready(api)
        with requests_mock.Mocker() as m:
            m.get(
                requests_mock.ANY,
                additional_matcher=lambda r: r.path == "/interactive-bill",
                json={
                    "TotalAmount": "100",
                    "VariableCharges": [
                        {"Description": "7AM - 9PM", "Price": "not-a-number", "CurrencyType": "cents"},
                    ],
                    "FixedCharges": [],
                },
            )
            assert api.get_bill_details() is True
        assert api._bill_details["peak_rate"] == 0.0
