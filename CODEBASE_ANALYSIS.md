# Unlimited OCR — Comprehensive Codebase Analysis

> **Date**: 2026-08-01 | **Analyzed by**: Accio Assistant

---

## 1. Executive Summary

**Unlimited OCR** is an open-source project by Baidu that packages an AI-powered document OCR engine behind a full-stack web application. The codebase spans two distinct layers:

| Layer | Technology | Files | LOC |
|-------|-----------|-------|-----|
| **Backend** | Flask + SQLite + PyMuPDF | `server.py`, `infer.py`, `run_local.py` | ~794 |
| **Frontend** | Vanilla JS SPA, modular CSS | `index.html` + `js/` + `css/` | ~1,744 |
| **Orphans** | Legacy unloaded files | `app.js`, `styles.css`, `components/`, `pages/` | ~1,977 |

**Overall grade: C+** — The project is functional but exhibits significant architectural debt from an incomplete refactoring, orphaned duplicate code, and multiple security concerns.

---

## 2. Architecture & Folder Structure

```
Unlimited OCR/
├── server.py              ← Flask backend (auth, OCR API, DB) [active]
├── index.html             ← SPA shell, all HTML inline [active]
├── infer.py               ← SGLang concurrent inference [active]
├── run_local.py           ← HuggingFace local inference [active]
├── styles.css             ← ⚠ ORPHAN: monolithic CSS (not loaded)
├── app.js                 ← ⚠ ORPHAN: monolithic JS (not loaded)
├── database.db            ← ⚠ ACCIDENTALLY COMMITTED
├── css/                   ← [active] Modular CSS (6 files)
├── js/                    ← [active] Modular JS (5 files)
├── components/            ← ⚠ ORPHAN: navbar.html, footer.html
├── pages/                 ← ⚠ ORPHAN: 4 view HTML snippets
├── assets/                ← Images, GIFs
├── wheel/                 ← SGLang custom wheel
├── log/                   ← Server logs (gitignored)
└── .venv/                 ← Python venv (gitignored)
```

### Architectural Pattern

The frontend is a **hand-rolled SPA** using a global state object (`appState`), a view-switching function (`switchView()`), and CSS class toggling (`.page-view.active`). No framework — pure imperative DOM manipulation.

The backend is a **monolithic Flask server** with direct SQLite access and file-system operations. No separation of concerns (no services layer, no repository pattern, no blueprints).

### Incomplete Refactoring — The Core Problem

The codebase was refactored from a monolith (`app.js` + `styles.css`) into a modular structure (`js/` + `css/`), but **both the old and new code remain on disk**. Worse, the modular versions omit functionality present in the monolith, and vice-versa:

| Function | `app.js` (orphan) | Modular (active) |
|----------|------------------|-------------------|
| `renderBoundingBoxesForPage` | Full impl with default demo boxes | **Empty** — just clears container |
| `viewHistoryItem` | Passes raw params via `onclick` | Fetches from API by doc ID |
| `processUploadedFile` | Full inline impl | In `dashboard-page.js` |
| `startLongHorizonOCR` | Duplicated in both | In `ocr-workspace.js` |
| `changePdfPage` | Handles both PDF.js + server images | Refactored version cleaner |
| Auto page-tracking via `## Page N` | **Not present** | **Available** (cool feature!) |
| `escapeHtml` | Defined, never called | Not present |
| `setupScrollReveal` | In `app.js` | In `js/pages/landing.js` |
| `setupEventListeners` | In `app.js` | Named `setupDashboardEvents` |

---

## 3. Findings by Severity

### CRITICAL

#### 3.1 Hardcoded Secret Key
**File**: `server.py:21`
```python
app.secret_key = "unlimited_ocr_secret_key_super_secure_2026"
```
**Impact**: Session cookies are signed with a predictable key visible in the public repository. Anyone can forge valid session cookies and impersonate users.  
**Fix**: Use `os.urandom(24)` or read from an environment variable.

#### 3.2 Unauthenticated User Fallback to Default ID
**File**: `server.py:43`
```python
user_id = session.get("user_id", 1)
```
**Impact**: Requests without a valid session silently fall back to `user_id=1`, leaking shared data across unauthenticated users and potentially allowing unauthorized document access.  
**Fix**: Return 401 Unauthorized when `user_id` is absent from the session.

#### 3.3 Database File Committed to Repository
**File**: `database.db` (root)
**Impact**: Contains real user data (usernames, email addresses, password hashes, OCR history) visible in the public repository history.  
**Fix**: Remove from Git history (`git rm --cached`), add `*.db` to `.gitignore`, rotate all credentials.

#### 3.4 Dead Code: Orphaned Monolith Files
**Files**: `app.js` (537 lines), `styles.css` (1,032 lines), `components/` (84 lines), `pages/` (399 lines) — **1,977 lines of dead code (~55% of frontend)**

