"""
tests/test_passport_integrity.py
──────────────────────────────────
Tests for the Creative Passport integrity marker.

canonical_record() and compute_record_hash() live in utils/passport.py.
record_hash is stamped into project.passport by the export caller
(views/view_project.py) before build_passport_pdf() is called.

Coverage
────────
  1. canonical_record() structure — required top-level keys present and typed.

  2. Determinism — identical project state produces identical record and
     identical hash on repeated calls.

  3. Ordering stability — dictionary insertion order in song.sections and
     timeline does not affect the canonical record or the hash.

  4. Hash sensitivity — mutating any relevant authorship field (lyrics,
     provenance, timeline event, contribution percentage, language) produces
     a different hash.

  5. Hash stability against irrelevant mutations — changing last_modified_at,
     contribution.computed_at, or PDF-layout choices does not affect the hash.

  6. Section canonical ordering — sections are always ordered by _SECTION_ORDER
     regardless of how they appear in the project dict.

  7. Repeated-export stability — two exports of the same project state with
     different watermark_ids produce different hashes (they cover different
     export instances), while the same stamped passport produces the same hash.

  8. Minimal project — a project with no song and no timeline hashes cleanly.

  9. Backward compatibility — a project loaded from a pre-record_hash file
     (missing 'record_hash' key in passport) loads and exports without error;
     build_passport_pdf() treats the missing key as empty string.

  10. No interaction with drift check — compute_record_hash() uses hashlib
      SHA-256 independently; calling it does not affect snapshot_locked_sections()
      or assert_locked_sections_unchanged().

  11. Hash format — 64-character lowercase hex string.

  12. Unicode content — non-ASCII lyrics (Devanagari, CJK) hash correctly and
      deterministically.

  13. PDF contains record hash — after stamping record_hash into project.passport,
      build_passport_pdf() produces a valid PDF without crashing.

Run:
    pytest tests/test_passport_integrity.py -v
    python tests/test_passport_integrity.py    (standalone)
"""

