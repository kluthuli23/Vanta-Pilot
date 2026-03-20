# services/email_service.py - COMPLETE FIXED VERSION
import os
import re
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict
import logging
import time
from email import policy

from services.business_profile_service import BusinessProfileService

# Optional: for HTML templates
try:
    from jinja2 import Template, Environment, FileSystemLoader
    JINJA_AVAILABLE = True
except ImportError:
    JINJA_AVAILABLE = False
    print("⚠️  Jinja2 not installed. Install with: pip install jinja2")

try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False

class EmailService:
    """Professional email service for sending invoices."""
    _templates_initialized = False
    
    def __init__(self, config_file=None):
        """Initialize email service with configuration."""
        if DOTENV_AVAILABLE:
            load_dotenv()
        self.config = self._load_config(config_file)
        self.logger = logging.getLogger(__name__)
        self.last_error: Optional[str] = None
        
        # Setup email templates
        self.template_dir = Path(__file__).parent.parent / "templates" / "email"
        self.template_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_templates()

    _smtp_session_passwords: Dict[int, Dict[str, float]] = {}
    _smtp_session_ttl_seconds = 12 * 60 * 60

    def _ensure_templates(self):
        """Create templates only when missing (avoid rewriting every request)."""
        if EmailService._templates_initialized:
            return
        html_template = self.template_dir / "invoice.html"
        text_template = self.template_dir / "invoice.txt"
        if html_template.exists() and text_template.exists():
            EmailService._templates_initialized = True
            return
        self._create_clean_templates()
        EmailService._templates_initialized = True
    
    def _load_config(self, config_file):
        """Load email configuration from file or environment."""
        raw_password = os.getenv('SMTP_PASSWORD', '')
        normalized_password = raw_password.replace(' ', '')
        use_tls_env = os.getenv('SMTP_USE_TLS', os.getenv('USE_TLS', 'True'))

        config = {
            'smtp_server': os.getenv('SMTP_SERVER', 'smtp.gmail.com'),
            'smtp_port': int(os.getenv('SMTP_PORT', 587)),
            'smtp_username': os.getenv('SMTP_USERNAME', ''),
            'smtp_password': normalized_password,
            'from_email': os.getenv('FROM_EMAIL', 'invoices@yourcompany.com'),
            'from_name': os.getenv('FROM_NAME', 'Vanta Pilot'),
            'use_tls': use_tls_env.lower() == 'true',
            'use_ssl': os.getenv('SMTP_USE_SSL', 'False').lower() == 'true'
        }
        
        # Load from file if provided
        if config_file and Path(config_file).exists():
            import json
            with open(config_file, 'r') as f:
                file_config = json.load(f)
                config.update(file_config)
        
        return config

    def _validate_smtp_config(self, cfg: Dict) -> bool:
        """Validate SMTP settings before attempting to send."""
        required = ['smtp_server', 'smtp_port', 'smtp_username', 'smtp_password']
        missing = [key for key in required if not cfg.get(key)]
        if missing:
            self.last_error = (
                "Missing SMTP configuration: " + ", ".join(missing)
            )
            print(
                "❌ Missing SMTP configuration: "
                + ", ".join(missing)
                + ". Set environment variables and try again."
            )
            return False

        if not cfg.get("from_email"):
            cfg["from_email"] = cfg.get("smtp_username", "")

        if cfg.get('from_email', 'invoices@yourcompany.com') == 'invoices@yourcompany.com':
            # Default sender is a placeholder and causes provider rejection.
            cfg['from_email'] = cfg['smtp_username']

        return True

    def get_last_error(self) -> Optional[str]:
        return self.last_error
    
    def _create_clean_templates(self):
        """Create clean email templates with NO custom filters."""
        
        # HTML Template - CLEAN
        html_content = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body { font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; }
        .header { text-align: center; border-bottom: 2px solid #3498db; padding: 20px; }
        .invoice-title { color: #2c3e50; font-size: 24px; }
        .customer-info { background: #f8f9fa; padding: 15px; margin: 20px 0; }
        table { width: 100%; border-collapse: collapse; }
        th { background: #34495e; color: white; padding: 10px; text-align: left; }
        td { padding: 10px; border-bottom: 1px solid #ddd; }
        .total { font-size: 20px; color: #27ae60; font-weight: bold; text-align: right; }
        .footer { margin-top: 30px; border-top: 1px solid #ddd; padding: 20px; text-align: center; font-size: 12px; color: #7f8c8d; }
    </style>
</head>
<body>
    <div class="header">
        <h1 class="invoice-title">Invoice {{ invoice_number }}</h1>
        <p>Date: {{ invoice_date }} | Due: {{ due_date }}</p>
    </div>

    <p style="margin: 18px 0 8px 0; color:#2c3e50;">
        Hi {{ greeting_name }},
    </p>
    <p style="margin: 0 0 18px 0; color:#2c3e50;">
        {{ intro_message }}
    </p>
    
    <div class="customer-info">
        <strong>Bill To:</strong><br>
        {{ customer_name }}<br>
        {% if customer_company %}{{ customer_company }}<br>{% endif %}
        {{ customer_email }}<br>
        {% if customer_phone %}{{ customer_phone }}{% endif %}
    </div>
    
    <table>
        <thead>
            <tr>
                <th>Description</th>
                <th>Qty</th>
                <th>Unit Price</th>
                <th>Total</th>
            </tr>
        </thead>
        <tbody>
            {% for item in items %}
            <tr>
                <td>{{ item.description }}</td>
                <td>{{ item.quantity }}</td>
                <td>R {{ "%.2f"|format(item.unit_price) }}</td>
                <td>R {{ "%.2f"|format(item.total) }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    
    <div class="total">
        <p>Subtotal: R {{ "%.2f"|format(subtotal) }}</p>
        {% if vat and vat > 0 %}
        <p>VAT: R {{ "%.2f"|format(vat) }}</p>
        {% endif %}
        <p style="font-size: 24px;">Total: R {{ "%.2f"|format(total) }}</p>
    </div>
    
    {% if payment_link %}
    <div style="text-align: center; margin: 30px 0;">
        <a href="{{ payment_link }}" style="background: #3498db; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px;">Pay Online</a>
    </div>
    {% endif %}
    
    <div class="footer">
        <p>{{ company_name }} | {{ company_email }} | {{ company_phone }}</p>
        <p>{{ company_address }}</p>
        {% if company_vat %}<p>VAT: {{ company_vat }}</p>{% endif %}
        <p>© {{ year }} {{ company_name }}</p>
    </div>
</body>
</html>"""
        
        # Text Template - CLEAN
        text_content = """=====================================
INVOICE {{ invoice_number }}
=====================================
Date: {{ invoice_date }}
Due Date: {{ due_date }}

BILL TO:
{{ customer_name }}
{% if customer_company %}{{ customer_company }}{% endif %}
{{ customer_email }}
{% if customer_phone %}{{ customer_phone }}{% endif %}

Hi {{ greeting_name }},
{{ intro_message }}

ITEMS:
=====================================
{% for item in items %}
{{ item.description }} - Qty: {{ item.quantity }} @ R {{ "%.2f"|format(item.unit_price) }} = R {{ "%.2f"|format(item.total) }}
{% endfor %}
=====================================
Subtotal: R {{ "%.2f"|format(subtotal) }}
{% if vat and vat > 0 %}VAT: R {{ "%.2f"|format(vat) }}{% endif %}
TOTAL: R {{ "%.2f"|format(total) }}
=====================================

{% if payment_link %}Pay online: {{ payment_link }}{% endif %}

=====================================
{{ company_name }}
{{ company_address }}
Email: {{ company_email }}
Phone: {{ company_phone }}
{% if company_vat %}VAT: {{ company_vat }}{% endif %}
=====================================
"""
        
        # Write templates
        (self.template_dir / "invoice.html").write_text(html_content)
        (self.template_dir / "invoice.txt").write_text(text_content)
        
        print("✅ Created clean email templates")
    
    def _resolve_sender_identity(
        self,
        business_profile: Optional[Dict] = None,
        runtime_cfg: Optional[Dict] = None,
    ) -> Dict[str, str]:
        """Resolve sender identity using tenant profile first, then global config."""
        profile = business_profile or {}
        cfg = runtime_cfg or self.config
        business_name = (profile.get("business_name") or "").strip()
        business_email = (profile.get("business_email") or "").strip().lower()
        business_phone = (profile.get("business_phone") or "").strip()
        business_address = (profile.get("business_address") or "").strip()
        raw_vat = str((profile.get("vat_number") or "")).strip()
        vat_digits = re.sub(r"\D", "", raw_vat)
        business_vat = vat_digits if len(vat_digits) == 10 else ""

        sender_name = business_name or cfg.get("from_name", "Vanta Pilot")
        smtp_from_email = cfg.get("from_email", "") or cfg.get("smtp_username", "")
        reply_to_email = business_email or smtp_from_email

        return {
            "sender_name": sender_name,
            "smtp_from_email": smtp_from_email,
            "reply_to_email": reply_to_email,
            "company_name": sender_name,
            "company_email": reply_to_email,
            "company_phone": business_phone,
            "company_address": business_address,
            "company_vat": business_vat,
        }

    def _first_name(self, full_name: str) -> str:
        text = (full_name or "").strip()
        if not text:
            return "there"
        return text.split()[0]

    def _runtime_config_from_profile(self, business_profile: Optional[Dict] = None) -> Dict:
        """Build effective SMTP config using profile overrides when provided."""
        if business_profile:
            cfg = {
                "smtp_server": "",
                "smtp_port": 587,
                "smtp_username": "",
                "smtp_password": "",
                "from_email": "",
                "from_name": "Vanta Pilot",
                "use_tls": True,
                "use_ssl": False,
            }
        else:
            cfg = dict(self.config)
        profile = business_profile or {}
        user_id = profile.get("user_id")
        if profile.get("smtp_server"):
            cfg["smtp_server"] = str(profile.get("smtp_server")).strip()
        if profile.get("smtp_port"):
            try:
                cfg["smtp_port"] = int(profile.get("smtp_port"))
            except (TypeError, ValueError):
                pass
        if profile.get("smtp_username"):
            cfg["smtp_username"] = str(profile.get("smtp_username")).strip()
        if profile.get("smtp_password"):
            stored_password = BusinessProfileService(str(self.template_dir.parent.parent / "data" / "business.db")).decrypt_smtp_password(
                str(profile.get("smtp_password"))
            )
            cfg["smtp_password"] = stored_password
        elif user_id is not None:
            cached = self._smtp_session_passwords.get(int(user_id))
            if cached and cached.get("expires_at", 0) > time.time():
                cfg["smtp_password"] = str(cached.get("password") or "")
            elif cached:
                self._smtp_session_passwords.pop(int(user_id), None)
        if profile.get("smtp_from_email"):
            cfg["from_email"] = str(profile.get("smtp_from_email")).strip().lower()
        if profile.get("smtp_use_tls") is not None:
            cfg["use_tls"] = bool(profile.get("smtp_use_tls"))
        if profile.get("smtp_use_ssl") is not None:
            cfg["use_ssl"] = bool(profile.get("smtp_use_ssl"))
        if profile.get("business_name"):
            cfg["from_name"] = str(profile.get("business_name")).strip()
        return cfg

    def is_user_smtp_authenticated(self, user_id: Optional[int]) -> bool:
        """Check if user has either a stored or active SMTP auth credential."""
        if user_id is None:
            return False
        profile = BusinessProfileService(str(self.template_dir.parent.parent / "data" / "business.db")).get_profile(int(user_id))
        if profile and profile.get("smtp_password"):
            decrypted = BusinessProfileService(str(self.template_dir.parent.parent / "data" / "business.db")).decrypt_smtp_password(
                str(profile.get("smtp_password"))
            )
            if decrypted:
                return True
        cached = self._smtp_session_passwords.get(int(user_id))
        if not cached:
            return False
        if cached.get("expires_at", 0) <= time.time():
            self._smtp_session_passwords.pop(int(user_id), None)
            return False
        return True

    def clear_user_smtp_auth(self, user_id: Optional[int]) -> None:
        """Clear cached and stored SMTP auth for a user."""
        if user_id is None:
            return
        self._smtp_session_passwords.pop(int(user_id), None)
        BusinessProfileService(str(self.template_dir.parent.parent / "data" / "business.db")).clear_smtp_password(int(user_id))

    def authorize_user_smtp(self, user_id: int, business_profile: Dict, smtp_password: str) -> bool:
        """Validate SMTP credentials and store password encrypted for reuse."""
        runtime_cfg = self._runtime_config_from_profile(business_profile)
        runtime_cfg["smtp_password"] = (smtp_password or "").strip()
        if not self._validate_smtp_config(runtime_cfg):
            return False

        try:
            if runtime_cfg["use_ssl"]:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(
                    runtime_cfg["smtp_server"],
                    runtime_cfg["smtp_port"],
                    context=context,
                ) as server:
                    server.login(runtime_cfg["smtp_username"], runtime_cfg["smtp_password"])
            else:
                with smtplib.SMTP(runtime_cfg["smtp_server"], runtime_cfg["smtp_port"]) as server:
                    if runtime_cfg["use_tls"]:
                        server.starttls()
                    server.login(runtime_cfg["smtp_username"], runtime_cfg["smtp_password"])
        except Exception as e:
            self.logger.error("SMTP auth test failed for user %s: %s", user_id, e)
            return False

        self._smtp_session_passwords[int(user_id)] = {
            "password": runtime_cfg["smtp_password"],
            "expires_at": time.time() + self._smtp_session_ttl_seconds,
        }
        if not BusinessProfileService(str(self.template_dir.parent.parent / "data" / "business.db")).store_smtp_password(
            int(user_id),
            runtime_cfg["smtp_password"],
        ):
            self.last_error = "SMTP connected, but failed to store the encrypted credential."
            return False
        return True

    def send_invoice(
        self,
        to_email: str,
        to_name: str,
        invoice_data: dict,
        pdf_path: Path,
        payment_link: str = None,
        cc: List[str] = None,
        bcc: List[str] = None,
        business_profile: Optional[Dict] = None,
    ) -> bool:
        """Send invoice email with PDF attachment."""
        try:
            self.last_error = None
            runtime_cfg = self._runtime_config_from_profile(business_profile)

            # Root must be multipart/mixed for reliable attachment delivery.
            msg = MIMEMultipart('mixed')
            body_part = MIMEMultipart('alternative')
            sender = self._resolve_sender_identity(business_profile, runtime_cfg=runtime_cfg)
            oauth_user_id = int((business_profile or {}).get("user_id") or 0)
            oauth_connected = False
            oauth_email = ""
            if oauth_user_id:
                from services.oauth_service import OAuthService
                oauth_conn = OAuthService().get_google_connection(oauth_user_id)
                if oauth_conn:
                    oauth_connected = True
                    oauth_email = (oauth_conn.get("provider_account_email") or "").strip().lower()
            if oauth_connected and oauth_email:
                sender["smtp_from_email"] = oauth_email
                sender["company_email"] = oauth_email
            elif not self._validate_smtp_config(runtime_cfg):
                return False
            msg['Subject'] = f"Invoice {invoice_data['invoice_number']} from {sender['sender_name']}"
            msg['From'] = f"{sender['sender_name']} <{sender['smtp_from_email']}>"
            if sender["reply_to_email"]:
                msg['Reply-To'] = sender["reply_to_email"]
            msg['To'] = f"{to_name} <{to_email}>"
            
            if cc:
                msg['Cc'] = ', '.join(cc)
            if bcc:
                msg['Bcc'] = ', '.join(bcc)
            
            # Prepare template data
            template_data = {
                'invoice_number': invoice_data['invoice_number'],
                'invoice_date': invoice_data['invoice_date'],
                'due_date': invoice_data.get('due_date', ''),
                'customer_name': to_name,
                'greeting_name': self._first_name(to_name),
                'customer_email': to_email,
                'customer_company': invoice_data.get('customer_company', ''),
                'customer_phone': invoice_data.get('customer_phone', ''),
                'items': invoice_data.get('items', []),
                'subtotal': invoice_data.get('subtotal', 0),
                'vat': invoice_data.get('tax_amount', 0),
                'total': invoice_data.get('total_amount', 0),
                'payment_link': payment_link or '',
                'invoice_link': f"file://{pdf_path}",
                'company_name': sender.get('company_name', ''),
                'company_email': sender.get('company_email', ''),
                'company_phone': sender.get('company_phone', ''),
                'company_address': sender.get('company_address', ''),
                'company_vat': sender.get('company_vat', ''),
                'year': datetime.now().year,
            }
            template_data['intro_message'] = (
                invoice_data.get('email_intro')
                or f"Please find invoice {template_data['invoice_number']} attached for your attention."
            )
            
            # Generate plain text version
            text_template = self.template_dir / "invoice.txt"
            if text_template.exists() and JINJA_AVAILABLE:
                template = Template(text_template.read_text())
                text_part = template.render(**template_data)
                body_part.attach(MIMEText(text_part, 'plain'))
            else:
                # Simple fallback
                text_part = self._simple_format(template_data)
                body_part.attach(MIMEText(text_part, 'plain'))
            
            # Generate HTML version
            html_template = self.template_dir / "invoice.html"
            if html_template.exists() and JINJA_AVAILABLE:
                template = Template(html_template.read_text())
                html_part = template.render(**template_data)
                body_part.attach(MIMEText(html_part, 'html'))

            msg.attach(body_part)
            
            # Attach PDF
            if pdf_path and pdf_path.exists():
                with open(pdf_path, 'rb') as f:
                    pdf_attachment = MIMEApplication(f.read(), _subtype='pdf')
                    pdf_attachment.add_header(
                        'Content-Disposition',
                        'attachment',
                        filename=pdf_path.name
                    )
                    msg.attach(pdf_attachment)

            if oauth_connected and oauth_user_id:
                from services.oauth_service import OAuthService
                ok, info = OAuthService().send_gmail_message(
                    oauth_user_id,
                    msg.as_bytes(policy=policy.SMTP),
                )
                if ok:
                    self.logger.info("✅ Invoice %s sent via Gmail API to %s", invoice_data['invoice_number'], to_email)
                    print(f"✅ Invoice sent successfully to {to_email}")
                    self._log_sent_email(to_email, invoice_data['invoice_number'], pdf_path)
                    return True
                self.logger.error("❌ Gmail API send failed: %s", info)
                print(f"❌ Failed to send email: {info}")
                self.last_error = info
                return False
            
            # Send email
            if runtime_cfg['use_ssl']:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(runtime_cfg['smtp_server'], 
                                      runtime_cfg['smtp_port'],
                                      context=context) as server:
                    if runtime_cfg['smtp_username']:
                        server.login(runtime_cfg['smtp_username'], 
                                    runtime_cfg['smtp_password'])
                    server.send_message(msg)
            else:
                with smtplib.SMTP(runtime_cfg['smtp_server'], 
                                 runtime_cfg['smtp_port']) as server:
                    if runtime_cfg['use_tls']:
                        server.starttls()
                    if runtime_cfg['smtp_username']:
                        server.login(runtime_cfg['smtp_username'], 
                                    runtime_cfg['smtp_password'])
                    server.send_message(msg)
            
            self.logger.info(f"✅ Invoice {invoice_data['invoice_number']} sent to {to_email}")
            print(f"✅ Invoice sent successfully to {to_email}")
            self._log_sent_email(to_email, invoice_data['invoice_number'], pdf_path)
            return True
            
        except Exception as e:
            self.last_error = str(e)
            self.logger.error(f"❌ Failed to send email: {e}")
            print(f"❌ Failed to send email: {e}")
            import traceback
            traceback.print_exc()
            return False

    def send_payment_reminder(
        self,
        to_email: str,
        to_name: str,
        invoice_number: str,
        due_date: str,
        balance_due: float,
        days_overdue: int,
        pdf_path: Path = None,
        business_profile: Optional[Dict] = None,
    ) -> bool:
        """Send overdue payment reminder email."""
        try:
            self.last_error = None
            runtime_cfg = self._runtime_config_from_profile(business_profile)

            sender = self._resolve_sender_identity(business_profile, runtime_cfg=runtime_cfg)
            oauth_user_id = int((business_profile or {}).get("user_id") or 0)
            oauth_connected = False
            oauth_email = ""
            if oauth_user_id:
                from services.oauth_service import OAuthService
                oauth_conn = OAuthService().get_google_connection(oauth_user_id)
                if oauth_conn:
                    oauth_connected = True
                    oauth_email = (oauth_conn.get("provider_account_email") or "").strip().lower()
            if oauth_connected and oauth_email:
                sender["smtp_from_email"] = oauth_email
                sender["company_email"] = oauth_email
            elif not self._validate_smtp_config(runtime_cfg):
                return False
            msg = MIMEMultipart("mixed")
            body_part = MIMEMultipart("alternative")
            msg["Subject"] = f"Payment Reminder: Invoice {invoice_number} is overdue"
            msg["From"] = f"{sender['sender_name']} <{sender['smtp_from_email']}>"
            if sender["reply_to_email"]:
                msg["Reply-To"] = sender["reply_to_email"]
            msg["To"] = f"{to_name} <{to_email}>"

            text_body = (
                f"Dear {to_name},\n\n"
                f"This is a reminder that invoice {invoice_number} is overdue.\n"
                f"Due date: {due_date}\n"
                f"Days overdue: {days_overdue}\n"
                f"Outstanding balance: R {balance_due:,.2f}\n\n"
                "Please arrange payment at your earliest convenience.\n\n"
                f"{sender['sender_name']}"
            )
            html_body = f"""
            <html>
              <body style="font-family: Arial, sans-serif;">
                <p>Dear {to_name},</p>
                <p>This is a reminder that invoice <strong>{invoice_number}</strong> is overdue.</p>
                <ul>
                  <li>Due date: {due_date}</li>
                  <li>Days overdue: {days_overdue}</li>
                  <li>Outstanding balance: <strong>R {balance_due:,.2f}</strong></li>
                </ul>
                <p>Please arrange payment at your earliest convenience.</p>
                <p>{sender['sender_name']}</p>
              </body>
            </html>
            """
            body_part.attach(MIMEText(text_body, "plain"))
            body_part.attach(MIMEText(html_body, "html"))
            msg.attach(body_part)

            if pdf_path and Path(pdf_path).exists():
                with open(pdf_path, "rb") as f:
                    pdf_attachment = MIMEApplication(f.read(), _subtype="pdf")
                    pdf_attachment.add_header(
                        "Content-Disposition",
                        "attachment",
                        filename=Path(pdf_path).name,
                    )
                    msg.attach(pdf_attachment)

            if oauth_connected and oauth_user_id:
                from services.oauth_service import OAuthService
                ok, info = OAuthService().send_gmail_message(
                    oauth_user_id,
                    msg.as_bytes(policy=policy.SMTP),
                )
                if ok:
                    self.logger.info("✅ Reminder sent via Gmail API for %s to %s", invoice_number, to_email)
                    return True
                self.logger.error("❌ Gmail API reminder send failed: %s", info)
                self.last_error = info
                return False

            if runtime_cfg["use_ssl"]:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(
                    runtime_cfg["smtp_server"], runtime_cfg["smtp_port"], context=context
                ) as server:
                    if runtime_cfg["smtp_username"]:
                        server.login(
                            runtime_cfg["smtp_username"],
                            runtime_cfg["smtp_password"],
                        )
                    server.send_message(msg)
            else:
                with smtplib.SMTP(
                    runtime_cfg["smtp_server"],
                    runtime_cfg["smtp_port"],
                ) as server:
                    if runtime_cfg["use_tls"]:
                        server.starttls()
                    if runtime_cfg["smtp_username"]:
                        server.login(
                            runtime_cfg["smtp_username"],
                            runtime_cfg["smtp_password"],
                        )
                    server.send_message(msg)

            self.logger.info("✅ Reminder sent for %s to %s", invoice_number, to_email)
            return True
        except Exception as e:
            self.last_error = str(e)
            self.logger.error("❌ Failed to send reminder email: %s", e)
            return False
    
    def _simple_format(self, data):
        """Simple text formatter when Jinja2 not available."""
        lines = []
        lines.append("=" * 50)
        lines.append(f"INVOICE {data['invoice_number']}")
        lines.append("=" * 50)
        lines.append(f"Date: {data['invoice_date']}")
        lines.append(f"Due: {data['due_date']}")
        lines.append("")
        lines.append(f"To: {data['customer_name']}")
        if data['customer_company']:
            lines.append(f"Company: {data['customer_company']}")
        lines.append(f"Email: {data['customer_email']}")
        lines.append("")
        lines.append(f"Hi {data.get('greeting_name', data.get('customer_name', 'there'))},")
        lines.append(data.get('intro_message', 'Please find your invoice attached for your attention.'))
        lines.append("")
        lines.append("ITEMS:")
        lines.append("-" * 50)
        for item in data['items']:
            lines.append(f"{item['description'][:40]} - Qty: {item['quantity']} @ R {item['unit_price']:.2f} = R {item['total']:.2f}")
        lines.append("-" * 50)
        lines.append(f"Subtotal: R {data['subtotal']:.2f}")
        if float(data.get('vat', 0) or 0) > 0:
            lines.append(f"VAT: R {data['vat']:.2f}")
        lines.append(f"TOTAL: R {data['total']:.2f}")
        lines.append("=" * 50)
        return '\n'.join(lines)
    
    def _log_sent_email(self, to_email, invoice_number, pdf_path):
        """Log sent email for history."""
        log_dir = Path(__file__).parent.parent / "logs" / "emails"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = log_dir / f"{datetime.now().strftime('%Y%m')}_email_log.csv"
        
        import csv
        file_exists = log_file.exists()
        
        with open(log_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['Date', 'Time', 'To', 'Invoice', 'PDF', 'Status'])
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d'),
                datetime.now().strftime('%H:%M:%S'),
                to_email,
                invoice_number,
                str(pdf_path),
                'Sent'
            ])

def test_email_service():
    """Test email service with sample data."""
    print("=" * 60)
    print("📧 Testing Email Service")
    print("=" * 60)
    
    service = EmailService()
    
    # Sample data
    invoice_data = {
        'invoice_number': 'INV-20260214-001',
        'invoice_date': '2026-02-14',
        'due_date': '2026-03-16',
        'customer_company': 'KN Solutions',
        'customer_phone': '0123456789',
        'subtotal': 14600.00,
        'tax_amount': 2190.00,
        'total_amount': 16790.00,
        'items': [
            {'description': 'Web Design', 'quantity': 1, 'unit_price': 4500.00, 'total': 5175.00},
            {'description': 'Hosting (12 months)', 'quantity': 12, 'unit_price': 150.00, 'total': 2070.00}
        ]
    }
    
    # Show what would be sent
    print("\n📝 Email content (text version):")
    print(service._simple_format({
        'invoice_number': invoice_data['invoice_number'],
        'invoice_date': invoice_data['invoice_date'],
        'due_date': invoice_data['due_date'],
        'customer_name': 'Khwezi Ngcobo',
        'customer_email': 'khwezi@example.com',
        'customer_company': invoice_data['customer_company'],
        'items': invoice_data['items'],
        'subtotal': invoice_data['subtotal'],
        'vat': invoice_data['tax_amount'],
        'total': invoice_data['total_amount']
    }))
    
    print("\n✅ Email service ready!")
    print("   To send real emails, configure SMTP in .env file")
    print("=" * 60)

if __name__ == "__main__":
    test_email_service()
