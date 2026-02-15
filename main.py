from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file, Response, abort
from flask_sqlalchemy import SQLAlchemy
import os
import re
import io
import time
from werkzeug.security import generate_password_hash as wz_generate_password_hash, check_password_hash as wz_check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
try:
    from flask_bcrypt import Bcrypt
except ImportError:
    class Bcrypt:  # type: ignore[override]
        """Fallback bcrypt-compatible wrapper using Werkzeug hashing."""
        def __init__(self, app=None):
            self.app = app

        def generate_password_hash(self, password):
            return wz_generate_password_hash(password).encode('utf-8')

        def check_password_hash(self, pw_hash, password):
            if isinstance(pw_hash, bytes):
                pw_hash = pw_hash.decode('utf-8')
            return wz_check_password_hash(str(pw_hash), password)
try:
    from dotenv import load_dotenv
    project_dir = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(project_dir, '.env'))  # Prefer project-local .env
    load_dotenv(os.path.join(project_dir, '.env.local'))  # Optional local override
    load_dotenv()  # Fallback to default dotenv discovery
except ImportError:
    pass  # python-dotenv not installed, use environment variables only
import secrets 
import smtplib
from datetime import datetime, timedelta, timezone
from email.header import Header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from typing import Any, Callable, List, Optional
from xml.sax.saxutils import escape as xml_escape
import base64

# ===== FLASK APP SETUP =====
app = Flask(__name__, static_folder='Static')
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)  # type: ignore[assignment]

is_production = os.environ.get("RENDER", "").lower() == "true" or os.environ.get("ENVIRONMENT", "").lower() == "production"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=is_production,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,  # 5 MB max request size
    SEND_FILE_MAX_AGE_DEFAULT=86400,  # 1 day static cache
    PREFERRED_URL_SCHEME='https',
)

SITE_URL = os.environ.get('SITE_URL', os.environ.get('RENDER_EXTERNAL_URL', '')).strip().rstrip('/')

# Database Configuration
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'site.db')
database_url = os.environ.get('DATABASE_URL', '').strip()
if database_url and '://' not in database_url:
    # Misconfigured DATABASE_URL (e.g., a secret token). Fall back to SQLite.
    app.logger.warning("Invalid DATABASE_URL format; falling back to SQLite.")
    database_url = ''
if database_url:
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
rate_limit_store: dict[str, list[float]] = {}

def get_csrf_token() -> str:
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token

def is_rate_limited(bucket: str, max_attempts: int, window_seconds: int) -> bool:
    now = time.time()
    recent = [t for t in rate_limit_store.get(bucket, []) if now - t < window_seconds]
    if len(recent) >= max_attempts:
        rate_limit_store[bucket] = recent
        return True
    recent.append(now)
    rate_limit_store[bucket] = recent
    return False

@app.before_request
def csrf_protect() -> None:
    if request.method in ('GET', 'HEAD', 'OPTIONS', 'TRACE'):
        return
    if request.path.startswith('/api/'):
        return
    session_token = session.get('_csrf_token')
    request_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not session_token or not request_token or not secrets.compare_digest(session_token, request_token):
        abort(400, description='Invalid CSRF token')

def get_base_url() -> str:
    """Return canonical site origin from env or request context."""
    if SITE_URL:
        return SITE_URL
    return request.url_root.rstrip('/')

@app.after_request
def apply_default_headers(response: Response) -> Response:
    """Apply baseline security and crawler directives."""
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    response.headers.setdefault('Cross-Origin-Opener-Policy', 'same-origin')
    response.headers.setdefault('Cross-Origin-Resource-Policy', 'same-origin')
    csp = (
        "default-src 'self'; "
        "img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "font-src 'self' https://cdnjs.cloudflare.com data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )
    response.headers.setdefault('Content-Security-Policy', csp)
    if is_production and request.is_secure:
        response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains; preload')

    noindex_exact_paths = {
        '/login',
        '/register',
        '/logout',
        '/forgot-password',
        '/change-password',
        '/messages',
    }
    noindex_prefixes = (
        '/dashboard',
        '/api/',
        '/add_',
        '/edit_',
        '/delete_',
        '/reset-password',
    )
    if response.status_code >= 400 or request.path in noindex_exact_paths or any(request.path.startswith(prefix) for prefix in noindex_prefixes):
        response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'

    sensitive_paths = (
        '/dashboard',
        '/messages',
        '/logout',
        '/login',
        '/register',
        '/forgot-password',
        '/change-password',
        '/reset-password',
        '/add_',
        '/edit_',
        '/delete_',
        '/api/new-messages',
    )
    is_sensitive = any(request.path.startswith(path) for path in sensitive_paths)
    if is_sensitive or session.get('logged_in'):
        # Prevent browser back button from showing cached authenticated pages after logout.
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0, private'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'

    return response

# ===== CONTEXT PROCESSOR - Make portfolio available to all templates =====
@app.context_processor
def inject_portfolio():
    """Make portfolio data available to all templates"""
    try:
        portfolio = Portfolio.query.first()
        return {
            'portfolio': portfolio,
            'admin_name': ADMIN_NAME,
            'csrf_token': get_csrf_token,
        }
    except:
        return {
            'portfolio': None,
            'admin_name': ADMIN_NAME,
            'csrf_token': get_csrf_token,
        }

# ===== EMAIL CONFIGURATION (Free SMTP - Gmail) =====
# Store these as environment variables in production
SENDER_EMAIL = (
    os.environ.get('SENDER_EMAIL')
    or os.environ.get('SMTP_USERNAME')
    or os.environ.get('EMAIL_USERNAME')
    or 'ajayprakashp59@gmail.com'
).strip()
# ⚠️ IMPORTANT: Replace with YOUR 16-CHARACTER GMAIL APP PASSWORD from https://myaccount.google.com/apppasswords
SENDER_PASSWORD = (
    os.environ.get('SENDER_PASSWORD')
    or os.environ.get('GMAIL_APP_PASSWORD')
    or os.environ.get('SMTP_PASSWORD')
    or os.environ.get('EMAIL_PASSWORD')
    or os.environ.get('APP_PASSWORD')
    or ''
).strip().replace(' ', '')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'ajayprakashp59@gmail.com')
ADMIN_PHONE = os.environ.get('ADMIN_PHONE', '8881254553')  # For WhatsApp/Contact
ADMIN_NAME = os.environ.get('ADMIN_NAME', 'Ajay Prakash')
ADMIN_GITHUB = os.environ.get('ADMIN_GITHUB', 'https://github.com/Ajay-Prakash-Pandey')
ADMIN_LINKEDIN = os.environ.get('ADMIN_LINKEDIN', 'https://www.linkedin.com/in/ajayprakashpandey')

# ===== DATABASE MODELS =====

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Password reset fields
    reset_token = db.Column(db.String(255), unique=True)
    reset_token_expiry = db.Column(db.DateTime)

