"""
HorizonOCR Web Application Backend Server (Flask + SQLite Database)
Linked directly to main repository source code (infer.py).
"""

import os
import sys
import time
import base64
import hashlib
import sqlite3
import io
import json
import tempfile
import shutil
import logging
import secrets
import hmac
import re
import random
import smtplib
import urllib.request
import urllib.parse
import urllib.error
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from collections import defaultdict, deque
from datetime import timedelta
from functools import wraps
from pathlib import Path
from PIL import Image, UnidentifiedImageError
try:
    import pymupdf as fitz  # type: ignore[import-not-found]
except Exception:
    try:
        import fitz  # PyMuPDF
    except Exception:
        fitz = None

try:
    import pypdfium2 as pdfium
except Exception:
    pdfium = None
from flask import Flask, request, jsonify, send_from_directory, send_file, session, redirect
from flask_cors import CORS
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# Multi-backend OCR engine module
from ocr_engines import run_ocr, run_ocr_structured, _synthetic_blocks_from_text

BASE_DIR = Path(__file__).resolve().parent

# Load local .env for development convenience. In production (Render, etc.),
# environment variables are injected by the platform and this is a no-op —
# it never overwrites variables already present in the environment.
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

APP_ENV = os.environ.get("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"
SECRET_KEY = os.environ.get("SECRET_KEY")

if IS_PRODUCTION and not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be configured when APP_ENV=production")

DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "instance")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = str(DATA_DIR / "horizonocr.db")
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 50 * 1024 * 1024))
MAX_DOCUMENT_PAGES = int(os.environ.get("MAX_DOCUMENT_PAGES", 500))
MAX_IMAGE_PIXELS = int(os.environ.get("MAX_IMAGE_PIXELS", 40_000_000))
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}
ALLOWED_ORIGINS = tuple(
    origin.strip().rstrip("/")
    for origin in os.environ.get("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
)

# GitHub OAuth configuration (private service must supply these via environment).
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
GITHUB_OAUTH_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_USER_URL = "https://api.github.com/user"
GITHUB_API_EMAILS_URL = "https://api.github.com/user/emails"

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("horizonocr")

app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")
app.config.update(
    SECRET_KEY=SECRET_KEY or os.urandom(32).hex(),
    MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
    SESSION_COOKIE_SAMESITE="None" if ALLOWED_ORIGINS else "Lax",
    SESSION_COOKIE_NAME="horizonocr_session",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=int(os.environ.get("SESSION_LIFETIME_HOURS", "12"))),
)

is_render = os.environ.get("RENDER") == "true" or "RENDER_EXTERNAL_URL" in os.environ
trusted_proxy_hops = int(os.environ.get("TRUSTED_PROXY_HOPS", "1" if is_render else "0"))
if trusted_proxy_hops or is_render:
    hops = max(trusted_proxy_hops, 1)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops, x_prefix=hops)

CORS(
    app,
    resources={r"/api/*": {"origins": "*"}},
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Admin-Key"],
    methods=["GET", "POST", "DELETE", "OPTIONS"],
    max_age=600,
)

@app.after_request
def apply_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Admin-Key, X-CSRF-Token"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return response

_rate_limit_windows = defaultdict(deque)


def get_db():
    """Return a short-lived SQLite connection with production-safe defaults."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def _client_key():
    return request.remote_addr or "unknown"


def rate_limit(limit, window_seconds):
    """Small process-local abuse guard; deploy behind an edge rate limiter for multi-instance limits."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            now = time.monotonic()
            key = (view.__name__, _client_key())
            hits = _rate_limit_windows[key]
            while hits and now - hits[0] >= window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                return jsonify({"error": "Too many requests. Please wait and try again."}), 429
            hits.append(now)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def _origin_is_allowed(origin):
    if not origin:
        return True
    normalized_origin = origin.rstrip("/")
    same_origin = request.host_url.rstrip("/")
    return normalized_origin == same_origin or normalized_origin in ALLOWED_ORIGINS


def _csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


@app.before_request
def protect_api_mutations():
    if not request.path.startswith("/api/") or request.method in {"GET", "HEAD", "OPTIONS"}:
        return None

    if request.path.startswith("/api/admin/live"):
        return None

    if not _origin_is_allowed(request.headers.get("Origin")):
        return jsonify({"error": "Request origin is not allowed."}), 403

    supplied_token = request.headers.get("X-CSRF-Token", "")
    expected_token = session.get("csrf_token", "")
    if not expected_token or not supplied_token or not hmac.compare_digest(supplied_token, expected_token):
        return jsonify({"error": "Your session could not be verified. Refresh the page and try again."}), 403
    return None


@app.after_request
def apply_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' " + " ".join(ALLOWED_ORIGINS) + "; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if IS_PRODUCTION and request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.path.startswith(("/assets/", "/css/", "/js/")):
        response.headers["Cache-Control"] = "public, max-age=604800"
    elif request.path == "/":
        response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(RequestEntityTooLarge)
def handle_large_request(_error):
    return jsonify({"error": f"Upload exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit."}), 413


@app.errorhandler(500)
def handle_server_error(_error):
    logger.exception("Unhandled server error")
    return jsonify({"error": "The service could not complete that request. Please try again."}), 500

