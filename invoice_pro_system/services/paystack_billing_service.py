"""Paystack subscription checkout helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict


class PaystackAPIError(RuntimeError):
    """Readable Paystack API error with useful response details for debugging."""

    def __init__(
        self,
        *,
        status_code: int | None = None,
        reason: str = "",
        data: Dict[str, Any] | None = None,
        raw_body: str = "",
        request_context: Dict[str, Any] | None = None,
    ):
        self.status_code = status_code
        self.reason = reason
        self.data = data or {}
        self.raw_body = raw_body
        self.request_context = request_context or {}
        super().__init__(self._format_message())

    def _format_value(self, value: Any) -> str:
        if value in (None, "", [], {}):
            return ""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(value)

    def _format_message(self) -> str:
        parts = []
        prefix = "Paystack API error"
        if self.status_code is not None:
            prefix = f"{prefix} ({self.status_code})"
        if self.reason:
            prefix = f"{prefix}: {self.reason}"
        parts.append(prefix)

        for label, key in (("message", "message"), ("errors", "errors"), ("meta", "meta")):
            value = self._format_value(self.data.get(key))
            if value:
                parts.append(f"{label}: {value}")

        context = self._format_value(self.request_context)
        if context:
            parts.append(f"request: {context}")

        raw_snippet = (self.raw_body or "").strip()
        if raw_snippet:
            if len(raw_snippet) > 800:
                raw_snippet = f"{raw_snippet[:800]}..."
            parts.append(f"raw body: {raw_snippet}")

        return " | ".join(parts)


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
        self.plan_amount = self._resolve_plan_amount()

    def _resolve_plan_amount(self) -> int:
        raw = (os.getenv("PAYSTACK_PLAN_AMOUNT", "") or "").strip()
        if raw.isdigit():
            return int(raw)

        cleaned = self.plan_price.strip().upper().replace("ZAR", "").replace("R", "").replace(",", "").strip()
        if not cleaned:
            return 0
        try:
            major_units = float(cleaned)
        except ValueError:
            return 0
        return int(round(major_units * 100))

    def is_available(self) -> bool:
        return bool(self.secret_key and self.plan_code and self.plan_amount >= 100)

    def configuration_error(self) -> str:
        if not self.secret_key:
            return "PAYSTACK_SECRET_KEY is not configured."
        if not self.plan_code:
            return "PAYSTACK_PLAN_CODE is not configured."
        if self.plan_amount < 100:
            return "PAYSTACK_PLAN_AMOUNT is missing or invalid. Use the smallest currency unit, e.g. 19900 for R199."
        return ""

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "VantaPilot/1.0 (+https://vanta-pilot-demo-production-d533.up.railway.app)",
        }

    def _request(self, method: str, path: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if not self.secret_key:
            raise RuntimeError("Paystack is not configured.")
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
        request_context = self._debug_request_context(method, path, payload)
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
            try:
                data = json.loads(detail or "{}")
            except json.JSONDecodeError:
                data = {}
            raise PaystackAPIError(
                status_code=exc.code,
                reason=str(exc.reason or ""),
                data=data if isinstance(data, dict) else {},
                raw_body=detail,
                request_context=request_context,
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Paystack: {exc.reason}") from exc

        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise PaystackAPIError(
                reason="Invalid JSON response",
                raw_body=raw,
                request_context=request_context,
            ) from exc
        if not data.get("status", False):
            raise PaystackAPIError(
                reason="Request returned status=false",
                data=data if isinstance(data, dict) else {},
                raw_body=raw,
                request_context=request_context,
            )
        return data

    def _debug_request_context(
        self,
        method: str,
        path: str,
        payload: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        safe_payload = {}
        for key, value in (payload or {}).items():
            if key == "metadata":
                safe_payload[key] = {
                    meta_key: ("[email redacted]" if meta_key == "email" else meta_value)
                    for meta_key, meta_value in dict(value or {}).items()
                }
            elif key == "email":
                safe_payload[key] = "[email redacted]"
            elif key == "callback_url":
                safe_payload[key] = value
            else:
                safe_payload[key] = value
        return {
            "method": method.upper(),
            "path": path,
            "plan_code": self.plan_code,
            "amount": self.plan_amount,
            "currency": self.currency,
            "payload": safe_payload,
        }

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
            "amount": self.plan_amount,
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
