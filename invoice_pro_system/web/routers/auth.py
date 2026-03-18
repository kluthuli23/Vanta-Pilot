"""Authentication router."""

import secrets
import os
import time
from urllib.parse import urlencode
from email.mime.text import MIMEText
from email import policy

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config.settings import config
from pathlib import Path
from services.auth_service import AuthService
from services.business_profile_service import BusinessProfileService
from services.email_service import EmailService
from services.oauth_service import OAuthService

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)

# OAuth state fallback cache (helps when browser host differs: localhost vs 127.0.0.1).
_PENDING_GOOGLE_OAUTH_STATES = {}
_OAUTH_STATE_TTL_SECONDS = 10 * 60
_AUTH_RATE_LIMIT_BUCKETS = {}
_AUTH_RATE_LIMITS = {
    "login": (10, 60),  # 10 attempts per minute per IP
    "signup": (6, 60),
    "forgot_password": (5, 300),  # 5 per 5 min
    "reset_password": (10, 300),
}


def _remember_oauth_state(state: str, user_id: int) -> None:
    now = time.time()
    _PENDING_GOOGLE_OAUTH_STATES[state] = {
        "user_id": int(user_id),
        "expires_at": now + _OAUTH_STATE_TTL_SECONDS,
    }
    # Opportunistic cleanup
    expired = [k for k, v in _PENDING_GOOGLE_OAUTH_STATES.items() if v.get("expires_at", 0) <= now]
    for key in expired:
        _PENDING_GOOGLE_OAUTH_STATES.pop(key, None)


def _consume_oauth_state(state: str):
    data = _PENDING_GOOGLE_OAUTH_STATES.pop(state, None)
    if not data:
        return None
    if data.get("expires_at", 0) <= time.time():
        return None
    return data


def _csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(24)
        request.session["csrf_token"] = token
    return str(token)


def _validate_csrf(request: Request, submitted_token: str) -> bool:
    expected = str(request.session.get("csrf_token", ""))
    return bool(expected) and bool(submitted_token) and secrets.compare_digest(
        expected, str(submitted_token)
    )


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return (request.client.host if request.client else "unknown").strip()


def _rate_limited(request: Request, action: str) -> bool:
    max_attempts, window_seconds = _AUTH_RATE_LIMITS[action]
    now = time.time()
    ip = _client_ip(request)
    key = f"{action}:{ip}"
    attempts = _AUTH_RATE_LIMIT_BUCKETS.get(key, [])
    attempts = [ts for ts in attempts if now - ts <= window_seconds]
    if len(attempts) >= max_attempts:
        _AUTH_RATE_LIMIT_BUCKETS[key] = attempts
        return True
    attempts.append(now)
    _AUTH_RATE_LIMIT_BUCKETS[key] = attempts
    return False


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse(url="/dashboard", status_code=303)
    draft = request.session.get("login_form_draft", {})
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
            "next": request.query_params.get("next", "/dashboard"),
            "csrf_token": _csrf_token(request),
            "draft_email": draft.get("email", ""),
        },
    )


@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse(url="/dashboard", status_code=303)
    draft = request.session.get("signup_form_draft", {})
    return templates.TemplateResponse(
        request,
        "signup.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "error": request.query_params.get("error"),
            "csrf_token": _csrf_token(request),
            "draft_email": draft.get("email", ""),
        },
    )