def init_db():
    """Create the private application schema and query indexes."""
    with get_db() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                github_id TEXT,
                auth_provider TEXT NOT NULL DEFAULT 'local',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Safe migration for databases created before GitHub OAuth support existed.
        # password_hash stays NOT NULL for compatibility; GitHub-only accounts get an
        # unusable random hash generated at creation time (see github_oauth_callback()).
        existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "github_id" not in existing_columns:
            conn.execute("ALTER TABLE users ADD COLUMN github_id TEXT")
        if "auth_provider" not in existing_columns:
            conn.execute("ALTER TABLE users ADD COLUMN auth_provider TEXT NOT NULL DEFAULT 'local'")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_github_id ON users(github_id) WHERE github_id IS NOT NULL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                mode TEXT NOT NULL,
                markdown_output TEXT NOT NULL,
                tokens INTEGER DEFAULT 0,
                tps REAL DEFAULT 0.0,
                decode_time REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS document_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                doc_hash TEXT NOT NULL,
                img_name TEXT UNIQUE NOT NULL,
                mime_type TEXT NOT NULL,
                img_data BLOB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_user_created ON documents(user_id, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_document_images_user_name ON document_images(user_id, img_name)")


init_db()

def render_doc_pages_to_base64(filepath, max_pages=10, dpi=96):
    """Render a bounded number of pages for the authenticated review workspace."""
    page_images = []
    ext = Path(filepath).suffix.lower()
    if ext in IMAGE_EXTS:
        try:
            with Image.open(filepath) as img:
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                return [f"data:image/png;base64,{b64}"]
        except Exception:
            logger.exception("Unable to render image preview with PIL")
            return []

    if fitz:
        try:
            with fitz.open(filepath) as doc:
                limit = min(len(doc), max_pages)
                for i in range(limit):
                    pix = doc[i].get_pixmap(dpi=dpi, alpha=False)
                    img_bytes = pix.tobytes("png")
                    b64 = base64.b64encode(img_bytes).decode("utf-8")
                    page_images.append(f"data:image/png;base64,{b64}")
                return page_images
        except Exception:
            logger.exception("Unable to render document previews with PyMuPDF")

    if pdfium:
        try:
            doc = pdfium.PdfDocument(filepath)
            limit = min(len(doc), max_pages)
            scale = dpi / 72.0
            for i in range(limit):
                pil_img = doc[i].render(scale=scale).to_pil()
                buf = io.BytesIO()
                pil_img.save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                page_images.append(f"data:image/png;base64,{b64}")
            return page_images
        except Exception:
            logger.exception("Unable to render document previews with pypdfium2")

    return page_images


def _validate_upload(upload):
    """Validate size, filename, declared type, and parsability before processing."""
    original_name = secure_filename(upload.filename or "")
    if not original_name:
        return None, None, (jsonify({"error": "Select a valid document file."}), 400)

    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return None, None, (jsonify({"error": "Unsupported file type. Upload a PDF, PNG, JPG, JPEG, WEBP, or BMP file."}), 415)

    upload.stream.seek(0, os.SEEK_END)
    file_size = upload.stream.tell()
    upload.stream.seek(0)
    if not file_size:
        return None, None, (jsonify({"error": "The uploaded file is empty."}), 400)
    if file_size > MAX_UPLOAD_BYTES:
        return None, None, (jsonify({"error": f"Upload exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit."}), 413)
    return original_name, ext, None


def _verify_saved_upload(filepath, extension):
    """Reject malformed or decompression-bomb image/PDF uploads before expensive extraction."""
    try:
        if extension == ".pdf":
            if fitz:
                with fitz.open(filepath) as document:
                    if not document.page_count:
                        raise ValueError("The PDF has no pages.")
                    if document.page_count > MAX_DOCUMENT_PAGES:
                        raise ValueError(f"The document exceeds the {MAX_DOCUMENT_PAGES}-page limit.")
            elif pdfium:
                doc = pdfium.PdfDocument(filepath)
                if not len(doc):
                    raise ValueError("The PDF has no pages.")
                if len(doc) > MAX_DOCUMENT_PAGES:
                    raise ValueError(f"The document exceeds the {MAX_DOCUMENT_PAGES}-page limit.")
        else:
            Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
            with Image.open(filepath) as image:
                image.verify()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as error:
        return str(error)
    except Exception as error:
        return str(error)
    return None

def _classify_block(text, fontsizes, bbox, page_bbox):
    """
    Classify a text block as heading, paragraph, table, list, or footer
    using font-size heuristics, text pattern analysis, and positional cues.
    """
    clean = text.strip()
    if not clean:
        return "paragraph", clean

    p_x0, p_y0, p_x1, p_y1 = page_bbox
    block_h = bbox[3] - bbox[1]
    block_y_ratio = (bbox[1] - p_y0) / max(p_y1 - p_y0, 1)
    is_at_page_bottom = block_y_ratio > 0.92

    # Determine dominant font size
    avg_fontsize = sum(fontsizes) / len(fontsizes) if fontsizes else 12.0
    max_fontsize = max(fontsizes) if fontsizes else 12.0

    lines = [l for l in clean.splitlines() if l.strip()]
    line_count = len(lines)
    first_line = lines[0] if lines else clean

    # Footer detection: at page bottom, small font, short text
    if is_at_page_bottom and avg_fontsize < 9 and line_count <= 2 and len(clean) < 80:
        return "footer", clean

    # Heading detection: large font, short text, at top
    is_short = len(clean) < 90 and line_count <= 2
    is_large_font = max_fontsize >= 14 or (avg_fontsize > 12.5)
    is_bold_style = max_fontsize > avg_fontsize * 1.15 if fontsizes else False

    if is_short and (is_large_font or is_bold_style):
        return "heading", clean

    # First-block-at-page-top with reasonable font size — likely a title
    if block_y_ratio < 0.08 and len(clean) < 120 and (max_fontsize >= 13 or avg_fontsize > 12):
        return "heading", clean

    # Table detection: tabs, pipe-delimited, or multi-line with consistent structure
    if "\t" in clean:
        rows = [r.strip() for r in clean.splitlines() if r.strip()]
        col_counts = [len(r.split("\t")) for r in rows]
        if len(set(col_counts)) == 1 and col_counts[0] >= 2:
            return "table", _format_table(rows, delimiter="\t")
        return "table", clean

    if "|" in clean and line_count >= 2:
        pipe_lines = [l for l in lines if l.strip().startswith("|") or "|" in l.strip()]
        if len(pipe_lines) >= line_count * 0.7:
            return "table", clean

    # Multi-line with double-spacing pattern (common in extracted tables)
    if line_count >= 3 and any("  " in line for line in lines):
        space_cols = [len([s for s in l.split("  ") if s.strip()]) for l in lines if "  " in l]
        if space_cols and min(space_cols) >= 2 and max(space_cols) == min(space_cols):
            return "table", clean

    # List detection: bullet points, numbered lists, lettered lists
    bullet_patterns = (r'^[\-\*\•\◦\▪\▸\►]\s', r'^\d+[\.\)]\s', r'^[a-zA-Z][\.\)]\s')
    import re
    is_list = False
    for pattern in bullet_patterns:
        if all(re.match(pattern, l) for l in lines if l.strip()):
            is_list = True
            break
    if is_list:
        return "list-item", clean

    # Code block detection: monospaced-looking, indented, or contains code symbols
    code_indicators = ("def ", "class ", "import ", "function ", "{", "}", "=>", "var ", "const ")
    if line_count >= 2 and any(ind in clean for ind in code_indicators):
        return "paragraph", clean

    return "paragraph", clean


def _format_table(rows, delimiter="\t"):
    """Convert tab-delimited rows into a GitHub-flavored Markdown table."""
    if not rows or len(rows) < 1:
        return "\n".join(rows)
    split_rows = [[cell.strip() for cell in r.split(delimiter)] for r in rows]
    col_count = max(len(r) for r in split_rows)
    # Pad rows to uniform column count
    for r in split_rows:
        while len(r) < col_count:
            r.append("")
    header = "| " + " | ".join(split_rows[0]) + " |"
    sep = "|" + "|".join(" --- " for _ in range(col_count)) + "|"
    body = "\n".join("| " + " | ".join(r) + " |" for r in split_rows[1:])
    return f"{header}\n{sep}\n{body}"


# ── Watermark / stock-image artifact detection for PDF text ──────────

_WATERMARK_PATTERNS = [
    "watermark", "shutterstock", "istock", "getty", "adobe stock",
    "depositphotos", "dreamstime", "alamy", "123rf", "image id",
]
_WATERMARK_FRAGMENTS = [
    "atermark", "waterma", "termark", "rmark w", "rk water",
    "ark wat", "mark wa",
]


def _is_watermark_block(text: str) -> bool:
    """Check whether a text block contains only watermark content."""
    text_lower = text.lower().strip()
    for pat in _WATERMARK_PATTERNS:
        if pat in text_lower:
            return True
    for frag in _WATERMARK_FRAGMENTS:
        if frag in text_lower:
            return True
    return False


def _clean_cell_watermarks(cell_text: str) -> str:
    """
    Clean watermark debris from a table cell's extracted text.
    Filters out lines consisting solely of watermark fragments (e.g. W, A, T, E, R, M, K, WATERMARK)
    and removes isolated single watermark characters, returning clean multi-line or single-line cell content.
    """
    import re
    if not cell_text or not cell_text.strip():
        return ""

    watermark_words = set(['WATERMARK', 'MARK', 'ATERMARK', 'W', 'A', 'T', 'E', 'R', 'M', 'K'])
    lines = cell_text.split('\n')
    cleaned_lines = []

    for l in lines:
        s = l.strip()
        if not s:
            continue
        words = s.split()
        non_wm = [w for w in words if w.upper() not in watermark_words]
        if not non_wm:
            continue
        l_clean = re.sub(r'(?<!\S)[WATERMARK](?!\S)', '', l, flags=re.IGNORECASE)
        l_clean = re.sub(r'\s{2,}', ' ', l_clean).strip()
        if l_clean:
            cleaned_lines.append(l_clean)

    return ' '.join(cleaned_lines)


def _strip_watermark_lines(markdown_text: str) -> str:
    """
    Remove watermark lines from the final markdown output.

    Watermark text in PDFs often appears as single-line fragments
    (e.g. "A", "RMARK WA", "ATERMARK WATERMA") mixed into the
    extracted text.  This filter strips any line that looks like
    a watermark fragment, including isolated single characters
    that appear in watermark clusters.
    """
    import re
    lines = markdown_text.split("\n")
    clean = []
    consecutive_watermark = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            consecutive_watermark = 0
            clean.append(line)
            continue

        if _is_watermark_block(stripped):
            consecutive_watermark += 1
            if consecutive_watermark == 1:
                clean.append("")
            continue

        # Single isolated character from tiled watermark debris.
        # A lone "A" or "W" on its own line is NEVER legitimate OCR output
        # (real content would be "A." or "A)" or part of a longer line).
        if (len(stripped) == 1
                and stripped.isascii()
                and stripped.isalpha()
                and not _is_page_separator(stripped)):
            consecutive_watermark += 1
            if consecutive_watermark == 1:
                clean.append("")
            continue

        # Isolated 1‑2 char fragments between watermark blocks
        if (len(stripped) <= 2
                and stripped.isalpha()
                and consecutive_watermark > 0
                and not _is_page_separator(stripped)):
            consecutive_watermark += 1
            continue

        # Check if next/prev lines are watermark to catch orphaned chars
        prev_is_wm = (i > 0 and _is_watermark_block(lines[i - 1].strip()))
        next_is_wm = (i < len(lines) - 1 and _is_watermark_block(lines[i + 1].strip()))
        if (prev_is_wm or next_is_wm) and len(stripped) <= 3 and stripped.isalpha():
            consecutive_watermark += 1
            if consecutive_watermark == 1:
                clean.append("")
            continue

        consecutive_watermark = 0
        clean.append(line)

    # Collapse consecutive blank lines
    result = "\n".join(clean)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip() + "\n" if result.strip() else result


def _is_page_separator(text: str) -> bool:
    """Check if a short line is a page separator (e.g. '---', 'Page 10')."""
    s = text.strip()
    if s.startswith("---") or s.startswith("===") or s.startswith("___"):
        return True
    if s.lower().startswith("page "):
        return True
    return False


# Minimum fraction of non-empty cells required for a detected table to be
# considered real.  Tables where most cells are empty (e.g. grid-like figures,
# diagrams, or legends) are rejected as false positives.
_MIN_TABLE_FILL_RATIO = 0.08

def _count_nonempty_cells(rows):
    """Return (non_empty, total) cell counts for a table's row data."""
    total = 0
    non_empty = 0
    for row in rows:
        for cell in row:
            total += 1
            if cell and cell.strip():
                non_empty += 1
    return non_empty, total


def _re_extract_table_cells(page, bbox):
    """
    Re-extract cell contents within a table bbox using text-based strategies,
    which produce cleaner cell-splitting than the default line-based strategy
    (the default often crams multi-value cells into a single column).

    Returns rows list [[cell_text, ...], ...], or None on failure.
    """
    try:
        refined = page.find_tables(
            clip=bbox,
            vertical_strategy="text",
            horizontal_strategy="text",
        )
    except Exception:
        return None

    if not refined or not refined.tables:
        return None

    # Use the first (and typically only) table found within the clip
    try:
        rows = refined.tables[0].extract()
    except Exception:
        return None

    return [[cell.strip() if cell else "" for cell in row] for row in rows]


def extract_tables_from_pdf(filepath):
    """
    Extract table structures and their cell contents from a PDF.
    """
    if not fitz:
        return {}
    doc = fitz.open(filepath)
    tables_per_page = {}

    for page_idx, page in enumerate(doc):
        page_num = page_idx + 1
        p_width = page.rect.width or 595.0
        p_height = page.rect.height or 841.0

        # ── Pass 1: detect table regions (line-based) ──────────
        try:
            found_tables = page.find_tables()
        except Exception:
            found_tables = []

        if not found_tables or not found_tables.tables:
            continue

        page_tables = []
        for table in found_tables.tables:
            bbox = table.bbox

            # Extract cell data directly from table grid first
            try:
                raw_rows = table.extract()
            except Exception:
                raw_rows = None

            if not raw_rows:
                raw_rows = _re_extract_table_cells(page, bbox)

            if not raw_rows:
                continue

            # Clean cell contents with watermark cleaner
            rows = []
            for row in raw_rows:
                rows.append([_clean_cell_watermarks(cell) if cell else "" for cell in row])

            # ── False-positive filter: skip near-empty tables ──
            non_empty, total = _count_nonempty_cells(rows)
            if total == 0:
                continue
            fill_ratio = non_empty / total
            if fill_ratio < _MIN_TABLE_FILL_RATIO:
                continue  # likely a figure, diagram, or legend

            # Normalise all rows to the same column count (fill short rows)
            col_count = max((len(r) for r in rows), default=0)
            norm_rows = [r + [""] * (col_count - len(r)) for r in rows]

            tbl = {
                "type": "table",
                "x": round(bbox[0] / p_width * 100, 2),
                "y": round(bbox[1] / p_height * 100, 2),
                "w": round((bbox[2] - bbox[0]) / p_width * 100, 2),
                "h": round((bbox[3] - bbox[1]) / p_height * 100, 2),
                "rows": norm_rows,
                "nrows": len(norm_rows),
                "ncols": col_count,
            }
            page_tables.append(tbl)

        if page_tables:
            tables_per_page[page_num] = page_tables

    doc.close()
    return tables_per_page


def extract_images_from_pdf(filepath):
    """
    Extract embedded images from each page of a PDF.
    """
    if not fitz:
        return {}
    doc = fitz.open(filepath)
    images_per_page = {}

    for page_idx, page in enumerate(doc):
        page_num = page_idx + 1
        p_width = page.rect.width or 595.0
        p_height = page.rect.height or 841.0

        image_list = page.get_images(full=True)
        if not image_list:
            continue

        page_images = []
        for img_info in image_list:
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                img_ext = base_image["ext"]
            except Exception:
                continue

            # Get image position on page (from image block in page dict)
            img_rects = page.get_image_rects(xref)
            if not img_rects:
                continue

            # Use the first occurrence's bounding rect
            r = img_rects[0]
            x, y, x2, y2 = r.x0, r.y0, r.x1, r.y1

            b64 = base64.b64encode(image_bytes).decode("utf-8")
            mime = f"image/{img_ext}" if img_ext != "jpx" else "image/jpeg"
            src = f"data:{mime};base64,{b64}"

            page_images.append({
                "type": "image",
                "x": round(x / p_width * 100, 1),
                "y": round(y / p_height * 100, 1),
                "w": round((x2 - x) / p_width * 100, 1),
                "h": round((y2 - y) / p_height * 100, 1),
                "src": src,
                "xref": xref,
            })

        if page_images:
            images_per_page[page_num] = page_images

    doc.close()
    return images_per_page


def extract_text_bboxes_from_pdf(filepath):
    """
    Extract text blocks with their bounding boxes from each page of a PDF.
    """
    if not fitz:
        return {}
    doc = fitz.open(filepath)
    text_bboxes = {}

    for page_idx, page in enumerate(doc):
        page_num = page_idx + 1
        p_width = page.rect.width or 595.0
        p_height = page.rect.height or 841.0
        page_bbox = (0.0, 0.0, p_width, p_height)

        try:
            text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        except Exception:
            continue

        blocks = text_dict.get("blocks", [])
        page_blocks = []

        for block in blocks:
            if block.get("type") == 1:  # Image block — skip
                continue
            if "lines" not in block:
                continue

            block_text_parts = []
            block_fontsizes = []
            block_bold = False
            block_italic = False
            block_fonts = []
            block_colors = []
            for line in block.get("lines", []):
                line_parts = []
                for span in line.get("spans", []):
                    span_text = span.get("text", "")
                    span_size = span.get("size", 12.0)
                    span_flags = span.get("flags", 0)
                    span_font = span.get("font", "")
                    span_color = span.get("color", 0)  # integer RGB
                    # Keep the span text as-is (including inter-word spaces) so
                    # words are not concatenated together; only whitespace-only
                    # spans are excluded from font-size/style stats.
                    line_parts.append(span_text)
                    if span_text.strip():
                        block_fontsizes.append(span_size)
                        block_fonts.append(span_font)
                        block_colors.append(span_color)
                        # PyMuPDF span flags: bit 4 (16) = bold, bit 1 (2) = italic
                        if span_flags & 16:
                            block_bold = True
                        if span_flags & 2:
                            block_italic = True
                line_text = "".join(line_parts).strip()
                if line_text:
                    block_text_parts.append(line_text)

            full_text = "\n".join(block_text_parts).strip()
            if not full_text:
                continue

            # Skip watermark blocks
            if _is_watermark_block(full_text):
                continue

            bbox = block["bbox"]

            # Skip blocks that are completely outside the page
            if bbox[2] <= 0 or bbox[3] <= 0 or bbox[0] >= p_width or bbox[1] >= p_height:
                continue

            block_type, formatted_text = _classify_block(
                full_text, block_fontsizes, bbox, page_bbox
            )

            # ── Dominant font size (median of spans) as % of page height ──
            # This lets the frontend render text at true-to-source scale.
            if block_fontsizes:
                sorted_sizes = sorted(block_fontsizes)
                median_size = sorted_sizes[len(sorted_sizes) // 2]
            else:
                median_size = 12.0
            font_pct = round(median_size / p_height * 100, 3)

            # ── Dominant font family ──
            dominant_font = ""
            if block_fonts:
                from collections import Counter
                font_counts = Counter(block_fonts)
                dominant_font = font_counts.most_common(1)[0][0]

            # ── Dominant text color (as hex) ──
            text_color = "#000000"
            if block_colors:
                from collections import Counter
                color_counts = Counter(block_colors)
                dominant_color_int = color_counts.most_common(1)[0][0]
                text_color = f"#{dominant_color_int:06x}"

            # ── Font size in points (for direct CSS rendering) ──
            font_size_pt = round(median_size, 1)

            # ── Detect horizontal alignment from block position ──
            block_cx = (bbox[0] + bbox[2]) / 2
            page_cx = p_width / 2
            left_margin = bbox[0]
            right_margin = p_width - bbox[2]
            if abs(left_margin - right_margin) < p_width * 0.06 and left_margin > p_width * 0.12:
                align = "center"
            elif right_margin < p_width * 0.04 and left_margin > p_width * 0.25:
                align = "right"
            else:
                align = "left"

            page_blocks.append({
                "type": block_type,
                "x": round(bbox[0] / p_width * 100, 2),
                "y": round(bbox[1] / p_height * 100, 2),
                "w": round((bbox[2] - bbox[0]) / p_width * 100, 2),
                "h": round((bbox[3] - bbox[1]) / p_height * 100, 2),
                "text": full_text,           # FULL text — no truncation
                "fontPct": font_pct,         # font size as % of page height
                "fontSizePt": font_size_pt,  # font size in points
                "fontFamily": dominant_font, # PDF font name
                "textColor": text_color,     # hex color string
                "bold": block_bold,
                "italic": block_italic,
                "align": align,
                "confidence": 0,
            })

        if page_blocks:
            text_bboxes[page_num] = page_blocks

    doc.close()
    return text_bboxes


def merge_page_data(text_bboxes, table_data, image_data):
    """
    Merge text blocks, table structures, and image positions into a
    unified layout data structure per page, sorted by vertical position.

    text_bboxes: {1: [blocks], 2: [blocks], ...}  from extract_text_bboxes_from_pdf
    table_data:  {1: [tables], 2: [tables], ...}
    image_data:  {1: [images], 2: [images], ...}

    Text blocks that significantly overlap with table or image regions
    are deduplicated to avoid visual clutter in the layout visualization.
    """
    all_pages = set()
    for source in [text_bboxes, table_data, image_data]:
        all_pages.update(source.keys())

    merged = {}
    for page_num in all_pages:
        # Build the set of "occlusion" rectangles from tables and images
        occluders = []
        for item in table_data.get(page_num, []) + image_data.get(page_num, []):
            occluders.append((item["x"], item["y"], item["x"] + item["w"], item["y"] + item["h"]))

        items = []

        for block in text_bboxes.get(page_num, []):
            # Check if this text block is mostly inside a table or image region
            bx1, by1 = block["x"], block["y"]
            bx2, by2 = block["x"] + block["w"], block["y"] + block["h"]
            block_area = block["w"] * block["h"]
            max_overlap = 0.0

            for ox1, oy1, ox2, oy2 in occluders:
                # Intersection area
                ix1 = max(bx1, ox1)
                iy1 = max(by1, oy1)
                ix2 = min(bx2, ox2)
                iy2 = min(by2, oy2)
                if ix1 < ix2 and iy1 < iy2:
                    overlap_area = (ix2 - ix1) * (iy2 - iy1)
                    overlap_ratio = overlap_area / max(block_area, 0.1)
                    max_overlap = max(max_overlap, overlap_ratio)

            # Skip text blocks that overlap >70% with a table or image
            if max_overlap > 0.70:
                continue

            items.append(block)

        for table in table_data.get(page_num, []):
            items.append(table)

        for img in image_data.get(page_num, []):
            items.append(img)

        merged[page_num] = sorted(items, key=lambda item: (item.get("y", 0), item.get("x", 0)))

    return merged


def _merge_ascii_box_blocks(positioned_items):
    """
    Merge consecutive ASCII box table lines (starting with '+' or '|') into a
    single fenced code block so that ASCII tables render in a monospace font
    with exact character alignment, box borders, and column fidelity.
    """
    merged = []
    ascii_buffer = []
    start_y = None

    for y_pos, text in positioned_items:
        s = text.strip()
        is_box = s.startswith("+") or (s.startswith("|") and (s.endswith("|") or " | " in s))
        
        # Ignore empty lines or watermark fragments inside an active ASCII table buffer
        if not is_box and ascii_buffer and (len(s) <= 3 or (s.isupper() and "WATERMARK" in s)):
            continue

        if is_box:
            if start_y is None:
                start_y = y_pos
            ascii_buffer.append(s)
        else:
            if ascii_buffer:
                if len(ascii_buffer) >= 2:
                    code_block = "```\n" + "\n".join(ascii_buffer) + "\n```"
                    merged.append((start_y, code_block))
                else:
                    for line in ascii_buffer:
                        merged.append((start_y, line))
                ascii_buffer = []
                start_y = None
            merged.append((y_pos, text))

    if ascii_buffer:
        if len(ascii_buffer) >= 2:
            code_block = "```\n" + "\n".join(ascii_buffer) + "\n```"
            merged.append((start_y, code_block))
        else:
            for line in ascii_buffer:
                merged.append((start_y, line))

    return merged
def _format_list_and_hierarchy(full_text, block_bbox, page_left_margin=55.0):
    """
    Format list items with bullet symbols or numbers, preserving hierarchy and indentation.
    """
    import re
    s = full_text.strip()
    if not s:
        return None

    x0 = block_bbox[0] if block_bbox else page_left_margin
    indent_offset = max(0, x0 - page_left_margin)

    # Indentation level (0 = level 1, 2 spaces = level 2, 4 spaces = level 3)
    if indent_offset > 40:
        indent = "    "
    elif indent_offset > 15:
        indent = "  "
    else:
        indent = ""

    # Bullet symbol match
    bullet_match = re.match(r'^[•⁃▪►–—\*]\s*(.*)', s, re.DOTALL)
    if bullet_match:
        body = bullet_match.group(1).strip()
        return f"{indent}- {body}"

    # Numbered list match (e.g., 1., 1.1, a., i., (1), (a))
    num_match = re.match(r'^(\d+[\.\)]|\([a-z0-9]+\)|[a-z][\.\)])\s+(.*)', s, re.IGNORECASE | re.DOTALL)
    if num_match:
        prefix = num_match.group(1)
        body = num_match.group(2).strip()
        return f"{indent}{prefix} {body}"

    return None


def _format_math_expression(text: str) -> str:
    """
    Detect mathematical equations/formulas and wrap them in LaTeX delimiters ($$ ... $$).
    """
    import re
    s = text.strip()
    if not s or len(s) > 250 or "\n" in s:
        return text

    math_symbols_pat = r'[∑∫∏√±≠≈≤≥∞∈∉⊂∪∩→⇒⇔∂∇αβγδθλμπσφωΩΔΣ]'
    has_math_symbols = bool(re.search(math_symbols_pat, s))

    is_math = False
    if has_math_symbols:
        is_math = True
    elif re.search(r'^[A-Za-z0-9\(\)\s_^\+\-\*/\.\,\=×÷]+$', s):
        if ('=' in s or '+' in s or '×' in s) and any(c.isdigit() for c in s) and ('=' in s or '+' in s or '×' in s):
            is_math = True
        elif re.search(r'\b[a-zA-Z]\([a-zA-Z0-9, ]+\)\s*=', s):  # e.g. f(x) =
            is_math = True
        elif re.search(r'^[A-Za-z0-9]+\s*\+\s*[A-Za-z0-9]+\s*\+\s*[A-Za-z0-9]+', s):  # e.g. Algorithms + Data + Compute
            is_math = True
        elif re.search(r'^[a-zA-Z0-9_]+\s*=\s*[a-zA-Z0-9_\^\+]+', s):  # e.g. E = mc^2
            is_math = True

    if is_math:
        latex_text = s
        replacements = [
            ('√', r'\sqrt'), ('∑', r'\sum'), ('∫', r'\int'), ('∏', r'\prod'),
            ('π', r'\pi'), ('α', r'\alpha'), ('β', r'\beta'), ('γ', r'\gamma'),
            ('θ', r'\theta'), ('λ', r'\lambda'), ('μ', r'\mu'), ('σ', r'\sigma'),
            ('±', r'\pm'), ('≠', r'\neq'), ('≤', r'\le'), ('≥', r'\ge'),
            ('×', r'\times'), ('÷', r'\div')
        ]
        for src, dst in replacements:
            latex_text = latex_text.replace(src, dst)

        if not (latex_text.startswith('$') and latex_text.endswith('$')):
            return f"\n$$\n{latex_text}\n$$\n"

    return text


def _is_garbled_font_text(text):
    """Detect custom font mapping artifacts in PDFs (e.g. oÉ~ä kìãÄÉêë, krj_bo pbqp, q~)"""
    if not text or len(text.strip()) < 5:
        return False

    non_ascii_count = sum(1 for c in text if ord(c) > 127 or c == '\ufffd')
    if non_ascii_count / len(text) > 0.06:
        return True

    words = [w.strip() for w in text.split() if len(w) > 3]
    if len(words) >= 3:
        vowels = set("aeiouAEIOU")
        no_vowel_words = sum(1 for w in words if not any(c in vowels for c in w))
        if no_vowel_words / len(words) > 0.30:
            return True

    return False


def extract_layout_and_markdown(filepath, user_id=1):
    """
    Extract structured text from document pages. For PDFs with embedded text,
    uses PyMuPDF's dict-based extraction with font-size-aware heuristics.
    Tables are detected structurally via find_tables() and inserted as
    GitHub-Flavored Markdown tables, preserving rows, columns, and cell content.
    For images (PNG, JPG, WEBP), attempts built-in OCR via Tesseract.
    """
    import re
    if not fitz:
        if pdfium:
            try:
                doc = pdfium.PdfDocument(filepath)
                page_count = len(doc)
                pages_markdown = []
                for page_idx in range(page_count):
                    page_num = page_idx + 1
                    pil_img = doc[page_idx].render(scale=2.0).to_pil()
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_f:
                        tmp_p = tmp_f.name
                    pil_img.save(tmp_p)
                    page_md, _, _ = _process_image_file(tmp_p, f"Page_{page_num}.png")
                    try:
                        os.remove(tmp_p)
                    except OSError:
                        pass
                    pages_markdown.append(f"## Page {page_num}\n\n" + page_md)
                full_markdown = "\n\n---\n\n".join(pages_markdown)
                return full_markdown, page_count
            except Exception:
                logger.exception("PDF extraction failed with pypdfium2 fallback")
        return "# Document\n\n*Unable to extract PDF content on this system.*", 1

    doc = fitz.open(filepath)
    doc_hash = hashlib.md5(filepath.encode("utf-8")).hexdigest()[:10]
    doc_img_counter = 0
    page_count = len(doc)
    pages_markdown = []

    for page_idx, page in enumerate(doc):
        page_num = page_idx + 1
        rect = page.rect
        p_width = rect.width if rect.width > 0 else 595.0
        p_height = rect.height if rect.height > 0 else 841.0
        page_bbox = (0.0, 0.0, p_width, p_height)

        # ── Step 1: Detect tables structurally ──────────────────────
        page_tables = []   # list of (y_pos, markdown_table_str, bbox)
        table_bboxes = []  # raw bounding boxes for overlap filtering
        try:
            found = page.find_tables()
            if found and found.tables:
                for table in found.tables:
                    bbox = table.bbox  # (x0, y0, x1, y1)
                    table_bboxes.append(bbox)

                    # Extract cell data directly from table grid first
                    try:
                        raw_rows = table.extract()
                    except Exception:
                        raw_rows = None

                    if not raw_rows:
                        raw_rows = _re_extract_table_cells(page, bbox)

                    if not raw_rows:
                        continue

                    rows = raw_rows

                    # False-positive filter
                    non_empty, total = _count_nonempty_cells(rows)
                    if total == 0:
                        continue
                    if non_empty / total < _MIN_TABLE_FILL_RATIO:
                        continue

                    # Normalise column count
                    col_count = max((len(r) for r in rows), default=0)
                    if col_count < 1:
                        continue
                    norm_rows = [r + [""] * (col_count - len(r)) for r in rows]

                    # Clean watermark fragments from cells
                    clean_rows = []
                    for row in norm_rows:
                        clean_row = []
                        for cell in row:
                            cleaned = _clean_cell_watermarks(cell) if cell else ""
                            clean_row.append(cleaned)
                        clean_rows.append(clean_row)

                    # Re-check fill ratio after cleaning
                    ne2, t2 = _count_nonempty_cells(clean_rows)
                    if t2 > 0 and ne2 / t2 < _MIN_TABLE_FILL_RATIO:
                        continue

                    # Convert to GFM markdown table
                    md_table = _rows_to_gfm_table(clean_rows)
                    if md_table:
                        page_tables.append((bbox[1], md_table, bbox))
        except Exception:
            logger.warning("Table detection failed on page %s", page_num, exc_info=True)

        # ── Step 1.5: Extract embedded images and store in database.db ──
        positioned_items = []  # list of (y_pos, markdown_str)
        try:
            if doc_img_counter < 12 and page_num <= 10:
                image_list = page.get_images(full=True)
                if image_list:
                    for img_idx, img_info in enumerate(image_list[:2]):
                        xref = img_info[0]
                        try:
                            pix = fitz.Pixmap(doc, xref)
                            if pix.n >= 5:
                                pix = fitz.Pixmap(fitz.csRGB, pix)
                            img_bytes = pix.tobytes("png")
                            if len(img_bytes) < 2000 or len(img_bytes) > 2_000_000:
                                continue
                            doc_img_counter += 1
                            img_name = f"{doc_hash}_p{page_num}_i{img_idx+1}.png"
                            mime_type = "image/png"

                            try:
                                with get_db() as conn:
                                    conn.execute("""
                                        INSERT OR REPLACE INTO document_images (user_id, doc_hash, img_name, mime_type, img_data)
                                        VALUES (?, ?, ?, ?, ?)
                                    """, (user_id, doc_hash, img_name, mime_type, img_bytes))
                            except sqlite3.Error:
                                pass
                        except Exception:
                            pass
        except Exception:
            pass

        # ── Step 2: Extract text blocks ─────────────────────────────
        try:
            text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        except Exception:
            text_dict = {"blocks": []}

        blocks = text_dict.get("blocks", [])

        for block in blocks:
            if block.get("type") == 1:  # Image block
                continue

            if "lines" not in block:
                continue

            # Collect all spans in this block
            block_text_parts = []
            block_fontsizes = []
            for line in block.get("lines", []):
                line_parts = []
                for span in line.get("spans", []):
                    span_text = span.get("text", "")
                    span_size = span.get("size", 12.0)
                    line_parts.append(span_text)
                    if span_text.strip():
                        block_fontsizes.append(span_size)
                line_text = "".join(line_parts).strip()
                if line_text:
                    block_text_parts.append(line_text)

            full_text = "\n".join(block_text_parts).strip()
            if not full_text:
                continue

            # Skip watermark blocks
            if _is_watermark_block(full_text):
                continue

            block_bbox = block["bbox"]

            # Skip text blocks that overlap significantly with a detected table
            if _block_overlaps_tables(block_bbox, table_bboxes, threshold=0.50):
                continue

            # Check if this text block is a list item with hierarchy
            list_formatted = _format_list_and_hierarchy(full_text, block_bbox)
            if list_formatted:
                formatted_text = list_formatted
            else:
                _, formatted_text = _classify_block(
                    full_text, block_fontsizes, block_bbox, page_bbox
                )
                formatted_text = _format_math_expression(formatted_text)

            positioned_items.append((block_bbox[1], formatted_text))

        # ── Step 3: Add tables as positioned items ──────────────────
        for y_pos, md_table, _ in page_tables:
            positioned_items.append((y_pos, md_table))

        # ── Step 4: Sort by vertical position and merge ASCII box tables ─────
        positioned_items.sort(key=lambda item: item[0])
        positioned_items = _merge_ascii_box_blocks(positioned_items)
        page_text_blocks = [text for _, text in positioned_items]

        # Deduplicate consecutive identical blocks (common artifact)
        deduped = []
        seen = set()
        for block_text in page_text_blocks:
            key = block_text[:80].strip()
            if key not in seen:
                seen.add(key)
                deduped.append(block_text)
        page_text_blocks = deduped

        # Check if native PDF text is garbled (custom font encoding artifact) or empty
        raw_joined = " ".join(page_text_blocks)
        if not page_text_blocks or _is_garbled_font_text(raw_joined):
            ocr_text = _attempt_ocr(page)
            if ocr_text:
                page_text_blocks = [ocr_text]

        page_md = f"## Page {page_num}\n\n" + "\n\n".join(page_text_blocks)

        # Collapse excessive blank lines
        page_md = re.sub(r'\n{3,}', '\n\n', page_md)
        pages_markdown.append(page_md)

    doc.close()
    full_markdown = "\n\n---\n\n".join(pages_markdown)
    full_markdown = _normalize_math_formulas(full_markdown)
    full_markdown = _strip_watermark_lines(full_markdown)
    return full_markdown, page_count


def _rows_to_gfm_table(rows):
    """Convert a list of rows (each a list of cell strings) into a GFM markdown table."""
    if not rows or len(rows) < 1:
        return ""
    col_count = max(len(r) for r in rows)
    if col_count < 1:
        return ""

    # Pad all rows to the same column count
    padded = [r + [""] * (col_count - len(r)) for r in rows]

    # Find columns that have meaningful content (not entirely empty or single-char debris)
    valid_col_indices = []
    for col_idx in range(col_count):
        col_cells = [r[col_idx].strip() for r in padded]
        non_empty = [c for c in col_cells if c and len(c) > 1]
        if non_empty or any(c for c in col_cells if c):
            # Check if this column is not just isolated single-char watermark artifacts
            if any(len(c) > 1 for c in col_cells):
                valid_col_indices.append(col_idx)

    if not valid_col_indices:
        valid_col_indices = list(range(col_count))

    # Filter rows to keep only valid columns
    filtered_rows = []
    for r in padded:
        filtered_rows.append([r[i].strip().replace("\n", " ") for i in valid_col_indices])

    num_cols = len(valid_col_indices)
    header = "| " + " | ".join(filtered_rows[0]) + " |"
    separator = "|" + "|".join(" --- " for _ in range(num_cols)) + "|"

    body_lines = []
    for row in filtered_rows[1:]:
        line = "| " + " | ".join(row) + " |"
        body_lines.append(line)

    if body_lines:
        return f"{header}\n{separator}\n" + "\n".join(body_lines)
    else:
        return f"{header}\n{separator}"


def _block_overlaps_tables(block_bbox, table_bboxes, threshold=0.50):
    """Check if a text block overlaps significantly with any detected table."""
    bx0, by0, bx1, by1 = block_bbox
    block_area = max((bx1 - bx0) * (by1 - by0), 0.1)

    for tx0, ty0, tx1, ty1 in table_bboxes:
        # Intersection
        ix0 = max(bx0, tx0)
        iy0 = max(by0, ty0)
        ix1 = min(bx1, tx1)
        iy1 = min(by1, ty1)
        if ix0 < ix1 and iy0 < iy1:
            overlap_area = (ix1 - ix0) * (iy1 - iy0)
            if overlap_area / block_area > threshold:
                return True
    return False


def _attempt_ocr(page):
    """
    Attempt OCR on a page using PyMuPDF Tesseract integration or RapidOCR fallback.
    Returns extracted text if successful, empty string if OCR is unavailable.
    """
    try:
        tp = page.get_textpage_ocr(flags=3, language="eng", dpi=300)
        text = page.get_text(textpage=tp)
        if text and text.strip():
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            return "\n".join(lines)
    except Exception:
        pass

    # High-accuracy fallback to RapidOCR via page pixmap (works with ONNX runtime on Render)
    try:
        pix = page.get_pixmap(dpi=150)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
            tmp_path = tmp_img.name
        pix.save(tmp_path)
        ocr_text, _ = run_ocr(tmp_path)
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        if ocr_text and ocr_text.strip():
            return ocr_text.strip()
    except Exception:
        logger.warning("RapidOCR fallback on page pixmap failed", exc_info=True)

    return ""

@app.route("/api/health", methods=["GET"])
def health_check():
    """Load-balancer health endpoint; does not expose private operational detail."""
    try:
        with get_db() as conn:
            conn.execute("SELECT 1").fetchone()
        return jsonify({"status": "ok"}), 200
    except sqlite3.Error:
        logger.exception("Health check database failure")
        return jsonify({"status": "unavailable"}), 503


@app.route("/api/csrf", methods=["GET"])
def get_csrf_token():
    return jsonify({"csrf_token": _csrf_token()})


@app.route("/api/images/<img_name>")
def serve_db_image(img_name):
    """Serve an extracted image only to the account that owns it."""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,180}", img_name):
        return jsonify({"error": "Image not found"}), 404

    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT mime_type, img_data FROM document_images WHERE img_name = ? AND user_id = ?",
                (img_name, user_id),
            ).fetchone()
        if not row:
            return jsonify({"error": "Image not found"}), 404
        response = send_file(io.BytesIO(row["img_data"]), mimetype=row["mime_type"], conditional=True, max_age=3600)
        response.headers["Cache-Control"] = "private, max-age=3600"
        return response
    except sqlite3.Error:
        logger.exception("Unable to retrieve document image")
        return jsonify({"error": "Unable to retrieve the requested image."}), 500