class Portfolio(db.Model):
    """Store dynamic portfolio content"""
    id = db.Column(db.Integer, primary_key=True)
    hero_title = db.Column(db.String(255), default="Welcome to My Portfolio")
    hero_subtitle = db.Column(db.Text, default="Full Stack Developer | Creative Designer")
    about_title = db.Column(db.String(255), default="About Me")
    about_description = db.Column(db.Text, default="")
    profile_image = db.Column(db.Text)  # Path to profile image
    resume_url = db.Column(db.Text)  # Path to resume PDF
    phone = db.Column(db.String(20))
    whatsapp = db.Column(db.String(20))
    location = db.Column(db.String(255))
    github = db.Column(db.String(255))
    linkedin = db.Column(db.String(255))
    twitter = db.Column(db.String(255))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class Skill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    skill_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)  # NEW: Skill description
    proficiency = db.Column(db.Integer, nullable=False)  # 0-100
    category = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pname = db.Column(db.String(255), nullable=False)
    projectlink = db.Column(db.Text)
    projectDescripton = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class ServiceCard(db.Model):
    """Homepage cards for 'What I Can Bring to Your Team'."""
    id = db.Column(db.Integer, primary_key=True)
    icon_class = db.Column(db.String(100), nullable=False, default='fas fa-star')
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class WhyHireItem(db.Model):
    """Homepage cards for 'Why Hire a Fresher Like Me?'."""
    id = db.Column(db.Integer, primary_key=True)
    icon_class = db.Column(db.String(100), nullable=False, default='fas fa-check')
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

# ===== DECORATORS =====

