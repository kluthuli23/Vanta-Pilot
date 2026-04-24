"""Dashboard router."""

import os
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config.settings import config
from database.safety import create_manual_backup
from services.audit_service import AuditService
from services.business_profile_service import BusinessProfileService
from services.customer_service import CustomerService
from services.email_service import EmailService
from services.invoice_service import InvoiceService
from services.oauth_service import OAuthService
from services.payment_service import PaymentService
from services.reminder_service import ReminderService
from services.subscription_service import SubscriptionService

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


def _current_user_id(request: Request) -> Optional[int]:
    value = request.session.get("user_id")
    return int(value) if value is not None else None


def _is_admin(request: Request) -> bool:
    return str(request.session.get("user_role", "")).strip().lower() == "admin"


def _restore_upload_enabled() -> bool:
    return str(os.getenv("ALLOW_DB_RESTORE_UPLOAD", "")).strip().lower() in ("1", "true", "yes", "on")


def _restore_token_valid(token: str) -> bool:
    expected = str(os.getenv("DB_RESTORE_TOKEN", "")).strip()
    return bool(expected) and bool(token) and token == expected


def _as_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _business_form_draft_from_form(form) -> dict:
    """Capture business form draft values to preserve on errors."""
    return {
        "business_name": str(form.get("business_name", "")).strip(),
        "business_email": str(form.get("business_email", "")).strip(),
        "business_phone": str(form.get("business_phone", "")).strip(),
        "vat_number": str(form.get("vat_number", "")).strip(),
        "business_address": str(form.get("business_address", "")).strip(),
        "bank_name": str(form.get("bank_name", "")).strip(),
        "account_holder": str(form.get("account_holder", "")).strip(),
        "account_number": str(form.get("account_number", "")).strip(),
        "branch_code": str(form.get("branch_code", "")).strip(),
        "smtp_provider": str(form.get("smtp_provider", "custom")).strip(),
        "smtp_server": str(form.get("smtp_server", "")).strip(),
        "smtp_port": str(form.get("smtp_port", "")).strip(),
        "smtp_username": str(form.get("smtp_username", "")).strip(),
        "smtp_from_email": str(form.get("smtp_from_email", "")).strip(),
        "smtp_use_tls": _as_bool(form.get("smtp_use_tls"), False),
        "smtp_use_ssl": _as_bool(form.get("smtp_use_ssl"), False),
    }


def _parse_banking_details(details: str) -> dict:
    fields = {
        "bank_name": "",
        "account_holder": "",
        "account_number": "",
        "branch_code": "",
    }
    for line in (details or "").splitlines():
        text = line.strip()
        if ":" not in text:
            continue
        key, value = text.split(":", 1)
        k = key.strip().lower()
        v = value.strip()
        if k == "bank":
            fields["bank_name"] = v
        elif k in ("account holder", "account name"):
            fields["account_holder"] = v
        elif k == "account number":
            fields["account_number"] = v
        elif k == "branch code":
            fields["branch_code"] = v
    return fields


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": ok, "detail": detail}