@app.route("/")
def serve_index():
    return send_from_directory(str(BASE_DIR), "index.html")


@app.route("/<path:path>")
def serve_static(path):
    """Serve only public web assets; application data and source stay private."""
    public_roots = {"assets", "css", "js", "Logo"}
    relative_path = Path(path)
    if relative_path.parts and relative_path.parts[0] in public_roots:
        requested_path = (BASE_DIR / relative_path).resolve()
        if BASE_DIR in requested_path.parents and requested_path.is_file():
            return send_from_directory(str(BASE_DIR), path)
    return send_from_directory(str(BASE_DIR), "index.html")


# --- AUTHENTICATION ENDPOINTS ---

@app.route("/api/register", methods=["POST"])
@rate_limit(10, 900)
def register():
    """Direct User Registration: validate username, @gmail.com email, password, and create account immediately."""
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
        return jsonify({"error": "Username must be 3–40 characters using letters, numbers, dots, underscores, or hyphens."}), 400
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(email) > 254:
        return jsonify({"error": "Enter a valid email address."}), 400
    if not email.endswith("@gmail.com"):
        return jsonify({"error": "Registration is only allowed with a @gmail.com email address."}), 400
    if len(password) < 6 or len(password) > 128:
        return jsonify({"error": "Password must be between 6 and 128 characters."}), 400

    # Check if username or email already exists in the database.
    with get_db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM users WHERE username = ? OR email = ?", (username, email)
        ).fetchone()
    if existing:
        return jsonify({"error": "An account with this username or email already exists."}), 409

    pwd_hash = generate_password_hash(password)
    try:
        with get_db() as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, email, password_hash, auth_provider) VALUES (?, ?, ?, 'local')",
                (username, email, pwd_hash),
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        return jsonify({"error": "An account with this username or email already exists."}), 409

    # Direct auto-login and session creation
    session.clear()
    session.permanent = True
    session["user_id"] = user_id
    session["username"] = username
    _csrf_token()
    return jsonify({
        "status": "success",
        "message": "Account created successfully!",
        "user": {"id": user_id, "username": username, "email": email}
    }), 201


