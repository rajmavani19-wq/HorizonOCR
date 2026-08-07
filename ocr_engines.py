"""
 Unlimited-OCR — English OCR Engine Module.
 
 Provides a unified interface to OCR backends optimised exclusively for
 English text extraction.  Each engine is tried in priority order; the
 first successful backend returns its extracted text.
 
 Supported engines:
   1. EasyOCR       — pip install easyocr             (deep-learning OCR)
   2. Tesseract      — pip install pytesseract         (+ Tesseract system binary)
   3. PaddleOCR      — pip install paddleocr           (PaddlePaddle-based)
   4. docTR          — pip install python-doctr[torch] (PyTorch/TensorFlow)
   5. TrOCR          — pip install transformers        (HuggingFace, Microsoft model)
   6. RapidOCR       — pip install rapidocr_onnxruntime (ONNX Runtime, lightweight)
 
 Language: English only.
 """

import os
import sys
import shutil
import warnings

# ── Suppress PyTorch DataLoader pin_memory warning on CPU-only systems ─
warnings.filterwarnings(
    "ignore",
    message="'pin_memory' argument is set as true but no accelerator is found",
    category=UserWarning,
)

# ── MUST be imported BEFORE any ML library ──────────────────────────
import model_cache  # noqa: F401 — sets up ./models/ local cache

from PIL import Image
import numpy as np


# ══════════════════════════════════════════════════════════════════════
#  Language mapping — English only
# ══════════════════════════════════════════════════════════════════════

_EASYOCR_LANG_MAP = {"en": ["en"]}
_TESSERACT_LANG_MAP = {"en": "eng"}
_PADDLE_LANG_MAP = {"en": "en"}





# ══════════════════════════════════════════════════════════════════════
#  Structured OCR — returns text + layout blocks
# ══════════════════════════════════════════════════════════════════════

def _build_structured_blocks(easyocr_results, img_width, img_height):
    """
    Convert EasyOCR raw results into structured layout blocks.

    Each block: {id, x, y, w, h, text, confidence, type}
    Coordinates are normalised to percentage (0‑100).
    Block type is inferred from position, size, and font heuristics.
    Watermark text regions are filtered out automatically.
    """
    if not easyocr_results:
        return []

    blocks = []
    for idx, item in enumerate(easyocr_results):
        if len(item) < 3:
            continue
        bbox, text, confidence = item[0], item[1], item[2]
        if not text or not str(text).strip():
            continue

        text_str = str(text).strip()

        # Normalise bounding box to percentage
        x1 = bbox[0][0] / img_width * 100
        y1 = bbox[0][1] / img_height * 100
        x2 = bbox[2][0] / img_width * 100
        y2 = bbox[2][1] / img_height * 100

        # ── Skip watermark / stock-image artifacts ─────────────────
        if _is_watermark_text(text_str, y1, (y2 - y1)):
            continue

        # Classify block type from heuristics
        block_type = _infer_block_type(
            text_str, y1, (x2 - x1), (y2 - y1), img_width, img_height
        )

        blocks.append({
            "id": idx + 1,
            "x": round(x1, 1),
            "y": round(y1, 1),
            "w": round(x2 - x1, 1),
            "h": round(y2 - y1, 1),
            "text": text_str,
            "confidence": round(float(confidence) * 100, 1) if confidence else 0,
            "type": block_type,
        })

    return blocks


# ── Watermark / stock-image artifact detection ────────────────────────

# Stock image agency names and common watermark patterns.
# Text containing any of these is treated as a watermark and removed.
_WATERMARK_PATTERNS = [
    "watermark",     # Generic "WATERMARK" text in stock previews
    "shutterstock",  # Shutterstock
    "istock",        # iStock / Getty
    "getty",         # Getty Images
    "adobe stock",   # Adobe Stock
    "depositphotos", # Depositphotos
    "dreamstime",    # Dreamstime
    "alamy",         # Alamy
    "123rf",         # 123RF
    "image id",      # Stock image ID label
]


