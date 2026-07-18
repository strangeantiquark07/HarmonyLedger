"""
tests/test_phase4.py
────────────────────
Phase 4 — Creative Ownership Intelligence test suite.

Tests are plain pytest-compatible functions using assert statements.
Run with:  pytest tests/test_phase4.py -v
           python tests/test_phase4.py  (standalone via run_tests() at bottom)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.contribution import compute_contribution
from utils.passport import build_passport_pdf
from utils.models import Project
from utils.timeline import append_event

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

_SECTION_KEYS = ("verse_1", "chorus", "verse_2", "bridge", "outro")


def _make_song(prov: str = "ai_generated") -> dict:
    return {
        "title":   "Test Song",
        "genre":   "Indie Folk",
        "mood":    "Hopeful",
        "tempo":   "92 BPM",
        "key":     "G major",
        "time_signature": "4/4",
        "sections": {
            k: {
                "provenance":     prov,
                "lyrics":         f"Some {k} lyrics.",
                "last_edited_by": "AI",
                "edit_count":     0,
                "locked":         False,
                "locked_at":      None,
                "locked_by":      None,
            }
            for k in _SECTION_KEYS
        },
    }


def _make_project(prov: str = "ai_generated") -> Project:
    p = Project(name="Test Project", vibe="Hopeful indie folk vibes")
    p.song = _make_song(prov)
    append_event(p.timeline, "project_created", "Human", "Project created")
    append_event(p.timeline, "ai_generated",    "AI",    "Song generated")
    return p


# ─────────────────────────────────────────────────────────────────────────────
# compute_contribution() — Section-authorship split
# ─────────────────────────────────────────────────────────────────────────────

def test_all_ai_generated_returns_ai_100():
    """All ai_generated sections → ai_pct == 100, human_pct == 0."""
    p = _make_project("ai_generated")
    r = compute_contribution(p)
    assert r["ai_pct"] == 100.0
    assert r["human_pct"] == 0.0


def test_all_human_written_returns_human_100():
    """All human_written sections → human_pct == 100, ai_pct == 0."""
    p = _make_project("human_written")
    r = compute_contribution(p)
    assert r["human_pct"] == 100.0
    assert r["ai_pct"] == 0.0


def test_all_ai_then_human_returns_50_50():
    """All ai_then_human sections → 50/50 split."""
    p = _make_project("ai_then_human")
    r = compute_contribution(p)
    assert r["human_pct"] == 50.0
    assert r["ai_pct"] == 50.0


def test_mixed_provenance_weighted_average():
    """Mixed provenance: 2 human_written, 2 ai_generated, 1 ai_then_human → 50/50."""
    p = Project(name="Mixed", vibe="test")
    p.song = {
        "sections": {
            "verse_1": {"provenance": "human_written"},   # weight 1.0
            "chorus":  {"provenance": "human_written"},   # weight 1.0
            "verse_2": {"provenance": "ai_generated"},    # weight 0.0
            "bridge":  {"provenance": "ai_generated"},    # weight 0.0
            "outro":   {"provenance": "ai_then_human"},   # weight 0.5
        }
    }
    r = compute_contribution(p)
    # human avg = (1+1+0+0+0.5)/5 = 2.5/5 = 0.5 → 50.0%
    assert r["human_pct"] == 50.0
    assert r["ai_pct"] == 50.0


def test_human_and_ai_pct_sum_to_100():
    """human_pct + ai_pct always sums to exactly 100.0 across any provenance mix."""
    for prov in ("ai_generated", "human_written", "ai_then_human"):
        p = _make_project(prov)
        r = compute_contribution(p)
        assert abs(r["human_pct"] + r["ai_pct"] - 100.0) < 0.01, (
            f"prov={prov!r}: {r['human_pct']} + {r['ai_pct']} != 100"
        )


# ─────────────────────────────────────────────────────────────────────────────
# compute_contribution() — Edge cases
# ─────────────────────────────────────────────────────────────────────────────

def test_empty_song_returns_zeros_no_crash():
    """Empty song dict → all zeros, no ZeroDivisionError."""
    p = Project(name="Empty", vibe="empty")
    r = compute_contribution(p)
    assert r["human_pct"] == 0.0
    assert r["ai_pct"] == 0.0
    assert r["direction_score"] == 0.0


def test_empty_timeline_returns_direction_score_zero():
    """Empty timeline → direction_score == 0, no crash."""
    p = _make_project("ai_generated")
    p.timeline = []
    r = compute_contribution(p)
    assert r["direction_score"] == 0.0


def test_return_shape_has_all_required_keys():
    """compute_contribution() always returns all five required keys."""
    p = _make_project()
    r = compute_contribution(p)
    required = {"human_pct", "ai_pct", "direction_score", "computed_at", "methodology_version"}
    assert required == set(r.keys())


def test_computed_at_is_iso_string():
    """computed_at is a non-empty ISO-8601 string."""
    from datetime import datetime
    p = _make_project()
    r = compute_contribution(p)
    # Should parse without raising
    datetime.fromisoformat(r["computed_at"])


def test_methodology_version_is_1():
    """methodology_version is 1 for the initial implementation."""
    p = _make_project()
    r = compute_contribution(p)
    assert r["methodology_version"] == 1


def test_does_not_mutate_project():
    """compute_contribution() is pure — does not change any project field."""
    p = _make_project()
    original_contribution = dict(p.contribution)
    original_timeline_len = len(p.timeline)
    compute_contribution(p)
    assert p.contribution == original_contribution
    assert len(p.timeline) == original_timeline_len


# ─────────────────────────────────────────────────────────────────────────────
# compute_contribution() — Direction score
# ─────────────────────────────────────────────────────────────────────────────

def test_direction_score_counts_human_events():
    """Direction events (lock, regen, edit, accept, reject) count toward score."""
    p = _make_project()
    p.timeline = []
    append_event(p.timeline, "ai_generated",        "AI",    "generated")   # NOT direction
    append_event(p.timeline, "section_locked",       "Human", "locked")      # direction
    append_event(p.timeline, "section_regenerated",  "AI",    "regen")       # direction
    append_event(p.timeline, "human_edit",           "Human", "edit")        # direction
    r = compute_contribution(p)
    # 3 of 4 events are direction events
    assert r["direction_score"] == round(3 / 4 * 100, 1)


def test_section_accepted_counts_as_direction_event():
    """section_accepted event contributes to direction_score."""
    p = _make_project()
    p.timeline = []
    append_event(p.timeline, "project_created",  "Human", "created")   # NOT direction
    append_event(p.timeline, "section_accepted", "Human", "accepted")  # direction
    r = compute_contribution(p)
    assert r["direction_score"] == round(1 / 2 * 100, 1)


def test_section_rejected_counts_as_direction_event():
    """section_rejected event contributes to direction_score."""
    p = _make_project()
    p.timeline = []
    append_event(p.timeline, "section_rejected", "Human", "rejected")
    r = compute_contribution(p)
    assert r["direction_score"] == 100.0


def test_direction_score_zero_when_only_ai_events():
    """No human direction events → direction_score == 0."""
    p = _make_project()
    p.timeline = []
    append_event(p.timeline, "project_created", "Human", "created")
    append_event(p.timeline, "ai_generated",    "AI",    "generated")
    r = compute_contribution(p)
    assert r["direction_score"] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# build_passport_pdf() — Core
# ─────────────────────────────────────────────────────────────────────────────

def test_passport_returns_bytes():
    """build_passport_pdf() returns bytes."""
    p = _make_project()
    pdf = build_passport_pdf(p)
    assert isinstance(pdf, bytes)


def test_passport_starts_with_pdf_magic_bytes():
    """PDF output starts with %PDF magic bytes."""
    p = _make_project()
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF", f"Expected %PDF, got {pdf[:8]!r}"


def test_passport_minimum_size():
    """PDF is at least 1 KB — not an empty or trivially broken output."""
    p = _make_project()
    pdf = build_passport_pdf(p)
    assert len(pdf) > 1024, f"PDF too small: {len(pdf)} bytes"


def test_passport_does_not_mutate_project_passport():
    """build_passport_pdf() is pure — does not write to project.passport."""
    p = _make_project()
    p.passport = {}
    build_passport_pdf(p)
    assert p.passport == {}


def test_passport_empty_song_does_not_crash():
    """Empty song/timeline produces a valid PDF without crashing."""
    p = Project(name="Empty Project", vibe="nothing")
    pdf = build_passport_pdf(p)
    assert isinstance(pdf, bytes) and pdf[:4] == b"%PDF"


# ─────────────────────────────────────────────────────────────────────────────
# build_passport_pdf() — Transparency statement preservation
# ─────────────────────────────────────────────────────────────────────────────

def test_custom_transparency_statement_not_overwritten():
    """Human-approved transparency_statement is not overwritten on export."""
    p = _make_project()
    custom = "This is carefully crafted human text that must survive."
    p.passport = {"transparency_statement": custom, "authorship_line": "", "watermark_id": None}
    build_passport_pdf(p)
    assert p.passport["transparency_statement"] == custom


def test_exporting_twice_preserves_transparency_statement():
    """Calling build_passport_pdf() twice does not overwrite custom statement."""
    p = _make_project()
    custom = "Approved statement — do not overwrite."
    p.passport = {"transparency_statement": custom, "authorship_line": "", "watermark_id": None}
    build_passport_pdf(p)
    build_passport_pdf(p)
    assert p.passport["transparency_statement"] == custom


# ─────────────────────────────────────────────────────────────────────────────
# Staleness logic — last creative event, not last event overall
# ─────────────────────────────────────────────────────────────────────────────

_DERIVED_EVENTS = {"contribution_computed", "passport_exported"}


def _last_creative_ts(timeline: list) -> str:
    """Mirror the staleness logic in _render_contribution_dashboard."""
    creative = [e for e in timeline if e.get("event_type") not in _DERIVED_EVENTS]
    return creative[-1]["timestamp"] if creative else ""


def test_staleness_ignores_contribution_computed_event():
    """contribution_computed must not reset the staleness clock."""
    import time
    from datetime import datetime

    p = _make_project("ai_generated")
    p.contribution = {
        "human_pct": 0.0, "ai_pct": 100.0, "direction_score": 0.0,
        "computed_at": datetime.now().isoformat(), "methodology_version": 1,
    }
    time.sleep(0.01)
    append_event(p.timeline, "contribution_computed", "AI", "computed")

    last_creative = _last_creative_ts(p.timeline)
    last_overall  = p.timeline[-1]["timestamp"]
    assert last_creative != last_overall
    # computed_at is after the last creative event → still fresh
    assert p.contribution["computed_at"] >= last_creative


def test_staleness_ignores_passport_exported_event():
    """passport_exported must not reset the staleness clock."""
    import time
    from datetime import datetime

    p = _make_project("ai_generated")
    p.contribution = {
        "human_pct": 0.0, "ai_pct": 100.0, "direction_score": 0.0,
        "computed_at": datetime.now().isoformat(), "methodology_version": 1,
    }
    time.sleep(0.01)
    append_event(p.timeline, "passport_exported", "Human", "exported")

    last_creative = _last_creative_ts(p.timeline)
    assert p.timeline[-1]["event_type"] == "passport_exported"
    assert last_creative != p.timeline[-1]["timestamp"]
    assert p.contribution["computed_at"] >= last_creative


def test_staleness_triggers_after_real_creative_action():
    """A real action after derived events makes the cache stale."""
    import time
    from datetime import datetime

    p = _make_project("ai_generated")
    p.contribution = {
        "human_pct": 0.0, "ai_pct": 100.0, "direction_score": 0.0,
        "computed_at": datetime.now().isoformat(), "methodology_version": 1,
    }
    append_event(p.timeline, "contribution_computed", "AI",    "computed")
    append_event(p.timeline, "passport_exported",     "Human", "exported")
    time.sleep(0.01)
    append_event(p.timeline, "human_edit", "Human", "Edited verse 1")

    last_creative = _last_creative_ts(p.timeline)
    assert last_creative == p.timeline[-1]["timestamp"]
    assert p.contribution["computed_at"] < last_creative


# ─────────────────────────────────────────────────────────────────────────────
# Accept / Reject — timeline event logging
# (Tests the event-logging logic directly, without Streamlit context)
# ─────────────────────────────────────────────────────────────────────────────

def test_section_accepted_event_leaves_lyrics_unchanged():
    """Logging section_accepted does not change lyrics or provenance."""
    p = _make_project("ai_generated")
    original_lyrics = p.song["sections"]["chorus"]["lyrics"]
    original_prov   = p.song["sections"]["chorus"]["provenance"]

    append_event(
        p.timeline,
        event_type  = "section_accepted",
        actor       = "Human",
        description = "Section accepted: chorus",
        metadata    = {"section_key": "chorus"},
    )

    assert p.song["sections"]["chorus"]["lyrics"]     == original_lyrics
    assert p.song["sections"]["chorus"]["provenance"] == original_prov


def test_section_rejected_event_logged_correctly():
    """section_rejected event is appended with correct fields."""
    p = _make_project("ai_generated")
    before_len = len(p.timeline)

    append_event(
        p.timeline,
        event_type  = "section_rejected",
        actor       = "Human",
        description = "Section rejected: bridge",
        metadata    = {"section_key": "bridge"},
    )

    assert len(p.timeline) == before_len + 1
    evt = p.timeline[-1]
    assert evt["event_type"] == "section_rejected"
    assert evt["actor"]      == "Human"
    assert evt["metadata"]["section_key"] == "bridge"


def test_direction_score_reflects_accept_reject_events():
    """direction_score includes section_accepted and section_rejected counts."""
    p = _make_project()
    p.timeline = []
    append_event(p.timeline, "ai_generated",     "AI",    "gen")
    append_event(p.timeline, "section_accepted", "Human", "accept chorus")
    append_event(p.timeline, "section_rejected", "Human", "reject bridge")
    r = compute_contribution(p)
    # 2 of 3 events are direction events
    assert r["direction_score"] == round(2 / 3 * 100, 1)


# ─────────────────────────────────────────────────────────────────────────────
# Standalone runner (bonus — matches Phase 3 style)
# ─────────────────────────────────────────────────────────────────────────────

_TESTS = [
    test_all_ai_generated_returns_ai_100,
    test_all_human_written_returns_human_100,
    test_all_ai_then_human_returns_50_50,
    test_mixed_provenance_weighted_average,
    test_human_and_ai_pct_sum_to_100,
    test_empty_song_returns_zeros_no_crash,
    test_empty_timeline_returns_direction_score_zero,
    test_return_shape_has_all_required_keys,
    test_computed_at_is_iso_string,
    test_methodology_version_is_1,
    test_does_not_mutate_project,
    test_direction_score_counts_human_events,
    test_section_accepted_counts_as_direction_event,
    test_section_rejected_counts_as_direction_event,
    test_direction_score_zero_when_only_ai_events,
    test_passport_returns_bytes,
    test_passport_starts_with_pdf_magic_bytes,
    test_passport_minimum_size,
    test_passport_does_not_mutate_project_passport,
    test_passport_empty_song_does_not_crash,
    test_custom_transparency_statement_not_overwritten,
    test_exporting_twice_preserves_transparency_statement,
    test_staleness_ignores_contribution_computed_event,
    test_staleness_ignores_passport_exported_event,
    test_staleness_triggers_after_real_creative_action,
    test_section_accepted_event_leaves_lyrics_unchanged,
    test_section_rejected_event_logged_correctly,
    test_direction_score_reflects_accept_reject_events,
]


def run_tests() -> int:
    """Run all Phase 4 tests. Returns the number of failures."""
    total  = len(_TESTS)
    passed = 0
    failed = 0

    print(f"\n{'=' * 60}")
    print(f"  HarmonyLedger — Phase 4 Test Harness")
    print(f"  Creative Ownership Intelligence")
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
