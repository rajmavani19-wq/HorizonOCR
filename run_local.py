"""
Local Unlimited-OCR runner for Windows / CPU / PyTorch.
Parses local images or PDFs using Hugging Face transformers.
"""

import os
import sys
import argparse
import tempfile

# ── MUST be imported BEFORE any ML library ──────────────────────────
import model_cache  # noqa: F401 — sets up ./models/ local cache

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

import torch
from transformers import AutoModel, AutoTokenizer

MODEL_NAME = "baidu/Unlimited-OCR"
LOCAL_MODEL_DIR = os.path.join(model_cache.MODELS_DIR, "baidu_unlimited_ocr")

def pdf_to_images(pdf_path: str, dpi: int = 300) -> list[str]:
    print(f"[PDF] Converting {pdf_path} (DPI={dpi}) to images...")
    tmp_dir = tempfile.mkdtemp(prefix="pdf_ocr_")
    paths = []
    if fitz:
        doc = fitz.open(pdf_path)
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        for i, page in enumerate(doc):
            out = os.path.join(tmp_dir, f"page_{i + 1:04d}.png")
            page.get_pixmap(matrix=mat).save(out)
            paths.append(out)
            print(f"  Converted page {i + 1}/{len(doc)}")
        doc.close()
    elif pdfium:
        doc = pdfium.PdfDocument(pdf_path)
        scale = dpi / 72.0
        for i in range(len(doc)):
            out = os.path.join(tmp_dir, f"page_{i + 1:04d}.png")
            pil_img = doc[i].render(scale=scale).to_pil()
            pil_img.save(out)
            paths.append(out)
            print(f"  Converted page {i + 1}/{len(doc)}")
    return paths

def main():
    parser = argparse.ArgumentParser(description="Run Unlimited-OCR locally")
    parser.add_argument("--input", default="Unlimited-OCR.pdf", help="Path to image or PDF file")
    parser.add_argument("--output_dir", default="./outputs", help="Output directory")
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--language", default="auto",
                        help="Document language (auto, en, zh, ja, ko, ar, ru, hi, th, "
                             "ta, te, kn, bn, fr, de, es, pt, it, nl, etc.)")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    print(f"[Setup] Loading model '{MODEL_NAME}' on device '{args.device}'...")

    try:
        # Use local cache directory to avoid re-downloading every run
        tokenizer = AutoTokenizer.from_pretrained(
            MODEL_NAME,
            trust_remote_code=True,
            cache_dir=LOCAL_MODEL_DIR,
        )
        
        dtype = torch.bfloat16 if (args.device == "cuda" and torch.cuda.is_bf16_supported()) else (torch.float16 if args.device == "cuda" else torch.float32)
        
        model = AutoModel.from_pretrained(
            MODEL_NAME,
            trust_remote_code=True,
            use_safetensors=True,
            torch_dtype=dtype,
            cache_dir=LOCAL_MODEL_DIR,
        )
        if args.device == "cuda":
            model = model.eval().cuda()
        else:
            model = model.eval().to("cpu")
            
        print("[Setup] Model loaded successfully from local cache.")
    except Exception as e:
        print(f"[Error] Failed to load model: {e}")
        sys.exit(1)

    ext = os.path.splitext(args.input)[1].lower()
    # Build language-aware prompt
    lang = (args.language or "auto").strip()
    if lang == "auto":
        lang_hint = "Detect and preserve the original language(s) in the document."
    else:
        lang_hint = f"The document is in {lang}. Parse text in {lang}."
    prompt_single = f"<image>document parsing. {lang_hint}"
    prompt_multi = f"<image>Multi page parsing. {lang_hint}"

    if ext == ".pdf":
        images = pdf_to_images(args.input)
        print(f"[Infer] Running multi-page inference on {len(images)} pages..."
              f" (language={lang})")
        model.infer_multi(
            tokenizer,
            prompt=prompt_multi,
            image_files=images,
            output_path=args.output_dir,
            image_size=1024,
            max_length=32768,
            no_repeat_ngram_size=35,
            ngram_window=1024,
            save_results=True,
        )
    else:
        print(f"[Infer] Running single image inference on {args.input}..."
              f" (language={lang})")
        model.infer(
            tokenizer,
            prompt=prompt_single,
            image_file=args.input,
            output_path=args.output_dir,
            base_size=1024,
            image_size=640,
            crop_mode=True,
            max_length=32768,
            no_repeat_ngram_size=35,
            ngram_window=128,
            save_results=True,
        )

    print(f"[Success] Done! Outputs saved to {args.output_dir}")

if __name__ == "__main__":
    main()