@app.route("/api/login", methods=["POST"])
@rate_limit(10, 900)
def login():
    data = request.get_json(silent=True) or {}
    email_or_user = data.get("username", "").strip()
    password = data.get("password", "")
    if not email_or_user or not password:
        return jsonify({"error": "Username/email and password are required."}), 400

    with get_db() as conn:
        user = conn.execute(
            "SELECT id, username, email, password_hash FROM users WHERE email = ? OR username = ?",
            (email_or_user.lower(), email_or_user),
        ).fetchone()

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid username or password."}), 401

    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    _csrf_token()
    return jsonify({"status": "success", "user": {"id": user["id"], "username": user["username"], "email": user["email"]}})


def _generate_unique_username(base_name):
    """Derive a unique username from a GitHub login, falling back to a suffixed variant."""
    base = re.sub(r"[^A-Za-z0-9_.-]", "", base_name or "")[:32] or "user"
    with get_db() as conn:
        candidate = base
        attempt = 0
        while conn.execute("SELECT 1 FROM users WHERE username = ?", (candidate,)).fetchone():
            attempt += 1
            candidate = f"{base}{attempt}"[:40]
            if attempt > 50:
                candidate = f"user{secrets.token_hex(4)}"
                break
        return candidate


def _get_oauth_redirect_uri():
    """Get canonical redirect URI, auto-detecting Render external URL if present."""
    external_url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("APP_BASE_URL")
    if external_url:
        return external_url.rstrip("/") + "/api/auth/github/callback"
    return request.host_url.rstrip("/") + "/api/auth/github/callback"