def _is_watermark_text(text: str, y_pct: float, height_pct: float) -> bool:
    """
    Detect whether a text region is a stock-image watermark.

    Heuristics used:
      1. Text contains known watermark agency names / patterns.
      2. Very short, repetitive text in the lower portion of the image
         that looks like tiled watermark text.
    """
    text_lower = text.lower().strip()

    # ── Known watermark pattern match ──────────────────────────────
    for pattern in _WATERMARK_PATTERNS:
        if pattern in text_lower:
            return True

    # ── Tiled "WATERMARK" fragments ────────────────────────────────
    # Stock sites often tile transparent text across the image.
    # OCR may read fragments like "ATERMARK", "WATERMA", "TERMARK", etc.
    watermark_fragments = ["atermark", "waterma", "termark", "rmark w",
                           "rk water", "ark wat", "mark wa"]
    for frag in watermark_fragments:
        if frag in text_lower:
            return True

    return False


def _infer_block_type(text, y_pct, width_pct, height_pct, img_w, img_h):
    """
    Heuristic block type classification based on position, size, and content.
    """
    _ = img_w, img_h  # reserved for future use
    text_len = len(text)
    text_short = text_len < 50

    # Top of page + short text → likely heading
    if y_pct < 12 and text_short:
        return "heading"

    # Very short + centered → title or heading
    if text_short and text_len < 25 and 15 < width_pct < 85:
        return "heading"

    # Bottom of page + small → footer
    if y_pct > 88 and height_pct < 4:
        return "footer"

    # Contains table-like separators
    if "\t" in text or (text.count("|") >= 2 and text.count("\n") >= 1):
        return "table"

    # Bullet list or numbered list
    import re
    if re.match(r'^[\-\*\•\◦\▪\▸\►]\s', text) or re.match(r'^\d+[\.\)]\s', text):
        return "list-item"

    # Default
    return "paragraph"


def _synthetic_blocks_from_text(text: str, img_w: int = 800, img_h: int = 600) -> list[dict]:
    """
    Generate approximate layout blocks from raw OCR text when EasyOCR
    bounding-box data is unavailable (e.g. when using Tesseract, PaddleOCR,
    or any non-EasyOCR engine).

    Text is split by blank-line-separated paragraphs.  Each paragraph
    becomes a block with estimated position based on line count.
    """
    if not text or not text.strip():
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]

    blocks = []
    total_paras = len(paragraphs)
    # Heuristic: allocate ~85% of image height for text area
    usable_h = img_h * 0.85
    top_margin = img_h * 0.05
    para_height = usable_h / max(total_paras, 1)

    for idx, para in enumerate(paragraphs):
        # Skip watermark text
        if _is_watermark_text(para, 0, 0):
            continue

        lines = para.split("\n")
        line_count = len(lines)

        # Shorter height if few lines
        block_h = min(para_height, line_count * (usable_h / 40))

        y_pct = (top_margin + idx * para_height) / img_h * 100
        h_pct = block_h / img_h * 100

        # Classify: short text at top → heading
        btype = "paragraph"
        if idx == 0 and len(para) < 80 and line_count <= 2:
            btype = "heading"
        elif idx > total_paras * 0.9 and len(para) < 60:
            btype = "footer"
        elif len(para) < 80 and line_count <= 2 and any(
            para.strip().startswith(c) for c in '-*\u2022\u25cf\u25cb\u25aa\u25b6'
        ):
            btype = "list-item"

        blocks.append({
            "id": idx + 1,
            "x": 5.0,
            "y": round(y_pct, 1),
            "w": 90.0,
            "h": round(h_pct, 1),
            "text": para,
            "confidence": 0,
            "type": btype,
        })

    return blocks


