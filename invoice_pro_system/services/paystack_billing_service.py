"""Paystack subscription checkout helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict


class PaystackBillingService:
    """Small wrapper around Paystack hosted checkout + subscription management."""

    base_url = "https://api.paystack.co"

    def __init__(self):
        self.secret_key = (os.getenv("PAYSTACK_SECRET_KEY", "") or "").strip()
        self.plan_code = (os.getenv("PAYSTACK_PLAN_CODE", "") or "").strip()
        self.public_key = (os.getenv("PAYSTACK_PUBLIC_KEY", "") or "").strip()
        self.plan_name = (os.getenv("PAYSTACK_PLAN_NAME", "") or "").strip() or "Vanta Pilot Pro"
        self.plan_price = (os.getenv("PAYSTACK_PLAN_PRICE", "") or "").strip() or "R199"
        self.plan_interval = (os.getenv("PAYSTACK_PLAN_INTERVAL", "") or "").strip() or "month"
        self.currency = (os.getenv("PAYSTACK_CURRENCY", "") or "").strip().upper() or "ZAR"

    def is_available(self) -> bool:
        return bool(self.secret_key and self.plan_code)

    def configuration_error(self) -> str:
        if not self.secret_key:
            return "PAYSTACK_SECRET_KEY is not configured."
        if not self.plan_code:
            return "PAYSTACK_PLAN_CODE is not configured."
        return ""

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if not self.secret_key:
            raise RuntimeError("Paystack is not configured.")
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=self._headers(),
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Paystack API error ({exc.code}): {detail or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Paystack: {exc.reason}") from exc

        data = json.loads(raw or "{}")
        if not data.get("status", False):
            raise RuntimeError(str(data.get("message") or "Paystack request failed."))
        return data

    def initialize_subscription_checkout(
        self,
        *,
        email: str,
        reference: str,
        callback_url: str,
        user_id: int,
    ) -> Dict[str, Any]:
        if not self.is_available():
            raise RuntimeError(self.configuration_error() or "Paystack is not configured.")
        payload = {
            "email": email,
            "reference": reference,
            "callback_url": callback_url,
            "plan": self.plan_code,
            "currency": self.currency,
            "metadata": {
                "user_id": str(user_id),
                "email": email,
            },
        }
        return self._request("POST", "/transaction/initialize", payload)

    def verify_transaction(self, reference: str) -> Dict[str, Any]:
        return self._request("GET", f"/transaction/verify/{reference}")

    def get_subscription_manage_link(self, subscription_code: str) -> str:
        if not subscription_code:
            raise RuntimeError("No Paystack subscription code is linked to this account yet.")
        data = self._request("GET", f"/subscription/{subscription_code}/manage/link")
        return str(data.get("data", {}).get("link") or "")

    def is_valid_signature(self, payload: bytes, signature: str) -> bool:
        if not self.secret_key or not signature:
            return False
        expected = hmac.new(
            self.secret_key.encode("utf-8"),
            payload,
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