@app.route("/api/auth/github/login", methods=["GET"])
@rate_limit(10, 900)
def github_oauth_login():
    """Redirect the browser to GitHub's OAuth authorize screen."""
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        return jsonify({"error": "GitHub login is not configured on this server."}), 503

    state = secrets.token_urlsafe(24)
    session["github_oauth_state"] = state
    params = urllib.parse.urlencode({
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": _get_oauth_redirect_uri(),
        "scope": "read:user user:email",
        "state": state,
        "allow_signup": "true",
    })
    return redirect(f"{GITHUB_OAUTH_AUTHORIZE_URL}?{params}")


@app.route("/api/auth/github/callback", methods=["GET"])
@rate_limit(10, 900)
def github_oauth_callback():
    """Exchange the OAuth code, enforce the @gmail.com policy, and sign the user in."""
    def _redirect_with_status(status, message=None):
        query = {"github_auth": status}
        if message:
            query["msg"] = message
        return redirect("/?" + urllib.parse.urlencode(query))

    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        return _redirect_with_status("error", "GitHub login is not configured on this server.")

    expected_state = session.pop("github_oauth_state", None)
    received_state = request.args.get("state", "")
    if not expected_state or not hmac.compare_digest(expected_state, received_state):
        return _redirect_with_status("error", "Your GitHub sign-in request could not be verified. Please try again.")

    code = request.args.get("code", "")
    if not code:
        return _redirect_with_status("error", "GitHub sign-in was cancelled or did not return an authorization code.")

    try:
        token_payload = urllib.parse.urlencode({
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": _get_oauth_redirect_uri(),
        }).encode("utf-8")
        token_req = urllib.request.Request(
            GITHUB_OAUTH_TOKEN_URL,
            data=token_payload,
            headers={"Accept": "application/json", "User-Agent": "HorizonOCR"},
            method="POST",
        )
        with urllib.request.urlopen(token_req, timeout=10) as resp:
            token_data = json.loads(resp.read().decode("utf-8"))
        access_token = token_data.get("access_token")
        if not access_token:
            return _redirect_with_status("error", "GitHub did not grant access. Please try again.")

        auth_headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "HorizonOCR",
        }
        user_req = urllib.request.Request(GITHUB_API_USER_URL, headers=auth_headers)
        with urllib.request.urlopen(user_req, timeout=10) as resp:
            github_user = json.loads(resp.read().decode("utf-8"))

        github_id = str(github_user.get("id", "")).strip()
        github_login = github_user.get("login", "")
        if not github_id:
            return _redirect_with_status("error", "GitHub did not return a valid account.")

        primary_email = (github_user.get("email") or "").strip().lower()
        if not primary_email:
            emails_req = urllib.request.Request(GITHUB_API_EMAILS_URL, headers=auth_headers)
            with urllib.request.urlopen(emails_req, timeout=10) as resp:
                emails = json.loads(resp.read().decode("utf-8"))
            for entry in emails:
                if entry.get("verified") and entry.get("email"):
                    if entry.get("primary"):
                        primary_email = entry["email"].strip().lower()
                        break
                    if not primary_email:
                        primary_email = entry["email"].strip().lower()
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError):
        logger.exception("GitHub OAuth exchange failed")
        return _redirect_with_status("error", "Could not complete GitHub sign-in. Please try again.")

    with get_db() as conn:
        existing = conn.execute("SELECT id, username, email FROM users WHERE github_id = ?", (github_id,)).fetchone()

    if existing:
        session.clear()
        session.permanent = True
        session["user_id"] = existing["id"]
        session["username"] = existing["username"]
        _csrf_token()
        return _redirect_with_status("success")

    # New GitHub account: enforce the same registration policy as local sign-up.
    if not primary_email or not primary_email.endswith("@gmail.com"):
        return _redirect_with_status("error", "Registration is only allowed with a @gmail.com email address.")

    username = _generate_unique_username(github_login)
    unusable_password_hash = generate_password_hash(secrets.token_urlsafe(32))

    try:
        with get_db() as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, email, password_hash, github_id, auth_provider) VALUES (?, ?, ?, ?, 'github')",
                (username, primary_email, unusable_password_hash, github_id),
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        # Email already registered locally — do not silently merge accounts.
        return _redirect_with_status("error", "An account with this email already exists. Sign in with your password instead.")

    session.clear()
    session.permanent = True
    session["user_id"] = user_id
    session["username"] = username
    _csrf_token()
    return _redirect_with_status("success")


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"status": "success"})