def run_ocr_structured(filepath: str) -> dict:
    """
    Run English OCR on an image and return structured output with
    layout blocks.

    Uses EasyOCR with the English model as the primary backend.
    Falls back to Tesseract / PaddleOCR / RapidOCR / docTR / TrOCR
    if EasyOCR is unavailable.

    Returns
    -------
    dict with keys:
        text    — complete extracted text (newline-separated)
        engine  — name of the backend used
        blocks  — list of structured blocks [{id, x, y, w, h,
                   text, confidence, type}, …]
    """
    img = None
    img_w, img_h = 0, 0
    try:
        img = Image.open(filepath)
        img_np = np.array(img.convert("RGB"))
        img_w, img_h = img.size
    except Exception:
        img_np = None

    # ── Tier 1: EasyOCR English model ──────────────────────────────
    try:
        import easyocr  # noqa: F401
    except ImportError:
        pass
    else:
        if img_np is not None:
            try:
                reader = _get_easyocr_reader()
                results = reader.readtext(img_np, detail=1, paragraph=False)

                if results:
                    blocks = _build_structured_blocks(results, img_w, img_h)
                    text_lines = [b["text"] for b in blocks if b["text"]]
                    text = "\n".join(text_lines)

                    print(f"[EasyOCR] Extracted {len(text)} chars "
                          f"across {len(blocks)} blocks")
                    return {
                        "text": text,
                        "engine": "easyocr",
                        "blocks": blocks,
                    }
                else:
                    print("[EasyOCR] No text regions found.")
            except Exception as e:
                print(f"[EasyOCR] Failed: {e}")

    # ── Tier 2: Fallback — try all other engines ───────────────────
    ocr_text, engine_used = run_ocr(filepath)

    # ── Tier 3: Generate synthetic blocks from any text source ─────
    if ocr_text and ocr_text.strip():
        blocks = _synthetic_blocks_from_text(ocr_text, img_w or 800, img_h or 600)
        print(f"[OCR-Fallback] {len(ocr_text)} chars via {engine_used}, "
              f"{len(blocks)} synthetic blocks")
        return {
            "text": ocr_text,
            "engine": engine_used or "fallback",
            "blocks": blocks,
        }

    return {
        "text": "",
        "engine": "none",
        "blocks": [],
    }


# ══════════════════════════════════════════════════════════════════════
#  Engine 1: EasyOCR — pure Python, no system deps
# ══════════════════════════════════════════════════════════════════════

# Cache the English EasyOCR Reader (built once, reused across calls)
_EASYOCR_READER = None


def _get_easyocr_reader():
    """
    Build (or retrieve) the EasyOCR Reader for English and reuse it.

    Constructing EasyOCR loads ~95 MB of models (detection + recognition).
    The reader is cached globally so it is built only once per process.
    """
    global _EASYOCR_READER
    if _EASYOCR_READER is None:
        import easyocr

        easyocr_dir = os.path.join(model_cache.MODELS_DIR, "easyocr")

        det_file = os.path.join(easyocr_dir, "craft_mlt_25k.pth")
        if os.path.isfile(det_file):
            print(f"[EasyOCR] Using locally cached models from: {easyocr_dir}")

        _EASYOCR_READER = easyocr.Reader(
            ["en"], gpu=False,
            model_storage_directory=easyocr_dir,
            verbose=False,
        )

        # Protect model files from accidental deletion / re‑download.
        for _fname in os.listdir(easyocr_dir):
            _fpath = os.path.join(easyocr_dir, _fname)
            if os.path.isfile(_fpath) and _fname.endswith(".pth"):
                try:
                    if sys.platform == "win32":
                        import ctypes
                        ctypes.windll.kernel32.SetFileAttributesW(
                            _fpath, 1)
                    else:
                        os.chmod(_fpath, 0o444)
                except OSError:
                    pass

    return _EASYOCR_READER


def try_easyocr(filepath: str) -> str:
    """OCR via EasyOCR (deep-learning, English only)."""
    try:
        import easyocr  # noqa: F811
    except ImportError:
        print("[EasyOCR] Not installed — pip install easyocr")
        return ""

    try:
        img = Image.open(filepath)
        img_np = np.array(img.convert("RGB"))
        reader = _get_easyocr_reader()
        results = reader.readtext(img_np, detail=0, paragraph=True)
        if results:
            text = "\n".join(results).strip()
            if text:
                print(f"[EasyOCR] Extracted {len(text)} chars")
                return text
    except Exception as e:
        print(f"[EasyOCR] Error: {e}")
    return ""


# ══════════════════════════════════════════════════════════════════════
#  Engine 2: Tesseract — system binary required
# ══════════════════════════════════════════════════════════════════════

