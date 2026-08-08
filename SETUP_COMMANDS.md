# HorizonOCR — Complete Setup & Run Commands

## Prerequisites

- **Python 3.12+** (recommended) or **Python 3.13**
- **Windows / Linux / macOS** (cross-platform support)
- **Git** (for version control & cloud deployment)

---

## Step 1: Navigate to the project directory

```powershell
cd "F:\Antigravity Files\HorizonOCR"
```

---

## Step 2: Activate the virtual environment

```powershell
.venv\Scripts\activate
```

You should see `(.venv)` appear at the start of your prompt.

---

## Step 3: Install Python dependencies

### Core (Required — Web server + PyMuPDF + RapidOCR engine)

```powershell
pip install -r requirements.txt
```

### Optional OCR engines (Install only if needed)

```powershell
# EasyOCR — Pure Python OCR adapter
pip install easyocr

# PaddleOCR — High accuracy OCR engine
pip install paddleocr

# docTR — Document Text Recognition (PyTorch)
pip install "python-doctr[torch]"

# Tesseract Python wrapper
pip install pytesseract
```

---

## Step 4: Run the application

### Option A — Web Application Server (Flask, port 8080)

```powershell
python server.py
```

Open your browser at: **http://127.0.0.1:8080**

Use the web UI to register/login, upload documents (PDF, PNG, JPG, WEBP), and view extracted Markdown + layout visualizations in real time.

### Option B — Local CLI Processing

```powershell
# Process single image or PDF
python run_local.py --input "path\to\document.pdf" --output_dir "./outputs"
```

---

## Quick One-Shot (Copy & Paste)

```powershell
# From project root
.venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `.venv\Scripts\activate` fails | Ensure you are using PowerShell. Or recreate venv: `python -m venv .venv` |
| `ModuleNotFoundError: No module named 'server'` | Ensure you have navigated (`cd`) into the project root directory |
| Port 8080 already in use | Terminate existing Python process or change `PORT` in environment variables |