import sys
import os
import copy
import json
import hashlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.passport import (
    canonical_record,
    compute_record_hash,
    build_passport_pdf,
    _SECTION_ORDER,
)
from utils.models import Project
from utils.timeline import append_event
from utils.contribution import compute_contribution
from utils.ai_engine import (
    snapshot_locked_sections,
    assert_locked_sections_unchanged,
    DriftError,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

_SECTION_KEYS = ("verse_1", "chorus", "verse_2", "bridge", "outro")


def _make_project(
    *,
    title: str = "Autumn Echoes",
    language: str = "English",
    prov: str = "ai_generated",
) -> Project:
    """Return a fully-populated Project for testing."""
    p = Project(name="Test Integrity Project", vibe="Hopeful indie folk vibes")
    p.language = language
    p.song = {
        "title":      title,
        "genre":      "Indie Folk",
        "style":      "Acoustic",
        "mood":       "Hopeful",
        "tempo":      "92 BPM",
        "key":        "G major",
        "time_signature": "4/4",
        "model_used": "gemini-2.5-flash",
        "sections": {
            k: {
                "provenance":     prov,
                "lyrics":         f"Some {k} lyrics for testing.",
                "last_edited_by": "AI",
                "edit_count":     0,
                "locked":         k in ("verse_1", "chorus"),
                "locked_at":      None,
                "locked_by":      None,
            }
            for k in _SECTION_KEYS
        },
    }
    append_event(p.timeline, "project_created",    "Human", "Project created")
    append_event(p.timeline, "ai_generated",        "AI",    title)
    append_event(p.timeline, "section_locked",      "Human", "Locked verse_1",
                 metadata={"section_key": "verse_1"})
    append_event(p.timeline, "section_locked",      "Human", "Locked chorus",
                 metadata={"section_key": "chorus"})
    append_event(p.timeline, "human_edit",          "Human", "Edited bridge",
                 metadata={"section_key": "bridge"})
    append_event(p.timeline, "section_regenerated", "AI",    "Regenerated outro",
                 metadata={"section_key": "outro"})
    p.contribution = compute_contribution(p)
    p.passport = {
        "exported_at":            "2025-07-18T14:30:00",
        "export_format":          "pdf",
        "transparency_statement": "",
        "authorship_line":        "",
        "watermark_id":           "test-watermark-aabbccdd",
        "record_hash":            None,
    }
    return p


def _make_minimal_project() -> Project:
    """A project with no song and no timeline."""
    p = Project(name="Minimal", vibe="nothing")
    p.passport = {
        "exported_at": "2025-01-01T00:00:00",
        "watermark_id": "minimal-wm",
    }
    return p


# ─────────────────────────────────────────────────────────────────────────────
# 1. canonical_record() structure
# ─────────────────────────────────────────────────────────────────────────────

def test_canonical_record_has_required_keys():
    p = _make_project()
    rec = canonical_record(p)
    required = {
        "project_id", "project_version", "language",
        "song_title", "song_genre", "song_model_used",
        "sections", "timeline", "contribution",
        "watermark_id", "exported_at",
    }
    missing = required - rec.keys()
    assert not missing, f"canonical_record() missing keys: {missing}"


def test_canonical_record_sections_is_list():
    p = _make_project()
    rec = canonical_record(p)
    assert isinstance(rec["sections"], list)


def test_canonical_record_timeline_is_list():
    p = _make_project()
    rec = canonical_record(p)
    assert isinstance(rec["timeline"], list)


def test_canonical_record_contribution_has_required_fields():
    p = _make_project()
    rec = canonical_record(p)
    contrib = rec["contribution"]
    for key in ("human_pct", "ai_pct", "direction_score", "methodology_version"):
        assert key in contrib, f"contribution missing '{key}'"


def test_canonical_record_contribution_excludes_computed_at():
    """computed_at changes on every recompute — must not appear in the record."""
    p = _make_project()
    rec = canonical_record(p)
    assert "computed_at" not in rec["contribution"]


def test_canonical_record_excludes_last_modified_at():
    """last_modified_at is a filesystem timestamp — must not appear in the record."""
    p = _make_project()
    rec = canonical_record(p)
    assert "last_modified_at" not in rec


def test_canonical_record_section_entries_have_required_fields():
    p = _make_project()
    rec = canonical_record(p)
    for entry in rec["sections"]:
        for f in ("key", "lyrics", "provenance", "locked"):
            assert f in entry, f"section entry missing '{f}': {entry}"


def test_canonical_record_timeline_entries_have_required_fields():
    p = _make_project()
    rec = canonical_record(p)
    for entry in rec["timeline"]:
        for f in ("seq", "event_type", "actor", "description", "timestamp"):
            assert f in entry, f"timeline entry missing '{f}': {entry}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Determinism
# ─────────────────────────────────────────────────────────────────────────────

def test_same_project_produces_same_canonical_record():
    p = _make_project()
    r1 = canonical_record(p)
    r2 = canonical_record(p)
    assert r1 == r2


def test_same_project_produces_same_hash():
    p = _make_project()
    h1 = compute_record_hash(p)
    h2 = compute_record_hash(p)
    assert h1 == h2


def test_hash_is_deterministic_across_separate_project_instances():
    """Two independently constructed projects with identical data → same hash."""
    p1 = _make_project()
    p2 = _make_project()
    # Both projects are constructed identically except project_id and timestamps.
    # Force identical values for the fields covered by the hash.
    p2.project_id              = p1.project_id
    p2.version                 = p1.version
    p2.passport["watermark_id"] = p1.passport["watermark_id"]
    p2.passport["exported_at"] = p1.passport["exported_at"]
    # Timeline timestamps differ (created at slightly different times).
    # Copy the exact timeline from p1 so the hashes can match.
    p2.timeline = list(p1.timeline)
    p2.contribution = dict(p1.contribution)
    assert compute_record_hash(p1) == compute_record_hash(p2)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Ordering stability
# ─────────────────────────────────────────────────────────────────────────────

def test_hash_stable_despite_section_dict_reordering():
    """Shuffling the order of keys inside the sections dict does not change the hash."""
    p_forward = _make_project()
    p_reverse = _make_project()

    # Force both to have identical metadata
    p_reverse.project_id              = p_forward.project_id
    p_reverse.passport["watermark_id"] = p_forward.passport["watermark_id"]
    p_reverse.passport["exported_at"] = p_forward.passport["exported_at"]
    p_reverse.timeline                = list(p_forward.timeline)
    p_reverse.contribution            = dict(p_forward.contribution)

    # Reverse the section insertion order in p_reverse
    orig_sections = p_forward.song["sections"]
    reversed_sections = {k: orig_sections[k] for k in reversed(list(orig_sections.keys()))}
    p_reverse.song = dict(p_forward.song)
    p_reverse.song["sections"] = reversed_sections

    h_forward = compute_record_hash(p_forward)
    h_reverse = compute_record_hash(p_reverse)
    assert h_forward == h_reverse, (
        "Hash changed when section dict key order was reversed — ordering stability broken"
    )


def test_hash_stable_despite_timeline_list_reordering():
    """Shuffling timeline list order (same events, different list positions) changes the
    hash only if seq values differ — if seq values are preserved the sort restores order."""
    p = _make_project()
    # Build a scrambled copy with the same seq values
    scrambled_timeline = list(reversed(p.timeline))
    p2 = _make_project()
    p2.project_id              = p.project_id
    p2.passport["watermark_id"] = p.passport["watermark_id"]
    p2.passport["exported_at"] = p.passport["exported_at"]
    p2.contribution            = dict(p.contribution)
    p2.timeline                = scrambled_timeline
    # seq values are preserved — sorted() in canonical_record restores original order
    assert compute_record_hash(p) == compute_record_hash(p2)


def test_canonical_record_sections_in_canonical_order():
    """canonical_record() always returns sections in _SECTION_ORDER, regardless of
    the order they appear in the project dict."""
    p = _make_project()
    rec = canonical_record(p)
    keys_in_record = [e["key"] for e in rec["sections"]]
    expected_keys  = [k for k in _SECTION_ORDER if k in p.song.get("sections", {})]
    assert keys_in_record == expected_keys


def test_json_serialisation_uses_sort_keys():
    """The hash function uses sort_keys=True — verify by round-tripping."""
    p = _make_project()
    rec = canonical_record(p)
    s1 = json.dumps(rec, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    s2 = json.dumps(rec, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert s1 == s2
    # And the hash of the serialised form matches compute_record_hash()
    expected = hashlib.sha256(s1.encode("utf-8")).hexdigest()
    assert compute_record_hash(p) == expected


# ─────────────────────────────────────────────────────────────────────────────
# 4. Hash sensitivity — relevant mutations change the hash
# ─────────────────────────────────────────────────────────────────────────────

def _mutated_project(original: Project, mutate_fn) -> Project:
    """Deep-copy *original*, apply *mutate_fn*, return the copy."""
    p = copy.deepcopy(original)
    mutate_fn(p)
    return p


def test_hash_changes_when_lyrics_change():
    base = _make_project()
    h_before = compute_record_hash(base)
    mutated  = _mutated_project(base, lambda p: p.song["sections"]["verse_1"].update(
        {"lyrics": "Completely different verse lyrics."}
    ))
    assert compute_record_hash(mutated) != h_before


def test_hash_changes_when_provenance_changes():
    base = _make_project()
    h_before = compute_record_hash(base)
    mutated  = _mutated_project(base, lambda p: p.song["sections"]["chorus"].update(
        {"provenance": "human_written"}
    ))
    assert compute_record_hash(mutated) != h_before


def test_hash_changes_when_locked_state_changes():
    base = _make_project()
    h_before = compute_record_hash(base)
    mutated  = _mutated_project(base, lambda p: p.song["sections"]["verse_1"].update(
        {"locked": False}
    ))
    assert compute_record_hash(mutated) != h_before


def test_hash_changes_when_timeline_event_added():
    base = _make_project()
    h_before = compute_record_hash(base)
    mutated  = _mutated_project(base, lambda p: append_event(
        p.timeline, "human_edit", "Human", "Extra edit"
    ))
    assert compute_record_hash(mutated) != h_before


def test_hash_changes_when_timeline_event_description_changes():
    base = _make_project()
    h_before = compute_record_hash(base)
    mutated  = _mutated_project(base, lambda p: p.timeline[0].update(
        {"description": "Altered description"}
    ))
    assert compute_record_hash(mutated) != h_before


def test_hash_changes_when_human_pct_changes():
    base = _make_project()
    h_before = compute_record_hash(base)
    mutated  = _mutated_project(base, lambda p: p.contribution.update(
        {"human_pct": 99.9, "ai_pct": 0.1}
    ))
    assert compute_record_hash(mutated) != h_before


def test_hash_changes_when_direction_score_changes():
    base = _make_project()
    h_before = compute_record_hash(base)
    mutated  = _mutated_project(base, lambda p: p.contribution.update(
        {"direction_score": 0.0}
    ))
    assert compute_record_hash(mutated) != h_before


def test_hash_changes_when_language_changes():
    base     = _make_project(language="English")
    mutated  = _mutated_project(base, lambda p: setattr(p, "language", "Hindi"))
    assert compute_record_hash(base) != compute_record_hash(mutated)


def test_hash_changes_when_song_title_changes():
    base    = _make_project(title="Original Title")
    mutated = _mutated_project(base, lambda p: p.song.update({"title": "New Title"}))
    assert compute_record_hash(base) != compute_record_hash(mutated)


def test_hash_changes_when_watermark_id_changes():
    base = _make_project()
    mutated = _mutated_project(base, lambda p: p.passport.update(
        {"watermark_id": "completely-different-watermark-id"}
    ))
    assert compute_record_hash(base) != compute_record_hash(mutated)


def test_hash_changes_when_exported_at_changes():
    base = _make_project()
    mutated = _mutated_project(base, lambda p: p.passport.update(
        {"exported_at": "2099-01-01T00:00:00"}
    ))
    assert compute_record_hash(base) != compute_record_hash(mutated)


def test_hash_changes_when_project_version_changes():
    base    = _make_project()
    mutated = _mutated_project(base, lambda p: setattr(p, "version", p.version + 1))
    assert compute_record_hash(base) != compute_record_hash(mutated)


def test_hash_changes_when_section_removed():
    base = _make_project()
    h_before = compute_record_hash(base)
    mutated  = _mutated_project(base, lambda p: p.song["sections"].pop("outro"))
    assert compute_record_hash(mutated) != h_before


def test_hash_changes_when_methodology_version_changes():
    base = _make_project()
    h_before = compute_record_hash(base)
    mutated  = _mutated_project(base, lambda p: p.contribution.update(
        {"methodology_version": 99}
    ))
    assert compute_record_hash(mutated) != h_before


# ─────────────────────────────────────────────────────────────────────────────
# 5. Hash stability against irrelevant mutations
# ─────────────────────────────────────────────────────────────────────────────

def test_hash_stable_when_last_modified_at_changes():
    """last_modified_at is a filesystem/session timestamp — excluded from record."""
    base = _make_project()
    h_before = compute_record_hash(base)
    mutated = _mutated_project(base, lambda p: setattr(
        p, "last_modified_at", "2099-12-31T23:59:59"
    ))
    assert compute_record_hash(mutated) == h_before


def test_hash_stable_when_contribution_computed_at_changes():
    """contribution.computed_at changes on every recompute — must not affect hash."""
    base = _make_project()
    h_before = compute_record_hash(base)
    mutated  = _mutated_project(base, lambda p: p.contribution.update(
        {"computed_at": "2099-01-01T00:00:00"}
    ))
    assert compute_record_hash(mutated) == h_before


def test_hash_stable_when_section_edit_count_changes():
    """edit_count is a counter, not an authorship field — excluded from record."""
    base = _make_project()
    h_before = compute_record_hash(base)
    mutated  = _mutated_project(base, lambda p: p.song["sections"]["bridge"].update(
        {"edit_count": 999}
    ))
    assert compute_record_hash(mutated) == h_before


def test_hash_stable_when_section_locked_at_changes():
    """locked_at is a timestamp field, not authorship content — excluded."""
    base = _make_project()
    h_before = compute_record_hash(base)
    mutated  = _mutated_project(base, lambda p: p.song["sections"]["verse_1"].update(
        {"locked_at": "2099-06-15T10:00:00"}
    ))
    assert compute_record_hash(mutated) == h_before


def test_hash_stable_when_section_last_edited_by_changes():
    """last_edited_by is metadata — excluded from canonical record."""
    base = _make_project()
    h_before = compute_record_hash(base)
    mutated  = _mutated_project(base, lambda p: p.song["sections"]["chorus"].update(
        {"last_edited_by": "Human"}
    ))
    assert compute_record_hash(mutated) == h_before


def test_hash_stable_when_timeline_event_metadata_changes():
    """event metadata (model_id, tokens_used, etc.) is excluded — seq/type/actor/desc/ts only."""
    base = _make_project()
    h_before = compute_record_hash(base)
    mutated  = _mutated_project(base, lambda p: p.timeline[0].update(
        {"metadata": {"extra_key": "extra_value"}}
    ))
    assert compute_record_hash(mutated) == h_before


def test_hash_stable_when_timeline_event_ext_changes():
    """timeline event ext envelope is excluded from canonical record."""
    base = _make_project()
    h_before = compute_record_hash(base)
    mutated  = _mutated_project(base, lambda p: p.timeline[0].update(
        {"ext": {"third_party": "data"}}
    ))
    assert compute_record_hash(mutated) == h_before


# ─────────────────────────────────────────────────────────────────────────────
# 6. Section canonical ordering
# ─────────────────────────────────────────────────────────────────────────────

def test_all_present_sections_appear_in_canonical_record():
    p   = _make_project()
    rec = canonical_record(p)
    present_in_project  = set(p.song["sections"].keys())
    present_in_record   = {e["key"] for e in rec["sections"]}
    assert present_in_project == present_in_record


def test_extra_sections_appear_after_standard_ones():
    """Custom sections (not in _SECTION_ORDER) must come after the standard ones."""
    p = _make_project()
    p.song["sections"]["custom_intro"] = {
        "provenance": "human_written",
        "lyrics":     "A custom intro.",
        "locked":     False,
        "locked_at":  None,
        "locked_by":  None,
        "last_edited_by": "Human",
        "edit_count": 1,
    }
    rec  = canonical_record(p)
    keys = [e["key"] for e in rec["sections"]]
    # All standard keys come before the custom one
    standard_indices = [keys.index(k) for k in _SECTION_ORDER if k in keys]
    custom_index     = keys.index("custom_intro")
    assert all(i < custom_index for i in standard_indices), (
        f"Custom section appeared before standard sections: {keys}"
    )


def test_missing_section_not_in_canonical_record():
    """A section key not present in the project must not appear in the record."""
    p = _make_project()
    p.song["sections"].pop("bridge")
    rec  = canonical_record(p)
    keys = [e["key"] for e in rec["sections"]]
    assert "bridge" not in keys


# ─────────────────────────────────────────────────────────────────────────────
# 7. Repeated-export stability
# ─────────────────────────────────────────────────────────────────────────────

def test_same_stamped_passport_produces_same_hash():
    """Calling compute_record_hash() twice on the same stamped project gives
    the same result — hash is deterministic for a fixed state."""
    p  = _make_project()
    h1 = compute_record_hash(p)
    h2 = compute_record_hash(p)
    assert h1 == h2


def test_different_watermarks_produce_different_hashes():
    """Two exports of the same project with different watermark_ids must produce
    different hashes — each export instance has a unique integrity marker."""
    p1 = _make_project()
    p2 = copy.deepcopy(p1)
    p2.passport["watermark_id"] = "different-watermark-xyz"
    assert compute_record_hash(p1) != compute_record_hash(p2)


def test_build_passport_pdf_with_record_hash_does_not_crash():
    """After stamping record_hash into project.passport, the PDF builds cleanly."""
    p = _make_project()
    p.passport["record_hash"] = compute_record_hash(p)
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 2048


def test_build_passport_pdf_without_record_hash_does_not_crash():
    """record_hash may be absent (pre-feature projects) — PDF must still build."""
    p = _make_project()
    p.passport.pop("record_hash", None)
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF"


def test_build_passport_pdf_with_none_record_hash_does_not_crash():
    """record_hash=None (just-created passport dict) — PDF must still build."""
    p = _make_project()
    p.passport["record_hash"] = None
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF"


def test_build_passport_pdf_with_empty_record_hash_does_not_crash():
    """record_hash='' — PDF must still build."""
    p = _make_project()
    p.passport["record_hash"] = ""
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF"


# ─────────────────────────────────────────────────────────────────────────────
# 8. Minimal project
# ─────────────────────────────────────────────────────────────────────────────

def test_canonical_record_minimal_project():
    p   = _make_minimal_project()
    rec = canonical_record(p)
    assert rec["sections"]   == []
    assert rec["timeline"]   == []
    assert rec["song_title"] == ""


def test_compute_record_hash_minimal_project():
    p = _make_minimal_project()
    h = compute_record_hash(p)
    assert isinstance(h, str)
    assert len(h) == 64


def test_hash_deterministic_minimal_project():
    p = _make_minimal_project()
    assert compute_record_hash(p) == compute_record_hash(p)


# ─────────────────────────────────────────────────────────────────────────────
# 9. Backward compatibility
# ─────────────────────────────────────────────────────────────────────────────

def test_project_without_record_hash_field_loads_cleanly():
    """An old project dict without 'record_hash' in passport parses without error."""
    data = {
        "project_id":    "old-project-id-123",
        "name":          "Old Project",
        "vibe":          "test vibe",
        "created_at":    "2024-01-01T00:00:00",
        "status":        "Complete",
        "version":       3,
        "schema_version":2,
        "language":      "English",
        "song":          {},
        "timeline":      [],
        "contribution":  {},
        "passport": {
            "exported_at":           "2024-06-01T10:00:00",
            "export_format":         "pdf",
            "transparency_statement":"",
            "authorship_line":       "",
            "watermark_id":          "old-wm",
            # Note: no "record_hash" key — pre-feature project
        },
        "collaborators": [],
        "ext":           {},
    }
    p = Project.from_dict(data)
    # record_hash absent → canonical_record returns empty string, PDF builds cleanly
    rec = canonical_record(p)
    assert rec["watermark_id"] == "old-wm"
    assert rec.get("record_hash") is None   # NOT in the canonical record itself
    # build_passport_pdf must not crash
    pdf = build_passport_pdf(p)
    assert pdf[:4] == b"%PDF"


def test_record_hash_in_passport_dict_survives_project_roundtrip():
    """record_hash stored in project.passport survives to_dict → from_dict."""
    p = _make_project()
    p.passport["record_hash"] = compute_record_hash(p)
    p2 = Project.from_dict(p.to_dict())
    assert p2.passport.get("record_hash") == p.passport["record_hash"]


def test_existing_passport_fields_unchanged_after_adding_record_hash():
    """Adding record_hash to project.passport does not disturb existing fields."""
    p = _make_project()
    original_wm  = p.passport["watermark_id"]
    original_exp = p.passport["exported_at"]
    p.passport["record_hash"] = compute_record_hash(p)
    assert p.passport["watermark_id"] == original_wm
    assert p.passport["exported_at"]  == original_exp


# ─────────────────────────────────────────────────────────────────────────────
# 10. No interaction with drift check
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_record_hash_does_not_affect_locked_section_snapshot():
    """compute_record_hash() is read-only; it must not mutate song sections."""
    p        = _make_project()
    snapshot = snapshot_locked_sections(p.song)
    # Compute the hash — must not change the song content
    _        = compute_record_hash(p)
    # The drift check must still pass
    assert_locked_sections_unchanged(p.song, snapshot)


def test_drift_check_still_catches_drift_after_hash_computed():
    """The existing locked-section drift check is not affected by record hash logic."""
    p        = _make_project()
    snapshot = snapshot_locked_sections(p.song)
    # Compute the hash for good measure
    _        = compute_record_hash(p)
    # Now inject drift into a locked section
    p.song["sections"]["verse_1"]["lyrics"] = "DRIFTED lyrics — tampered"
    drifted = False
    try:
        assert_locked_sections_unchanged(p.song, snapshot)
    except DriftError:
        drifted = True
    assert drifted, "DriftError must still be raised even after compute_record_hash() was called"


def test_record_hash_covers_locked_content_change():
    """If locked lyrics change (triggering drift detection), the record hash also changes."""
    base    = _make_project()
    h_base  = compute_record_hash(base)
    mutated = _mutated_project(base, lambda p: p.song["sections"]["verse_1"].update(
        {"lyrics": "Different lyrics — would trigger drift if checked"}
    ))
    h_mutated = compute_record_hash(mutated)
    assert h_base != h_mutated, (
        "Hash should change when locked-section lyrics change"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 11. Hash format
# ─────────────────────────────────────────────────────────────────────────────

def test_hash_is_string():
    assert isinstance(compute_record_hash(_make_project()), str)


def test_hash_is_64_characters():
    h = compute_record_hash(_make_project())
    assert len(h) == 64, f"Expected 64 chars, got {len(h)}"


def test_hash_is_lowercase_hex():
    import re
    h = compute_record_hash(_make_project())
    assert re.fullmatch(r"[0-9a-f]{64}", h), f"Hash is not lowercase hex: {h!r}"


def test_hash_starts_with_expected_prefix_for_known_data():
    """Verify the hash function is actually SHA-256 by computing it manually."""
    p   = _make_project()
    rec = canonical_record(p)
    s   = json.dumps(rec, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    expected = hashlib.sha256(s.encode("utf-8")).hexdigest()
    assert compute_record_hash(p) == expected


# ─────────────────────────────────────────────────────────────────────────────
# 12. Unicode content
# ─────────────────────────────────────────────────────────────────────────────

_UNICODE_LYRICS = {
    "Hindi":    "\u092e\u0947\u0930\u093e \u0917\u093e\u0928\u093e",
    "Telugu":   "\u0c28\u0c3e \u0c2a\u0c3e\u0c1f",
    "Japanese": "\u79c1\u306e\u6b4c",
}


def test_unicode_lyrics_hash_deterministically():
    for lang, lyric in _UNICODE_LYRICS.items():
        p = _make_project(language=lang, title=lyric)
        for sec in p.song["sections"].values():
            sec["lyrics"] = lyric
        h1 = compute_record_hash(p)
        h2 = compute_record_hash(p)
        assert h1 == h2, f"[{lang}] Unicode hash not deterministic"


def test_unicode_lyrics_produce_different_hash_than_ascii():
    base = _make_project(title="English Title")
    for lang, lyric in _UNICODE_LYRICS.items():
        p = _make_project(title=lyric)
        assert compute_record_hash(base) != compute_record_hash(p), (
            f"[{lang}] Unicode title did not produce different hash from ASCII title"
        )


def test_unicode_project_with_record_hash_builds_valid_pdf():
    for lang, lyric in _UNICODE_LYRICS.items():
        p = _make_project(language=lang, title=lyric)
        for sec in p.song["sections"].values():
            sec["lyrics"] = lyric
        p.passport["record_hash"] = compute_record_hash(p)
        pdf = build_passport_pdf(p)
        assert pdf[:4] == b"%PDF", f"[{lang}] Invalid PDF"
        assert len(pdf) > 2048, f"[{lang}] PDF too small"


# ─────────────────────────────────────────────────────────────────────────────
# Standalone runner
# ─────────────────────────────────────────────────────────────────────────────

_TESTS = [
    test_canonical_record_has_required_keys,
    test_canonical_record_sections_is_list,
    test_canonical_record_timeline_is_list,
    test_canonical_record_contribution_has_required_fields,
    test_canonical_record_contribution_excludes_computed_at,
    test_canonical_record_excludes_last_modified_at,
    test_canonical_record_section_entries_have_required_fields,
    test_canonical_record_timeline_entries_have_required_fields,
    test_same_project_produces_same_canonical_record,
    test_same_project_produces_same_hash,
    test_hash_is_deterministic_across_separate_project_instances,
    test_hash_stable_despite_section_dict_reordering,
    test_hash_stable_despite_timeline_list_reordering,
    test_canonical_record_sections_in_canonical_order,
    test_json_serialisation_uses_sort_keys,
    test_hash_changes_when_lyrics_change,
    test_hash_changes_when_provenance_changes,
    test_hash_changes_when_locked_state_changes,
    test_hash_changes_when_timeline_event_added,
    test_hash_changes_when_timeline_event_description_changes,
    test_hash_changes_when_human_pct_changes,
    test_hash_changes_when_direction_score_changes,
    test_hash_changes_when_language_changes,
    test_hash_changes_when_song_title_changes,
    test_hash_changes_when_watermark_id_changes,
    test_hash_changes_when_exported_at_changes,
    test_hash_changes_when_project_version_changes,
    test_hash_changes_when_section_removed,
    test_hash_changes_when_methodology_version_changes,
    test_hash_stable_when_last_modified_at_changes,
    test_hash_stable_when_contribution_computed_at_changes,
    test_hash_stable_when_section_edit_count_changes,
    test_hash_stable_when_section_locked_at_changes,
    test_hash_stable_when_section_last_edited_by_changes,
    test_hash_stable_when_timeline_event_metadata_changes,
    test_hash_stable_when_timeline_event_ext_changes,
    test_all_present_sections_appear_in_canonical_record,
    test_extra_sections_appear_after_standard_ones,
    test_missing_section_not_in_canonical_record,
    test_same_stamped_passport_produces_same_hash,
    test_different_watermarks_produce_different_hashes,
    test_build_passport_pdf_with_record_hash_does_not_crash,
    test_build_passport_pdf_without_record_hash_does_not_crash,
    test_build_passport_pdf_with_none_record_hash_does_not_crash,
    test_build_passport_pdf_with_empty_record_hash_does_not_crash,
    test_canonical_record_minimal_project,
    test_compute_record_hash_minimal_project,
    test_hash_deterministic_minimal_project,
    test_project_without_record_hash_field_loads_cleanly,
    test_record_hash_in_passport_dict_survives_project_roundtrip,
    test_existing_passport_fields_unchanged_after_adding_record_hash,
    test_compute_record_hash_does_not_affect_locked_section_snapshot,
    test_drift_check_still_catches_drift_after_hash_computed,
    test_record_hash_covers_locked_content_change,
    test_hash_is_string,
    test_hash_is_64_characters,
    test_hash_is_lowercase_hex,
    test_hash_starts_with_expected_prefix_for_known_data,
    test_unicode_lyrics_hash_deterministically,
    test_unicode_lyrics_produce_different_hash_than_ascii,
    test_unicode_project_with_record_hash_builds_valid_pdf,
]


def run_tests() -> int:
    total  = len(_TESTS)
    passed = 0
    failed = 0

    print(f"\n{'=' * 64}")
    print(f"  HarmonyLedger — Passport Integrity Test Suite")
    print(f"  {total} tests")
    print(f"{'=' * 64}\n")

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

    print(f"\n{'=' * 64}")
    if failed:
        print(f"  Results: {passed}/{total}  ·  {failed} FAILED")
    else:
        print(f"  Results: {passed}/{total}  ·  ALL PASSED")
    print(f"{'=' * 64}\n")
    return failed


if __name__ == "__main__":
    sys.exit(0 if run_tests() == 0 else 1)