def login_required(f: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        if 'logged_in' not in session:
            flash('Please log in first', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ===== EMAIL UTILITIES (FREE - SMTP) =====

def send_email(to_email: str, subject: str, html_content: str) -> bool:
    """Email sending disabled to avoid SMTP failures on free hosting."""
    # Original Gmail SMTP implementation (kept for reference):
    # try:
    #     if not SENDER_EMAIL or not SENDER_PASSWORD:
    #         app.logger.error("Email credentials missing. Set SENDER_EMAIL and SENDER_PASSWORD.")
    #         return False
    #     if "your_16_character_app_password_here" in SENDER_PASSWORD.lower():
    #         app.logger.error("SENDER_PASSWORD is still placeholder text. Set a real Gmail app password.")
    #         return False
    #
    #     msg = MIMEMultipart('alternative')
    #     msg['Subject'] = str(Header(subject, 'utf-8'))
    #     msg['From'] = SENDER_EMAIL
    #     msg['To'] = to_email
    #
    #     part = MIMEText(html_content, 'html', 'utf-8')
    #     msg.attach(part)
    #
    #     # Try SSL first, then fall back to STARTTLS if port 465 is blocked.
    #     try:
    #         with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=20) as server:
    #             server.login(SENDER_EMAIL, SENDER_PASSWORD)
    #             server.sendmail(SENDER_EMAIL, [to_email], msg.as_string())
    #         return True
    #     except Exception as ssl_error:
    #         app.logger.warning("SMTP SSL failed, retrying with STARTTLS: %s", str(ssl_error))
    #         with smtplib.SMTP('smtp.gmail.com', 587, timeout=20) as server:
    #             server.ehlo()
    #             server.starttls()
    #             server.ehlo()
    #             server.login(SENDER_EMAIL, SENDER_PASSWORD)
    #             server.sendmail(SENDER_EMAIL, [to_email], msg.as_string())
    #         return True
    # except Exception as e:
    #     app.logger.exception("Email sending failed: %s", str(e))
    #     return False
    app.logger.warning("Email sending is disabled (SMTP blocked on free hosting).")
    return False


def is_email_configured() -> bool:
    """Email sending disabled; always return False."""
    # Original check (kept for reference):
    # if not SENDER_EMAIL or not SENDER_PASSWORD:
    #     return False
    # return "your_16_character_app_password_here" not in SENDER_PASSWORD.lower()
    return False

def send_password_reset_email(email: str, reset_url: str) -> bool:
    """Send password reset email"""
    html = f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <h2>Password Reset Request</h2>
            <p>Click the link below to reset your password. This link will expire in 1 hour.</p>
            <a href="{reset_url}" style="background-color: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Reset Password</a>
            <p>Or copy this link: {reset_url}</p>
            <p>If you didn't request this, ignore this email.</p>
        </body>
    </html>
    """
    return send_email(email, "Password Reset Request", html)

def send_contact_notification(name: str, email: str, phone: str, message: str) -> bool:
    """Send contact notification to admin with full details"""
    html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px;">
            <div style="background: white; max-width: 600px; margin: 0 auto; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; text-align: center;">
                    <h2 style="margin: 0;">📬 NEW CONTACT MESSAGE</h2>
                </div>
                
                <div style="padding: 30px;">
                    <h3 style="color: #333; margin-bottom: 20px;">Message Details:</h3>
                    
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr style="border-bottom: 1px solid #eee;">
                            <td style="padding: 12px; font-weight: bold; color: #667eea; width: 30%;">📝 From:</td>
                            <td style="padding: 12px; color: #333;">{name}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #eee;">
                            <td style="padding: 12px; font-weight: bold; color: #667eea;">📧 Email:</td>
                            <td style="padding: 12px; color: #333;"><a href="mailto:{email}" style="color: #667eea; text-decoration: none;">{email}</a></td>
                        </tr>
                        <tr style="border-bottom: 1px solid #eee;">
                            <td style="padding: 12px; font-weight: bold; color: #667eea;">📱 Phone:</td>
                            <td style="padding: 12px; color: #333;">{phone}</td>
                        </tr>
                    </table>
                    
                    <div style="background: #f9f9f9; padding: 15px; margin: 20px 0; border-radius: 5px; border-left: 4px solid #667eea;">
                        <h4 style="margin-top: 0; color: #333;">💬 Message:</h4>
                        <p style="color: #555; line-height: 1.6; white-space: pre-wrap;">{message}</p>
                    </div>
                    
                    <div style="background: #e7f3ff; padding: 15px; border-radius: 5px; margin-top: 20px;">
                        <p style="margin: 0; color: #2196F3; font-size: 14px;">
                            ⏰ Received: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC
                        </p>
                    </div>
                    
                    <div style="margin-top: 20px; text-align: center;">
                        <a href="https://wa.me/918881254553" style="background: #25d366; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block; margin-right: 10px;">💬 Reply on WhatsApp</a>
                        <a href="mailto:{email}" style="background: #dd5100; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block;">📧 Reply via Email</a>
                    </div>
                </div>
                
                <div style="background: #f5f5f5; padding: 15px; text-align: center; font-size: 12px; color: #999;">
                    <p style="margin: 0;">Sent by Portfolio Contact System</p>
                </div>
            </div>
        </body>
    </html>
    """
    return send_email(ADMIN_EMAIL, f"NEW CONTACT: {name}", html)

def send_contact_acknowledgement(name: str, email: str) -> bool:
    """Send acknowledgement email to the contact form sender."""
    html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; background: #f6f8fb; padding: 20px;">
            <div style="max-width: 620px; margin: 0 auto; background: #ffffff; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.08);">
                <div style="background: linear-gradient(135deg, #1a365d 0%, #2c5282 100%); color: #fff; padding: 20px; text-align: center;">
                    <h2 style="margin: 0;">Thank you for reaching out, {name}!</h2>
                </div>
                <div style="padding: 24px; color: #2d3748; line-height: 1.6;">
                    <p style="margin-top: 0;">Your message has been received successfully.</p>
                    <p>We typically reply within <strong>24 hours</strong>.</p>
                    <p style="margin-bottom: 0;">For urgent requests, contact on WhatsApp: <strong>{ADMIN_PHONE}</strong>.</p>
                </div>
                <div style="background: #f1f5f9; padding: 14px 24px; color: #4a5568; font-size: 13px;">
                    Automated acknowledgement from Ajay Prakash Pandey Portfolio.
                </div>
            </div>
        </body>
    </html>
    """
    return send_email(email, "We received your message", html)
def get_whatsapp_message_link(phone: str, message: str) -> str:
    """Generate WhatsApp message link"""
    import urllib.parse
    return f"https://wa.me/{phone}?text={urllib.parse.quote(message)}"

# ===== UTILITY FUNCTIONS =====

def validate_email(email: str) -> bool:
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def validate_phone(phone: str) -> bool:
    """Validate contact number format (allows +, spaces, dashes, parentheses)."""
    if not phone:
        return False
    cleaned = re.sub(r'[\s\-\(\)]', '', phone)
    if cleaned.startswith('+'):
        cleaned = cleaned[1:]
    return cleaned.isdigit() and 7 <= len(cleaned) <= 15

def validate_password(password: str) -> tuple[bool, str]:
    """Validate password strength"""
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not any(char.isupper() for char in password):
        return False, "Password must contain uppercase letter"
    if not any(char.isdigit() for char in password):
        return False, "Password must contain digit"
    return True, "Valid"

def generate_reset_token() -> str:
    """Generate unique reset token"""
    return secrets.token_urlsafe(32)

def result_to_list_of_tuples(results: List[Any], model_class: Any) -> List[Any]:
    """Convert SQLAlchemy objects to tuples for template compatibility"""
    output = []
    if model_class == Project:
        attributes = ['id', 'pname', 'projectlink', 'projectDescripton']
    elif model_class == Contact:
        attributes = ['id', 'name', 'email', 'message', 'created_at']
    elif model_class == Skill:
        attributes = ['id', 'skill_name', 'description', 'proficiency', 'category']
    else:
        return results
    
    for item in results:
        row = [getattr(item, attr) for attr in attributes]
        output.append(row)
    return output

def build_dynamic_resume_text(portfolio: Optional[Any]) -> str:
    """Build ATS-friendly plain resume text using saved portfolio data."""
    def clean_text(value: str) -> str:
        # Keep content plain and consistent for ATS parsing.
        replacements = {
            "’": "'",
            "“": '"',
            "”": '"',
            "–": "-",
            "—": "-",
        }
        for src, dst in replacements.items():
            value = value.replace(src, dst)
        return re.sub(r"\s+", " ", value).strip()

    profile_name = ADMIN_NAME.strip() if ADMIN_NAME else ""
    profile_email = ADMIN_EMAIL.strip() if ADMIN_EMAIL else ""
    profile_phone = (portfolio.phone.strip() if portfolio and portfolio.phone else ADMIN_PHONE.strip() if ADMIN_PHONE else "")
    profile_location = (portfolio.location.strip() if portfolio and portfolio.location else "")
    profile_summary = (portfolio.about_description.strip() if portfolio and portfolio.about_description else "")
    profile_headline = (portfolio.hero_subtitle.strip() if portfolio and portfolio.hero_subtitle else "")
    profile_github = (portfolio.github.strip() if portfolio and portfolio.github else ADMIN_GITHUB.strip() if ADMIN_GITHUB else "")
    profile_linkedin = (portfolio.linkedin.strip() if portfolio and portfolio.linkedin else ADMIN_LINKEDIN.strip() if ADMIN_LINKEDIN else "")
    profile_twitter = (portfolio.twitter.strip() if portfolio and portfolio.twitter else "")

    skills_data = Skill.query.order_by(Skill.category, Skill.skill_name).all()
    projects_data = Project.query.order_by(Project.created_at.desc()).all()

    lines: List[str] = []

    if profile_name:
        lines.append(clean_text(profile_name))
    if profile_headline:
        lines.append(clean_text(profile_headline))

    contact_lines: List[str] = []
    if profile_email:
        contact_lines.append(f"Email: {clean_text(profile_email)}")
    if profile_phone:
        contact_lines.append(f"Phone: {clean_text(profile_phone)}")
    if profile_location:
        contact_lines.append(f"Location: {clean_text(profile_location)}")
    if profile_github:
        contact_lines.append(f"GitHub: {clean_text(profile_github)}")
    if profile_linkedin:
        contact_lines.append(f"LinkedIn: {clean_text(profile_linkedin)}")
    if profile_twitter:
        contact_lines.append(f"Twitter: {clean_text(profile_twitter)}")

    if contact_lines:
        if lines:
            lines.append("")
        lines.append("CONTACT")
        lines.extend(contact_lines)

    if profile_summary:
        if lines:
            lines.append("")
        lines.append("PROFESSIONAL SUMMARY")
        lines.append(clean_text(profile_summary))

    if skills_data:
        if lines:
            lines.append("")
        lines.append("SKILLS")
        skills_by_category: dict[str, list[str]] = {}
        for skill in skills_data:
            category = clean_text(skill.category) if skill.category else "Other"
            skill_text = clean_text(skill.skill_name)
            if skill.proficiency is not None:
                skill_text = f"{skill_text} ({int(skill.proficiency)}%)"
            skills_by_category.setdefault(category, []).append(skill_text)
        for category in sorted(skills_by_category.keys()):
            lines.append(f"{category}: {', '.join(skills_by_category[category])}")

    if projects_data:
        if lines:
            lines.append("")
        lines.append("PROJECTS")
        for project in projects_data:
            lines.append(f"- {clean_text(project.pname)}")
            if project.projectDescripton and project.projectDescripton.strip():
                lines.append(f"  Description: {clean_text(project.projectDescripton)}")
            if project.projectlink and project.projectlink.strip():
                lines.append(f"  Link: {clean_text(project.projectlink)}")

    if not lines:
        lines.append("No portfolio data found.")

    return "\n".join(lines)

def build_ats_resume_pdf(resume_text: str) -> io.BytesIO:
    """Generate a simple text-first PDF resume for ATS compatibility."""
    try:
        from reportlab.lib.pagesizes import LETTER
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise RuntimeError("PDF generator dependency missing: reportlab") from exc

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=LETTER)

    page_width, page_height = LETTER
    left_margin = 54
    right_margin = 54
    top_margin = 54
    bottom_margin = 54
    max_width = page_width - left_margin - right_margin
    line_height = 14
    font_name = "Helvetica"
    font_size = 10.5

    def wrap_line(raw_line: str) -> list[str]:
        if raw_line.strip() == "":
            return [""]
        words = raw_line.split()
        if not words:
            return [""]
        lines_out: list[str] = []
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if pdfmetrics.stringWidth(trial, font_name, font_size) <= max_width:
                current = trial
            else:
                lines_out.append(current)
                current = word
        lines_out.append(current)
        return lines_out

    y = page_height - top_margin
    c.setFont(font_name, font_size)

    for source_line in resume_text.splitlines():
        for line in wrap_line(source_line):
            if y <= bottom_margin:
                c.showPage()
                c.setFont(font_name, font_size)
                y = page_height - top_margin
            c.drawString(left_margin, y, line)
            y -= line_height

    c.save()
    buffer.seek(0)
    return buffer

def build_human_readable_resume_pdf(resume_text: str) -> io.BytesIO:
    """Generate a styled, human-readable PDF from portfolio resume text."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import LETTER
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise RuntimeError("PDF generator dependency missing: reportlab") from exc

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=LETTER)
    page_width, page_height = LETTER

    left_margin = 46
    right_margin = 46
    top_margin = 44
    bottom_margin = 46
    usable_width = page_width - left_margin - right_margin

    section_titles = {"CONTACT", "PROFESSIONAL SUMMARY", "SKILLS", "PROJECTS"}

    def wrap_line(raw_line: str, font_name: str, font_size: float, width: float) -> list[str]:
        text = raw_line.strip()
        if text == "":
            return [""]
        words = text.split()
        lines_out: list[str] = []
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if pdfmetrics.stringWidth(trial, font_name, font_size) <= width:
                current = trial
            else:
                lines_out.append(current)
                current = word
        lines_out.append(current)
        return lines_out

    def new_page() -> float:
        c.showPage()
        return page_height - top_margin

    lines = [ln.rstrip() for ln in resume_text.splitlines()]
    name_line = lines[0].strip() if lines else "Portfolio Resume"
    headline_line = lines[1].strip() if len(lines) > 1 and lines[1].strip() and lines[1].strip() not in section_titles else ""
    body_lines = lines[2:] if headline_line else lines[1:]

    sections: dict[str, list[str]] = {}
    section_order: list[str] = []
    current_section = "BODY"
    sections[current_section] = []

    for line in body_lines:
        key = line.strip()
        if key in section_titles:
            current_section = key
            if current_section not in sections:
                sections[current_section] = []
                section_order.append(current_section)
            continue
        sections.setdefault(current_section, []).append(line)
        if current_section not in section_order and current_section != "BODY":
            section_order.append(current_section)

    y = page_height - top_margin

    # Header block
    c.setFillColor(colors.HexColor("#123765"))
    c.roundRect(left_margin, y - 78, usable_width, 78, 8, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(left_margin + 14, y - 26, name_line)

    if headline_line:
        c.setFont("Helvetica", 11)
        headline_lines = wrap_line(headline_line, "Helvetica", 11, usable_width - 28)
        hy = y - 44
        for hl in headline_lines[:2]:
            c.drawString(left_margin + 14, hy, hl)
            hy -= 14

    y -= 96

    # Contact band
    contact_lines = sections.get("CONTACT", [])
    if contact_lines:
        c.setFillColor(colors.HexColor("#F1F5F9"))
        c.roundRect(left_margin, y - 36, usable_width, 30, 6, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#1F2937"))
        c.setFont("Helvetica", 10)
        contact_text = " | ".join([ln.strip() for ln in contact_lines if ln.strip()])
        clipped = contact_text[:260] + ("..." if len(contact_text) > 260 else "")
        for row in wrap_line(clipped, "Helvetica", 10, usable_width - 18)[:2]:
            c.drawString(left_margin + 10, y - 22, row)
            y -= 12
        y -= 20
    else:
        y -= 6

    def draw_section_title(title: str, current_y: float) -> float:
        if current_y <= bottom_margin + 36:
            current_y = new_page()
        c.setFillColor(colors.HexColor("#1D4ED8"))
        c.roundRect(left_margin, current_y - 18, usable_width, 16, 4, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(left_margin + 8, current_y - 14, title)
        return current_y - 24

    # Section rendering order for human readability
    ordered = ["PROFESSIONAL SUMMARY", "SKILLS", "PROJECTS"]
    for title in ordered:
        content = sections.get(title, [])
        if not content:
            continue
        y = draw_section_title(title, y)

        for raw in content:
            if y <= bottom_margin + 16:
                y = new_page()
            line = raw.rstrip()
            if not line.strip():
                y -= 6
                continue

            is_bullet = line.startswith("- ")
            is_detail = line.startswith("  ")
            text = line[2:].strip() if is_bullet else line.strip()
            font_name = "Helvetica-Bold" if (title == "PROJECTS" and is_bullet) else "Helvetica"
            font_size = 10.4
            indent = left_margin + 12 if is_detail else left_margin + 2
            if is_bullet:
                c.setFillColor(colors.HexColor("#123765"))
                c.setFont("Helvetica-Bold", 10)
                c.drawString(left_margin + 2, y, "-")
                indent = left_margin + 14

            c.setFillColor(colors.HexColor("#111827"))
            c.setFont(font_name, font_size)
            wrapped = wrap_line(text, font_name, font_size, page_width - indent - right_margin)
            for row in wrapped:
                if y <= bottom_margin + 12:
                    y = new_page()
                    c.setFillColor(colors.HexColor("#111827"))
                    c.setFont(font_name, font_size)
                c.drawString(indent, y, row)
                y -= 13.5
            y -= 2

        y -= 6

    c.save()
    buffer.seek(0)
    return buffer

# ===== DATABASE INITIALIZATION =====

def init_db(interactive_admin: bool = False):
    """Initialize database and seed defaults. Optional interactive admin setup."""
    try:
        with app.app_context():
            db.create_all()
            
            # Create default portfolio entry if none exists
            if Portfolio.query.count() == 0:
                default_portfolio = Portfolio()
                db.session.add(default_portfolio)
                db.session.commit()

            # Seed homepage service cards once
            if ServiceCard.query.count() == 0:
                default_services = [
                    ServiceCard(icon_class='fas fa-laptop-code', title='Web Development',
                                description='Build responsive, modern web applications from scratch using HTML, CSS, JavaScript, Flask, and best practices.',
                                sort_order=1),
                    ServiceCard(icon_class='fas fa-mobile-alt', title='Responsive Design',
                                description='Mobile-first, cross-browser compatible designs that deliver seamless experiences across all devices and screen sizes.',
                                sort_order=2),
                    ServiceCard(icon_class='fas fa-database', title='Database Design',
                                description='Efficient database architecture, optimization, and implementation using SQL and modern database technologies.',
                                sort_order=3),
                    ServiceCard(icon_class='fas fa-cogs', title='Software Systems',
                                description='Build robust server-side solutions with Python, Flask, and scalable architecture for enterprise-level applications.',
                                sort_order=4),
                    ServiceCard(icon_class='fas fa-shield-alt', title='Security & Quality',
                                description='Code security best practices, testing, and quality assurance to ensure reliable and maintainable applications.',
                                sort_order=5),
                ]
                db.session.add_all(default_services)
                db.session.commit()

            # Seed 'why hire me' cards once
            if WhyHireItem.query.count() == 0:
                default_why_items = [
                    WhyHireItem(icon_class='fas fa-fire', title='Eager & Passionate',
                                description='Highly motivated to learn, grow, and contribute. I bring fresh perspectives and enthusiasm to every project.',
                                sort_order=1),
                    WhyHireItem(icon_class='fas fa-book', title='Quick Learner',
                                description='Strong foundation in core concepts, adaptable to new technologies, and committed to continuous improvement.',
                                sort_order=2),
                    WhyHireItem(icon_class='fas fa-users', title='Team Player',
                                description='Collaborative mindset, excellent communication skills, and willing to learn from experienced mentors.',
                                sort_order=3),
                ]
                db.session.add_all(default_why_items)
                db.session.commit()
            
            # Create admin only in explicit interactive mode (local dev)
            if interactive_admin and User.query.count() == 0:
                print("\n--- Initial Admin Setup ---")
                username = input("Enter admin username: ")
                email = input("Enter admin email: ")
                
                while True:
                    password = input("Enter admin password (min 8 chars, 1 uppercase, 1 digit): ")
                    is_valid, msg = validate_password(password)
                    if is_valid:
                        break
                    print(f"Invalid: {msg}")
                
                hashed = bcrypt.generate_password_hash(password).decode('utf-8')
                user = User(username=username, email=email, password=hashed)
                db.session.add(user)
                db.session.commit()
                print(f"Admin '{username}' created successfully.")
            
            print("Database initialized successfully.")
        return True
    except Exception as e:
        print(f"Database error: {e}")
        return False

# Ensure tables/default content exist when app is loaded by gunicorn.
init_db(interactive_admin=False)

# ===== ROUTES: PUBLIC =====

@app.route("/robots.txt")
def robots_txt():
    """Allow indexing for public pages and expose sitemap URL."""
    base_url = get_base_url()
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /dashboard",
        "Disallow: /login",
        "Disallow: /register",
        "Disallow: /logout",
        "Disallow: /forgot-password",
        "Disallow: /change-password",
        "Disallow: /messages",
        "Disallow: /api/",
        f"Sitemap: {base_url}/sitemap.xml",
    ]
    return Response("\n".join(lines), mimetype="text/plain")

@app.route("/sitemap.xml")
def sitemap_xml():
    """Generate a sitemap for major public pages."""
    today = datetime.now(timezone.utc).date().isoformat()
    public_endpoints = ["index", "services", "about", "projects", "skills", "contact", "download_resume"]
    urls = []

    for endpoint in public_endpoints:
        try:
            loc = url_for(endpoint, _external=True)
            urls.append((loc, today))
        except Exception:
            continue

    xml_items = []
    for loc, lastmod in urls:
        xml_items.append(
            "<url>"
            f"<loc>{xml_escape(loc)}</loc>"
            f"<lastmod>{lastmod}</lastmod>"
            "<changefreq>weekly</changefreq>"
            "<priority>0.8</priority>"
            "</url>"
        )

    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(xml_items) +
        "</urlset>"
    )
    return Response(xml_content, mimetype="application/xml")

@app.route("/")
def index():
    try:
        portfolio = Portfolio.query.first()
        skills = Skill.query.order_by(Skill.category.asc(), Skill.skill_name.asc()).all()
        service_cards = ServiceCard.query.order_by(ServiceCard.sort_order.asc(), ServiceCard.id.asc()).all()
        why_items = WhyHireItem.query.order_by(WhyHireItem.sort_order.asc(), WhyHireItem.id.asc()).all()
        return render_template('index.html', portfolio=portfolio, skills=skills, service_cards=service_cards, why_items=why_items)
    except:
        return render_template('index.html', portfolio=None, skills=[], service_cards=[], why_items=[])

@app.route("/about")
def about():
    try:
        portfolio = Portfolio.query.first()
        return render_template('AboutME.html', portfolio=portfolio)
    except:
        return render_template('AboutME.html', portfolio=None)

@app.route("/services")
def services():
    """SEO landing page for roles and services."""
    portfolio = Portfolio.query.first()
    return render_template('services.html', portfolio=portfolio)

@app.route("/projects")
def projects():
    try:
        with app.app_context():
            projects_data = Project.query.all()
            portfolio = Portfolio.query.first()
            compatible = result_to_list_of_tuples(projects_data, Project)
        return render_template('projects.html', projects=compatible, portfolio=portfolio)
    except Exception:
        app.logger.exception('Failed to load projects data')
        flash('Projects are temporarily unavailable. Please try again shortly.', 'error')
        return render_template('projects.html', projects=[], portfolio=None)

@app.route("/skills")
def skills():
    """Display all skills from database"""
    try:
        with app.app_context():
            skills_data = Skill.query.order_by(Skill.category, Skill.skill_name).all()
            portfolio = Portfolio.query.first()
        return render_template('Skills.html', skills=skills_data, portfolio=portfolio)
    except Exception as e:
        flash(f'Error loading skills: {str(e)}', 'error')
        return render_template('Skills.html', skills=[], portfolio=None)

@app.route("/contact")
def contact():
    portfolio = Portfolio.query.first()
    return render_template('contact.html', portfolio=portfolio)

@app.route("/contact", methods=['POST'])
def contact_post():
    """Handle contact form submission using free-only channels (DB + email)."""
    try:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown').split(',')[0].strip()
        if is_rate_limited(f"contact:{ip}", max_attempts=5, window_seconds=600):
            flash('Too many requests. Please wait a few minutes and try again.', 'error')
            return redirect(url_for('contact'))

        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        message = request.form.get('message', '').strip()

        if not all([name, email, phone, message]):
            flash('All fields are required', 'error')
            return redirect(url_for('contact'))

        if not validate_email(email):
            flash('Invalid email address', 'error')
            return redirect(url_for('contact'))

        if not validate_phone(phone):
            flash('Invalid phone number', 'error')
            return redirect(url_for('contact'))

        if len(message) < 10:
            flash('Message must be at least 10 characters', 'error')
            return redirect(url_for('contact'))

        with app.app_context():
            contact_msg = Contact(name=name, email=email, message=message)
            db.session.add(contact_msg)
            db.session.commit()

        if not is_email_configured():
            app.logger.error("Email notifications skipped: SENDER_EMAIL/SENDER_PASSWORD are not configured.")
            flash('Message saved. To receive email notifications, set SENDER_EMAIL and SENDER_PASSWORD in .env, then restart the app.', 'warning')
            return redirect(url_for('contact'))

        admin_email_sent = send_contact_notification(name, email, phone, message)
        user_email_sent = send_contact_acknowledgement(name, email)

        wa_phone = ADMIN_PHONE.replace('+', '').replace(' ', '').replace('-', '')
        wa_admin_message = f'NEW MESSAGE:\n\nFrom: {name}\nEmail: {email}\nPhone: {phone}\n\nMessage:\n{message}'
        wa_admin_link = get_whatsapp_message_link(wa_phone, wa_admin_message)

        if admin_email_sent and user_email_sent:
            flash('Message sent successfully. Confirmation email sent to you and admin notified.', 'success')
        elif admin_email_sent and not user_email_sent:
            flash('Message sent and admin notified, but confirmation email could not be sent to your inbox.', 'warning')
        elif user_email_sent and not admin_email_sent:
            app.logger.warning('Admin email failed for contact from %s; manual WhatsApp fallback link: %s', email, wa_admin_link)
            flash('Message received and confirmation email sent to you. Admin email failed; message is saved in dashboard.', 'warning')
        else:
            app.logger.error('Both admin and user emails failed for contact from %s. Manual WhatsApp fallback link: %s', email, wa_admin_link)
            flash('Message saved successfully, but email notifications are temporarily unavailable.', 'warning')

        return redirect(url_for('contact'))
    except Exception as e:
        app.logger.exception('Contact submission failed: %s', str(e))
        flash('Something went wrong while sending your message. Please try again.', 'error')
        return redirect(url_for('contact'))

# ===== ROUTES: AUTHENTICATION =====

@app.route("/register", methods=['GET', 'POST'])
def register():
    """User registration"""
    if request.method == 'POST':
        try:
            ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown').split(',')[0].strip()
            if is_rate_limited(f"register:{ip}", max_attempts=8, window_seconds=900):
                flash('Too many registration attempts. Please try again later.', 'error')
                return redirect(url_for('register'))

            username = request.form.get('uname', '').strip()
            email = request.form.get('email', '').strip()
            password = request.form.get('password', '')
            confirm_pwd = request.form.get('confirm_pwd', '')
            
            # Validation
            if not all([username, email, password, confirm_pwd]):
                flash('All fields required', 'error')
                return redirect(url_for('register'))
            
            if len(username) < 3:
                flash('Username must be at least 3 characters', 'error')
                return redirect(url_for('register'))
            
            if not validate_email(email):
                flash('Invalid email format', 'error')
                return redirect(url_for('register'))
            
            is_valid, msg = validate_password(password)
            if not is_valid:
                flash(msg, 'error')
                return redirect(url_for('register'))
            
            if password != confirm_pwd:
                flash('Passwords do not match', 'error')
                return redirect(url_for('register'))
            
            # Check if user exists
            with app.app_context():
                if User.query.filter_by(username=username).first():
                    flash('Username already exists', 'error')
                    return redirect(url_for('register'))
                if User.query.filter_by(email=email).first():
                    flash('Email already registered', 'error')
                    return redirect(url_for('register'))
                
                # Create user
                hashed = bcrypt.generate_password_hash(password).decode('utf-8')
                user = User(username=username, email=email, password=hashed)
                db.session.add(user)
                db.session.commit()
            
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash(f'Registration error: {str(e)}', 'error')
            return redirect(url_for('register'))
    
    return render_template('registration.html')

@app.route("/login", methods=['GET', 'POST'])
def login():
    """User login - only admin can access"""
    if request.method == 'POST':
        try:
            ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown').split(',')[0].strip()
            if is_rate_limited(f"login:{ip}", max_attempts=10, window_seconds=900):
                flash('Too many login attempts. Please wait 15 minutes and try again.', 'error')
                return redirect(url_for('login'))

            username = request.form.get('uname', '').strip()
            password = request.form.get('password', '')
            
            if not all([username, password]):
                flash('Username and password required', 'error')
                return redirect(url_for('login'))
            
            with app.app_context():
                user = User.query.filter_by(username=username).first()
            
            # Check username and password
            if user and bcrypt.check_password_hash(user.password, password):
                # Only allow admin user with correct email
                if user.email == ADMIN_EMAIL:
                    session['logged_in'] = True
                    session['username'] = username
                    flash('Login successful!', 'success')
                    return redirect(url_for('dashboard'))
                else:
                    flash('Access denied. Only admin can login.', 'error')
                    return redirect(url_for('login'))
            
            flash('Invalid username or password', 'error')
            return redirect(url_for('login'))
        except Exception as e:
            flash(f'Login error: {str(e)}', 'error')
            return redirect(url_for('login'))
    
    return render_template('login.html')

@app.route("/change-password", methods=['GET', 'POST'])
def change_password():
    """Change admin password by verifying email"""
    if request.method == 'POST':
        try:
            email = request.form.get('email', '').strip()
            new_password = request.form.get('new_password', '').strip()
            confirm_password = request.form.get('confirm_password', '').strip()
            
            # Verify admin email
            if email != ADMIN_EMAIL:
                flash('Invalid email. Only the registered admin email can change password.', 'error')
                return redirect(url_for('change_password'))
            
            if not new_password or not confirm_password:
                flash('Password fields cannot be empty', 'error')
                return redirect(url_for('change_password'))
            
            if new_password != confirm_password:
                flash('Passwords do not match', 'error')
                return redirect(url_for('change_password'))
            
            if len(new_password) < 6:
                flash('Password must be at least 6 characters long', 'error')
                return redirect(url_for('change_password'))
            
            with app.app_context():
                user = User.query.filter_by(email=email).first()
                if user:
                    # Hash and update password
                    hashed_password = bcrypt.generate_password_hash(new_password).decode('utf-8')
                    user.password = hashed_password
                    db.session.commit()
                    flash('Password changed successfully! Please login with your new password.', 'success')
                    return redirect(url_for('login'))
                else:
                    flash('No user found with this email', 'error')
                    return redirect(url_for('change_password'))
        except Exception as e:
            flash(f'Error changing password: {str(e)}', 'error')
            return redirect(url_for('change_password'))
    
    return render_template('change_password.html')

@app.route("/forgot-password", methods=['GET', 'POST'])
def forgot_password():
    """Request password reset"""
    if request.method == 'POST':
        try:
            ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown').split(',')[0].strip()
            if is_rate_limited(f"forgot:{ip}", max_attempts=6, window_seconds=900):
                flash('Too many reset requests. Please try again later.', 'error')
                return redirect(url_for('forgot_password'))

            email = request.form.get('email', '').strip()
            
            if not validate_email(email):
                flash('Invalid email format', 'error')
                return redirect(url_for('forgot_password'))
            
            with app.app_context():
                user = User.query.filter_by(email=email).first()
                
                if user:
                    # Generate reset token
                    reset_token = generate_reset_token()
                    user.reset_token = reset_token
                    user.reset_token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
                    db.session.commit()
                    
                    # Send reset email
                    reset_path = url_for('reset_password', token=reset_token)
                    reset_url = f"{get_base_url()}{reset_path}"
                    email_sent = send_password_reset_email(email, reset_url)
                    if not email_sent:
                        flash('Unable to send reset email right now. Please try again shortly.', 'error')
                        return redirect(url_for('forgot_password'))
            
            # Always show this message for security (don't reveal if email exists)
            flash('If an account exists, you will receive a password reset email.', 'info')
            return redirect(url_for('login'))
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
            return redirect(url_for('forgot_password'))
    
    return render_template('forgot_password.html')

@app.route("/reset-password/<token>", methods=['GET', 'POST'])
def reset_password(token: str):
    """Reset password with token"""
    try:
        with app.app_context():
            user = User.query.filter_by(reset_token=token).first()
            
            if not user or datetime.now(timezone.utc) > user.reset_token_expiry:
                flash('Invalid or expired reset link', 'error')
                return redirect(url_for('login'))
        
        if request.method == 'POST':
            try:
                password = request.form.get('password', '')
                confirm_pwd = request.form.get('confirm_pwd', '')
                
                is_valid, msg = validate_password(password)
                if not is_valid:
                    flash(msg, 'error')
                    return redirect(url_for('reset_password', token=token))
                
                if password != confirm_pwd:
                    flash('Passwords do not match', 'error')
                    return redirect(url_for('reset_password', token=token))
                
                with app.app_context():
                    user = User.query.filter_by(reset_token=token).first()
                    hashed = bcrypt.generate_password_hash(password).decode('utf-8')
                    user.password = hashed
                    user.reset_token = None
                    user.reset_token_expiry = None
                    db.session.commit()
                
                flash('Password reset successful! Please login.', 'success')
                return redirect(url_for('login'))
            except Exception as e:
                flash(f'Error: {str(e)}', 'error')
                return redirect(url_for('reset_password', token=token))
        
        return render_template('reset_password.html', token=token)
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('login'))

@app.route("/logout")
def logout():
    """Logout user"""
    session.clear()
    flash('Logged out successfully!', 'success')
    response = redirect(url_for('login'))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0, private'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# ===== ROUTES: DASHBOARD (PROTECTED) =====

@login_required
@app.route("/dashboard")
def dashboard():
    """Admin dashboard"""
    try:
        with app.app_context():
            portfolio = Portfolio.query.first()
            projects = Project.query.all()
            skills = Skill.query.all()
            messages = Contact.query.order_by(Contact.created_at.desc()).limit(5).all()
            service_cards = ServiceCard.query.order_by(ServiceCard.sort_order.asc(), ServiceCard.id.asc()).all()
            why_items = WhyHireItem.query.order_by(WhyHireItem.sort_order.asc(), WhyHireItem.id.asc()).all()
        
        return render_template('dashboard.html', 
                             portfolio=portfolio, 
                             projects=projects,
                             skills=skills,
                             messages=messages,
                             service_cards=service_cards,
                             why_items=why_items)
    except Exception as e:
        flash(f'Dashboard error: {str(e)}', 'error')
        return redirect(url_for('index'))

@login_required
@app.route("/dashboard/profile", methods=['GET', 'POST'])
def edit_profile():
    """Edit portfolio profile"""
    if request.method == 'POST':
        try:
            with app.app_context():
                portfolio = Portfolio.query.first() or Portfolio()
                
                portfolio.hero_title = request.form.get('hero_title', '')
                portfolio.hero_subtitle = request.form.get('hero_subtitle', '')
                portfolio.about_title = request.form.get('about_title', '')
                portfolio.about_description = request.form.get('about_description', '')
                portfolio.phone = request.form.get('phone', '')
                portfolio.whatsapp = request.form.get('whatsapp', '')
                portfolio.location = request.form.get('location', '')
                portfolio.github = request.form.get('github', '')
                portfolio.linkedin = request.form.get('linkedin', '')
                portfolio.twitter = request.form.get('twitter', '')
                
                # Handle profile image upload
                if 'profile_image' in request.files:
                    file = request.files['profile_image']
                    if file and file.filename and file.filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                        ext = file.filename.rsplit('.', 1)[1].lower()
                        mime_by_ext = {
                            'jpg': 'image/jpeg',
                            'jpeg': 'image/jpeg',
                            'png': 'image/png',
                            'gif': 'image/gif',
                            'webp': 'image/webp',
                        }
                        image_bytes = file.read()
                        if image_bytes:
                            encoded = base64.b64encode(image_bytes).decode('ascii')
                            portfolio.profile_image = f"data:{mime_by_ext[ext]};base64,{encoded}"
                
                # Handle resume upload
                if 'resume' in request.files:
                    file = request.files['resume']
                    if file and file.filename.endswith('.pdf'):
                        filename = f"resume_{datetime.utcnow().timestamp()}.pdf"
                        filepath = os.path.join(app.static_folder, 'resumes', filename)
                        os.makedirs(os.path.dirname(filepath), exist_ok=True)
                        file.save(filepath)
                        portfolio.resume_url = f"/Static/resumes/{filename}"
                
                db.session.add(portfolio)
                db.session.commit()
            
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f'Error updating profile: {str(e)}', 'error')
            return redirect(url_for('edit_profile'))
    
    try:
        portfolio = Portfolio.query.first()
        return render_template('edit_profile.html', portfolio=portfolio)
    except:
        return render_template('edit_profile.html', portfolio=None)

