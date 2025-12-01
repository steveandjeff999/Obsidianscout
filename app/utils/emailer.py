import os
import json
from flask import current_app
from flask_mail import Mail, Message
import smtplib
import socket


def _config_path():
    inst = getattr(current_app, 'instance_path', None) or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'instance')
    return os.path.join(current_app.instance_path, 'email_config.json')


def _ensure_folder():
    path = current_app.instance_path
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def load_email_config():
    _ensure_folder()
    p = _config_path()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_email_config(cfg):
    _ensure_folder()
    p = _config_path()
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)


def validate_smtp(cfg, timeout=10):
    """Attempt to connect and login to the SMTP server using the provided cfg.

    cfg: dict with keys host, port, username, password, use_tls, use_ssl
    Returns (ok: bool, message: str)
    """
    host = cfg.get('host')
    port = cfg.get('port')
    username = cfg.get('username')
    password = cfg.get('password')
    use_tls = bool(cfg.get('use_tls'))
    use_ssl = bool(cfg.get('use_ssl'))

    if not host:
        return False, 'No SMTP host configured'

    try:
        port_num = int(port) if port else (465 if use_ssl else 587)
    except Exception:
        port_num = int(port) if port and str(port).isdigit() else (465 if use_ssl else 587)

    try:
        if use_ssl:
            smtp = smtplib.SMTP_SSL(host, port_num, timeout=timeout)
        else:
            smtp = smtplib.SMTP(host, port_num, timeout=timeout)
        smtp.ehlo()
        if use_tls and not use_ssl:
            smtp.starttls()
            smtp.ehlo()
        if username:
            smtp.login(username, password or '')
        smtp.quit()
        return True, 'OK'
    except smtplib.SMTPAuthenticationError as e:
        return False, f'SMTP auth failed: {e.smtp_code} {e.smtp_error.decode() if isinstance(e.smtp_error, bytes) else e.smtp_error}'
    except (smtplib.SMTPException, socket.error) as e:
        return False, f'SMTP error: {type(e).__name__}: {e}'
    except Exception as e:
        return False, f'Unknown error: {type(e).__name__}: {e}'


def _ensure_mail_extension():
    """Ensure Flask-Mail is initialized on the current app and return the Mail instance."""
    # Try to reuse an existing initialized Mail instance stored in app.extensions
    mail = current_app.extensions.get('flask-mail') if hasattr(current_app, 'extensions') else None
    if mail:
        return mail

    # Create Mail instance and store it on app.extensions for reuse
    mail = Mail(current_app)
    if not hasattr(current_app, 'extensions'):
        current_app.extensions = {}
    current_app.extensions['flask-mail'] = mail
    return mail


def _build_html_email(subject, body, from_addr=None, to_list=None):
        """Return a simple, clean HTML wrapper for plaintext email bodies.

        Keeps inline styles simple and preserves paragraphs/newlines.
        """
        brand = current_app.config.get('APP_NAME') or 'ObsidianScout'
        preheader = ''
        body_str = str(body or '')
        try:
            # Find the first non-empty line to use as preheader
            lines = [l for l in body_str.splitlines() if l.strip()]
            preheader = lines[0][:120] if lines else ''
        except Exception:
            preheader = ''

        # Remove the preheader line from the main body to avoid visible duplication
        body_content = body_str
        if preheader and body_str.startswith(preheader):
            body_content = body_str[len(preheader):].lstrip('\n')

        # Turn double-newline separated paragraphs into <p>, single newlines -> <br>
        parts = []
        if body_content:
            for para in body_content.split('\n\n'):
                safe_para = para.replace('\n', '<br>')
                parts.append(f"<p style=\"margin:0 0 1rem 0;line-height:1.5;color:#333;\">{safe_para}</p>")
        content_html = '\n'.join(parts) if parts else ''

        footer_email = from_addr or current_app.config.get('MAIL_DEFAULT_SENDER') or ''
        recipients = ', '.join(to_list) if to_list else ''

        html = f"""
<!doctype html>
<html>
    <head>
        <meta charset=\"utf-8\"> 
        <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"> 
        <title>{subject}</title>
    </head>
    <body style=\"font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background:#f6f7fb; margin:0; padding:20px;\">
        <div style=\"max-width:680px;margin:0 auto;background:#ffffff;border-radius:8px;overflow:hidden;border:1px solid #e6e9ef;\">
            <div style=\"padding:18px 24px;background:linear-gradient(90deg,#1f2937,#374151);color:#fff\">
                <h1 style=\"margin:0;font-size:18px;font-weight:600;\">{brand}</h1>
                <div style=\"font-size:13px;opacity:0.9\">{subject}</div>
            </div>
            <div style=\"padding:20px 24px;color:#111;\">
                <div style=\"font-size:14px;margin-bottom:8px;color:#555;\">{preheader}</div>
                {content_html}
            </div>
            <div style=\"padding:12px 24px;background:#fafafa;border-top:1px solid #f0f0f3;font-size:12px;color:#666;\">
                <div>From: {footer_email}</div>
                <div style=\"margin-top:6px;color:#999;font-size:11px\">This message was sent to: {recipients}</div>
            </div>
        </div>
    </body>
</html>
"""
        return html


