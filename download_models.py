"""
One-time model downloader for Unlimited-OCR (English only).

Downloads the EasyOCR detection model and English recognition model
into the project-local ./models/ directory.

Run once after initial setup:

    python download_models.py
"""

import os
import sys

# ── Must import model_cache first ────────────────────────────────────
import model_cache  # noqa: F401


def _make_readonly(filepath: str) -> None:
    """Mark a file as read-only (Windows / POSIX)."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(filepath, 1)
    else:
        os.chmod(filepath, 0o444)


def download_easyocr_model(url: str, filename: str, target_dir: str) -> bool:
    """Download a single EasyOCR model file and verify its MD5."""
    from easyocr.utils import download_and_unzip, calculate_md5
    from easyocr.config import detection_models, recognition_models

    expected_md5 = None
    for source in [detection_models, recognition_models.get("gen1", {}),
                   recognition_models.get("gen2", {})]:
        if isinstance(source, dict):
            for model in source.values():
                if isinstance(model, dict) and model.get("filename") == filename:
                    expected_md5 = model.get("md5sum")
                    break

    fpath = os.path.join(target_dir, filename)

    if os.path.isfile(fpath) and expected_md5:
        actual = calculate_md5(fpath)
        if actual == expected_md5:
            print(f"  [SKIP] {filename} — already cached, MD5 OK")
            _make_readonly(fpath)
            return True

    print(f"  [DOWNLOAD] {filename}...")
    try:
        download_and_unzip(url, filename, target_dir, verbose=True)
        if expected_md5:
            actual = calculate_md5(fpath)
            if actual != expected_md5:
                print(f"  [FAIL] {filename} — MD5 mismatch!")
                return False
        size_mb = os.path.getsize(fpath) / (1024 * 1024)
        print(f"  [OK] {filename} — {size_mb:.1f} MB, MD5 verified")
        _make_readonly(fpath)
        return True
    except Exception as e:
        print(f"  [FAIL] {filename} — {e}")
        return False


def main():
    from easyocr.config import detection_models, recognition_models

    easyocr_dir = os.path.join(model_cache.MODELS_DIR, "easyocr")
    os.makedirs(easyocr_dir, exist_ok=True)

    # ── Detection model (shared) ──────────────────────────────────────
    print("\n=== Detection model ===")
    det = detection_models["craft"]
    download_easyocr_model(det["url"], det["filename"], easyocr_dir)

    # ── English recognition model ─────────────────────────────────────
    print("\n=== English recognition model ===")
    model = recognition_models["gen2"]["english_g2"]
    download_easyocr_model(model["url"], model["filename"], easyocr_dir)

    # Summary
    print("\n=== Cache contents ===")
    total_mb = 0
    for f in sorted(os.listdir(easyocr_dir)):
        fpath = os.path.join(easyocr_dir, f)
        if os.path.isfile(fpath):
            size_mb = os.path.getsize(fpath) / (1024 * 1024)
            total_mb += size_mb
            print(f"  {f}: {size_mb:.1f} MB")
    print(f"  Total: {total_mb:.1f} MB")
    print("Done!")


if __name__ == "__main__":
    main()
