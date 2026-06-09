from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings


@dataclass(frozen=True)
class FlowCreatePaymentResult:
    redirect_url: str
    token: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class FlowRedirectResult:
    redirect_url: str
    token: str | None
    raw: dict[str, Any]


class FlowAPIError(Exception):
    def __init__(self, message: str, *, raw: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.raw = raw or {}


class FlowClient:
    """Minimal Flow client.

    Notes:
    - Flow's public docs are not always fetchable in CI/agent environments.
    - The signing method is implemented as HMAC-SHA256 over the canonical querystring.
      If your Flow account uses a different scheme, adjust `sign_params` accordingly.
    """

    def __init__(self) -> None:
        self.api_key = getattr(settings, "FLOW_API_KEY", "6D8760F5-1AF4-41D5-957F-28LABF08FF87")
        self.secret_key = getattr(settings, "FLOW_SECRET_KEY", "f668e58e6ee5ee2a03c787d6264030d174835c29")
        self.api_base = getattr(settings, "FLOW_API_BASE", "https://sandbox.flow.cl/api")
        self.timeout = getattr(settings, "FLOW_TIMEOUT_SECONDS", 20)

        self.create_path = getattr(settings, "FLOW_CREATE_PATH", "/payment/create")
        self.status_path = getattr(settings, "FLOW_STATUS_PATH", "/payment/getStatus")
        self.customer_create_path = getattr(settings, "FLOW_CUSTOMER_CREATE_PATH", "/customer/create")
        self.customer_get_path = getattr(settings, "FLOW_CUSTOMER_GET_PATH", "/customer/get")
        self.customer_register_path = getattr(settings, "FLOW_CUSTOMER_REGISTER_PATH", "/customer/register")
        self.customer_register_status_path = getattr(
            settings,
            "FLOW_CUSTOMER_REGISTER_STATUS_PATH",
            "/customer/getRegisterStatus",
        )
        self.plan_create_path = getattr(settings, "FLOW_PLAN_CREATE_PATH", "/plans/create")
        self.plan_get_path = getattr(settings, "FLOW_PLAN_GET_PATH", "/plans/get")
        self.subscription_create_path = getattr(settings, "FLOW_SUBSCRIPTION_CREATE_PATH", "/subscription/create")
        self.subscription_get_path = getattr(settings, "FLOW_SUBSCRIPTION_GET_PATH", "/subscription/get")
        self.subscription_cancel_path = getattr(settings, "FLOW_SUBSCRIPTION_CANCEL_PATH", "/subscription/cancel")

    def is_configured(self) -> bool:
        return bool(self.api_key and self.secret_key)

    def _string_to_sign(self, params: dict[str, Any]) -> str:
        """Build Flow string to sign.

        Flow spec: sort keys ascending, concatenate as: key + value (no separators),
        excluding the signature param `s`.
        Example: amount5000apiKeyXXXXcurrencyCLP
        """

        parts: list[str] = []
        for key in sorted(params.keys()):
            if key == "s":
                continue
            value = params.get(key)
            if value is None:
                value_str = ""
            else:
                value_str = str(value)
            parts.append(f"{key}{value_str}")
        return "".join(parts)

    def sign_params(self, params: dict[str, Any]) -> str:
        message = self._string_to_sign(params).encode("utf-8")
        secret = self.secret_key.encode("utf-8")
        digest = hmac.new(secret, message, hashlib.sha256).hexdigest()
        return digest

    def _request(self, method: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = self.api_base.rstrip("/") + path
        signed = dict(params)
        signed["s"] = self.sign_params(signed)

        if method.upper() == "GET":
            resp = requests.get(url, params=signed, timeout=self.timeout)
        else:
            resp = requests.post(url, data=signed, timeout=self.timeout)

        # Flow suele responder JSON incluso en 400/401.
        if resp.status_code in (400, 401):
            try:
                return resp.json()
            except Exception:  # noqa: BLE001
                return {"error": resp.text or f"HTTP {resp.status_code}"}

        resp.raise_for_status()
        return resp.json()

    def create_payment(
        self,
        *,
        commerce_order: str,
        subject: str,
        amount: int,
        email: str,
        url_return: str,
        url_confirmation: str,
        optional: dict[str, Any] | None = None,
    ) -> FlowCreatePaymentResult:
        params: dict[str, Any] = {
            "apiKey": self.api_key,
            "commerceOrder": commerce_order,
            "subject": subject,
            "amount": amount,
            "email": email,
            "urlReturn": url_return,
            "urlConfirmation": url_confirmation,
        }
        if optional:
            params.update(optional)

        data = self._request("POST", self.create_path, params)

        # Common shapes seen in Flow integrations:
        # - {"url": "https://...", "token": "..."}
        # - {"redirect": "...", "token": "..."}
        redirect_url = (
            data.get("url")
            or data.get("redirect")
            or data.get("redirectUrl")
            or data.get("urlPayment")
            or data.get("paymentUrl")
            or data.get("redirect_url")
        )
        token = data.get("token")
        if not redirect_url:
            detail = data.get("message") or data.get("error") or data.get("detail")
            if detail:
                raise FlowAPIError(f"Flow create_payment failed: {detail}", raw=data)
            raise FlowAPIError("Flow create_payment response missing redirect url", raw=data)

        # Flow commonly returns a base URL + token separately; payment page expects token.
        if token and "token=" not in redirect_url:
            sep = "&" if "?" in redirect_url else "?"
            redirect_url = f"{redirect_url}{sep}token={token}"

        return FlowCreatePaymentResult(redirect_url=redirect_url, token=token, raw=data)

    def get_status(self, *, token: str) -> dict[str, Any]:
        params: dict[str, Any] = {
            "apiKey": self.api_key,
            "token": token,
        }
        # Según documentación de Flow, getStatus se consume por GET con querystring.
        return self._request("GET", self.status_path, params)

    def create_customer(self, *, name: str, email: str, external_id: str) -> dict[str, Any]:
        params = {
            "apiKey": self.api_key,
            "name": name,
            "email": email,
            "externalId": external_id,
        }
        return self._request("POST", self.customer_create_path, params)

    def get_customer(self, *, customer_id: str) -> dict[str, Any]:
        params = {"apiKey": self.api_key, "customerId": customer_id}
        return self._request("GET", self.customer_get_path, params)

    def register_customer(self, *, customer_id: str, url_return: str) -> FlowRedirectResult:
        params = {
            "apiKey": self.api_key,
            "customerId": customer_id,
            "url_return": url_return,
        }
        data = self._request("POST", self.customer_register_path, params)
        redirect_url = data.get("url") or data.get("redirect") or data.get("redirectUrl")
        token = data.get("token")
        if not redirect_url:
            detail = data.get("message") or data.get("error") or data.get("detail")
            if detail:
                raise FlowAPIError(f"Flow register_customer failed: {detail}", raw=data)
            raise FlowAPIError("Flow register_customer response missing redirect url", raw=data)
        if token and "token=" not in redirect_url:
            sep = "&" if "?" in redirect_url else "?"
            redirect_url = f"{redirect_url}{sep}token={token}"
        return FlowRedirectResult(redirect_url=redirect_url, token=token, raw=data)

    def get_customer_register_status(self, *, token: str) -> dict[str, Any]:
        params = {"apiKey": self.api_key, "token": token}
        return self._request("GET", self.customer_register_status_path, params)

    def create_plan(
        self,
        *,
        plan_id: str,
        name: str,
        amount: int,
        interval: int,
        currency: str = "CLP",
        interval_count: int = 1,
        trial_period_days: int = 0,
        days_until_due: int = 3,
        periods_number: int = 0,
        url_callback: str | None = None,
        charges_retries_number: int = 3,
        currency_convert_option: int = 1,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "apiKey": self.api_key,
            "planId": plan_id,
            "name": name,
            "currency": currency,
            "amount": amount,
            "interval": interval,
            "interval_count": interval_count,
            "trial_period_days": trial_period_days,
            "days_until_due": days_until_due,
            "charges_retries_number": charges_retries_number,
            "currency_convert_option": currency_convert_option,
        }
        if periods_number:
            params["periods_number"] = periods_number
        if url_callback:
            params["urlCallback"] = url_callback
        return self._request("POST", self.plan_create_path, params)

    def get_plan(self, *, plan_id: str) -> dict[str, Any]:
        params = {"apiKey": self.api_key, "planId": plan_id}
        return self._request("GET", self.plan_get_path, params)

    def create_subscription(
        self,
        *,
        plan_id: str,
        customer_id: str,
        trial_period_days: int | None = None,
        periods_number: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "apiKey": self.api_key,
            "planId": plan_id,
            "customerId": customer_id,
        }
        if trial_period_days is not None:
            params["trial_period_days"] = trial_period_days
        if periods_number is not None and periods_number > 0:
            params["periods_number"] = periods_number
        return self._request("POST", self.subscription_create_path, params)

    def get_subscription(self, *, subscription_id: str) -> dict[str, Any]:
        params = {"apiKey": self.api_key, "subscriptionId": subscription_id}
        return self._request("GET", self.subscription_get_path, params)

    def cancel_subscription(self, *, subscription_id: str, at_period_end: bool = True) -> dict[str, Any]:
        params = {
            "apiKey": self.api_key,
            "subscriptionId": subscription_id,
            "at_period_end": 1 if at_period_end else 0,
        }
        return self._request("POST", self.subscription_cancel_path, params)