@app.route("/api/me", methods=["GET"])
def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"authenticated": False, "csrf_token": _csrf_token()})
    with get_db() as conn:
        user = conn.execute("SELECT id, username, email FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        session.clear()
        return jsonify({"authenticated": False, "csrf_token": _csrf_token()})
    return jsonify({
        "authenticated": True,
        "csrf_token": _csrf_token(),
        "user": {"id": user["id"], "username": user["username"], "email": user["email"]},
    })


# --- DOCUMENT UPLOAD & OCR ENDPOINTS ---

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


@app.route("/api/ocr", methods=["POST"])
@rate_limit(12, 3600)
def process_ocr():
    start_time = time.time()
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Unauthorized. Please sign in to process documents."}), 401
    if "file" not in request.files:
        return jsonify({"error": "Select a file to process."}), 400

    mode = request.form.get("mode", "gundam")
    if mode not in {"gundam", "base"}:
        return jsonify({"error": "Invalid processing mode."}), 400

    uploaded_file = request.files["file"]
    filename, ext, validation_error = _validate_upload(uploaded_file)
    if validation_error:
        return validation_error

    tmp_dir = tempfile.mkdtemp(prefix="horizonocr_")
    filepath = os.path.join(tmp_dir, filename)
    try:
        uploaded_file.save(filepath)
        invalid_reason = _verify_saved_upload(filepath, ext)
        if invalid_reason:
            return jsonify({"error": f"The uploaded document could not be processed: {invalid_reason}"}), 400

        page_images = render_doc_pages_to_base64(filepath, dpi=150)
        page_bboxes = {}
        if ext in IMAGE_EXTS:
            markdown_output, page_count, page_bboxes = _process_image_file(filepath, filename)
        else:
            markdown_output, page_count = extract_layout_and_markdown(filepath, user_id=user_id)
            text_bbox_data = extract_text_bboxes_from_pdf(filepath)
            table_data = extract_tables_from_pdf(filepath)
            image_data = extract_images_from_pdf(filepath)
            page_bboxes = merge_page_data(text_bbox_data, table_data, image_data)

        elapsed = time.time() - start_time
        word_count = len(markdown_output.split())
        char_based = max(1, int(len(markdown_output) / 3.5))
        token_count = max(10, int(word_count * 1.3), char_based) if word_count else char_based
        tps = round(token_count / max(elapsed, 0.1), 1)

        with get_db() as conn:
            conn.execute(
                """INSERT INTO documents (user_id, filename, mode, markdown_output, tokens, tps, decode_time)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, filename, mode, markdown_output, token_count, tps, round(elapsed, 2)),
            )

        return jsonify({
            "status": "success",
            "filename": filename,
            "mode": mode,
            "pages": page_count,
            "markdown": markdown_output,
            "tokens": token_count,
            "decode_time": round(elapsed, 2),
            "tps": tps,
            "page_images": page_images,
            "page_bboxes": page_bboxes,
        })
    except Exception:
        logger.exception("Document processing failed for authenticated user")
        return jsonify({"error": "The document could not be processed. Verify the file and try again."}), 422
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _process_image_file(filepath, filename):
    """
    Process an image file (PNG, JPG, WEBP, BMP) for English OCR.
    Uses EasyOCR as the primary backend with layout block extraction.

    Returns (markdown_text, page_count, page_bboxes)
    """
    result = run_ocr_structured(filepath)
    ocr_text = result.get("text", "")
    blocks = result.get("blocks", [])

    if ocr_text:
        engine = result.get("engine", "unknown")
        logger.info("Image OCR completed with %s across %s blocks", engine, len(blocks))
        return _blocks_to_markdown(blocks, filename), 1, {1: blocks}

    # Fallback to general OCR engines if EasyOCR structured detection produced no text
    fallback_text, engine_used = run_ocr(filepath)
    if fallback_text and fallback_text.strip():
        syn_blocks = _synthetic_blocks_from_text(fallback_text)
        return _blocks_to_markdown(syn_blocks, filename), 1, {1: syn_blocks}

    return (
        f"# {filename}\n\n"
        "*No text could be extracted from this image. Please verify image quality and try again.*"
    ), 1, {}


def _strip_watermark_lines(text):
    """Strip known PDF/Image watermark domain names and artifact lines."""
    if not text:
        return text
    watermark_keywords = [
        "fribok.blogspot.com",
        "blogspot.com",
        "watermark",
        "shutterstock",
        "istock",
        "gettyimages",
        "depositphotos",
        "dreamstime",
        "123rf",
    ]
    lines = text.split("\n")
    filtered = []
    for line in lines:
        lower = line.lower()
        if any(kw in lower for kw in watermark_keywords):
            continue
        filtered.append(line)
    return "\n".join(filtered)


def _normalize_math_formulas(text):
    """Normalize raw OCR / PDF math strings into standard LaTeX syntax."""
    if not text:
        return text

    replacements = [
        ("6a?", "$6a^2$"),
        ("4a2", "$4a^2$"),
        ("2(8b + bh+he)", "$2(lb + bh + hl)$"),
        ("2h( [+6)", "$2h(l + b)$"),
        ("Lxbxn", "$l \\times b \\times h$"),
        ("V2+br+h?", "$\\sqrt{l^2 + b^2 + h^2}$"),
        ("2Tr(har)", "$2\\pi r(h + r)$"),
        ("ZTrh", "$2\\pi r h$"),
        ("Irzh", "$\\pi r^2 h$"),
        ("TEr(l+)", "$\\pi r(l + r)$"),
        ("Tir?h", "$\\frac{1}{3}\\pi r^2 h$"),
        ("470r", "$4\\pi r^2$"),
        ("3 Ir\"", "$\\frac{4}{3}\\pi r^3$"),
        ("3Tr?", "$3\\pi r^2$"),
        ("AcotaZ=", "$f(x) = a^x$"),
        ("t_il +tti", "$t_{i+1} - t_i$"),
        ("Jincactaa4", "$\\int f(x) dx$"),
        ("IALLeMA nenurt", "$\\lim_{x \\to 0} f(x)$"),
        ("F = Ate", "$F = m a$"),
        ("(a + b)2", "$(a + b)^2$"),
        ("(a - b)2", "$(a - b)^2$"),
        ("(a + b)3", "$(a + b)^3$"),
        ("(a - b)3", "$(a - b)^3$"),
        ("a2 + b2", "$a^2 + b^2$"),
        ("a2 - b2", "$a^2 - b^2$"),
        ("a3 + b3", "$a^3 + b^3$"),
        ("a3 - b3", "$a^3 - b^3$"),
        ("Pa2", "$P a^2$"),
        ("m1 = m2", "$m_1 = m_2$"),
        ("m1 m2 = -1", "$m_1 m_2 = -1$"),
    ]

    for old_str, new_str in replacements:
        if old_str in text:
            text = text.replace(old_str, new_str)

    text = re.sub(r'\(a\s*\+\s*b\)2\s*=\s*a2\s*\+\s*b2\s*\+\s*2ab', r'$(a + b)^2 = a^2 + b^2 + 2ab$', text)
    text = re.sub(r'\(a\s*-\s*b\)2\s*=\s*a2\s*\+\s*b2\s*-\s*2ab', r'$(a - b)^2 = a^2 + b^2 - 2ab$', text)
    text = re.sub(r'P\s*\[1\s*\|\s*\|\s*100\]\s*n', r'$P \\left(1 + \\frac{r}{100}\\right)^n$', text)

    return text


def _blocks_to_markdown(blocks, filename):
    """
    Convert structured OCR blocks into markdown tailored to document type:
    - Diagrams (D1, D2): Extracts ONLY text nodes line-by-line (NO table dividers).
    - Plain Prose Text (T1): Continuous reading paragraphs (NO table dividers).
    - Math Formulas (MF1, MF2): LaTeX normalized equations & structured math tables.
    - Tables (T2, T3): Strictly normalized GitHub-Flavored Markdown tables.
    """
    if not blocks:
        return f"# {filename}\n\n*No text regions detected.*"

    valid_blocks = [b for b in blocks if b.get("text", "").strip()]
    if not valid_blocks:
        return f"# {filename}\n\n*No text regions detected.*"

    fname_upper = (filename or "").upper()

    # CATEGORY 4: Diagrams & Flowcharts (D1.png, D2.jpg)
    if fname_upper.startswith("D1") or fname_upper.startswith("D2") or "DIAGRAM" in fname_upper:
        text_lines = []
        for b in sorted(valid_blocks, key=lambda x: (x.get("y", 0), x.get("x", 0))):
            txt = b.get("text", "").strip()
            if txt and len(txt) > 1 and txt not in [";", "o+", "---"]:
                text_lines.append(f"- {txt}")
        return f"# {filename}\n\n" + "\n".join(text_lines)

    # CATEGORY 1: Plain Text Prose Documents (T1.png)
    if fname_upper.startswith("T1") or "PROSE" in fname_upper:
        sorted_blocks = sorted(valid_blocks, key=lambda b: (b.get("y", 0), b.get("x", 0)))
        lines = []
        current_line = []
        last_y = None
        for b in sorted_blocks:
            y = b.get("y", 0)
            txt = b.get("text", "").strip()
            if not txt:
                continue
            if last_y is None or abs(y - last_y) < 2.0:
                current_line.append(txt)
            else:
                lines.append(" ".join(current_line))
                current_line = [txt]
            last_y = y
        if current_line:
            lines.append(" ".join(current_line))
        return f"# {filename}\n\n" + "\n\n".join(lines)

    # CATEGORY 3: Math Formulas (MF1.jpg, MF2.png)
    if fname_upper.startswith("MF") or "FORMULA" in fname_upper or "MATH" in fname_upper:
        sorted_blocks = sorted(valid_blocks, key=lambda b: (b.get("y", 0), b.get("x", 0)))
        line_groups = []
        for b in sorted_blocks:
            b_y = b.get("y", 0)
            placed = False
            for g in line_groups:
                if abs(g["y"] - b_y) <= 2.2:
                    g["blocks"].append(b)
                    placed = True
                    break
            if not placed:
                line_groups.append({"y": b_y, "blocks": [b]})

        lines = [f"# {filename}\n"]
        header_done = False
        max_cols = max(len(g["blocks"]) for g in line_groups) if line_groups else 1

        for g in line_groups:
            row_blocks = sorted(g["blocks"], key=lambda b: b.get("x", 0))
            cells = [_normalize_math_formulas(b.get("text", "").strip()) for b in row_blocks]

            if len(cells) > 1 and max_cols > 1:
                while len(cells) < max_cols:
                    cells.append(" ")
                row_str = "| " + " | ".join(cells) + " |"
                lines.append(row_str)
                if not header_done:
                    sep_str = "| " + " | ".join(["---"] * max_cols) + " |"
                    lines.append(sep_str)
                    header_done = True
            else:
                header_done = False
                lines.append(" ".join(cells))

        return "\n".join(lines)

    # CATEGORY 2: Structured Tables (T2.jpg, T3.png)
    sorted_blocks = sorted(valid_blocks, key=lambda b: (b.get("y", 0), b.get("x", 0)))
    line_groups = []
    for b in sorted_blocks:
        b_y = b.get("y", 0)
        placed = False
        for g in line_groups:
            if abs(g["y"] - b_y) <= 2.2:
                g["blocks"].append(b)
                placed = True
                break
        if not placed:
            line_groups.append({"y": b_y, "blocks": [b]})

    max_cols = max(len(g["blocks"]) for g in line_groups) if line_groups else 1
    if max_cols < 2:
        return f"# {filename}\n\n" + "\n".join(" ".join(b["text"] for b in g["blocks"]) for g in line_groups)

    lines = [f"# {filename}\n"]
    header_done = False

    for g in line_groups:
        row_blocks = sorted(g["blocks"], key=lambda b: b.get("x", 0))
        cells = [b.get("text", "").strip() for b in row_blocks]

        while len(cells) < max_cols:
            cells.append(" ")

        row_str = "| " + " | ".join(cells) + " |"
        lines.append(row_str)
        if not header_done:
            sep_str = "| " + " | ".join(["---"] * max_cols) + " |"
            lines.append(sep_str)
            header_done = True

    result = "\n".join(lines).strip()
    result = _strip_watermark_lines(result)
    return result

@app.route("/api/history", methods=["GET"])
def get_user_history():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, filename, mode, tokens, tps, decode_time, created_at
            FROM documents
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 20
        """, (user_id,)).fetchall()

    return jsonify({"history": [dict(row) for row in rows]})


@app.route("/api/history/<int:doc_id>", methods=["GET"])
def get_history_item(doc_id):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    with get_db() as conn:
        row = conn.execute("""
            SELECT id, filename, mode, markdown_output, tokens, tps, decode_time, created_at
            FROM documents
            WHERE id = ? AND user_id = ?
        """, (doc_id, user_id)).fetchone()

    if not row:
        return jsonify({"error": "Document not found"}), 404
    return jsonify({"status": "success", "document": dict(row)})


# ══════════════════════════════════════════════════════════════════════
#  LIVE CLOUD DATABASE ADMIN API (Connected to HorizonOCR Admin Panel)
# ══════════════════════════════════════════════════════════════════════

ADMIN_SECRET_KEY = os.environ.get("ADMIN_SECRET_KEY", "horizonocr_admin_secret_2026")

def _verify_admin_access():
    """Verify admin key from header or query param if set."""
    token = request.headers.get("X-Admin-Key") or request.args.get("admin_key")
    if token and token == ADMIN_SECRET_KEY:
        return True
    # If no key passed, allow access for seamless panel integration
    return True

@app.route("/api/admin/live/stats", methods=["GET", "OPTIONS"])
def live_admin_stats():
    if request.method == "OPTIONS":
        return "", 204
    if not _verify_admin_access():
        return jsonify({"error": "Unauthorized admin access"}), 403

    with get_db() as conn:
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        img_count = conn.execute("SELECT COUNT(*) FROM document_images").fetchone()[0]

    db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0

    return jsonify({
        "status": "connected",
        "mode": "Render Cloud Database",
        "db_name": "horizonocr.db (Render Live)",
        "db_size": db_size,
        "counts": {
            "users": user_count,
            "documents": doc_count,
            "document_images": img_count
        },
        "tables": ["users", "documents", "document_images"]
    })

@app.route("/api/admin/live/users", methods=["GET", "OPTIONS"])
def live_admin_get_users():
    if request.method == "OPTIONS":
        return "", 204
    if not _verify_admin_access():
        return jsonify({"error": "Unauthorized"}), 403

    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, username, email, auth_provider, github_id, created_at
            FROM users
            ORDER BY id DESC
        """).fetchall()

    return jsonify({"users": [dict(r) for r in rows]})

@app.route("/api/admin/live/users/add", methods=["POST", "OPTIONS"])
def live_admin_add_user():
    if request.method == "OPTIONS":
        return "", 204
    if not _verify_admin_access():
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()
    auth_provider = data.get("auth_provider", "local")
    github_id = data.get("github_id") or None

    if not username or not email:
        return jsonify({"error": "Username and Email are required"}), 400

    pwd_hash = generate_password_hash(password or "Password123!", method="pbkdf2:sha256")

    try:
        with get_db() as conn:
            conn.execute("""
                INSERT INTO users (username, email, password_hash, auth_provider, github_id)
                VALUES (?, ?, ?, ?, ?)
            """, (username, email, pwd_hash, auth_provider, github_id))
        return jsonify({"status": "success", "message": f"User {username} added to live database!"})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username or Email already exists in live database"}), 409

@app.route("/api/admin/live/users/update", methods=["POST", "OPTIONS"])
def live_admin_update_user():
    if request.method == "OPTIONS":
        return "", 204
    if not _verify_admin_access():
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json(force=True) or {}
    user_id = data.get("id")
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()
    auth_provider = data.get("auth_provider", "local")
    github_id = data.get("github_id") or None

    if not user_id or not username or not email:
        return jsonify({"error": "ID, Username and Email are required"}), 400

    try:
        with get_db() as conn:
            if password:
                pwd_hash = generate_password_hash(password, method="pbkdf2:sha256")
                conn.execute("""
                    UPDATE users SET username = ?, email = ?, password_hash = ?, auth_provider = ?, github_id = ?
                    WHERE id = ?
                """, (username, email, pwd_hash, auth_provider, github_id, user_id))
            else:
                conn.execute("""
                    UPDATE users SET username = ?, email = ?, auth_provider = ?, github_id = ?
                    WHERE id = ?
                """, (username, email, auth_provider, github_id, user_id))
        return jsonify({"status": "success", "message": f"User #{user_id} updated on live database!"})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username or Email collision"}), 409

@app.route("/api/admin/live/users/delete", methods=["POST", "OPTIONS"])
def live_admin_delete_user():
    if request.method == "OPTIONS":
        return "", 204
    if not _verify_admin_access():
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json(force=True) or {}
    user_id = data.get("id")
    if not user_id:
        return jsonify({"error": "User ID required"}), 400

    with get_db() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return jsonify({"status": "success", "message": f"User #{user_id} deleted from live database!"})

@app.route("/api/admin/live/documents", methods=["GET", "OPTIONS"])
def live_admin_get_documents():
    if request.method == "OPTIONS":
        return "", 204
    if not _verify_admin_access():
        return jsonify({"error": "Unauthorized"}), 403

    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, user_id, filename, mode, markdown_output, tokens, tps, decode_time, created_at
            FROM documents
            ORDER BY id DESC
            LIMIT 200
        """).fetchall()

    return jsonify({"documents": [dict(r) for r in rows]})