@router.post("/login")
async def login_submit(request: Request):
    if _rate_limited(request, "login"):
        params = urlencode({"error": "Too many login attempts. Please wait a minute."})
        return RedirectResponse(url=f"/login?{params}", status_code=303)
    form = await request.form()
    if not _validate_csrf(request, str(form.get("csrf_token", ""))):
        params = urlencode({"error": "Invalid form token. Refresh and try again."})
        return RedirectResponse(url=f"/login?{params}", status_code=303)
    email = str(form.get("email", "")).strip().lower()
    password = str(form.get("password", ""))
    next_url = str(form.get("next", "/dashboard")) or "/dashboard"
    request.session["login_form_draft"] = {"email": email}
    if not next_url.startswith("/"):
        next_url = "/dashboard"

    user = AuthService(bootstrap_admin=False).authenticate(email, password)
    if not user:
        params = urlencode({"error": "Invalid email or password.", "next": next_url})
        return RedirectResponse(url=f"/login?{params}", status_code=303)

    request.session["user_id"] = user["id"]
    request.session["user_email"] = user["email"]
    request.session["user_role"] = user["role"]
    request.session.pop("login_form_draft", None)
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/signup")
async def signup_submit(request: Request):
    if _rate_limited(request, "signup"):
        params = urlencode({"error": "Too many signup attempts. Please wait a minute."})
        return RedirectResponse(url=f"/signup?{params}", status_code=303)
    form = await request.form()
    if not _validate_csrf(request, str(form.get("csrf_token", ""))):
        params = urlencode({"error": "Invalid form token. Refresh and try again."})
        return RedirectResponse(url=f"/signup?{params}", status_code=303)
    email = str(form.get("email", "")).strip().lower()
    password = str(form.get("password", ""))
    confirm = str(form.get("confirm_password", ""))
    request.session["signup_form_draft"] = {"email": email}

    if password != confirm:
        params = urlencode({"error": "Passwords do not match."})
        return RedirectResponse(url=f"/signup?{params}", status_code=303)

    user = AuthService(bootstrap_admin=False).create_user(email=email, password=password, role="owner")
    if not user:
        params = urlencode({"error": "Signup failed. Email may already exist or password is too short."})
        return RedirectResponse(url=f"/signup?{params}", status_code=303)

    request.session["user_id"] = user["id"]
    request.session["user_email"] = user["email"]
    request.session["user_role"] = user["role"]
    request.session.pop("signup_form_draft", None)
    request.session["onboarding_notice"] = (
        "Account created. Add your business details, banking details, and Gmail connection to send your first invoice."
    )
    BusinessProfileService().upsert_profile(
        user_id=int(user["id"]),
        business_name="",
        business_address="",
        business_phone="",
        business_email=email,
        vat_number="",
        banking_details="",
        smtp_server="smtp.gmail.com",
        smtp_port=587,
        smtp_username=email,
        smtp_password="",
        smtp_from_email=email,
        smtp_use_tls=True,
        smtp_use_ssl=False,
    )
    return RedirectResponse(url="/settings/business", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    form = await request.form()
    if not _validate_csrf(request, str(form.get("csrf_token", ""))):
        params = urlencode({"error": "Invalid form token."})
        return RedirectResponse(url=f"/dashboard?{params}", status_code=303)
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(
        request,
        "forgot_password.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
            "csrf_token": _csrf_token(request),
        },
    )


@router.post("/forgot-password")
async def forgot_password_submit(request: Request):
    if _rate_limited(request, "forgot_password"):
        params = urlencode({"error": "Too many requests. Please wait a few minutes."})
        return RedirectResponse(url=f"/forgot-password?{params}", status_code=303)
    form = await request.form()
    if not _validate_csrf(request, str(form.get("csrf_token", ""))):
        params = urlencode({"error": "Invalid form token. Refresh and try again."})
        return RedirectResponse(url=f"/forgot-password?{params}", status_code=303)
    email = str(form.get("email", "")).strip().lower()
    auth = AuthService(bootstrap_admin=False)
    token = auth.create_password_reset_token(email)
    user = auth.get_user_by_email(email) if email else None

    # Always return generic success text to avoid account enumeration.
    generic_message = (
        "If that email exists, a password reset link has been sent."
    )
    if token and email:
        reset_url = str(request.url_for("reset_password_page")) + f"?token={token}"
        # Best-effort email. Prefer per-user Gmail OAuth; fallback to global SMTP.
        try:
            body = (
                f"Hi,\n\nUse this link to reset your Vanta Pilot password:\n{reset_url}\n\n"
                "This link expires in 30 minutes.\nIf you did not request this, ignore this email."
            )
            msg = MIMEText(body, "plain")
            msg["Subject"] = "Reset your Vanta Pilot password"
            msg["To"] = email

            sent = False
            if user:
                user_id = int(user["id"])
                oauth_service = OAuthService()
                oauth_conn = oauth_service.get_google_connection(user_id)
                if oauth_conn:
                    from_email = (
                        oauth_conn.get("provider_account_email")
                        or email
                    )
                    msg["From"] = from_email
                    ok, _ = oauth_service.send_gmail_message(
                        user_id,
                        msg.as_bytes(policy=policy.SMTP),
                    )
                    sent = bool(ok)

            if not sent:
                email_service = EmailService()
                cfg = email_service.config
                if cfg.get("smtp_server") and cfg.get("smtp_username") and cfg.get("smtp_password"):
                    import smtplib
                    msg["From"] = cfg.get("from_email") or cfg.get("smtp_username")
                    with smtplib.SMTP(cfg["smtp_server"], int(cfg.get("smtp_port", 587))) as server:
                        if cfg.get("use_tls", True):
                            server.starttls()
                        server.login(cfg["smtp_username"], cfg["smtp_password"])
                        server.send_message(msg)
                    sent = True

            if not sent:
                print(f"Password reset link (dev): {reset_url}")
        except Exception:
            print(f"Password reset link (dev): {reset_url}")

    params = urlencode({"message": generic_message})
    return RedirectResponse(url=f"/forgot-password?{params}", status_code=303)


