# HorizonOCR — High-Performance Document Engine & Vision Workspace

> **Transform Documents Into Structured Intelligence.**  
> HorizonOCR converts complex PDFs, multi-column tables, scanned receipts, and mathematical formulas into clean Markdown, LaTeX equations, and synchronized layout visualizations with speed and precision.

---

## 🌟 Features

- ⚡ **Instant Processing**: Framework-free, ultra-responsive single page application (SPA) with zero loading lag.
- 🔒 **Private & Authenticated Workspace**: Session-scoped user accounts, password hashing, and CSRF protection.
- 📄 **Multi-Format Document Extraction**: Native PDF parsing via PyMuPDF combined with modular OCR engines (RapidOCR, EasyOCR, Tesseract, docTR).
- 📐 **Reconstructed Layout Visualizations**: Side-by-side view comparing original page layouts with extracted Markdown and parsed bounding boxes.
- 🎬 **Video Demo & Interactive Preview**: Embedded HTML5 showcase video and responsive UI.
- 🚀 **Cloud Ready**: Configured out of the box for Render, Google Cloud Platform (GCP Free Tier), and Oracle Cloud Infrastructure (OCI).

---

## 🏗️ Architecture & Technology Stack

- **Frontend**: Vanilla HTML5, CSS3 (Modern dark-mode design with glassmorphism), Vanilla JavaScript SPA router.
- **Backend Service**: Python 3.12+ Flask application with Gunicorn production server.
- **Document Engines**: PyMuPDF (`fitz`), Pillow, RapidOCR, EasyOCR, docTR adapters.
- **Database**: SQLite3 (`horizonocr.db`) with user account isolation and structured session storage.

---

## 🚀 Quick Start (Local Setup)

### 1. Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/HorizonOCR.git
cd HorizonOCR
```

### 2. Activate virtual environment
```powershell
# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Start the application
```bash
python server.py
```

Access the live workspace at **http://127.0.0.1:8080/**.

---

## ☁️ Deployment

HorizonOCR can be deployed seamlessly to production cloud environments:

- **Render.com**: Native support via included [`render.yaml`](file:///f:/Antigravity%20Files/HorizonOCR/render.yaml).
- **Docker**: Production container setup via included [`Dockerfile`](file:///f:/Antigravity%20Files/HorizonOCR/Dockerfile).
- **Google Cloud Platform (GCP)** & **Oracle Cloud Infrastructure (OCI)**: Refer to [`PRODUCTION_DEPLOYMENT.md`](file:///f:/Antigravity%20Files/HorizonOCR/PRODUCTION_DEPLOYMENT.md).

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