# ===== ROUTES: PROJECTS =====

@login_required
@app.route("/add_project", methods=['POST'])
def add_project():
    """Add new project"""
    try:
        pname = request.form.get('pname', '').strip()
        projectlink = request.form.get('projectlink', '').strip()
        description = request.form.get('projectDescripton', '').strip()
        
        if not pname:
            flash('Project name required', 'error')
            return redirect(url_for('dashboard'))
        
        with app.app_context():
            project = Project(pname=pname, projectlink=projectlink, projectDescripton=description)
            db.session.add(project)
            db.session.commit()
        
        flash('Project added!', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('dashboard'))

@login_required
@app.route("/delete_project/<int:project_id>", methods=['GET', 'POST'])
def delete_project(project_id: int):
    """Delete project"""
    try:
        with app.app_context():
            project = Project.query.get(project_id)
            if project:
                db.session.delete(project)
                db.session.commit()
                flash('Project deleted!', 'success')
            else:
                flash('Project not found', 'error')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('dashboard'))

# ===== ROUTES: HOMEPAGE CONTENT =====

@login_required
@app.route("/add_service_card", methods=['POST'])
def add_service_card():
    """Add homepage service card."""
    try:
        title = request.form.get('title', '').strip()
        icon_class = request.form.get('icon_class', 'fas fa-star').strip() or 'fas fa-star'
        description = request.form.get('description', '').strip()
        sort_order = int(request.form.get('sort_order', 0))

        if not title or not description:
            flash('Service title and description are required', 'error')
            return redirect(url_for('dashboard'))

        with app.app_context():
            card = ServiceCard(
                icon_class=icon_class,
                title=title,
                description=description,
                sort_order=sort_order
            )
            db.session.add(card)
            db.session.commit()

        flash('Service card added!', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    return redirect(url_for('dashboard'))

@login_required
@app.route("/delete_service_card/<int:card_id>", methods=['POST'])
def delete_service_card(card_id: int):
    """Delete homepage service card."""
    try:
        with app.app_context():
            card = ServiceCard.query.get(card_id)
            if card:
                db.session.delete(card)
                db.session.commit()
                flash('Service card deleted!', 'success')
            else:
                flash('Service card not found', 'error')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    return redirect(url_for('dashboard'))

@login_required
@app.route("/add_why_item", methods=['POST'])
def add_why_item():
    """Add 'why hire me' card."""
    try:
        title = request.form.get('title', '').strip()
        icon_class = request.form.get('icon_class', 'fas fa-check').strip() or 'fas fa-check'
        description = request.form.get('description', '').strip()
        sort_order = int(request.form.get('sort_order', 0))

        if not title or not description:
            flash('Why-hire title and description are required', 'error')
            return redirect(url_for('dashboard'))

        with app.app_context():
            item = WhyHireItem(
                icon_class=icon_class,
                title=title,
                description=description,
                sort_order=sort_order
            )
            db.session.add(item)
            db.session.commit()

        flash('Why-hire item added!', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    return redirect(url_for('dashboard'))

@login_required
@app.route("/delete_why_item/<int:item_id>", methods=['POST'])
def delete_why_item(item_id: int):
    """Delete 'why hire me' card."""
    try:
        with app.app_context():
            item = WhyHireItem.query.get(item_id)
            if item:
                db.session.delete(item)
                db.session.commit()
                flash('Why-hire item deleted!', 'success')
            else:
                flash('Why-hire item not found', 'error')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    return redirect(url_for('dashboard'))

# ===== ROUTES: SKILLS =====

@login_required
@app.route("/add_skill", methods=['POST'])
def add_skill():
    """Add new skill"""
    try:
        skill_name = request.form.get('skill_name', '').strip()
        description = request.form.get('description', '').strip()  # NEW
        proficiency = int(request.form.get('proficiency', 50))
        category = request.form.get('category', 'Other').strip()
        
        if not skill_name:
            flash('Skill name required', 'error')
            return redirect(url_for('dashboard'))
        
        if proficiency < 0 or proficiency > 100:
            flash('Proficiency must be 0-100', 'error')
            return redirect(url_for('dashboard'))
        
        with app.app_context():
            # Check if skill exists
            if Skill.query.filter_by(skill_name=skill_name).first():
                flash('Skill already exists', 'error')
                return redirect(url_for('dashboard'))
            
            skill = Skill(skill_name=skill_name, description=description, 
                         proficiency=proficiency, category=category)
            db.session.add(skill)
            db.session.commit()
        
        flash('Skill added!', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('dashboard'))

@login_required
@app.route("/edit_skill/<int:skill_id>", methods=['POST'])
def edit_skill(skill_id: int):
    """Edit existing skill"""
    try:
        with app.app_context():
            skill = Skill.query.get(skill_id)
            if not skill:
                flash('Skill not found', 'error')
                return redirect(url_for('dashboard'))
            
            skill.skill_name = request.form.get('skill_name', '').strip()
            skill.description = request.form.get('description', '').strip()
            skill.proficiency = int(request.form.get('proficiency', skill.proficiency))
            skill.category = request.form.get('category', skill.category).strip()
            
            db.session.commit()
        
        flash('Skill updated!', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('dashboard'))

@login_required
@app.route("/delete_skill/<int:skill_id>", methods=['GET', 'POST'])
def delete_skill(skill_id: int):
    """Delete skill"""
    try:
        with app.app_context():
            skill = Skill.query.get(skill_id)
            if skill:
                db.session.delete(skill)
                db.session.commit()
                flash('Skill deleted!', 'success')
            else:
                flash('Skill not found', 'error')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('dashboard'))

# ===== ROUTES: MESSAGES =====

@login_required
@app.route("/messages")
def messages():
    """View all contact messages"""
    try:
        with app.app_context():
            msgs = Contact.query.order_by(Contact.created_at.desc()).all()
        return render_template('message.html', messages=msgs)
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('dashboard'))