@router.get("/reset-password", response_class=HTMLResponse, name="reset_password_page")
async def reset_password_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse(url="/dashboard", status_code=303)
    token = str(request.query_params.get("token", "")).strip()
    return templates.TemplateResponse(
        request,
        "reset_password.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "token": token,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
            "csrf_token": _csrf_token(request),
        },
    )


@router.post("/reset-password")
async def reset_password_submit(request: Request):
    if _rate_limited(request, "reset_password"):
        params = urlencode({"error": "Too many attempts. Please wait a few minutes."})
        return RedirectResponse(url=f"/reset-password?{params}", status_code=303)
    form = await request.form()
    if not _validate_csrf(request, str(form.get("csrf_token", ""))):
        params = urlencode({"error": "Invalid form token. Refresh and try again."})
        return RedirectResponse(url=f"/reset-password?{params}", status_code=303)
    token = str(form.get("token", "")).strip()
    password = str(form.get("password", ""))
    confirm = str(form.get("confirm_password", ""))
    if password != confirm:
        params = urlencode({"error": "Passwords do not match.", "token": token})
        return RedirectResponse(url=f"/reset-password?{params}", status_code=303)
    ok = AuthService(bootstrap_admin=False).consume_password_reset_token(token, password)
    if not ok:
        params = urlencode(
            {"error": "Reset link is invalid/expired, or password is too short.", "token": token}
        )
        return RedirectResponse(url=f"/reset-password?{params}", status_code=303)
    params = urlencode({"message": "Password updated. Please sign in."})
    return RedirectResponse(url=f"/login?{params}", status_code=303)


@router.get("/oauth/google/start")
async def google_oauth_start(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        params = urlencode({"next": "/settings/business"})
        return RedirectResponse(url=f"/login?{params}", status_code=303)

    state = secrets.token_urlsafe(24)
    request.session["google_oauth_state"] = state
    request.session["google_oauth_next"] = "/settings/business"
    _remember_oauth_state(state, int(user_id))
    redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", str(request.url_for("google_oauth_callback")))
    ok, url_or_error = OAuthService().build_google_auth_url(redirect_uri=redirect_uri, state=state)
    if not ok:
        params = urlencode({"error": url_or_error})
        return RedirectResponse(url=f"/settings/business?{params}", status_code=303)
    response = RedirectResponse(url=url_or_error, status_code=303)
    response.set_cookie(
        key="google_oauth_state",
        value=state,
        max_age=600,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/oauth/google/callback", name="google_oauth_callback")
async def google_oauth_callback(request: Request):
    state = str(request.query_params.get("state", ""))
    pending = _consume_oauth_state(state) if state else None
    user_id = request.session.get("user_id")
    if not user_id and pending:
        user_id = pending.get("user_id")
        if user_id:
            request.session["user_id"] = int(user_id)
    if not user_id:
        params = urlencode({"next": "/settings/business"})
        return RedirectResponse(url=f"/login?{params}", status_code=303)

    expected_state = str(request.session.get("google_oauth_state", ""))
    cookie_state = str(request.cookies.get("google_oauth_state", ""))
    state_match = bool(state) and (
        state == expected_state
        or state == cookie_state
        or pending is not None
    )
    if not state_match:
        params = urlencode({"error": "OAuth state validation failed."})
        return RedirectResponse(url=f"/settings/business?{params}", status_code=303)
    code = str(request.query_params.get("code", ""))
    if not code:
        params = urlencode({"error": "Google OAuth did not return a code."})
        return RedirectResponse(url=f"/settings/business?{params}", status_code=303)

    redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", str(request.url_for("google_oauth_callback")))
    ok, message = OAuthService().exchange_google_code(
        user_id=int(user_id),
        code=code,
        redirect_uri=redirect_uri,
    )
    request.session.pop("google_oauth_state", None)
    request.session.pop("google_oauth_next", None)
    if ok:
        params = urlencode({"message": message})
    else:
        params = urlencode({"error": message})
    response = RedirectResponse(url=f"/settings/business?{params}", status_code=303)
    response.delete_cookie("google_oauth_state")
    return response


@router.post("/oauth/google/disconnect")
async def google_oauth_disconnect(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        params = urlencode({"next": "/settings/business"})
        return RedirectResponse(url=f"/login?{params}", status_code=303)
    ok = OAuthService().clear_google_connection(int(user_id))
    if ok:
        params = urlencode({"message": "Google account disconnected."})
    else:
        params = urlencode({"error": "Failed to disconnect Google account."})
    return RedirectResponse(url=f"/settings/business?{params}", status_code=303)
