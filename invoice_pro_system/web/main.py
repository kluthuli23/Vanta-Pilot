"""Main FastAPI application for Vanta Pilot web UI."""

import asyncio
import os
import secrets
import sqlite3
import sys
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv

# Add project root to path so we can import project modules.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
load_dotenv(project_root / ".env")

if os.getenv("APP_ENV", "development").strip().lower() == "production":
    if os.getenv("SESSION_SECRET_KEY", "dev-insecure-change-me") == "dev-insecure-change-me":
        raise RuntimeError("SESSION_SECRET_KEY must be set in production.")

from config.settings import config
from services.auth_service import AuthService
from services.invoice_service import InvoiceService
from services.reminder_service import ReminderService
from services.subscription_service import SubscriptionService
from web.routers import auth, customers, dashboard, invoices

_reminder_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan for background reminder processing."""
    global _reminder_task
    if not os.getenv("PYTEST_CURRENT_TEST"):
        try:
            AuthService()
        except Exception:
            pass
        _reminder_task = asyncio.create_task(_reminder_worker())

    try:
        yield
    finally:
        if _reminder_task is not None:
            _reminder_task.cancel()
            try:
                await _reminder_task
            except asyncio.CancelledError:
                pass
            _reminder_task = None


app = FastAPI(title="Vanta Pilot", version="1.0.0", lifespan=lifespan)

web_dir = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(web_dir / "templates"))
app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")

app.include_router(customers.router, prefix="/customers", tags=["customers"])
app.include_router(customers.router, prefix="/accounts", tags=["accounts"])
app.include_router(invoices.router, prefix="/invoices", tags=["invoices"])
app.include_router(dashboard.router, prefix="", tags=["dashboard"])
app.include_router(auth.router, prefix="", tags=["auth"])


class AuthRequiredMiddleware(BaseHTTPMiddleware):
    """Require authenticated sessions for protected routes."""

    async def dispatch(self, request: Request, call_next):
        if os.getenv("PYTEST_CURRENT_TEST"):
            return await call_next(request)

        path = request.url.path
        public_paths = {
            "/login",
            "/signup",
            "/forgot-password",
            "/reset-password",
            "/health",
            "/favicon.ico",
        }
        if path in public_paths or path.startswith("/static"):
            return await call_next(request)

        if not request.session.get("user_id"):
            params = urlencode({"next": path})
            return RedirectResponse(url=f"/login?{params}", status_code=303)
        if not request.session.get("csrf_token"):
            request.session["csrf_token"] = secrets.token_urlsafe(24)

        return await call_next(request)


# Order matters: Session must wrap auth checks.
app.add_middleware(AuthRequiredMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET_KEY", "dev-insecure-change-me"),
    same_site=os.getenv("SESSION_SAME_SITE", "lax"),
    https_only=os.getenv("SESSION_HTTPS_ONLY", "false").strip().lower() in ("1", "true", "yes", "on"),
)


@app.middleware("http")
async def subscription_context_middleware(request: Request, call_next):
    """Attach subscription context and soft-lock write actions after trial expiry."""
    path = request.url.path
    public_prefixes = ("/static",)
    public_paths = {
        "/login",
        "/signup",
        "/forgot-password",
        "/reset-password",
        "/health",
        "/favicon.ico",
    }
    if path in public_paths or path.startswith(public_prefixes):
        return await call_next(request)

    user_id = request.session.get("user_id")
    summary = SubscriptionService().get_summary(int(user_id)) if user_id else {}
    request.state.subscription = summary

    exempt_write_paths = {
        "/logout",
        "/oauth/google/disconnect",
    }
    if (
        request.method not in {"GET", "HEAD", "OPTIONS"}
        and user_id
        and summary
        and not summary.get("write_allowed", False)
        and path not in exempt_write_paths
    ):
        params = urlencode({"error": summary.get("banner_message") or "Your trial has ended."})
        return RedirectResponse(url=f"/billing?{params}", status_code=303)

    return await call_next(request)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Attach request id for traceability and include it in responses."""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.middleware("http")
async def overdue_status_middleware(request: Request, call_next):
    """Refresh overdue invoice statuses before handling requests."""
    try:
        InvoiceService().update_overdue_statuses()
    except Exception:
        pass
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Render a friendly error page with a request id."""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    print(
        f"[ERROR] request_id={request_id} path={request.url.path} error={exc}\n"
        f"{traceback.format_exc()}"
    )
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "request_id": request_id,
            "error_message": "An unexpected error occurred. Please try again.",
        },
        status_code=500,
    )


async def _reminder_worker():
    """Background worker for periodic overdue reminders."""
    interval_seconds = int(os.getenv("REMINDER_RUN_INTERVAL_SECONDS", "3600"))
    startup_delay_seconds = int(os.getenv("REMINDER_STARTUP_DELAY_SECONDS", "30"))
    if startup_delay_seconds > 0:
        await asyncio.sleep(startup_delay_seconds)
    while True:
        try:
            ReminderService().process_due_reminders(limit=100)
        except Exception:
            pass
        await asyncio.sleep(max(60, interval_seconds))


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page."""
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/health")
async def health_check():
    """Health check endpoint with a real DB connectivity probe."""
    db_exists = config.DB_PATH.exists()
    db_connected = False
    error = None

    if db_exists:
        try:
            with sqlite3.connect(config.DB_PATH) as conn:
                conn.execute("SELECT 1")
            db_connected = True
        except sqlite3.Error as exc:
            error = str(exc)

    return {
        "status": "healthy" if db_connected else "unhealthy",
        "database_file_exists": db_exists,
        "database_connected": db_connected,
        "database_path": str(config.DB_PATH),
        "error": error,
    }


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Redirect default favicon path to static asset."""
    return RedirectResponse(url="/static/favicon.svg")