TESSERACT_PATHS_WINDOWS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"C:\Tesseract-OCR\tesseract.exe",
]


def _find_tesseract() -> str | None:
    """Locate the Tesseract binary on this system."""
    for p in TESSERACT_PATHS_WINDOWS:
        if os.path.isfile(p):
            return p
    tesseract = shutil.which("tesseract")
    if tesseract:
        return tesseract
    if sys.platform == "darwin":
        brew_path = "/usr/local/bin/tesseract"
        if os.path.isfile(brew_path):
            return brew_path
        opt_path = "/opt/homebrew/bin/tesseract"
        if os.path.isfile(opt_path):
            return opt_path
    if sys.platform.startswith("linux"):
        for p in ("/usr/bin/tesseract", "/usr/local/bin/tesseract"):
            if os.path.isfile(p):
                return p
    return None


def try_tesseract_pymupdf(filepath: str) -> str:
    """OCR via PyMuPDF's built-in Tesseract bridge (English)."""
    try:
        import fitz
    except ImportError:
        return ""

    try:
        doc = fitz.open(filepath)
        page = doc[0]
        try:
            tp = page.get_textpage_ocr(flags=3, language="eng", dpi=300)
            text = page.get_text(textpage=tp)
        except Exception:
            text = ""
        doc.close()
        if text and text.strip():
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            result = "\n".join(lines)
            print(f"[Tesseract-PyMuPDF] Extracted {len(result)} chars")
            return result
    except Exception as e:
        print(f"[Tesseract-PyMuPDF] Error: {e}")
    return ""


def try_tesseract_pytesseract(filepath: str) -> str:
    """OCR via pytesseract (Python wrapper around Tesseract CLI, English)."""
    try:
        import pytesseract
    except ImportError:
        print("[Tesseract-pytesseract] Not installed — pip install pytesseract")
        return ""

    tesseract_bin = _find_tesseract()
    if not tesseract_bin:
        print("[Tesseract] Binary not found — install Tesseract OCR")
        return ""

    pytesseract.pytesseract.tesseract_cmd = tesseract_bin
    try:
        img = Image.open(filepath)
        text = pytesseract.image_to_string(img, lang="eng")
        if text and text.strip():
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            result = "\n".join(lines)
            print(f"[Tesseract-pytesseract] Extracted {len(result)} chars")
            return result
    except Exception as e:
        print(f"[Tesseract-pytesseract] Error: {e}")
    return ""


# ══════════════════════════════════════════════════════════════════════
#  Engine 3: PaddleOCR — PaddlePaddle-based
# ══════════════════════════════════════════════════════════════════════

_PADDLEOCR_ENGINE = None


def _get_paddleocr_engine():
    """Get or create a PaddleOCR instance (English)."""
    global _PADDLEOCR_ENGINE
    if _PADDLEOCR_ENGINE is None:
        from paddleocr import PaddleOCR
        _PADDLEOCR_ENGINE = PaddleOCR(
            use_angle_cls=True, lang="en", show_log=False
        )
    return _PADDLEOCR_ENGINE


def try_paddleocr(filepath: str) -> str:
    """OCR via PaddleOCR (English)."""
    try:
        from paddleocr import PaddleOCR  # noqa: F811
    except ImportError:
        print("[PaddleOCR] Not installed — pip install paddleocr")
        return ""

    try:
        ocr = _get_paddleocr_engine()
        results = ocr.ocr(filepath, cls=True)
        if not results or not results[0]:
            return ""
        lines = []
        for line_info in results[0]:
            if line_info and len(line_info) >= 2:
                text = line_info[1][0] if isinstance(line_info[1], (list, tuple)) else str(line_info[1])
                if text and text.strip():
                    lines.append(text.strip())
        if lines:
            text = "\n".join(lines)
            print(f"[PaddleOCR] Extracted {len(text)} chars")
            return text
    except Exception as e:
        print(f"[PaddleOCR] Error: {e}")
    return ""


# ══════════════════════════════════════════════════════════════════════
#  Engine 4: docTR — PyTorch / TensorFlow OCR
# ══════════════════════════════════════════════════════════════════════

