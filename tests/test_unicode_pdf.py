"""
tests/test_unicode_pdf.py
──────────────────────────
Unicode / multilingual PDF smoke-test suite.

Verifies that build_passport_pdf() produces a valid, non-empty PDF for
every supported language, with special focus on non-Latin scripts that
previously rendered as black boxes due to the absence of Unicode fonts.

Coverage
────────
  1. Font registration — all expected Unicode font aliases are registered with
     ReportLab at module-import time:
       - NotoSans, NotoSans-Bold (Latin)
       - NotoSansDevanagari, NotoSansDevanagari-Bold (Hindi/Marathi)
       - NotoSansTamil, NotoSansTamil-Bold (Tamil)
       - NotoSansTelugu, NotoSansTelugu-Bold (Telugu)
       - HeiseiKakuGo-W5 (Japanese — ReportLab built-in CIDFont)

  2. Language-aware font selection — _font() returns the correct font family
     for each supported language and handles bold variants, unknown languages,
     and empty strings without raising.

  3. Multilingual PDF generation — build_passport_pdf() produces a valid PDF
     (starts with %PDF, non-trivial size) for every supported language when
     the song title, lyrics, and project name contain native-script text.
     Languages tested:
       - Hindi    (Devanagari: नमस्ते)
       - Marathi  (Devanagari: मराठी)
       - Telugu   (Telugu script: తెలుగు)
       - Tamil    (Tamil script: தமிழ்)
       - Japanese (CJK: 日本語 — uses HeiseiKakuGo-W5 CIDFont)
       - English  (Latin, baseline)
       - Spanish  (Latin + diacritics: ñ, é, ó)
       - French   (Latin + diacritics: é, à, ç)

  4. Smoke test — the generated PDF is larger than 2 KB (not an empty shell)
     and contains at least 2 pages (summary + detail).

  5. Font fallback — _font() never raises, even for an unrecognised language
     or an empty string.

  6. Idempotency — calling build_passport_pdf() twice on the same multilingual
     project returns valid PDF bytes both times.

Run:
    pytest tests/test_unicode_pdf.py -v
    python tests/test_unicode_pdf.py       (standalone)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.passport import (
    build_passport_pdf,
    _font,
    _REGISTERED_FONTS,
    _LANG_FONT_BASE,
    _JP_FONT,
    CONTRIBUTION_DISCLAIMER,
)
from utils.models import Project
from utils.timeline import append_event
from utils.contribution import compute_contribution


# ─────────────────────────────────────────────────────────────────────────────
# Native-script test strings for each supported language
# ─────────────────────────────────────────────────────────────────────────────

_SCRIPT_SAMPLES = {
    "Hindi":    {
        "title":   "मेरा गाना",           # My Song
        "lyrics":  "यह एक हिंदी गाना है।", # This is a Hindi song.
        "name":    "हिंदी परियोजना",       # Hindi Project
    },
    "Marathi":  {
        "title":   "माझे गाणे",            # My Song (Marathi)
        "lyrics":  "हे एक मराठी गाणे आहे।",
        "name":    "मराठी प्रकल्प",
    },
    "Telugu":   {
        "title":   "నా పాట",              # My Song (Telugu)
        "lyrics":  "ఇది తెలుగు పాట.",
        "name":    "తెలుగు ప్రాజెక్ట్",
    },
    "Tamil":    {
        "title":   "என் பாடல்",            # My Song (Tamil)
        "lyrics":  "இது ஒரு தமிழ் பாடல்.",
        "name":    "தமிழ் திட்டம்",
    },
    "Japanese": {
        "title":   "私の歌",               # My Song (Japanese)
        "lyrics":  "これは日本語の歌です。",
        "name":    "日本語プロジェクト",
    },
    "English":  {
        "title":   "My Song",
        "lyrics":  "These are English lyrics.",
        "name":    "English Project",
    },
    "Spanish":  {
        "title":   "Mi canción de otoño",
        "lyrics":  "Bajo el cielo añil, tú y yo bailamos sin fin.",
        "name":    "Proyecto Español",
    },
    "French":   {
        "title":   "Ma chanson préférée",
        "lyrics":  "Sous le ciel étoilé, nous dansons à jamais.",
        "name":    "Projet Français",
    },
}

_SECTION_KEYS = ("verse_1", "chorus", "verse_2", "bridge", "outro")


def _make_multilingual_project(language: str) -> Project:
    """Build a fully-populated Project fixture for the given language."""
    sample = _SCRIPT_SAMPLES[language]
    p = Project(name=sample["name"], vibe="test vibe")
    p.language = language
    p.song = {
        "title":      sample["title"],
        "genre":      "Indie Folk",
        "style":      "Acoustic",
        "mood":       "Hopeful",
        "tempo":      "92 BPM",
        "key":        "G major",
        "time_signature": "4/4",
        "model_used": "gemini-2.5-flash",
        "sections": {
            k: {
                "provenance":     "ai_generated",
                "lyrics":         sample["lyrics"],
                "last_edited_by": "AI",
                "edit_count":     0,
                "locked":         k in ("verse_1", "chorus"),
                "locked_at":      None,
                "locked_by":      None,
            }
            for k in _SECTION_KEYS
        },
    }
    append_event(p.timeline, "project_created",    "Human", f"Project created ({language})")
    append_event(p.timeline, "ai_generated",        "AI",   sample["title"])
    append_event(p.timeline, "section_locked",      "Human", "Locked verse_1",
                 metadata={"section_key": "verse_1"})
    append_event(p.timeline, "human_edit",          "Human", sample["lyrics"][:40],
                 metadata={"section_key": "bridge"})
    p.contribution = compute_contribution(p)
    return p


def _pdf_page_count(pdf: bytes) -> int:
    return pdf.count(b"/Type /Page")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Font registration
# ─────────────────────────────────────────────────────────────────────────────

def test_noto_sans_regular_registered():
    assert "NotoSans" in _REGISTERED_FONTS, \
        "NotoSans not registered — check assets/fonts/NotoSans-Regular.ttf"

def test_noto_sans_bold_registered():
    assert "NotoSans-Bold" in _REGISTERED_FONTS, \
        "NotoSans-Bold not registered — check assets/fonts/NotoSans-Bold.ttf"

def test_noto_sans_devanagari_regular_registered():
    assert "NotoSansDevanagari" in _REGISTERED_FONTS, \
        "NotoSansDevanagari not registered — check assets/fonts/NotoSansDevanagari-Regular.ttf"

def test_noto_sans_devanagari_bold_registered():
    assert "NotoSansDevanagari-Bold" in _REGISTERED_FONTS, \
        "NotoSansDevanagari-Bold not registered"

def test_heisei_kako_jp_registered():
    assert _JP_FONT in _REGISTERED_FONTS, \
        f"{_JP_FONT} not registered — ReportLab CIDFont HeiseiKakuGo-W5 unavailable"

def test_noto_sans_tamil_regular_registered():
    assert "NotoSansTamil" in _REGISTERED_FONTS, \
        "NotoSansTamil not registered — check assets/fonts/NotoSansTamil-Regular.ttf"

def test_noto_sans_tamil_bold_registered():
    assert "NotoSansTamil-Bold" in _REGISTERED_FONTS, \
        "NotoSansTamil-Bold not registered"

def test_noto_sans_telugu_regular_registered():
    assert "NotoSansTelugu" in _REGISTERED_FONTS, \
        "NotoSansTelugu not registered — check assets/fonts/NotoSansTelugu-Regular.ttf"

def test_noto_sans_telugu_bold_registered():
    assert "NotoSansTelugu-Bold" in _REGISTERED_FONTS, \
        "NotoSansTelugu-Bold not registered"

def test_all_nine_unicode_fonts_registered():
    """Nine required font registrations: 8 Noto Sans TTFs + HeiseiKakuGo-W5 CIDFont."""
    expected = {
        "NotoSans", "NotoSans-Bold",
        "NotoSansDevanagari", "NotoSansDevanagari-Bold",
        "NotoSansTamil", "NotoSansTamil-Bold",
        "NotoSansTelugu", "NotoSansTelugu-Bold",
        _JP_FONT,   # HeiseiKakuGo-W5
    }
    missing = expected - _REGISTERED_FONTS
    assert not missing, f"Missing font registrations: {missing}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Language-aware font selection
# ─────────────────────────────────────────────────────────────────────────────

def test_font_hindi_regular():
    assert _font("Hindi") == "NotoSansDevanagari"

def test_font_hindi_bold():
    assert _font("Hindi", bold=True) == "NotoSansDevanagari-Bold"

def test_font_marathi_regular():
    assert _font("Marathi") == "NotoSansDevanagari"

def test_font_marathi_bold():
    assert _font("Marathi", bold=True) == "NotoSansDevanagari-Bold"

def test_font_telugu_regular():
    assert _font("Telugu") == "NotoSansTelugu"

def test_font_telugu_bold():
    assert _font("Telugu", bold=True) == "NotoSansTelugu-Bold"

def test_font_tamil_regular():
    assert _font("Tamil") == "NotoSansTamil"

def test_font_tamil_bold():
    assert _font("Tamil", bold=True) == "NotoSansTamil-Bold"

def test_font_japanese_regular():
    assert _font("Japanese") == _JP_FONT, \
        f"Expected {_JP_FONT!r}, got {_font('Japanese')!r}"

def test_font_japanese_bold():
    # HeiseiKakuGo-W5 CIDFont has no separate bold variant
    result = _font("Japanese", bold=True)
    assert result == _JP_FONT, \
        f"Expected {_JP_FONT!r} (CIDFont has no bold), got {result!r}"

def test_font_english_regular():
    assert _font("English") == "NotoSans"

def test_font_english_bold():
    assert _font("English", bold=True) == "NotoSans-Bold"

def test_font_spanish_regular():
    assert _font("Spanish") == "NotoSans"

def test_font_french_regular():
    assert _font("French") == "NotoSans"

def test_font_unknown_language_returns_fallback():
    """_font() must never raise for an unknown language — returns NotoSans."""
    result = _font("Klingon")
    assert result in ("NotoSans", "Helvetica"), \
        f"Expected NotoSans (or Helvetica fallback), got {result!r}"

def test_font_empty_string_language_returns_fallback():
    """_font() must never raise for an empty string language."""
    result = _font("")
    assert result in ("NotoSans", "Helvetica"), \
        f"Expected NotoSans (or Helvetica fallback), got {result!r}"

def test_font_returns_registered_name():
    """_font() must always return a name that is registered in ReportLab."""
    from reportlab.pdfbase import pdfmetrics
    for lang in _LANG_FONT_BASE:
        name = _font(lang)
        # Should not raise; pdfmetrics.getFont raises KeyError for unknown names
        pdfmetrics.getFont(name)
        bold_name = _font(lang, bold=True)
        pdfmetrics.getFont(bold_name)


# ─────────────────────────────────────────────────────────────────────────────
# 3 + 4. Multilingual PDF generation smoke tests
# ─────────────────────────────────────────────────────────────────────────────

def _assert_valid_pdf(pdf: bytes, language: str) -> None:
    assert isinstance(pdf, bytes), f"[{language}] Expected bytes"
    assert pdf[:4] == b"%PDF", f"[{language}] Not a valid PDF (wrong magic bytes)"
    assert len(pdf) > 2048, f"[{language}] PDF too small ({len(pdf)} bytes)"
    pages = _pdf_page_count(pdf)
    assert pages >= 2, f"[{language}] Expected ≥2 pages, got {pages}"


def test_pdf_hindi():
    p = _make_multilingual_project("Hindi")
    pdf = build_passport_pdf(p)
    _assert_valid_pdf(pdf, "Hindi")

def test_pdf_marathi():
    p = _make_multilingual_project("Marathi")
    pdf = build_passport_pdf(p)
    _assert_valid_pdf(pdf, "Marathi")

def test_pdf_telugu():
    p = _make_multilingual_project("Telugu")
    pdf = build_passport_pdf(p)
    _assert_valid_pdf(pdf, "Telugu")

def test_pdf_tamil():
    p = _make_multilingual_project("Tamil")
    pdf = build_passport_pdf(p)
    _assert_valid_pdf(pdf, "Tamil")

def test_pdf_japanese():
    p = _make_multilingual_project("Japanese")
    pdf = build_passport_pdf(p)
    _assert_valid_pdf(pdf, "Japanese")

def test_pdf_english():
    p = _make_multilingual_project("English")
    pdf = build_passport_pdf(p)
    _assert_valid_pdf(pdf, "English")

def test_pdf_spanish():
    p = _make_multilingual_project("Spanish")
    pdf = build_passport_pdf(p)
    _assert_valid_pdf(pdf, "Spanish")

def test_pdf_french():
    p = _make_multilingual_project("French")
    pdf = build_passport_pdf(p)
    _assert_valid_pdf(pdf, "French")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Font fallback safety
# ─────────────────────────────────────────────────────────────────────────────

def test_font_never_raises_for_all_supported_languages():
    """_font() must not raise for any supported language, regular or bold."""
    from utils.models import SUPPORTED_LANGUAGES
    for lang in SUPPORTED_LANGUAGES:
        _font(lang)           # must not raise
        _font(lang, bold=True)


def test_pdf_with_empty_language_field_does_not_crash():
    """A project with language='' still produces a valid PDF (falls back to NotoSans)."""
    p = _make_multilingual_project("English")
    p.language = ""
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF"


def test_pdf_with_unknown_language_does_not_crash():
    """A project language not in the map still produces a valid PDF."""
    p = _make_multilingual_project("English")
    p.language = "Klingon"
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Idempotency
# ─────────────────────────────────────────────────────────────────────────────

def test_hindi_pdf_idempotent():
    """Calling build_passport_pdf() twice on the same Hindi project is safe."""
    p    = _make_multilingual_project("Hindi")
    pdf1 = build_passport_pdf(p)
    pdf2 = build_passport_pdf(p)
    assert pdf1[:4] == b"%PDF"
    assert pdf2[:4] == b"%PDF"

def test_japanese_pdf_idempotent():
    """Calling build_passport_pdf() twice on the same Japanese project is safe."""
    p    = _make_multilingual_project("Japanese")
    pdf1 = build_passport_pdf(p)
    pdf2 = build_passport_pdf(p)
    assert pdf1[:4] == b"%PDF"
    assert pdf2[:4] == b"%PDF"


# ─────────────────────────────────────────────────────────────────────────────
# 7. PDF size comparison — non-Latin fonts embed more glyph data
# ─────────────────────────────────────────────────────────────────────────────

def test_all_language_pdfs_are_non_trivially_sized():
    """Every language-specific PDF must be > 4 KB (embedded glyph data present)."""
    for lang in _SCRIPT_SAMPLES:
        p   = _make_multilingual_project(lang)
        pdf = build_passport_pdf(p)
        assert len(pdf) > 4096, \
            f"[{lang}] PDF too small ({len(pdf)} bytes) — font embedding may have failed"


# ─────────────────────────────────────────────────────────────────────────────
# Standalone runner
# ─────────────────────────────────────────────────────────────────────────────

_TESTS = [
    test_noto_sans_regular_registered,
    test_noto_sans_bold_registered,
    test_noto_sans_devanagari_regular_registered,
    test_noto_sans_devanagari_bold_registered,
    test_heisei_kako_jp_registered,
    test_noto_sans_tamil_regular_registered,
    test_noto_sans_tamil_bold_registered,
    test_noto_sans_telugu_regular_registered,
    test_noto_sans_telugu_bold_registered,
    test_all_nine_unicode_fonts_registered,
    test_font_hindi_regular,
    test_font_hindi_bold,
    test_font_marathi_regular,
    test_font_marathi_bold,
    test_font_telugu_regular,
    test_font_telugu_bold,
    test_font_tamil_regular,
    test_font_tamil_bold,
    test_font_japanese_regular,
    test_font_japanese_bold,
    test_font_english_regular,
    test_font_english_bold,
    test_font_spanish_regular,
    test_font_french_regular,
    test_font_unknown_language_returns_fallback,
    test_font_empty_string_language_returns_fallback,
    test_font_returns_registered_name,
    test_pdf_hindi,
    test_pdf_marathi,
    test_pdf_telugu,
    test_pdf_tamil,
    test_pdf_japanese,
    test_pdf_english,
    test_pdf_spanish,
    test_pdf_french,
    test_font_never_raises_for_all_supported_languages,
    test_pdf_with_empty_language_field_does_not_crash,
    test_pdf_with_unknown_language_does_not_crash,
    test_hindi_pdf_idempotent,
    test_japanese_pdf_idempotent,
    test_all_language_pdfs_are_non_trivially_sized,
]


def run_tests() -> int:
    total  = len(_TESTS)
    passed = 0
    failed = 0

    print(f"\n{'=' * 60}")
    print(f"  HarmonyLedger — Unicode PDF Smoke Test Suite")
    print(f"  {total} tests  |  8 languages  |  10 font families")
    print(f"{'=' * 60}\n")

    for fn in _TESTS:
        name = fn.__name__
        try:
            fn()
            print(f"  [PASS]  {name}")
            passed += 1
        except Exception as exc:
            print(f"  [FAIL]  {name}")
            print(f"       -> {exc}")
            failed += 1

    print(f"\n{'=' * 60}")
    if failed:
        print(f"  Results: {passed}/{total}  ·  {failed} FAILED")
    else:
        print(f"  Results: {passed}/{total}  ·  ALL PASSED")
    print(f"{'=' * 60}\n")
    return failed


if __name__ == "__main__":
    sys.exit(0 if run_tests() == 0 else 1)
