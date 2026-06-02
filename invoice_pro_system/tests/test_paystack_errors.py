from services.paystack_billing_service import PaystackAPIError, PaystackBillingService


def test_paystack_api_error_includes_structured_response_details():
    error = PaystackAPIError(
        status_code=403,
        reason="Forbidden",
        data={
            "message": "error code: 1010",
            "errors": {"plan": ["Invalid plan code"]},
            "meta": {"nextStep": "Check test/live mode"},
        },
        request_context={
            "path": "/transaction/initialize",
            "plan_code": "PLN_test",
            "amount": 19900,
            "currency": "ZAR",
        },
        raw_body='{"status":false,"message":"error code: 1010"}',
    )

    message = str(error)

    assert "Paystack API error (403): Forbidden" in message
    assert "message: error code: 1010" in message
    assert '"plan": ["Invalid plan code"]' in message
    assert '"nextStep": "Check test/live mode"' in message
    assert '"plan_code": "PLN_test"' in message
    assert '"amount": 19900' in message
    assert 'raw body: {"status":false,"message":"error code: 1010"}' in message


def test_paystack_requests_include_standard_json_headers(monkeypatch):
    monkeypatch.setenv("PAYSTACK_SECRET_KEY", "sk_test_x")

    headers = PaystackBillingService()._headers()

    assert headers["Authorization"] == "Bearer sk_test_x"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"
    assert headers["User-Agent"].startswith("VantaPilot/")
