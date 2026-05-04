"""Customers router."""

from pathlib import Path
from urllib.parse import urlencode
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config.settings import config
from services.audit_service import AuditService
from services.customer_service import CustomerService
from services.invoice_service import InvoiceService
from services.payment_service import PaymentService
from services.reminder_service import ReminderService

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


def _current_user_id(request: Request) -> Optional[int]:
    value = request.session.get("user_id")
    return int(value) if value is not None else None


def _write_allowed(request: Request) -> bool:
    subscription = getattr(request.state, "subscription", None)
    if not subscription:
        return True
    return bool(subscription.get("write_allowed", False))


def _billing_redirect(message: Optional[str] = None) -> RedirectResponse:
    params = urlencode(
        {
            "error": message
            or "Your trial has ended. Subscribe to continue creating, editing, and managing customer records."
        }
    )
    return RedirectResponse(url=f"/billing?{params}", status_code=303)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def customer_list(request: Request):
    """Render customer list page."""
    user_id = _current_user_id(request)
    service = CustomerService()
    include_inactive = request.query_params.get("include_inactive", "").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    customers = service.get_all_customers(active_only=not include_inactive, user_id=user_id)
    all_customers = service.get_all_customers(active_only=False, user_id=user_id)
    active_count = len([c for c in all_customers if c.get("is_active", 1)])
    edit_id = request.query_params.get("edit_id")
    edit_customer = None
    if edit_id and str(edit_id).isdigit():
        edit_customer = service.get_customer_by_id(int(edit_id), active_only=False, user_id=user_id)

    context = {
        "request": request,
        "app_name": config.APP_NAME,
        "customers": customers,
        "customer_count": len(all_customers),
        "active_count": active_count,
        "include_inactive": include_inactive,
        "edit_customer": edit_customer,
        "message": request.query_params.get("message"),
        "error": request.query_params.get("error"),
    }

    if request.url.path.startswith("/accounts"):
        invoice_service = InvoiceService()
        payment_service = PaymentService()
        reminder_service = ReminderService()
        customer_ids = [customer["id"] for customer in customers]
        reminder_overview = reminder_service.get_customer_reminder_overview(customer_ids)
        accounts = []
        for customer in customers:
            invoices = invoice_service.get_customer_invoices(customer["id"], user_id=user_id)
            outstanding = payment_service.get_outstanding_invoices(
                customer_id=customer["id"],
                user_id=user_id,
            )
            total_billed = sum(inv.get("total_amount", 0) for inv in invoices)
            total_outstanding = sum(inv.get("balance_due", 0) for inv in outstanding)
            total_paid = 0.0
            for inv in invoices:
                payments = payment_service.get_payments_for_invoice(inv["id"], user_id=user_id)
                total_paid += sum(p.get("amount", 0) for p in payments)

            accounts.append(
                {
                    "customer": customer,
                    "invoice_count": len(invoices),
                    "total_billed": total_billed,
                    "total_paid": total_paid,
                    "total_outstanding": total_outstanding,
                    "last_reminder_sent": reminder_overview.get(customer["id"], {}).get("last_sent_at"),
                    "next_reminder_due": reminder_overview.get(customer["id"], {}).get("next_due_at"),
                }
            )

        context["accounts"] = accounts
        return templates.TemplateResponse(request, "accounts.html", context)

    return templates.TemplateResponse(request, "customers.html", context)


@router.get("/{customer_id}/edit", response_class=HTMLResponse)
async def edit_customer_page(request: Request, customer_id: int):
    """Render a dedicated edit page with current customer information."""
    user_id = _current_user_id(request)
    service = CustomerService()
    customer = service.get_customer_by_id(customer_id, active_only=False, user_id=user_id)
    if not customer:
        params = urlencode({"error": f"Customer {customer_id} not found."})
        return RedirectResponse(url=f"/customers?{params}", status_code=303)
    reminder_service = ReminderService()
    reminder_override = reminder_service.get_customer_override(customer_id)
    reminder_global = reminder_service.get_global_settings()

    return templates.TemplateResponse(
        request,
        "customer_edit.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "customer": customer,
            "reminder_override": reminder_override,
            "reminder_global": reminder_global,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.get("/{customer_id}", response_class=HTMLResponse)
async def customer_account_page(request: Request, customer_id: int):
    """Render customer account with invoice history and balances."""
    user_id = _current_user_id(request)
    customer_service = CustomerService()
    invoice_service = InvoiceService()
    payment_service = PaymentService()
    audit_service = AuditService()

    customer = customer_service.get_customer_by_id(customer_id, active_only=False, user_id=user_id)
    if not customer:
        params = urlencode({"error": f"Customer {customer_id} not found."})
        return RedirectResponse(url=f"/customers?{params}", status_code=303)

    invoices = invoice_service.get_customer_invoices(customer_id, user_id=user_id)
    outstanding_invoices = payment_service.get_outstanding_invoices(customer_id=customer_id, user_id=user_id)

    total_billed = sum(inv.get("total_amount", 0) for inv in invoices)
    total_outstanding = sum(inv.get("balance_due", 0) for inv in outstanding_invoices)

    total_paid = 0.0
    payment_history = []
    for inv in invoices:
        payments = payment_service.get_payments_for_invoice(inv["id"], user_id=user_id)
        for payment in payments:
            amount = payment.get("amount", 0) or 0
            total_paid += amount
            payment_history.append(
                {
                    "invoice_id": inv.get("id"),
                    "invoice_number": inv.get("invoice_number", ""),
                    "payment_date": payment.get("payment_date", ""),
                    "amount": amount,
                    "payment_method": payment.get("payment_method", ""),
                    "reference_number": payment.get("reference_number", ""),
                }
            )

    payment_history.sort(key=lambda p: p.get("payment_date", ""), reverse=True)

    invoice_ids = {inv.get("id") for inv in invoices}
    customer_audit_logs = [
        log
        for log in audit_service.query_logs(limit=200, entity_type="customer")
        if log.get("entity_id") == customer_id
    ]
    invoice_audit_logs = [
        log
        for log in audit_service.query_logs(limit=400, entity_type="invoice")
        if log.get("entity_id") in invoice_ids
    ]
    account_activity = sorted(
        customer_audit_logs + invoice_audit_logs,
        key=lambda log: log.get("created_at", ""),
        reverse=True,
    )[:100]

    return templates.TemplateResponse(
        request,
        "customer_account.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "customer": customer,
            "invoices": invoices,
            "invoice_count": len(invoices),
            "total_billed": total_billed,
            "total_paid": total_paid,
            "total_outstanding": total_outstanding,
            "payment_history": payment_history,
            "account_activity": account_activity,
        },
    )


