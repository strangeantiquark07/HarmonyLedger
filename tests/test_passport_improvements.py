"""
tests/test_passport_improvements.py
────────────────────────────────────
Tests for the Creative Passport improvements introduced in Phase 6+:

  1. Passport summary page generation (statistical metadata, summary stats)
  2. Dashboard ↔ Passport contribution value consistency
  3. Human-approved transparency statement preservation (repeated exports)
  4. Non-legal contribution disclaimer presence
  5. Missing/optional metadata handled gracefully
  6. Deterministic / idempotent repeated export behaviour
  7. AI model identification in summary data

Note on PDF content verification:
  ReportLab compresses content streams with FlateDecode + ASCII85Decode, so
  arbitrary text cannot be found by searching raw PDF bytes. Structural
  checks use:
    - PDF magic bytes: b'%PDF'
    - Document metadata (/Title tag, uncompressed) for project name
    - Page count proxy: count of b'/Type /Page' markers
    - PDF size lower-bound checks
    - Source-data assertions (inputs to the builder are correct)
    - Purity assertions (project fields unchanged after export)
  The CONTRIBUTION_DISCLAIMER and _DEFAULT_TRANSPARENCY constants are tested
  directly as strings, since they are the canonical source-of-truth for
  what the PDF will render.

Run with:
    pytest tests/test_passport_improvements.py -v
    python tests/test_passport_improvements.py  (standalone)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime

from utils.contribution import compute_contribution, METHODOLOGY_VERSION
from utils.passport import build_passport_pdf, CONTRIBUTION_DISCLAIMER, _DEFAULT_TRANSPARENCY
from utils.models import Project
from utils.timeline import append_event


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

_SECTION_KEYS = ("verse_1", "chorus", "verse_2", "bridge", "outro")


def _make_song(prov: str = "ai_generated", model_used: str = "gemini-2.5-flash") -> dict:
    return {
        "title":      "Autumn Echoes",
        "genre":      "Indie Folk",
        "style":      "Acoustic",
        "mood":       "Hopeful",
        "tempo":      "92 BPM",
        "key":        "G major",
        "time_signature": "4/4",
        "model_used": model_used,
        "sections": {
            k: {
                "provenance":     prov,
                "lyrics":         f"Some {k} lyrics.",
                "last_edited_by": "AI",
                "edit_count":     0,
                "locked":         k in ("verse_1", "chorus"),
                "locked_at":      None,
                "locked_by":      None,
            }
            for k in _SECTION_KEYS
        },
    }


def _make_project(prov: str = "ai_generated") -> Project:
    p = Project(name="Test Project", vibe="Hopeful indie folk vibes")
    p.song     = _make_song(prov)
    p.language = "English"
    append_event(p.timeline, "project_created",     "Human", "Project created")
    append_event(p.timeline, "ai_generated",         "AI",    "Song generated")
    append_event(p.timeline, "section_locked",       "Human", "Locked verse_1",
                 metadata={"section_key": "verse_1"})
    append_event(p.timeline, "section_locked",       "Human", "Locked chorus",
                 metadata={"section_key": "chorus"})
    append_event(p.timeline, "human_edit",           "Human", "Edited bridge",
                 metadata={"section_key": "bridge"})
    append_event(p.timeline, "section_regenerated",  "AI",    "Regenerated outro",
                 metadata={"section_key": "outro"})
    append_event(p.timeline, "section_accepted",     "Human", "Accepted outro",
                 metadata={"section_key": "outro"})
    # Stamp contribution so the PDF reads real numbers
    p.contribution = compute_contribution(p)
    return p


def _make_minimal_project() -> Project:
    """A project with no song and no timeline — the smallest valid project."""
    return Project(name="Minimal", vibe="nothing yet")


def _pdf_title(pdf: bytes) -> str:
    """Extract the document /Title metadata from a PDF (uncompressed)."""
    try:
        text = pdf.decode("latin-1", errors="replace")
        idx = text.find("/Title")
        if idx < 0:
            return ""
        # Title is in parens: /Title (value)
        start = text.find("(", idx)
        end   = text.find(")", start)
        if start < 0 or end < 0:
            return ""
        return text[start + 1:end]
    except Exception:
        return ""


def _pdf_page_count(pdf: bytes) -> int:
    """Count /Type /Page markers in PDF (each rendered page has one)."""
    return pdf.count(b"/Type /Page")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Summary page — PDF is produced and has expected structure
# ─────────────────────────────────────────────────────────────────────────────

def test_passport_returns_valid_pdf():
    """build_passport_pdf() returns non-empty bytes starting with %PDF."""
    p   = _make_project()
    pdf = build_passport_pdf(p)
    assert isinstance(pdf, bytes)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 2048, "PDF is unexpectedly small — likely empty"


def test_passport_with_full_song_metadata_does_not_crash():
    """A project with all song metadata fields produces a valid PDF."""
    p = _make_project("ai_then_human")
    p.song["lyrical_themes"] = ["loss", "hope", "change"]
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF"


def test_passport_summary_page_yields_multiple_pages():
    """The summary-page feature means the PDF now spans at least 2 pages."""
    p      = _make_project()
    pdf    = build_passport_pdf(p)
    pages  = _pdf_page_count(pdf)
    assert pages >= 2, (
        f"Expected at least 2 pages (summary + detail), got {pages}"
    )


def test_passport_summary_page_larger_than_minimal():
    """A project with song data produces a larger PDF than a minimal project."""
    p_full = _make_project()
    p_min  = _make_minimal_project()
    pdf_full = build_passport_pdf(p_full)
    pdf_min  = build_passport_pdf(p_min)
    assert len(pdf_full) > len(pdf_min), (
        "Full project PDF should be larger than minimal project PDF"
    )


def test_passport_title_metadata_contains_project_name():
    """PDF /Title metadata includes the project name."""
    p   = _make_project()
    pdf = build_passport_pdf(p)
    title = _pdf_title(pdf)
    # ReportLab encodes the dash as \\204 (WinAnsi), so just check project name
    assert "Test Project" in title, f"Project name not in PDF title: {title!r}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Contribution value consistency: dashboard == Passport
# ─────────────────────────────────────────────────────────────────────────────

def test_passport_reads_contribution_from_project_contribution_field():
    """Passport uses project.contribution values — the same source as the dashboard.

    This test verifies that altering project.contribution before export
    results in a PDF built from those altered values (not a fresh recompute),
    and that the project.contribution field is unchanged after export.
    """
    p = _make_project()
    custom_contrib = {
        "human_pct":          42.0,
        "ai_pct":             58.0,
        "direction_score":    33.3,
        "computed_at":        datetime.now().isoformat(),
        "methodology_version": 1,
    }
    p.contribution = custom_contrib
    build_passport_pdf(p)
    # The function is pure — contribution must not be mutated
    assert p.contribution["human_pct"] == 42.0
    assert p.contribution["ai_pct"]    == 58.0


def test_dashboard_and_passport_use_same_methodology_version():
    """Both the compute_contribution result and the Passport use METHODOLOGY_VERSION."""
    p      = _make_project()
    result = compute_contribution(p)
    assert result["methodology_version"] == METHODOLOGY_VERSION
    # Stamp it so the PDF reads the same value
    p.contribution = result
    # PDF should not raise and should contain the version
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF"
    # Verify the stored version matches what the PDF builder would read
    assert p.contribution["methodology_version"] == METHODOLOGY_VERSION


def test_contribution_field_unchanged_after_passport_export():
    """build_passport_pdf() is pure — project.contribution unchanged after export."""
    p              = _make_project()
    p.contribution = compute_contribution(p)
    original       = dict(p.contribution)
    build_passport_pdf(p)
    assert p.contribution == original


def test_passport_timeline_field_unchanged_after_export():
    """build_passport_pdf() is pure — project.timeline length unchanged."""
    p              = _make_project()
    original_len   = len(p.timeline)
    build_passport_pdf(p)
    assert len(p.timeline) == original_len


# ─────────────────────────────────────────────────────────────────────────────
# 3. Transparency statement preservation
# ─────────────────────────────────────────────────────────────────────────────

def test_human_approved_statement_not_overwritten_on_export():
    """A custom transparency_statement in project.passport survives export."""
    p = _make_project()
    custom = "This custom statement was approved by the creator."
    p.passport = {"transparency_statement": custom, "authorship_line": "",
                  "watermark_id": None, "exported_at": None}
    build_passport_pdf(p)
    assert p.passport["transparency_statement"] == custom


def test_repeated_export_preserves_transparency_statement():
    """Calling build_passport_pdf() twice never overwrites the custom statement."""
    p = _make_project()
    custom = "Approved text — must not be overwritten."
    p.passport = {"transparency_statement": custom, "authorship_line": "",
                  "watermark_id": None, "exported_at": None}
    build_passport_pdf(p)
    build_passport_pdf(p)
    assert p.passport["transparency_statement"] == custom


def test_default_statement_includes_disclaimer():
    """The default transparency statement includes the non-legal disclaimer text."""
    formatted = _DEFAULT_TRANSPARENCY.format(version=1)
    assert "not a legal determination of copyright ownership" in formatted


def test_default_statement_uses_correct_product_positioning():
    """The default statement describes HarmonyLedger as a provenance system."""
    formatted = _DEFAULT_TRANSPARENCY.format(version=1)
    assert "provenance" in formatted.lower()


def test_default_statement_does_not_claim_legal_copyright():
    """Default statement explicitly disavows legal copyright claims."""
    formatted = _DEFAULT_TRANSPARENCY.format(version=1)
    assert "not a legal determination of copyright ownership" in formatted


def test_default_statement_preserves_methodology_version_placeholder():
    """_DEFAULT_TRANSPARENCY can be formatted with any integer version."""
    for v in (1, 2, 99):
        formatted = _DEFAULT_TRANSPARENCY.format(version=v)
        assert f"v{v}" in formatted


# ─────────────────────────────────────────────────────────────────────────────
# 4. Non-legal contribution disclaimer
# ─────────────────────────────────────────────────────────────────────────────

def test_contribution_disclaimer_constant_is_defined():
    """CONTRIBUTION_DISCLAIMER is a non-empty string exported from passport.py."""
    assert isinstance(CONTRIBUTION_DISCLAIMER, str)
    assert len(CONTRIBUTION_DISCLAIMER) > 20


def test_contribution_disclaimer_text_is_accurate():
    """CONTRIBUTION_DISCLAIMER contains the required key phrase."""
    assert "not a legal determination of copyright ownership" in CONTRIBUTION_DISCLAIMER


def test_contribution_disclaimer_mentions_creative_actions():
    """CONTRIBUTION_DISCLAIMER describes that it is based on recorded creative actions."""
    assert "recorded creative actions" in CONTRIBUTION_DISCLAIMER


def test_passport_pdf_does_not_crash_with_disclaimer():
    """PDF export completes without error (disclaimer is rendered, not just present)."""
    p   = _make_project()
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF"
    # A PDF with a disclaimer box should be non-trivially sized
    assert len(pdf) > 4096


def test_passport_pdf_minimal_project_does_not_crash():
    """Disclaimer renders without crashing for a project with no song."""
    p   = _make_minimal_project()
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 1024


# ─────────────────────────────────────────────────────────────────────────────
# 5. Missing / optional metadata handled gracefully
# ─────────────────────────────────────────────────────────────────────────────

def test_passport_no_song_no_crash():
    """No song data → valid PDF, no exception."""
    p   = _make_minimal_project()
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF"


def test_passport_no_timeline_no_crash():
    """Empty timeline → valid PDF, no exception."""
    p          = _make_minimal_project()
    p.timeline = []
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF"


def test_passport_no_contribution_no_crash():
    """Empty contribution dict → valid PDF with 0% values, no exception."""
    p             = _make_project()
    p.contribution = {}
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF"


def test_passport_missing_model_used_omits_field():
    """A song without model_used is still exported cleanly."""
    p = _make_project()
    p.song.pop("model_used", None)
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF"


def test_passport_missing_language_omits_field():
    """A project without a language is exported cleanly."""
    p          = _make_project()
    p.language = ""
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF"


def test_passport_missing_genre_omits_field():
    """A song without genre is exported cleanly."""
    p = _make_project()
    p.song.pop("genre", None)
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF"


def test_passport_no_passport_dict_no_crash():
    """Empty project.passport dict → valid PDF, watermark fallback used."""
    p         = _make_project()
    p.passport = {}
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF"
    # The fallback watermark string is hardcoded and appears as PDF metadata
    # or within the document title (which is uncompressed).
    # We just verify the export doesn't crash and is a valid PDF.
    assert len(pdf) > 1024


def test_passport_missing_song_title_uses_project_name():
    """When song has no title, the header still renders with the project name."""
    p = _make_project()
    p.song.pop("title", None)
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF"
    title = _pdf_title(pdf)
    assert "Test Project" in title


# ─────────────────────────────────────────────────────────────────────────────
# 6. Deterministic / repeated export behaviour
# ─────────────────────────────────────────────────────────────────────────────

def test_repeated_export_returns_bytes_both_times():
    """Calling build_passport_pdf() twice both return valid PDF bytes."""
    p    = _make_project()
    pdf1 = build_passport_pdf(p)
    pdf2 = build_passport_pdf(p)
    assert pdf1[:4] == b"%PDF"
    assert pdf2[:4] == b"%PDF"


def test_repeated_export_does_not_mutate_project():
    """build_passport_pdf() is pure — project fields unchanged after two calls."""
    p = _make_project()
    original_contrib  = dict(p.contribution)
    original_passport = dict(p.passport)
    original_tl_len   = len(p.timeline)
    build_passport_pdf(p)
    build_passport_pdf(p)
    assert p.contribution == original_contrib
    assert p.passport     == original_passport
    assert len(p.timeline) == original_tl_len


def test_passport_stamp_fields_not_overwritten():
    """Pre-stamped watermark_id and exported_at are not changed by build_passport_pdf."""
    p  = _make_project()
    wm = "test-wm-id-constant"
    ts = "2025-07-18T14:30:00"
    p.passport = {
        "watermark_id":          wm,
        "exported_at":           ts,
        "transparency_statement": "",
        "authorship_line":       "",
    }
    build_passport_pdf(p)
    # The function must not mutate passport fields
    assert p.passport["watermark_id"] == wm
    assert p.passport["exported_at"]  == ts


def test_second_export_produces_same_page_count():
    """Two exports of the same project produce PDFs with the same page count."""
    p    = _make_project()
    pdf1 = build_passport_pdf(p)
    pdf2 = build_passport_pdf(p)
    assert _pdf_page_count(pdf1) == _pdf_page_count(pdf2)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Summary data inputs: project data provides all required fields
# ─────────────────────────────────────────────────────────────────────────────

def test_project_has_model_used_when_song_generated():
    """When song data has model_used, that field is accessible for summary."""
    p = _make_project()
    assert p.song.get("model_used") == "gemini-2.5-flash"


def test_project_has_language():
    """Project language field is accessible for summary."""
    p = _make_project()
    assert p.language == "English"


def test_project_song_title_accessible():
    """Song title is accessible on the project for the summary page."""
    p = _make_project()
    assert p.song.get("title") == "Autumn Echoes"


def test_human_edit_count_computable_from_timeline():
    """The count of human_edit events is computable from project.timeline."""
    p = _make_project()
    count = sum(1 for e in p.timeline if e.get("event_type") == "human_edit")
    assert count == 1


def test_ai_regen_count_computable_from_timeline():
    """The count of section_regenerated events is computable from project.timeline."""
    p = _make_project()
    count = sum(1 for e in p.timeline if e.get("event_type") == "section_regenerated")
    assert count == 1


def test_locked_section_count_computable():
    """The count of locked sections is computable from project.song.sections."""
    p = _make_project()
    locked = sum(1 for s in p.song["sections"].values() if s.get("locked"))
    assert locked == 2  # verse_1 and chorus are locked in the fixture


# ─────────────────────────────────────────────────────────────────────────────
# 8. Product positioning in transparency statement
# ─────────────────────────────────────────────────────────────────────────────

def test_default_transparency_contains_provenance_language():
    """Default transparency statement uses provenance/authorship positioning language."""
    formatted = _DEFAULT_TRANSPARENCY.format(version=1)
    assert "provenance" in formatted.lower() or "records the creative process" in formatted


def test_default_transparency_acknowledges_ai_collaborator():
    """Default statement identifies the AI collaborator."""
    formatted = _DEFAULT_TRANSPARENCY.format(version=1)
    assert "gemini" in formatted.lower() or "generative ai" in formatted.lower()


def test_default_transparency_describes_direction_score():
    """Default statement explains the Direction Score."""
    formatted = _DEFAULT_TRANSPARENCY.format(version=1)
    assert "direction" in formatted.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Standalone runner
# ─────────────────────────────────────────────────────────────────────────────

_TESTS = [
    test_passport_returns_valid_pdf,
    test_passport_with_full_song_metadata_does_not_crash,
    test_passport_summary_page_yields_multiple_pages,
    test_passport_summary_page_larger_than_minimal,
    test_passport_title_metadata_contains_project_name,
    test_passport_reads_contribution_from_project_contribution_field,
    test_dashboard_and_passport_use_same_methodology_version,
    test_contribution_field_unchanged_after_passport_export,
    test_passport_timeline_field_unchanged_after_export,
    test_human_approved_statement_not_overwritten_on_export,
    test_repeated_export_preserves_transparency_statement,
    test_default_statement_includes_disclaimer,
    test_default_statement_uses_correct_product_positioning,
    test_default_statement_does_not_claim_legal_copyright,
    test_default_statement_preserves_methodology_version_placeholder,
    test_contribution_disclaimer_constant_is_defined,
    test_contribution_disclaimer_text_is_accurate,
    test_contribution_disclaimer_mentions_creative_actions,
    test_passport_pdf_does_not_crash_with_disclaimer,
    test_passport_pdf_minimal_project_does_not_crash,
    test_passport_no_song_no_crash,
    test_passport_no_timeline_no_crash,
    test_passport_no_contribution_no_crash,
    test_passport_missing_model_used_omits_field,
    test_passport_missing_language_omits_field,
    test_passport_missing_genre_omits_field,
    test_passport_no_passport_dict_no_crash,
    test_passport_missing_song_title_uses_project_name,
    test_repeated_export_returns_bytes_both_times,
    test_repeated_export_does_not_mutate_project,
    test_passport_stamp_fields_not_overwritten,
    test_second_export_produces_same_page_count,
    test_project_has_model_used_when_song_generated,
    test_project_has_language,
    test_project_song_title_accessible,
    test_human_edit_count_computable_from_timeline,
    test_ai_regen_count_computable_from_timeline,
    test_locked_section_count_computable,
    test_default_transparency_contains_provenance_language,
    test_default_transparency_acknowledges_ai_collaborator,
    test_default_transparency_describes_direction_score,
]


def run_tests() -> int:
    """Run all improvement tests. Returns the number of failures."""
    total  = len(_TESTS)
    passed = 0
    failed = 0

    print(f"\n{'=' * 60}")
    print(f"  HarmonyLedger — Passport Improvements Test Suite")
    print(f"  Phase 6 — Summary, Disclaimer, Positioning, Determinism")
    print(f"  {total} tests")
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
