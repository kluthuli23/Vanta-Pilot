"""Stripe subscription checkout helpers."""

from __future__ import annotations

import os
from typing import Optional

try:
    import stripe
except ImportError:  # pragma: no cover - handled gracefully at runtime
    stripe = None


class StripeBillingService:
    """Small wrapper around Stripe Checkout + Customer Portal + webhooks."""

    def __init__(self):
        self.secret_key = (os.getenv("STRIPE_SECRET_KEY", "") or "").strip()
        self.price_id = (os.getenv("STRIPE_PRICE_ID", "") or "").strip()
        self.webhook_secret = (os.getenv("STRIPE_WEBHOOK_SECRET", "") or "").strip()
        self.publishable_key = (os.getenv("STRIPE_PUBLISHABLE_KEY", "") or "").strip()
        self.plan_name = (os.getenv("STRIPE_PLAN_NAME", "") or "").strip() or "Vanta Pilot Pro"
        self.plan_price = (os.getenv("STRIPE_PLAN_PRICE", "") or "").strip() or "R199"
        self.plan_interval = (os.getenv("STRIPE_PLAN_INTERVAL", "") or "").strip() or "month"
        if stripe and self.secret_key:
            stripe.api_key = self.secret_key

    def is_available(self) -> bool:
        return bool(stripe and self.secret_key and self.price_id)

    def is_webhook_configured(self) -> bool:
        return bool(self.is_available() and self.webhook_secret)

    def configuration_error(self) -> str:
        if stripe is None:
            return "The Stripe Python package is not installed."
        if not self.secret_key:
            return "STRIPE_SECRET_KEY is not configured."
        if not self.price_id:
            return "STRIPE_PRICE_ID is not configured."
        return ""

    def create_checkout_session(
        self,
        *,
        user_id: int,
        customer_email: str,
        success_url: str,
        cancel_url: str,
        existing_customer_id: str = "",
    ):
        if not self.is_available():
            raise RuntimeError(self.configuration_error() or "Stripe is not configured.")

        payload = {
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "line_items": [{"price": self.price_id, "quantity": 1}],
            "client_reference_id": str(user_id),
            "metadata": {
                "user_id": str(user_id),
                "customer_email": customer_email,
            },
            "allow_promotion_codes": True,
        }
        if existing_customer_id:
            payload["customer"] = existing_customer_id
        else:
            payload["customer_email"] = customer_email

        return stripe.checkout.Session.create(**payload)

    def create_portal_session(self, *, customer_id: str, return_url: str):
        if not self.is_available():
            raise RuntimeError(self.configuration_error() or "Stripe is not configured.")
        if not customer_id:
            raise RuntimeError("No Stripe customer is linked to this account yet.")
        return stripe.billing_portal.Session.create(customer=customer_id, return_url=return_url)

    def retrieve_checkout_session(self, session_id: str):
        if not self.is_available():
            raise RuntimeError(self.configuration_error() or "Stripe is not configured.")
        return stripe.checkout.Session.retrieve(session_id)

    def construct_webhook_event(self, payload: bytes, signature: str):
        if not self.is_webhook_configured():
            raise RuntimeError("Stripe webhook secret is not configured.")
        return stripe.Webhook.construct_event(payload, signature, self.webhook_secret)
