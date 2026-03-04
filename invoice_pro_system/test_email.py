# test_email.py
from services.email_service import EmailService

s = EmailService()
print(' Testing email configuration...')
print(f'From: {s.config["from_email"]}')
print(f'SMTP Server: {s.config["smtp_server"]}:{s.config["smtp_port"]}')
print(f'Password length: {len(s.config["smtp_password"])} characters')
print(f'TLS Enabled: {s.config["use_tls"]}')

if s.config["from_email"] != "invoices@yourcompany.com":
    print(' Configuration looks good!')
else:
    print('  Using default email - check your .env file')
