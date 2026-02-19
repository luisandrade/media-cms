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


class FlowClient:
    """Minimal Flow client.

    Notes:
    - Flow's public docs are not always fetchable in CI/agent environments.
    - The signing method is implemented as HMAC-SHA256 over the canonical querystring.
      If your Flow account uses a different scheme, adjust `sign_params` accordingly.
    """

    def __init__(self) -> None:
        self.api_key = getattr(settings, "FLOW_API_KEY", "6D8760F5-1AF4-41D5-957F-28LABF08FF87")
        self.secret_key = getattr(settings, "FLOW_SECRET_KEY", "668e58e6ee5ee2a03c787d6264030d174835c29")
        self.api_base = getattr(settings, "FLOW_API_BASE", "https://sandbox.flow.cl/api")
        self.timeout = getattr(settings, "FLOW_TIMEOUT_SECONDS", 20)

        self.create_path = getattr(settings, "FLOW_CREATE_PATH", "/payment/create")
        self.status_path = getattr(settings, "FLOW_STATUS_PATH", "/payment/getStatus")

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
        redirect_url = data.get("url") or data.get("redirect") or data.get("redirectUrl")
        token = data.get("token")
        if not redirect_url:
            raise ValueError("Flow create_payment response missing redirect url")

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