def _business_setup_items(profile: dict, google_connected: bool, smtp_authenticated: bool) -> list[dict]:
    return [
        {
            "label": "Business name",
            "done": bool((profile.get("business_name") or "").strip()),
        },
        {
            "label": "Business email",
            "done": bool((profile.get("business_email") or "").strip()),
        },
        {
            "label": "Banking details",
            "done": bool((profile.get("banking_details") or "").strip()),
        },
        {
            "label": "Email connected",
            "done": bool(google_connected or smtp_authenticated),
        },
    ]


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard showing business overview."""
    user_id = _current_user_id(request)
    customer_service = CustomerService()
    invoice_service = InvoiceService()
    payment_service = PaymentService()

    customers = customer_service.get_all_customers(active_only=True, user_id=user_id)
    summary = payment_service.get_payment_summary(30, user_id=user_id)
    recent_invoices = invoice_service.get_all_invoices(limit=10, user_id=user_id)
    has_any_invoice = len(invoice_service.get_all_invoices(limit=1, user_id=user_id)) > 0
    outstanding = payment_service.get_outstanding_invoices(user_id=user_id)
    total_outstanding = sum(inv.get("balance_due", 0) for inv in outstanding)
    profile = BusinessProfileService().get_profile(user_id) if user_id is not None else {}
    google_connected = OAuthService().is_google_connected(user_id) if user_id is not None else False
    smtp_authenticated = EmailService().is_user_smtp_authenticated(user_id) if user_id is not None else False
    billing_summary = SubscriptionService().get_summary(user_id)
    setup_items = _business_setup_items(profile, google_connected, smtp_authenticated)
    checklist = [
        {
            "label": "Business profile set",
            "done": bool((profile.get("business_name") or "").strip() and (profile.get("business_email") or "").strip()),
            "href": "/settings/business",
        },
        {
            "label": "Banking details added",
            "done": bool((profile.get("banking_details") or "").strip()),
            "href": "/settings/business",
        },
        {
            "label": "Email channel connected",
            "done": bool(google_connected or smtp_authenticated),
            "href": "/settings/business",
        },
        {
            "label": "At least one customer",
            "done": len(customers) > 0,
            "href": "/customers",
        },
        {
            "label": "At least one invoice created",
            "done": has_any_invoice,
            "href": "/invoices",
        },
    ]
    checklist_done = len([c for c in checklist if c["done"]])

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "customer_count": len(customers),
            "total_outstanding": total_outstanding,
            "recent_invoices": recent_invoices,
            "outstanding_invoices": outstanding[:5],
            "summary": summary,
            "checklist": checklist,
            "checklist_done": checklist_done,
            "setup_items": setup_items,
            "setup_done": len([item for item in setup_items if item["done"]]),
            "billing_summary": billing_summary,
            "now": datetime.now(),
        },
    )


@router.get("/billing", response_class=HTMLResponse)
async def billing_page(request: Request):
    """Billing and trial status page."""
    user_id = _current_user_id(request)
    summary = SubscriptionService().get_summary(user_id)
    return templates.TemplateResponse(
        request,
        "billing.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "billing_summary": summary,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.get("/system-check", response_class=HTMLResponse)
async def system_check(request: Request):
    """System readiness checks for demo setup and operations."""
    if not _is_admin(request):
        params = urlencode({"error": "System checks are available to admin accounts only."})
        return RedirectResponse(url=f"/dashboard?{params}", status_code=303)

    checks = []

    # Database checks
    db_exists = config.DB_PATH.exists()
    db_ok = False
    db_error = ""
    if db_exists:
        try:
            with sqlite3.connect(config.DB_PATH) as conn:
                conn.execute("SELECT 1")
            db_ok = True
        except sqlite3.Error as exc:
            db_error = str(exc)
    checks.append(
        _check(
            "Database connectivity",
            db_exists and db_ok,
            str(config.DB_PATH) if db_ok else (db_error or "Database file missing."),
        )
    )

    # Session/config security checks
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    secret_key = os.getenv("SESSION_SECRET_KEY", "dev-insecure-change-me")
    checks.append(
        _check(
            "Session secret",
            not (app_env == "production" and secret_key == "dev-insecure-change-me"),
            "Set SESSION_SECRET_KEY in production.",
        )
    )
    checks.append(
        _check(
            "Session HTTPS-only",
            os.getenv("SESSION_HTTPS_ONLY", "false").strip().lower() in ("1", "true", "yes", "on")
            if app_env == "production"
            else True,
            "Enable SESSION_HTTPS_ONLY=true in production.",
        )
    )

    # OAuth checks
    oauth_client_id = (os.getenv("GOOGLE_OAUTH_CLIENT_ID", "") or "").strip()
    oauth_client_secret = (os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "") or "").strip()
    oauth_redirect = (os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "") or "").strip()
    checks.append(
        _check(
            "Google OAuth configured",
            bool(oauth_client_id and oauth_client_secret and oauth_redirect),
            "Set GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, GOOGLE_OAUTH_REDIRECT_URI.",
        )
    )
    checks.append(
        _check(
            "OAuth token encryption key",
            bool((os.getenv("OAUTH_TOKEN_ENCRYPTION_KEY", "") or "").strip()),
            "Set OAUTH_TOKEN_ENCRYPTION_KEY for encrypted token storage.",
        )
    )

    # Writable directory checks
    invoices_dir = config.BASE_DIR / "invoices"
    logos_dir = config.BASE_DIR / "web" / "static" / "uploads" / "logos"
    for label, path in (
        ("Invoices directory writable", invoices_dir),
        ("Logos directory writable", logos_dir),
    ):
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            checks.append(_check(label, True, str(path.resolve())))
        except Exception as exc:
            checks.append(_check(label, False, f"{path}: {exc}"))

    total = len(checks)
    passed = len([c for c in checks if c["ok"]])
    return templates.TemplateResponse(
        request,
        "system_check.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "checks": checks,
            "total_checks": total,
            "passed_checks": passed,
            "backup_message": request.query_params.get("backup_message"),
            "backup_error": request.query_params.get("backup_error"),
            "now": datetime.now(),
        },
    )


@router.post("/system/create-backup")
async def create_system_backup(request: Request):
    """Create an admin-only timestamped backup in the mounted DB volume."""
    if not _is_admin(request):
        params = urlencode({"error": "System checks are available to admin accounts only."})
        return RedirectResponse(url=f"/dashboard?{params}", status_code=303)

    try:
        backup_path = create_manual_backup(config.DB_PATH, reason="manual")
        params = urlencode({"backup_message": f"Backup created: {backup_path.name}"})
    except Exception as exc:
        params = urlencode({"backup_error": f"Backup failed: {exc}"})
    return RedirectResponse(url=f"/system-check?{params}", status_code=303)


@router.get("/system/data-check")
async def system_data_check(request: Request):
    """Admin-only production data verification summary."""
    if not _is_admin(request):
        return JSONResponse({"error": "Admin access required."}, status_code=403)

    counts = {
        "users": 0,
        "active_users": 0,
        "business_profiles": 0,
        "customers": 0,
        "active_customers": 0,
        "invoices": 0,
        "oauth_connections": 0,
    }
    sample_users = []
    error = None

    try:
        with sqlite3.connect(config.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            counts["users"] = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
            counts["active_users"] = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT(*) FROM business_profiles")
            counts["business_profiles"] = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT(*) FROM customers")
            counts["customers"] = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT(*) FROM customers WHERE is_active = 1")
            counts["active_customers"] = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT(*) FROM invoices")
            counts["invoices"] = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='oauth_connections'")
            if int(cursor.fetchone()[0]) > 0:
                cursor.execute("SELECT COUNT(*) FROM oauth_connections")
                counts["oauth_connections"] = int(cursor.fetchone()[0])
            cursor.execute(
                """
                SELECT id, email, role, is_active, created_at
                FROM users
                ORDER BY id ASC
                LIMIT 10
                """
            )
            sample_users = [dict(row) for row in cursor.fetchall()]
    except Exception as exc:
        error = str(exc)

    return {
        "database_path": str(config.DB_PATH),
        "database_exists": config.DB_PATH.exists(),
        "counts": counts,
        "sample_users": sample_users,
        "error": error,
    }


@router.get("/system/restore-db", response_class=HTMLResponse)
async def restore_db_page(request: Request):
    """Temporary guarded page for restoring a SQLite database file."""
    token = str(request.query_params.get("token", "")).strip()
    if not _restore_upload_enabled() or not _restore_token_valid(token):
        return HTMLResponse("Not found", status_code=404)

    return templates.TemplateResponse(
        request,
        "system_restore_db.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "token": token,
            "database_path": str(config.DB_PATH),
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/system/restore-db")
async def restore_db_upload(request: Request, database_file: UploadFile = File(...)):
    """Temporarily accept a SQLite file upload and restore it into the mounted DB path."""
    form = await request.form()
    token = str(form.get("token", "")).strip()
    if not _restore_upload_enabled() or not _restore_token_valid(token):
        return HTMLResponse("Not found", status_code=404)

    if not database_file.filename or not database_file.filename.lower().endswith(".db"):
        params = urlencode({"token": token, "error": "Upload a .db SQLite file."})
        return RedirectResponse(url=f"/system/restore-db?{params}", status_code=303)

    target_path = Path(config.DB_PATH)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
        temp_path = Path(tmp.name)
        while True:
            chunk = await database_file.read(1024 * 1024)
            if not chunk:
                break
            tmp.write(chunk)

    await database_file.close()

    try:
        with sqlite3.connect(temp_path) as conn:
            cursor = conn.cursor()
            for table_name in ("users", "business_profiles", "customers", "invoices"):
                cursor.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name = ?",
                    (table_name,),
                )
                if int(cursor.fetchone()[0]) == 0:
                    raise RuntimeError(f"Uploaded database is missing required table: {table_name}")

        if target_path.exists():
            backup_path = target_path.with_suffix(f".pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
            shutil.copy2(target_path, backup_path)

        shutil.move(str(temp_path), str(target_path))
        params = urlencode(
            {
                "token": token,
                "message": f"Database restored to {target_path}. Remove ALLOW_DB_RESTORE_UPLOAD and ALLOW_DB_BOOTSTRAP, then redeploy.",
            }
        )
        return RedirectResponse(url=f"/system/restore-db?{params}", status_code=303)
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        params = urlencode({"token": token, "error": f"Restore failed: {exc}"})
        return RedirectResponse(url=f"/system/restore-db?{params}", status_code=303)


@router.get("/audit", response_class=HTMLResponse)
async def audit_trail(request: Request):
    """Audit trail page with filtering."""
    if not _is_admin(request):
        params = urlencode({"error": "Audit trail is available to admin accounts only."})
        return RedirectResponse(url=f"/dashboard?{params}", status_code=303)

    user_id = _current_user_id(request)
    audit_service = AuditService()
    customer_service = CustomerService()
    invoice_service = InvoiceService()

    entity_type = request.query_params.get("entity_type") or ""
    event_text = request.query_params.get("event_text") or ""
    date_from = request.query_params.get("date_from") or ""
    date_to = request.query_params.get("date_to") or ""

    logs = audit_service.query_logs(
        limit=300,
        entity_type=entity_type or None,
        event_text=event_text or None,
        date_from=date_from or None,
        date_to=date_to or None,
    )
    customer_ids = {
        c["id"] for c in customer_service.get_all_customers(active_only=False, user_id=user_id)
    }
    invoice_ids = {
        i["id"] for i in invoice_service.get_all_invoices(limit=10000, offset=0, user_id=user_id)
    }
    logs = [
        log
        for log in logs
        if (
            (log.get("entity_type") == "customer" and log.get("entity_id") in customer_ids)
            or (log.get("entity_type") == "invoice" and log.get("entity_id") in invoice_ids)
            or (log.get("entity_type") == "invoice_batch")
            or (log.get("entity_type") == "reminder_settings")
            or (log.get("entity_type") == "user" and log.get("entity_id") == user_id)
            or (log.get("entity_type") == "business_profile" and log.get("entity_id") == user_id)
        )
    ]

    return templates.TemplateResponse(
        request,
        "audit.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "logs": logs,
            "entity_type": entity_type,
            "event_text": event_text,
            "date_from": date_from,
            "date_to": date_to,
        },
    )


@router.get("/settings/reminders", response_class=HTMLResponse)
async def reminder_settings_page(request: Request):
    """Reminder configuration page."""
    reminder_service = ReminderService()
    settings = reminder_service.get_global_settings()
    return templates.TemplateResponse(
        request,
        "reminder_settings.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "settings": settings,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/settings/reminders")
async def update_reminder_settings(request: Request):
    """Update global reminder settings."""
    form = await request.form()
    enabled = str(form.get("enabled", "")).lower() in ("1", "true", "on", "yes")
    interval_days = int(str(form.get("interval_days", "7")))
    start_after_days = int(str(form.get("start_after_days_overdue", "0")))
    max_reminders = int(str(form.get("max_reminders", "12")))

    ok = ReminderService().update_global_settings(
        enabled=enabled,
        interval_days=interval_days,
        start_after_days_overdue=start_after_days,
        max_reminders=max_reminders,
    )
    if ok:
        params = urlencode({"message": "Reminder settings updated."})
    else:
        params = urlencode({"error": "Failed to update reminder settings."})
    return RedirectResponse(url=f"/settings/reminders?{params}", status_code=303)


@router.get("/settings/business", response_class=HTMLResponse)
async def business_settings_page(request: Request):
    """Business profile settings page."""
    user_id = _current_user_id(request)
    if user_id is None:
        params = urlencode({"next": "/settings/business"})
        return RedirectResponse(url=f"/login?{params}", status_code=303)
    profile = BusinessProfileService().get_profile(user_id)
    draft = request.session.get("business_form_draft")
    if draft:
        profile = dict(profile)
        profile["business_name"] = draft.get("business_name", profile.get("business_name", ""))
        profile["business_email"] = draft.get("business_email", profile.get("business_email", ""))
        profile["business_phone"] = draft.get("business_phone", profile.get("business_phone", ""))
        profile["vat_number"] = draft.get("vat_number", profile.get("vat_number", ""))
        profile["business_address"] = draft.get("business_address", profile.get("business_address", ""))
        profile["smtp_server"] = draft.get("smtp_server", profile.get("smtp_server", ""))
        profile["smtp_port"] = draft.get("smtp_port", profile.get("smtp_port", 587))
        profile["smtp_username"] = draft.get("smtp_username", profile.get("smtp_username", ""))
        profile["smtp_from_email"] = draft.get("smtp_from_email", profile.get("smtp_from_email", ""))
        profile["smtp_use_tls"] = 1 if draft.get("smtp_use_tls") else 0
        profile["smtp_use_ssl"] = 1 if draft.get("smtp_use_ssl") else 0
    google_conn = OAuthService().get_google_connection(user_id)
    onboarding_notice = request.session.pop("onboarding_notice", None)
    smtp_authenticated = EmailService().is_user_smtp_authenticated(user_id)
    setup_items = _business_setup_items(profile, bool(google_conn), smtp_authenticated)
    banking_fields = _parse_banking_details(profile.get("banking_details", ""))
    if draft:
        banking_fields = {
            "bank_name": draft.get("bank_name", ""),
            "account_holder": draft.get("account_holder", ""),
            "account_number": draft.get("account_number", ""),
            "branch_code": draft.get("branch_code", ""),
        }
    return templates.TemplateResponse(
        request,
        "business_settings.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "profile": profile,
            "banking_fields": banking_fields,
            "google_connected": bool(google_conn),
            "google_account_email": (google_conn or {}).get("provider_account_email", ""),
            "smtp_authenticated": smtp_authenticated,
            "smtp_provider": (draft or {}).get("smtp_provider", "custom"),
            "smtp_use_tls": _as_bool(profile.get("smtp_use_tls", 1), True),
            "smtp_use_ssl": _as_bool(profile.get("smtp_use_ssl", 0), False),
            "setup_items": setup_items,
            "setup_done": len([item for item in setup_items if item["done"]]),
            "onboarding_notice": onboarding_notice,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/settings/business")
async def update_business_settings(request: Request):
    """Update business profile and logo."""
    user_id = _current_user_id(request)
    if user_id is None:
        params = urlencode({"next": "/settings/business"})
        return RedirectResponse(url=f"/login?{params}", status_code=303)
    form = await request.form()
    request.session["business_form_draft"] = _business_form_draft_from_form(form)
    logo_file = form.get("logo_file")
    bank_name = str(form.get("bank_name", "")).strip()
    account_holder = str(form.get("account_holder", "")).strip()
    account_number = str(form.get("account_number", "")).strip()
    branch_code = str(form.get("branch_code", "")).strip()
    smtp_server = str(form.get("smtp_server", "")).strip()
    smtp_port_raw = str(form.get("smtp_port", "587")).strip()
    smtp_username = str(form.get("smtp_username", "")).strip()
    smtp_from_email = str(form.get("smtp_from_email", "")).strip()
    smtp_use_tls = str(form.get("smtp_use_tls", "")).lower() in ("1", "true", "on", "yes")
    smtp_use_ssl = str(form.get("smtp_use_ssl", "")).lower() in ("1", "true", "on", "yes")
    try:
        smtp_port = int(smtp_port_raw or "587")
    except ValueError:
        smtp_port = 587
    profile = BusinessProfileService().get_profile(user_id)
    composed_banking_details = "\n".join(
        [
            f"Bank: {bank_name}" if bank_name else "",
            f"Account Holder: {account_holder}" if account_holder else "",
            f"Account Number: {account_number}" if account_number else "",
            f"Branch Code: {branch_code}" if branch_code else "",
        ]
    ).strip()

    ok = BusinessProfileService().upsert_profile(
        user_id=user_id,
        business_name=str(form.get("business_name", "")).strip(),
        business_address=str(form.get("business_address", "")).strip(),
        business_phone=str(form.get("business_phone", "")).strip(),
        business_email=str(form.get("business_email", "")).strip(),
        vat_number=str(form.get("vat_number", "")).strip(),
        banking_details=composed_banking_details,
        smtp_server=smtp_server,
        smtp_port=smtp_port,
        smtp_username=smtp_username,
        smtp_password="",
        smtp_from_email=smtp_from_email,
        smtp_use_tls=smtp_use_tls,
        smtp_use_ssl=smtp_use_ssl,
        logo_upload=logo_file,
    )
    if ok:
        request.session.pop("business_form_draft", None)
        params = urlencode({"message": "Business profile updated."})
    else:
        params = urlencode({"error": "Failed to update business profile."})
    return RedirectResponse(url=f"/settings/business?{params}", status_code=303)


@router.post("/settings/business/smtp-auth")
async def authenticate_business_smtp(request: Request):
    """Authenticate SMTP credentials for current session (not persisted)."""
    user_id = _current_user_id(request)
    if user_id is None:
        params = urlencode({"next": "/settings/business"})
        return RedirectResponse(url=f"/login?{params}", status_code=303)

    form = await request.form()
    request.session["business_form_draft"] = _business_form_draft_from_form(form)
    smtp_password = str(form.get("smtp_password_auth", "")).strip()
    if not smtp_password:
        params = urlencode({"error": "Enter the SMTP password or app password to connect this email."})
        return RedirectResponse(url=f"/settings/business?{params}", status_code=303)

    profile = BusinessProfileService().get_profile(user_id)
    draft = request.session.get("business_form_draft", {})
    profile = dict(profile)
    profile["smtp_server"] = draft.get("smtp_server", profile.get("smtp_server", ""))
    profile["smtp_port"] = draft.get("smtp_port", profile.get("smtp_port", 587))
    profile["smtp_username"] = draft.get("smtp_username", profile.get("smtp_username", ""))
    profile["smtp_from_email"] = draft.get("smtp_from_email", profile.get("smtp_from_email", ""))
    profile["smtp_use_tls"] = 1 if draft.get("smtp_use_tls") else 0
    profile["smtp_use_ssl"] = 1 if draft.get("smtp_use_ssl") else 0
    ok = EmailService().authorize_user_smtp(user_id, profile, smtp_password)
    if ok:
        params = urlencode({"message": "Other email provider connected for this session."})
    else:
        params = urlencode({"error": "SMTP connection failed. Check the host, port, username, password, and TLS/SSL settings."})
    return RedirectResponse(url=f"/settings/business?{params}", status_code=303)


@router.post("/settings/business/smtp-auth/clear")
async def clear_business_smtp_auth(request: Request):
    """Clear current session SMTP auth cache for user."""
    user_id = _current_user_id(request)
    if user_id is None:
        params = urlencode({"next": "/settings/business"})
        return RedirectResponse(url=f"/login?{params}", status_code=303)

    EmailService().clear_user_smtp_auth(user_id)
    params = urlencode({"message": "Other email provider connection cleared."})
    return RedirectResponse(url=f"/settings/business?{params}", status_code=303)
