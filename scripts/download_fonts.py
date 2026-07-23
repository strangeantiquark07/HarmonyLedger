#!/usr/bin/env python3
"""
scripts/download_fonts.py
──────────────────────────
Downloads the Noto Sans Unicode font files required for the Creative Passport
PDF to render non-Latin scripts (Devanagari, Telugu, Tamil) as readable text.

Run this script if the assets/fonts/ directory is missing or incomplete:

    python scripts/download_fonts.py

Japanese text uses HeiseiKakuGo-W5, a CIDFont built into every ReportLab
installation — no TTF download is needed for Japanese.

Font source: Google Fonts CDN (fonts.gstatic.com). All Noto fonts are
released under the SIL Open Font License 1.1.
"""

import os
import sys
import urllib.request

# Destination: assets/fonts/ relative to the project root
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FONTS_DIR = os.path.join(_PROJECT_ROOT, "assets", "fonts")

# (filename, download_url) pairs
# URLs are pinned to specific Google Fonts CDN versions so behaviour is
# reproducible. Update the URLs if a newer version is needed.
FONT_DOWNLOADS = [
    (
        "NotoSans-Regular.ttf",
        "https://fonts.gstatic.com/s/notosans/v42/"
        "o-0mIpQlx3QUlC5A4PNB6Ryti20_6n1iPHjcz6L1SoM-jCpoiyD9A99d.ttf",
    ),
    (
        "NotoSans-Bold.ttf",
        "https://fonts.gstatic.com/s/notosans/v42/"
        "o-0mIpQlx3QUlC5A4PNB6Ryti20_6n1iPHjcz6L1SoM-jCpoiyAaBN9d.ttf",
    ),
    (
        "NotoSansDevanagari-Regular.ttf",
        "https://fonts.gstatic.com/s/notosansdevanagari/v30/"
        "TuGoUUFzXI5FBtUq5a8bjKYTZjtRU6Sgv3NaV_SNmI0b8QQCQmHn6B2OHjbL_08AlXQly-A.ttf",
    ),
    (
        "NotoSansDevanagari-Bold.ttf",
        "https://fonts.gstatic.com/s/notosansdevanagari/v30/"
        "TuGoUUFzXI5FBtUq5a8bjKYTZjtRU6Sgv3NaV_SNmI0b8QQCQmHn6B2OHjbL_08AlZMiy-A.ttf",
    ),
    (
        "NotoSansTamil-Regular.ttf",
        "https://fonts.gstatic.com/s/notosanstamil/v31/"
        "ieVc2YdFI3GCY6SyQy1KfStzYKZgzN1z4LKDbeZce-0429tBManUktuex7vGo70R.ttf",
    ),
    (
        "NotoSansTamil-Bold.ttf",
        "https://fonts.gstatic.com/s/notosanstamil/v31/"
        "ieVc2YdFI3GCY6SyQy1KfStzYKZgzN1z4LKDbeZce-0429tBManUktuex7shpL0R.ttf",
    ),
    (
        "NotoSansTelugu-Regular.ttf",
        "https://fonts.gstatic.com/s/notosanstelugu/v30/"
        "0FlxVOGZlE2Rrtr-HmgkMWJNjJ5_RyT8o8c7fHkeg-esVC5dzHkHIJQqrEntezbqQQ.ttf",
    ),
    (
        "NotoSansTelugu-Bold.ttf",
        "https://fonts.gstatic.com/s/notosanstelugu/v30/"
        "0FlxVOGZlE2Rrtr-HmgkMWJNjJ5_RyT8o8c7fHkeg-esVC5dzHkHIJQqrEntnDHqQQ.ttf",
    ),
]

_MIN_SIZE = 50_000  # bytes — any file smaller than this is incomplete


def download_fonts(force: bool = False) -> int:
    """Download missing or incomplete font files.

    Args:
        force: If True, re-download even if the file already exists.

    Returns:
        Number of files downloaded (0 if everything was already present).
    """
    os.makedirs(_FONTS_DIR, exist_ok=True)
    downloaded = 0

    for filename, url in FONT_DOWNLOADS:
        dest = os.path.join(_FONTS_DIR, filename)
        if not force and os.path.isfile(dest) and os.path.getsize(dest) >= _MIN_SIZE:
            print(f"  SKIP   {filename}  (already present, {os.path.getsize(dest):,} bytes)")
            continue
        print(f"  DOWNLOAD  {filename} ...", end=" ", flush=True)
        try:
            urllib.request.urlretrieve(url, dest)
            size = os.path.getsize(dest)
            if size < _MIN_SIZE:
                os.remove(dest)
                print(f"FAIL  (downloaded {size} bytes — too small, check URL)")
            else:
                print(f"OK  ({size:,} bytes)")
                downloaded += 1
        except Exception as exc:
            print(f"FAIL  ({exc})")

    return downloaded


if __name__ == "__main__":
    force = "--force" in sys.argv

    print()
    print("HarmonyLedger — Font Downloader")
    print(f"Destination: {_FONTS_DIR}")
    if force:
        print("Mode: force re-download all fonts")
    print()

    n = download_fonts(force=force)

    print()
    if n > 0:
        print(f"Downloaded {n} font file(s).")
    else:
        print("All fonts already present — no downloads needed.")
    print()
    print("Note: Japanese uses HeiseiKakuGo-W5 (ReportLab built-in CIDFont).")
    print("      No TTF download is needed for Japanese text.")
    print()