**Impact**:
- Maintenance confusion: developers may edit the wrong file
- The `app.js` monolith contains functionality the modular version **lost** (e.g., real bounding box rendering with demo fallback)
- The modular version contains a feature the monolith **never had** (auto page-switching via `## Page N` detection)
- Potential for future bugs when someone expects behavior from one version in the other

**Fix**: Decide on one architecture, migrate all features from the orphan into it, then delete orphans.

### HIGH

#### 3.5 No File Size Validation on Backend
**File**: `server.py` (OCR endpoint)
**Impact**: The UI claims 50MB limit, but no server-side enforcement exists. Attackers can upload arbitrarily large files, exhausting disk space.  
**Fix**: Check `Content-Length` header or file size before `uploaded_file.save()`.

#### 3.6 No Dependency Specification
**Impact**: No `requirements.txt`, `pyproject.toml`, or `Pipfile`. Users must manually install dependencies from README instructions. Version conflicts between `pymupdf==1.27.2.2` (README) and the `infer.py` wheel's requirements (`kernels==0.11.7` vs README's `kernels==0.9.0`) are already present.  
**Fix**: Create `requirements.txt` with pinned versions. Resolve the `kernels` version discrepancy.

#### 3.7 Misleading "Streaming" UX
**File**: `js/pages/ocr-workspace.js:174-230`
**Impact**: The OCR endpoint is a **blocking POST** (not SSE/streaming), yet the frontend simulates a typewriter animation with random chunk sizes at 25ms intervals. This is fundamentally misleading — users think they're seeing real-time AI output but they're watching a pre-rendered replay.  
**Fix**: Either implement true SSE streaming from the backend or remove the simulation and load results immediately.

#### 3.8 No CSRF Protection
**Impact**: All mutating endpoints (register, login, OCR upload) lack CSRF tokens. With cookie-based sessions, cross-site request forgery is possible.  
**Fix**: Add Flask-WTF or implement CSRF token validation.

#### 3.9 No Rate Limiting
**Impact**: Auth endpoints (`/api/register`, `/api/login`) and the OCR endpoint have no rate limiting, enabling brute-force attacks and resource abuse.  
**Fix**: Add Flask-Limiter or a simple in-memory rate limiter.

### MEDIUM

#### 3.10 Token Count Is a Heuristic Approximation
**File**: `server.py:77`
```python
token_count = max(80, int(len(markdown_output) / 3.5))
```
**Impact**: Token count, TPS, and other metrics displayed to users are fabricated. The actual model inference happens in `infer.py` (which does track real tokens), but the web server bypasses real inference entirely. In `server.py`, the OCR is done via PyMuPDF's `get_text("blocks")` — not the AI model at all.  
**Fix**: Either integrate real SGLang inference into `server.py`'s OCR endpoint, or clearly label metrics as estimates.

#### 3.11 Orphan Components Directory
**Files**: `components/navbar.html`, `components/footer.html`, `pages/*.html`
**Impact**: These are standalone HTML fragments never loaded by `index.html` (which has all HTML hardcoded inline). They appear to be artifacts of a component-based architecture that was abandoned mid-implementation.  
**Fix**: Either implement dynamic component loading or delete the orphan files.

#### 3.12 Missing CSS Keyframes
**File**: `css/ocr-workspace.css` references `@keyframes bboxFadeIn` on `.bbox-box:31` but the keyframes rule is never defined. Bounding boxes will appear instantly rather than animating in.

#### 3.13 Error Handling Is Silent
**Pattern**: Throughout the JS codebase, errors are caught with `console.warn()` and silently swallowed. The user sees a fallback UI with no indication of failure:
```javascript
} catch (err) {
    console.warn("[OCR Backend API] Fallback to simulated stream:", err);
}
```
**Fix**: Surface errors to the user via a visible error banner or toast.

### LOW / COSMETIC

#### 3.14 Unused CSS Variable
`--bg-glass` is defined in `:root` but never referenced anywhere in the CSS.

#### 3.15 Vague Type Hinting
`infer.py:54` uses `list[str]` (PEP 585 syntax) but the file also uses `from __future__ import annotations` would be needed for older Python. Not a bug per se, but inconsistent with the rest of the codebase.

#### 3.16 Benchmark Data Is Static HTML
The benchmark table in `index.html` shows static data. No dynamic fetch or validation from actual benchmark runs.

---

## 4. Code Quality Assessment

| Dimension | Rating | Notes |
|-----------|--------|-------|
| **Readability** | B | Generally clean, well-commented. Monolithic `app.js` has better inline comments than modular files. |
| **DRY Principle** | D | 55% of frontend code is duplicated between orphan monolith and modular versions. |
| **Modularity** | C | Modular structure exists but incomplete; backend has zero separation of concerns. |
| **Error Handling** | D | Silent failures everywhere. No user-facing error states. |
| **Security** | D | Hardcoded secret key, no CSRF, no rate limiting, no file size validation, default user_id fallback. |
| **Testing** | F | Zero tests — no unit tests, no integration tests, no test directory. |
| **Documentation** | B+ | README is comprehensive. Inline comments are good. Missing API docs and architectural decisions. |

