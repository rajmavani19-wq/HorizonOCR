# Unlimited OCR — Complete Setup & Run Commands

## Prerequisites

- **Python 3.13+** (the project venv was created with 3.13)
- **Windows** (primary development platform; also works on macOS/Linux)
- **Git** (optional, for cloning)

---

## Step 1: Navigate to the project directory

```powershell
cd "F:\Antigravity Files\Unlimited OCR"
```

---

## Step 2: Activate the virtual environment

```powershell
.venv\Scripts\activate
```

You should see `(.venv)` appear at the start of your prompt.

---

## Step 3: Install Python dependencies

### Core (required — web server + basic OCR)

```powershell
pip install -r requirements.txt
```

### Optional OCR engines (install only what you need)

```powershell
# EasyOCR — pure Python, no system deps (recommended)
pip install easyocr

# PaddleOCR — high accuracy, good for Chinese + English
pip install paddleocr

# TrOCR — Microsoft transformer-based
pip install transformers torch

# docTR — Document Text Recognition
pip install "python-doctr[torch]"

# Tesseract via Python wrapper (requires system Tesseract binary)
pip install pytesseract
```

### Heavy model (baidu/Unlimited-OCR via HuggingFace)

```powershell
pip install transformers torch accelerate
```

> **Note:** The first time you run the project with a new OCR engine, its model files
> will be downloaded to the `./models/` directory. This happens automatically and
> only once. Subsequent runs load from local cache.

---

## Step 4: Run the project

### Option A — Web Server (Flask, port 8080)

```powershell
python server.py
```

Open your browser at: **http://127.0.0.1:8080**

Use the web UI to upload images/PDFs and get OCR results.

### Option B — Local CLI (heavy baidu/Unlimited-OCR model)

```powershell
# Single image
python run_local.py --input "path\to\image.png" --output_dir "./outputs"

# PDF (all pages)
python run_local.py --input "path\to\document.pdf" --output_dir "./outputs"

# With GPU (if available)
python run_local.py --input "document.pdf" --device cuda
```

### Option C — SGLang concurrent inference (Linux + NVIDIA GPU only)

```powershell
python infer.py --pdf "document.pdf" --output_dir "./outputs" --concurrency 4
```

---

## Quick one-shot (copy-paste all at once)

```powershell
# From project root
.venv\Scripts\activate
pip install -r requirements.txt
pip install easyocr
python server.py
```

---

## Verification

To verify the RapidOCR backend works (lightweight, no extra installs needed):

```powershell
python _probe_pipeline.py
```

Expected output should show `STABLE True` and extracted text.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `.venv\Scripts\activate` fails | Make sure you are in PowerShell, not cmd.exe. Or re-create venv: `python -m venv .venv` |
| `ModuleNotFoundError: No module named 'model_cache'` | Ensure you `cd`'d into the project root first |
| Model re-downloads every run | After the recent fix, models go to `./models/` and persist. First run will still download. |
| `ImportError: rapidocr_onnxruntime` | Run `pip install rapidocr_onnxruntime` |
| Port 8080 already in use | Change the port in `server.py` line 532, or kill the process using port 8080 |