def send_email(to, subject, body, html=None, from_addr=None, bypass_user_opt_out=False):
    """Send an email using Flask-Mail configured from instance/email_config.json.

    `to` may be a string or list of addresses.
    Returns (success: bool, message: str)
    """
    cfg = load_email_config()
    if not cfg or not cfg.get('host'):
        return False, 'Email not configured'

    # Map file-backed config into Flask-Mail app.config keys (overwrite to ensure latest values)
    host = (cfg.get('host') or '').strip()
    port_val = cfg.get('port')
    username_val = (cfg.get('username') or '').strip()
    password_val = (cfg.get('password') or '').strip()
    use_tls_val = bool(cfg.get('use_tls'))
    use_ssl_val = bool(cfg.get('use_ssl'))
    default_from_val = (cfg.get('default_from') or cfg.get('from_addr') or cfg.get('username') or '').strip()

    current_app.config['MAIL_SERVER'] = host
    try:
        current_app.config['MAIL_PORT'] = int(port_val) if port_val is not None and str(port_val) != '' else (465 if use_ssl_val else 587)
    except Exception:
        current_app.config['MAIL_PORT'] = port_val
    current_app.config['MAIL_USERNAME'] = username_val
    current_app.config['MAIL_PASSWORD'] = password_val
    current_app.config['MAIL_USE_TLS'] = use_tls_val
    current_app.config['MAIL_USE_SSL'] = use_ssl_val
    current_app.config['MAIL_DEFAULT_SENDER'] = default_from_val or username_val

    # Log masked diagnostic info (do not log passwords)
    try:
        masked_user = username_val[:2] + '...' + username_val[-2:] if username_val and len(username_val) > 4 else username_val
        pwd_info = f'len={len(password_val)}' if password_val is not None else 'not set'
        current_app.logger.info(f"SMTP send: host={host}, port={current_app.config.get('MAIL_PORT')}, user={masked_user}, pwd={pwd_info}, TLS={use_tls_val}, SSL={use_ssl_val}")
    except Exception:
        pass

    # Prepare recipients list
    if isinstance(to, str):
        recipients = [to]
    else:
        recipients = list(to)

    # Respect per-user opt-out: if a user has set `only_password_reset_emails`, they should
    # not receive general emails; this applies unless caller explicitly sets `bypass_user_opt_out=True`.
    try:
        if not bypass_user_opt_out and recipients:
            from app.models import User
            from app.utils import user_prefs as user_prefs_util
            # Query users who are in recipients and check their preferences
            try:
                from app import db
                from sqlalchemy import inspect as sa_inspect
                try:
                    inspector = sa_inspect(db.get_engine(current_app))
                    cols = [c['name'] for c in inspector.get_columns('user')] if 'user' in inspector.get_table_names() else []
                except Exception:
                    cols = []
                if 'only_password_reset_emails' in cols:
                    rows = User.query.filter(User.email.in_(recipients)).with_entities(User.username, User.email, User.only_password_reset_emails).all()
                else:
                    rows = User.query.filter(User.email.in_(recipients)).with_entities(User.username, User.email).all()
                excluded = set()
                for row in rows:
                    try:
                        if len(row) == 3:
                            uname, email, only_pw = row
                            if only_pw:
                                excluded.add(email)
                                continue
                        else:
                            uname, email = row
                        if user_prefs_util.get_pref(uname, 'only_password_reset_emails', False):
                            excluded.add(email)
                    except Exception:
                        pass
            except Exception:
                excluded = set()
            if excluded:
                recipients = [r for r in recipients if r not in excluded]
                try:
                    current_app.logger.info('Excluded %d recipient(s) due to only_password_reset_emails opt-out', len(excluded))
                except Exception:
                    pass
            if not recipients:
                return False, 'No recipients (all opted out)'
    except Exception:
        # If something goes wrong with phonebook/user query, fail open and continue with original recipients.
        pass

    # If caller didn't provide html, create a simple styled html alternative
    if not html and body:
        try:
            html = _build_html_email(subject, body, from_addr=from_addr or current_app.config.get('MAIL_DEFAULT_SENDER'), to_list=recipients)
        except Exception:
            html = None

    # Create Mail instance (or reuse) and send message
    try:
        mail = _ensure_mail_extension()
        msg = Message(subject=subject,
                      recipients=recipients,
                      body=body,
                      sender=from_addr or current_app.config.get('MAIL_DEFAULT_SENDER'))
        if html:
            msg.html = html
        mail.send(msg)
        return True, 'Email sent'
    except Exception as e:
        # Return exception type and message for clearer diagnostics
        # Also log exception with traceback to app logger (without printing password)
        try:
            current_app.logger.error('SMTP send failed: %s: %s', type(e).__name__, e, exc_info=True)
        except Exception:
            pass
        return False, f'{type(e).__name__}: {e}'