---

## 5. Performance Considerations

- **Flask dev server** (`app.run()`) is single-threaded by default — concurrent uploads will block. Production deployment should use gunicorn/uwsgi.
- **PDF page rendering** (`render_doc_pages_to_base64`) encodes all pages as base64 in memory — a 500-page document at 150 DPI could consume hundreds of MB.
- **OCR extraction** (`extract_layout_and_markdown`) uses `page.get_text("blocks")` which is fast for PyMuPDF but is **not the AI model** — the real SGLang inference lives in `infer.py` and is never called from the web server.
- **SQLite with no connection pooling** — each request opens and closes a new connection.
- **No caching** — repeated requests for the same user's history re-query and re-render.

---

## 6. Dependency Analysis

### Python (back-end)
| Package | Version (README) | Notes |
|---------|-----------------|-------|
| flask | unspecified | Latest? |
| flask-cors | unspecified | Latest? |
| pymupdf | 1.27.2.2 | Also in infer.py deps |
| werkzeug | unspecified | Security: includes `generate_password_hash` |
| requests | unspecified | For SGLang API calls in infer.py |
| torch | 2.10.0 | infer.py only |
| transformers | 4.57.1 | run_local.py only |
| kernels | 0.9.0 (README) vs 0.11.7 (README shell example) | **Version conflict** |
| sglang | custom wheel | Platform-specific (Linux + CUDA) |

### JavaScript (front-end, CDN-loaded)
| Library | Source | Notes |
|---------|--------|-------|
| Lucide Icons | unpkg.com | Icon system — no version pinning |
| Marked.js | jsdelivr.net | Markdown rendering |
| PDF.js 3.11.174 | cdnjs | Client-side PDF preview |

**Concerns**: All three CDN libraries are loaded from public CDNs with no SRI hashes. A compromised CDN or MITM attack could inject malicious JS.

---

## 7. Recommendations & Action Plan

### Phase 1 — Immediate (Security & Data Integrity)

| # | Action | Effort |
|---|--------|--------|
| 1 | Replace hardcoded `secret_key` with `os.environ.get("SECRET_KEY", os.urandom(24).hex())` | 5 min |
| 2 | Remove `database.db` from Git; rotate if deployed | 10 min |
| 3 | Return 401 instead of falling back to `user_id=1` for unauthenticated OCR requests | 5 min |
| 4 | Add server-side file size validation (check `Content-Length` or temp file size) | 10 min |
| 5 | Add SRI hashes to all 3 CDN `<script>` tags | 15 min |

### Phase 2 — Architecture Cleanup

| # | Action | Effort |
|---|--------|--------|
| 6 | **Decide architecture**: monolith (`app.js`/`styles.css`) or modular (`js/`/`css/`). Recommend modular. | — |
| 7 | Migrate missing features from `app.js` into the modular files (especially `renderBoundingBoxesForPage` with demo fallback) | 1 hr |
| 8 | Delete orphan files: `app.js`, `styles.css`, `components/`, `pages/` | 2 min |
| 9 | Create `requirements.txt` with pinned versions | 15 min |
| 10 | Add CSRF protection (Flask-WTF or manual token) | 30 min |

### Phase 3 — Quality & Robustness

| # | Action | Effort |
|---|--------|--------|
| 11 | Add user-facing error states (error banner component) | 1 hr |
| 12 | Add rate limiting on auth and OCR endpoints | 30 min |
| 13 | Add connection pooling for SQLite or switch to a context manager pattern | 20 min |
| 14 | Fix missing `@keyframes bboxFadeIn` | 5 min |
| 15 | Add `.db` to `.gitignore` | 1 min |

### Phase 4 — Long-Term Improvements

| # | Action | Effort |
|---|--------|--------|
| 16 | Implement true SSE streaming from backend for real-time OCR progress | 4–6 hr |
| 17 | Decouple OCR engine integration — create an `ocr_service.py` that can route to SGLang, HF Transformers, or PyMuPDF fallback | 2–3 hr |
| 18 | Add test suite (pytest for backend, basic DOM tests for frontend) | 4–8 hr |
| 19 | Add proper logging (Python `logging` module instead of `print()`) | 1 hr |
| 20 | Consider Flask blueprint refactoring: `auth_bp`, `ocr_bp`, `history_bp` | 2 hr |

---

## 8. Summary

The codebase is a promising but incomplete project. The core value (AI OCR model) is solid, but the web application wrapper has significant technical debt from a half-finished refactoring. The most urgent issues are security-related: the hardcoded secret key, the leaked database, and the unauthenticated user fallback. Architectural cleanup of the dead code should follow immediately to prevent maintenance drift.

The 5 most impactful fixes (totaling ~45 minutes of work) would address the critical security vulnerabilities. The remaining recommendations can be implemented incrementally over 2–3 weeks of focused effort.
