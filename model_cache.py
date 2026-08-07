"""
Model Cache Configuration
=========================
Sets up a project-local directory (./models/) for storing all downloaded
OCR/AI models. This ensures models are downloaded ONCE and reused across
all subsequent project runs — no repeated downloads.

Import this module BEFORE any ML library (transformers, easyocr, torch, etc.)
to guarantee environment variables take effect.

Usage:
    import model_cache   # Must be first ML-related import
    from transformers import AutoModel   # Now uses local cache
"""

import os
import sys

# ── Determine project root ──────────────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(_PROJECT_ROOT, "models")

# Create the models directory if it doesn't exist
os.makedirs(MODELS_DIR, exist_ok=True)

# ── Subdirectories for each framework ───────────────────────────────────
_HF_HUB_DIR       = os.path.join(MODELS_DIR, "huggingface_hub")
_TRANSFORMERS_DIR = os.path.join(MODELS_DIR, "transformers")
_TORCH_DIR        = os.path.join(MODELS_DIR, "torch")
_EASYOCR_DIR      = os.path.join(MODELS_DIR, "easyocr")
_PADDLEOCR_DIR    = os.path.join(MODELS_DIR, "paddleocr")
_RAPIDOCR_DIR     = os.path.join(MODELS_DIR, "rapidocr")
_SGLANG_DIR       = os.path.join(MODELS_DIR, "baidu_unlimited_ocr")

for _d in [_HF_HUB_DIR, _TRANSFORMERS_DIR, _TORCH_DIR,
           _EASYOCR_DIR, _PADDLEOCR_DIR, _RAPIDOCR_DIR, _SGLANG_DIR]:
    os.makedirs(_d, exist_ok=True)

# ── Set environment variables BEFORE any ML imports ─────────────────────
# Hugging Face ecosystem
os.environ.setdefault("HF_HOME", _HF_HUB_DIR)
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", _HF_HUB_DIR)
os.environ.setdefault("TRANSFORMERS_CACHE", _TRANSFORMERS_DIR)

# PyTorch hub (used by docTR, etc.)
os.environ.setdefault("TORCH_HOME", _TORCH_DIR)

# EasyOCR
os.environ.setdefault("EASYOCR_MODULE_PATH", _EASYOCR_DIR)

# PaddleOCR (if $PADDLEOCR_HOME is supported by the installed version)
os.environ.setdefault("PADDLEOCR_HOME", _PADDLEOCR_DIR)

# ── Summary ─────────────────────────────────────────────────────────────
print(f"[model_cache] Local model directory: {MODELS_DIR}")
print(f"  HuggingFace Hub : {_HF_HUB_DIR}")
print(f"  Transformers    : {_TRANSFORMERS_DIR}")
print(f"  Torch           : {_TORCH_DIR}")
print(f"  EasyOCR         : {_EASYOCR_DIR}")
print(f"  PaddleOCR       : {_PADDLEOCR_DIR}")