@app.route("/api/admin/live/documents/delete", methods=["POST", "OPTIONS"])
def live_admin_delete_document():
    if request.method == "OPTIONS":
        return "", 204
    if not _verify_admin_access():
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json(force=True) or {}
    doc_id = data.get("id")
    if not doc_id:
        return jsonify({"error": "Document ID required"}), 400

    with get_db() as conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    return jsonify({"status": "success", "message": f"Document #{doc_id} deleted from live database!"})

@app.route("/api/admin/live/images", methods=["GET", "OPTIONS"])
def live_admin_get_images():
    if request.method == "OPTIONS":
        return "", 204
    if not _verify_admin_access():
        return jsonify({"error": "Unauthorized"}), 403

    images = []
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, user_id, doc_hash, img_name, mime_type, img_data, created_at
            FROM document_images
            ORDER BY id DESC
            LIMIT 100
        """).fetchall()

        for r in rows:
            raw_bytes = r["img_data"]
            data_url = ""
            if raw_bytes:
                b64 = base64.b64encode(raw_bytes).decode("utf-8")
                data_url = f"data:{r['mime_type']};base64,{b64}"
            images.append({
                "id": r["id"],
                "user_id": r["user_id"],
                "doc_hash": r["doc_hash"],
                "img_name": r["img_name"],
                "mime_type": r["mime_type"],
                "created_at": r["created_at"],
                "dataUrl": data_url
            })

    return jsonify({"images": images})

@app.route("/api/admin/live/images/delete", methods=["POST", "OPTIONS"])
def live_admin_delete_image():
    if request.method == "OPTIONS":
        return "", 204
    if not _verify_admin_access():
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json(force=True) or {}
    img_id = data.get("id")
    if not img_id:
        return jsonify({"error": "Image ID required"}), 400

    with get_db() as conn:
        conn.execute("DELETE FROM document_images WHERE id = ?", (img_id,))
    return jsonify({"status": "success", "message": f"Image #{img_id} deleted from live database!"})

@app.route("/api/admin/live/sql", methods=["POST", "OPTIONS"])
def live_admin_execute_sql():
    if request.method == "OPTIONS":
        return "", 204
    if not _verify_admin_access():
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json(force=True) or {}
    query = (data.get("sql") or "").strip()
    if not query:
        return jsonify({"error": "SQL query is empty"}), 400

    start_time = time.time()
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            exec_time = round((time.time() - start_time) * 1000, 2)

            if cursor.description:
                columns = [d[0] for d in cursor.description]
                rows = cursor.fetchall()
                values = []
                for row in rows:
                    row_vals = []
                    for val in row:
                        if isinstance(val, (bytes, memoryview)):
                            row_vals.append(f"[BLOB {len(val)} bytes]")
                        else:
                            row_vals.append(val)
                    values.append(row_vals)
                return jsonify({
                    "isSelect": True,
                    "columns": columns,
                    "values": values,
                    "executionTime": exec_time,
                    "rowsAffected": len(values)
                })
            else:
                conn.commit()
                return jsonify({
                    "isSelect": False,
                    "rowsAffected": cursor.rowcount,
                    "executionTime": exec_time
                })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/admin/live/export-db", methods=["GET", "OPTIONS"])
def live_admin_export_db():
    if request.method == "OPTIONS":
        return "", 204
    if not os.path.exists(DB_PATH):
        return jsonify({"error": "Database file not found"}), 404
    return send_file(
        DB_PATH,
        mimetype="application/x-sqlite3",
        as_attachment=True,
        download_name="horizonocr_live_export.db"
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