def try_doctr(filepath: str) -> str:
    """OCR via docTR (Document Text Recognition, Mindee)."""
    try:
        from doctr.io import DocumentFile
        from doctr.models import ocr_predictor
    except ImportError:
        print("[docTR] Not installed — pip install python-doctr[torch]")
        return ""

    try:
        model = ocr_predictor(pretrained=True)
        doc = DocumentFile.from_images(filepath)
        result = model(doc)
        text = result.render()
        if text and text.strip():
            print(f"[docTR] Extracted {len(text)} chars")
            return text.strip()
    except Exception as e:
        print(f"[docTR] Error: {e}")
    return ""


# ══════════════════════════════════════════════════════════════════════
#  Engine 5: TrOCR — Microsoft Transformer-based OCR
# ══════════════════════════════════════════════════════════════════════

def try_trocr(filepath: str) -> str:
    """OCR via TrOCR (Microsoft's Transformer OCR via HuggingFace, English)."""
    try:
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        import torch
    except ImportError:
        print("[TrOCR] Not installed — pip install transformers torch")
        return ""

    try:
        model_name = "microsoft/trocr-base-printed"
        cache_dir = os.path.join(model_cache.MODELS_DIR, "transformers")
        processor = TrOCRProcessor.from_pretrained(model_name, cache_dir=cache_dir)
        model = VisionEncoderDecoderModel.from_pretrained(model_name, cache_dir=cache_dir)

        img = Image.open(filepath).convert("RGB")
        pixel_values = processor(img, return_tensors="pt").pixel_values

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = model.to(device)
        pixel_values = pixel_values.to(device)

        generated_ids = model.generate(pixel_values)
        text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]

        if text and text.strip():
            print(f"[TrOCR] Extracted {len(text)} chars")
            return text.strip()
    except Exception as e:
        print(f"[TrOCR] Error: {e}")
    return ""


# ══════════════════════════════════════════════════════════════════════
#  Engine 6: RapidOCR — lightweight ONNX Runtime backend
# ══════════════════════════════════════════════════════════════════════

_RAPIDOCR_ENGINE = None


def _get_rapidocr_engine():
    """Build the RapidOCR engine once and reuse it (~13 MB ONNX models)."""
    global _RAPIDOCR_ENGINE
    if _RAPIDOCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _RAPIDOCR_ENGINE = RapidOCR()
    return _RAPIDOCR_ENGINE


def try_rapidocr(filepath: str) -> str:
    """OCR via RapidOCR ONNX Runtime (English)."""
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except ImportError:
        print("[RapidOCR] Not installed — pip install rapidocr_onnxruntime")
        return ""

    try:
        engine = _get_rapidocr_engine()
        result, _ = engine(filepath)
        if result:
            lines = []
            for item in result:
                if len(item) >= 2 and item[1]:
                    lines.append(str(item[1]).strip())
            if lines:
                text = "\n".join(lines)
                print(f"[RapidOCR] Extracted {len(text)} chars")
                return text
    except Exception as e:
        print(f"[RapidOCR] Error: {e}")
    return ""


# ══════════════════════════════════════════════════════════════════════
#  Unified multi-engine pipeline
# ══════════════════════════════════════════════════════════════════════

# Each entry: (engine_name, callable)
# The callable signature is: fn(filepath) → str
_ENGINE_REGISTRY = [
    ("easyocr",       try_easyocr),
    ("tesseract-pyt", try_tesseract_pytesseract),
    ("tesseract-pmu", try_tesseract_pymupdf),
    ("paddleocr",     try_paddleocr),
    ("doctr",         try_doctr),
    ("rapidocr",      try_rapidocr),
    ("trocr",         try_trocr),
]


def run_ocr(filepath: str) -> tuple[str, str | None]:
    """
    Run English OCR on an image file using all available engines.

    Engines are tried in priority order; the first successful backend
    returns its extracted text.

    Returns
    -------
    (text, engine_name)
        text : str  — Extracted OCR text, or "" if no engine succeeded.
        engine_name : str | None  — Name of the successful backend, or None.
    """
    for engine_name, engine_fn in _ENGINE_REGISTRY:
        text = engine_fn(filepath)
        if text:
            return text, engine_name
    return "", None
