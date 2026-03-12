"""Invoices router."""

from datetime import date, datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config.settings import config
from services.business_profile_service import BusinessProfileService
from services.customer_service import CustomerService
from services.email_service import EmailService
from services.invoice_service import InvoiceService
from services.oauth_service import OAuthService
from services.payment_service import PaymentService
from services.pdf_service import PDFInvoiceService

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


def _current_user_id(request: Request) -> Optional[int]:
    value = request.session.get("user_id")
    return int(value) if value is not None else None


def _current_business_profile(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return BusinessProfileService().get_profile(int(user_id))


def _parse_items_text(raw_items: str):
    """Parse textarea lines into [(description, qty, price), ...].

    Line format: description|quantity|price
    """
    items = []
    for line in raw_items.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3:
            raise ValueError(f"Invalid item line: {line}")
        desc, qty_text, price_text = parts
        qty = int(qty_text)
        price = float(price_text)
        items.append((desc, qty, price))
    return items


def _send_readiness_issues(profile: dict, user_id: Optional[int]) -> list[str]:
    issues: list[str] = []
    if not (profile or {}):
        return ["Business profile not found. Update Settings > Business first."]
    if not str(profile.get("business_name", "")).strip():
        issues.append("Set Business Name in Settings > Business.")
    if not str(profile.get("business_email", "")).strip():
        issues.append("Set Business Email in Settings > Business.")
    if not str(profile.get("banking_details", "")).strip():
        issues.append("Add Banking Details in Settings > Business.")

    oauth_connected = OAuthService().is_google_connected(user_id) if user_id else False
    if not oauth_connected:
        issues.append("Connect Gmail in Settings > Business to enable sending.")
    return issues


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def invoice_list(request: Request):
    """Render invoice list and create form page."""
    user_id = _current_user_id(request)
    invoice_service = InvoiceService()
    customer_service = CustomerService()
    payment_service = PaymentService()
    selected_customer_id = request.query_params.get("customer_id")
    preselected_customer_id = None
    if selected_customer_id and selected_customer_id.isdigit():
        preselected_customer_id = int(selected_customer_id)

    invoices = invoice_service.get_all_invoices(limit=100, user_id=user_id)
    customers = customer_service.get_all_customers(active_only=True, user_id=user_id)
    summary = payment_service.get_payment_summary(30, user_id=user_id)

    return templates.TemplateResponse(
        request,
        "invoices.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "invoices": invoices,
            "customers": customers,
            "invoice_count": len(invoices),
            "summary": summary,
            "preselected_customer_id": preselected_customer_id,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/create")
async def create_invoice(request: Request):
    """Create invoice from web form."""
    user_id = _current_user_id(request)
    form = await request.form()

    try:
        customer_id = int(str(form.get("customer_id", "0")))
        due_days = int(str(form.get("due_days", "30")))
        due_date_raw = str(form.get("due_date", "")).strip()
        if due_date_raw:
            selected_due = datetime.fromisoformat(due_date_raw).date()
            delta_days = (selected_due - date.today()).days
            due_days = max(1, delta_days)
        description = str(form.get("description", "")).strip()
        items_text = str(form.get("items", "")).strip()

        if not customer_id or not items_text:
            raise ValueError("Customer and at least one item are required.")

        items = _parse_items_text(items_text)
        if not items:
            raise ValueError("Provide at least one valid item line.")

        invoice_service = InvoiceService()
        invoice_id = invoice_service.create_invoice(
            customer_id=customer_id,
            items=items,
            description=description,
            due_days=due_days,
            user_id=user_id,
        )

        if not invoice_id:
            raise ValueError(invoice_service.get_last_error() or "Invoice could not be created.")

        params = urlencode({"message": f"Invoice created successfully (ID {invoice_id})."})
        return RedirectResponse(url=f"/invoices/{invoice_id}?{params}", status_code=303)

    except Exception as exc:
        params = urlencode({"error": f"Invoice creation failed: {exc}"})
        return RedirectResponse(url=f"/invoices?{params}", status_code=303)


@router.get("/{invoice_id}", response_class=HTMLResponse)
async def invoice_detail(request: Request, invoice_id: int):
    """Render invoice detail page with actions and embedded PDF."""
    user_id = _current_user_id(request)
    invoice_service = InvoiceService()
    invoice = invoice_service.get_invoice(invoice_id, user_id=user_id)
    if not invoice:
        params = urlencode({"error": f"Invoice {invoice_id} not found."})
        return RedirectResponse(url=f"/invoices?{params}", status_code=303)

    payments = PaymentService().get_payments_for_invoice(invoice_id, user_id=user_id)
    total_amount = float(invoice.get("total_amount", 0) or 0)
    amount_paid = float(invoice.get("amount_paid", 0) or 0)
    outstanding = float(invoice.get("balance_due", total_amount - amount_paid) or 0)
    if outstanding < 0:
        outstanding = 0.0
    paid_pct = 0.0 if total_amount <= 0 else min((amount_paid / total_amount) * 100, 100.0)

    return templates.TemplateResponse(
        request,
        "invoice_detail.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "invoice": invoice,
            "line_items": invoice.get("items", []),
            "payments": payments,
            "total_amount": total_amount,
            "amount_paid": amount_paid,
            "outstanding_amount": outstanding,
            "paid_percentage": paid_pct,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/{invoice_id}/status")
async def update_status(request: Request, invoice_id: int):
    """Update invoice status from form."""
    user_id = _current_user_id(request)
    form = await request.form()
    status = str(form.get("status", "")).strip()

    if status == "sent":
        params = urlencode(
            {
                "error": (
                    "Use the 'Send Invoice' button to email the invoice. "
                    "Status changes to sent automatically after successful email delivery."
                )
            }
        )
        return RedirectResponse(url=f"/invoices/{invoice_id}?{params}", status_code=303)

    invoice_service = InvoiceService()
    ok = invoice_service.update_invoice_status(invoice_id, status, user_id=user_id)
    if ok:
        if status == "sent":
            params = urlencode({"message": "Invoice emailed and status set to 'sent'."})
        else:
            params = urlencode({"message": f"Status updated to '{status}'."})
    else:
        params = urlencode(
            {"error": invoice_service.get_last_error() or "Status update failed."}
        )

    return RedirectResponse(url=f"/invoices/{invoice_id}?{params}", status_code=303)


@router.post("/{invoice_id}/send")
async def send_invoice_to_customer(request: Request, invoice_id: int):
    """Send invoice email and automatically set status to sent on success."""
    user_id = _current_user_id(request)
    invoice_service = InvoiceService()
    invoice = invoice_service.get_invoice(invoice_id, user_id=user_id)
    if not invoice:
        params = urlencode({"error": f"Invoice {invoice_id} not found."})
        return RedirectResponse(url=f"/invoices/{invoice_id}?{params}", status_code=303)

    if invoice.get("status") == "cancelled":
        params = urlencode({"error": "Cancelled invoices cannot be sent."})
        return RedirectResponse(url=f"/invoices/{invoice_id}?{params}", status_code=303)

    to_email = (invoice.get("customer_email") or "").strip()
    if not to_email:
        params = urlencode({"error": "Cannot send invoice: customer email is missing."})
        return RedirectResponse(url=f"/invoices/{invoice_id}?{params}", status_code=303)

    profile = _current_business_profile(request)
    readiness_issues = _send_readiness_issues(profile or {}, user_id)
    if readiness_issues:
        params = urlencode({"error": "Cannot send invoice: " + " | ".join(readiness_issues)})
        return RedirectResponse(url=f"/invoices/{invoice_id}?{params}", status_code=303)

    pdf_path = PDFInvoiceService().generate_invoice_from_db(invoice, business_profile=profile)
    if not pdf_path:
        params = urlencode({"error": "Failed to generate invoice PDF for email."})
        return RedirectResponse(url=f"/invoices/{invoice_id}?{params}", status_code=303)

    email_items = []
    for item in invoice.get("items", []):
        qty = item.get("quantity", 0)
        unit_price = item.get("unit_price", 0)
        email_items.append(
            {
                "description": item.get("item_description", ""),
                "quantity": qty,
                "unit_price": unit_price,
                "total": item.get("line_total", qty * unit_price),
            }
        )

    invoice_payload = {
        "invoice_number": invoice.get("invoice_number", ""),
        "invoice_date": (invoice.get("invoice_date") or "")[:10],
        "due_date": (invoice.get("due_date") or "")[:10],
        "customer_company": invoice.get("customer_company", ""),
        "subtotal": invoice.get("subtotal", 0),
        "tax_amount": invoice.get("tax_amount", 0),
        "total_amount": invoice.get("total_amount", 0),
        "items": email_items,
    }

    to_name = f"{invoice.get('customer_name', '')} {invoice.get('customer_surname', '')}".strip()
    email_service = EmailService()
    email_ok = email_service.send_invoice(
        to_email=to_email,
        to_name=to_name or "Customer",
        invoice_data=invoice_payload,
        pdf_path=Path(pdf_path),
        business_profile=profile,
    )
    if not email_ok:
        params = urlencode(
            {"error": email_service.get_last_error() or "Email send failed. Status remains draft."}
        )
        return RedirectResponse(url=f"/invoices/{invoice_id}?{params}", status_code=303)

    if invoice.get("status") == "draft":
        status_ok = invoice_service.update_invoice_status(invoice_id, "sent", user_id=user_id)
        if not status_ok:
            params = urlencode(
                {
                    "error": (
                        invoice_service.get_last_error()
                        or "Email sent, but failed to update status to sent."
                    )
                }
            )
            return RedirectResponse(url=f"/invoices/{invoice_id}?{params}", status_code=303)
        params = urlencode({"message": "Invoice emailed successfully. Status updated to sent."})
    else:
        params = urlencode({"message": "Invoice emailed successfully."})
    return RedirectResponse(url=f"/invoices/{invoice_id}?{params}", status_code=303)


@router.post("/{invoice_id}/edit")
async def edit_invoice(request: Request, invoice_id: int):
    """Edit draft invoice line items/details."""
    user_id = _current_user_id(request)
    form = await request.form()
    description = str(form.get("description", "")).strip()
    due_date = str(form.get("due_date", "")).strip() or None
    items_text = str(form.get("items", "")).strip()

    try:
        items = _parse_items_text(items_text)
        if not items:
            raise ValueError("Provide at least one item")
    except Exception as exc:
        params = urlencode({"error": f"Invalid items format: {exc}"})
        return RedirectResponse(url=f"/invoices/{invoice_id}?{params}", status_code=303)

    service = InvoiceService()
    ok = service.update_draft_invoice(
        invoice_id=invoice_id,
        items=items,
        description=description,
        due_date=due_date,
        user_id=user_id,
    )
    if ok:
        params = urlencode({"message": "Draft invoice updated successfully."})
    else:
        params = urlencode({"error": service.get_last_error() or "Failed to update invoice."})
    return RedirectResponse(url=f"/invoices/{invoice_id}?{params}", status_code=303)


@router.post("/{invoice_id}/delete")
async def delete_invoice(request: Request, invoice_id: int):
    """Delete draft invoice."""
    user_id = _current_user_id(request)
    service = InvoiceService()
    ok = service.delete_draft_invoice(invoice_id=invoice_id, user_id=user_id)
    if ok:
        params = urlencode({"message": f"Draft invoice {invoice_id} deleted."})
        return RedirectResponse(url=f"/invoices?{params}", status_code=303)
    params = urlencode({"error": service.get_last_error() or "Failed to delete invoice."})
    return RedirectResponse(url=f"/invoices/{invoice_id}?{params}", status_code=303)


@router.post("/{invoice_id}/payment")
async def add_payment(request: Request, invoice_id: int):
    """Record payment from form."""
    user_id = _current_user_id(request)
    form = await request.form()

    try:
        amount = float(str(form.get("amount", "0")))
        method = str(form.get("method", "bank_transfer"))
        reference = str(form.get("reference", "")).strip() or None
        notes = str(form.get("notes", "")).strip() or None

        payment_service = PaymentService()
        payment_id = payment_service.record_payment(
            invoice_id=invoice_id,
            amount=amount,
            payment_method=method,
            reference_number=reference,
            notes=notes,
            user_id=user_id,
        )

        if payment_id:
            params = urlencode({"message": f"Payment recorded (ID {payment_id})."})
        else:
            params = urlencode(
                {"error": payment_service.get_last_error() or "Payment recording failed."}
            )

    except Exception as exc:
        params = urlencode({"error": f"Payment failed: {exc}"})

    return RedirectResponse(url=f"/invoices/{invoice_id}?{params}", status_code=303)


@router.get("/{invoice_id}/pdf")
async def invoice_pdf(request: Request, invoice_id: int, download: bool = Query(default=False)):
    """Serve invoice PDF inline by default; as attachment if download=true."""
    user_id = _current_user_id(request)
    invoice = InvoiceService().get_invoice(invoice_id, user_id=user_id)
    if not invoice:
        return RedirectResponse(url="/invoices?error=Invoice+not+found", status_code=303)

    profile = _current_business_profile(request)
    pdf_path = PDFInvoiceService().generate_invoice_from_db(invoice, business_profile=profile)
    if not pdf_path:
        return RedirectResponse(
            url="/invoices?error=Failed+to+generate+PDF",
            status_code=303,
        )

    path = Path(pdf_path)
    disposition = "attachment" if download else "inline"
    headers = {"Content-Disposition": f'{disposition}; filename="{path.name}"'}

    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        filename=path.name,
        headers=headers,
    )