@router.post("/create")
async def create_customer(request: Request):
    """Create a customer from web form input."""
    if not _write_allowed(request):
        return _billing_redirect()
    user_id = _current_user_id(request)
    form = await request.form()
    payload = {
        "name": str(form.get("name", "")).strip(),
        "surname": str(form.get("surname", "")).strip(),
        "company": str(form.get("company", "")).strip() or None,
        "email": str(form.get("email", "")).strip() or None,
        "phone": str(form.get("phone", "")).strip() or None,
        "address": str(form.get("address", "")).strip() or None,
    }

    if not payload["name"] or not payload["surname"]:
        params = urlencode({"error": "Name and surname are required."})
        return RedirectResponse(url=f"/customers?{params}", status_code=303)

    service = CustomerService()
    customer_id = service.create_customer(**payload, user_id=user_id)

    if customer_id:
        params = urlencode({"message": f"Customer created successfully (ID {customer_id})."})
    else:
        params = urlencode({"error": "Failed to create customer. Check input values."})

    return RedirectResponse(url=f"/customers?{params}", status_code=303)


@router.post("/{customer_id}/update")
async def update_customer(request: Request, customer_id: int):
    """Update customer from web form input."""
    if not _write_allowed(request):
        return _billing_redirect()
    user_id = _current_user_id(request)
    form = await request.form()
    payload = {
        "name": str(form.get("name", "")).strip(),
        "surname": str(form.get("surname", "")).strip(),
        "company": str(form.get("company", "")).strip() or None,
        "email": str(form.get("email", "")).strip() or None,
        "phone": str(form.get("phone", "")).strip() or None,
        "address": str(form.get("address", "")).strip() or None,
        "is_active": str(form.get("is_active", "")).lower() in ("1", "true", "on", "yes"),
    }

    if not payload["name"] or not payload["surname"]:
        params = urlencode({"error": "Name and surname are required."})
        return RedirectResponse(url=f"/customers/{customer_id}/edit?{params}", status_code=303)

    service = CustomerService()
    success = service.update_customer(customer_id, user_id=user_id, **payload)

    reminder_service = ReminderService()
    reminder_mode = str(form.get("reminder_mode", "default")).strip().lower()
    reminder_ok = True
    if reminder_mode == "default":
        reminder_ok = reminder_service.clear_customer_override(customer_id)
    elif reminder_mode == "custom":
        try:
            enabled_raw = str(form.get("reminder_enabled", "1")).strip().lower()
            enabled = enabled_raw in ("1", "true", "on", "yes")
            interval_days = str(form.get("reminder_interval_days", "")).strip()
            start_after = str(form.get("reminder_start_after_days", "")).strip()
            max_reminders = str(form.get("reminder_max_reminders", "")).strip()
            reminder_ok = reminder_service.set_customer_override(
                customer_id=customer_id,
                enabled=enabled,
                interval_days=int(interval_days) if interval_days else None,
                start_after_days_overdue=int(start_after) if start_after else None,
                max_reminders=int(max_reminders) if max_reminders else None,
            )
        except ValueError:
            reminder_ok = False

    if success and reminder_ok:
        params = urlencode({"message": f"Customer {customer_id} updated successfully."})
        return RedirectResponse(url=f"/customers/{customer_id}/edit?{params}", status_code=303)

    params = urlencode({"error": f"Failed to update customer {customer_id}."})
    return RedirectResponse(url=f"/customers/{customer_id}/edit?{params}", status_code=303)


@router.post("/{customer_id}/delete")
async def delete_customer(request: Request, customer_id: int):
    """Delete customer (soft delete by default)."""
    if not _write_allowed(request):
        return _billing_redirect()
    user_id = _current_user_id(request)
    form = await request.form()
    hard_delete = str(form.get("hard_delete", "")).lower() in ("1", "true", "on", "yes")

    service = CustomerService()
    success = service.delete_customer(customer_id, soft_delete=not hard_delete, user_id=user_id)

    if success:
        mode = "permanently deleted" if hard_delete else "deactivated"
        params = urlencode({"message": f"Customer {customer_id} {mode} successfully."})
    else:
        params = urlencode({"error": f"Failed to delete customer {customer_id}."})
    return RedirectResponse(url=f"/customers?{params}", status_code=303)