@login_required
@app.route("/delete_message/<int:msg_id>", methods=['GET', 'POST'])
def delete_message(msg_id: int):
    """Delete contact message"""
    try:
        with app.app_context():
            msg = Contact.query.get(msg_id)
            if msg:
                db.session.delete(msg)
                db.session.commit()
                flash('Message deleted!', 'success')
            else:
                flash('Message not found', 'error')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('messages'))

# ===== API ENDPOINTS =====

@app.route("/api/skills")
def api_skills():
    """Get all skills as JSON"""
    try:
        with app.app_context():
            skills = Skill.query.order_by(Skill.category).all()
            return jsonify({
                'success': True,
                'skills': [{
                    'id': s.id,
                    'name': s.skill_name,
                    'description': s.description,
                    'proficiency': s.proficiency,
                    'category': s.category
                } for s in skills]
            }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route("/api/portfolio")
def api_portfolio():
    """Get portfolio data as JSON"""
    try:
        with app.app_context():
            portfolio = Portfolio.query.first()
            return jsonify({
                'success': True,
                'portfolio': {
                    'hero_title': portfolio.hero_title if portfolio else '',
                    'hero_subtitle': portfolio.hero_subtitle if portfolio else '',
                    'about_description': portfolio.about_description if portfolio else '',
                    'resume_url': portfolio.resume_url if portfolio else ''
                }
            }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route("/api/health", methods=['GET'])
@app.route("/api/health/", methods=['GET'])
def api_health():
    """Health check endpoint for hosting probes."""
    return jsonify({'success': True, 'status': 'ok'}), 200

@app.route("/googlee8af82905a798382.html", methods=['GET'])
def google_site_verification():
    """Serve Google Search Console verification file."""
    return Response("google-site-verification: googlee8af82905a798382.html", mimetype="text/html")


@app.route("/api/new-messages", methods=['GET'])
@login_required
def get_new_messages():
    """API endpoint to check for new messages"""
    try:
        # Get all messages (ordered by newest first)
        all_messages = Contact.query.order_by(Contact.created_at.desc()).all()
        
        total_count = len(all_messages)
        
        # Get messages from last hour for "new" badge
        from datetime import datetime, timedelta, timezone
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        recent_messages = Contact.query.filter(Contact.created_at > one_hour_ago).all()
        new_count = len(recent_messages)
        
        return jsonify({
            'success': True,
            'total_messages': total_count,
            'new_messages': new_count,
            'recent': [
                {
                    'id': msg.id,
                    'name': msg.name,
                    'email': msg.email,
                    'message': msg.message[:50] + '...' if len(msg.message) > 50 else msg.message,
                    'created_at': msg.created_at.strftime('%Y-%m-%d %H:%M:%S') if msg.created_at else ''
                }
                for msg in recent_messages[:5]
            ]
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ===== RESUME DOWNLOAD =====

@app.route('/download-uploaded-resume')
def download_uploaded_resume():
    """Download uploaded resume PDF from dashboard profile."""
    try:
        portfolio = Portfolio.query.first()
        if not portfolio or not portfolio.resume_url:
            flash('Uploaded resume is not available right now. Please use Portfolio Resume PDF.', 'warning')
            return redirect(url_for('index'))

        resume_path = os.path.join(os.path.dirname(__file__), portfolio.resume_url.lstrip('/'))
        if not os.path.exists(resume_path):
            flash('Uploaded resume file is missing. Please use Portfolio Resume PDF.', 'warning')
            return redirect(url_for('index'))

        response = send_file(
            resume_path,
            as_attachment=True,
            download_name='Resume.pdf',
            mimetype='application/pdf'
        )
        response.headers['Cache-Control'] = 'no-store, max-age=0'
        return response
    except Exception as e:
        flash(f'Error downloading uploaded resume: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/download-resume')
@app.route('/download-resume.pdf')
def download_resume():
    """Download an ATS-friendly PDF resume generated from portfolio data."""
    try:
        portfolio = Portfolio.query.first()
        resume_text = build_dynamic_resume_text(portfolio)
        resume_pdf = build_ats_resume_pdf(resume_text)
        response = send_file(
            resume_pdf,
            as_attachment=True,
            download_name='Ajay_Prakash_Resume.pdf',
            mimetype='application/pdf'
        )
        response.headers['Cache-Control'] = 'no-store, max-age=0'
        return response
    except Exception as e:
        flash(f'Error downloading resume: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/download-resume-readable')
@app.route('/download-resume-readable.pdf')
def download_resume_readable():
    """Download a human-readable PDF resume generated from portfolio data."""
    try:
        portfolio = Portfolio.query.first()
        resume_text = build_dynamic_resume_text(portfolio)
        resume_pdf = build_human_readable_resume_pdf(resume_text)
        response = send_file(
            resume_pdf,
            as_attachment=True,
            download_name='Ajay_Prakash_Resume_Readable.pdf',
            mimetype='application/pdf'
        )
        response.headers['Cache-Control'] = 'no-store, max-age=0'
        return response
    except Exception as e:
        flash(f'Error downloading readable resume: {str(e)}', 'error')
        return redirect(url_for('index'))

# ===== ERROR HANDLERS =====

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500

# ===== MAIN =====

if __name__ == "__main__":
    if init_db(interactive_admin=True):
        print("Database ready!")
    else:
        print("Database initialization failed")
    
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 10000)), debug=False)

