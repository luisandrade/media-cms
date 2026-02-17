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
        self.api_key = getattr(settings, "FLOW_API_KEY", "")
        self.secret_key = getattr(settings, "FLOW_SECRET_KEY", "")
        self.api_base = getattr(settings, "FLOW_API_BASE", "https://sandbox.flow.cl/api")
        self.timeout = getattr(settings, "FLOW_TIMEOUT_SECONDS", 20)

        self.create_path = getattr(settings, "FLOW_CREATE_PATH", "/payment/create")
        self.status_path = getattr(settings, "FLOW_STATUS_PATH", "/payment/getStatus")

    def is_configured(self) -> bool:
        return bool(self.api_key and self.secret_key)

    def _canonical_querystring(self, params: dict[str, Any]) -> str:
        # Exclude signature if present
        items = [(k, params[k]) for k in sorted(params.keys()) if k != "s"]
        return "&".join([f"{k}={items[i][1]}" for i, (k, _) in enumerate(items)])

    def sign_params(self, params: dict[str, Any]) -> str:
        message = self._canonical_querystring(params).encode("utf-8")
        secret = self.secret_key.encode("utf-8")
        digest = hmac.new(secret, message, hashlib.sha256).hexdigest()
        return digest

    def post(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = self.api_base.rstrip("/") + path
        signed = dict(params)
        signed["s"] = self.sign_params(signed)
        resp = requests.post(url, data=signed, timeout=self.timeout)
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

        data = self.post(self.create_path, params)

        # Common shapes seen in Flow integrations:
        # - {"url": "https://...", "token": "..."}
        # - {"redirect": "...", "token": "..."}
        redirect_url = data.get("url") or data.get("redirect") or data.get("redirectUrl")
        token = data.get("token") or data.get("flowOrder")
        if not redirect_url:
            raise ValueError("Flow create_payment response missing redirect url")

        return FlowCreatePaymentResult(redirect_url=redirect_url, token=token, raw=data)

    def get_status(self, *, token: str) -> dict[str, Any]:
        params: dict[str, Any] = {
            "apiKey": self.api_key,
            "token": token,
        }
        return self.post(self.status_path, params)
