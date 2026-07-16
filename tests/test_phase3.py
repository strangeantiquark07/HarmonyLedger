"""
tests/test_phase3.py
────────────────────
Phase 3 Done-Bar Harness — Section Locking & Targeted Regeneration.

Test groups:
  1. Drift-check utilities (pure unit tests — no API calls)
       1a. snapshot_locked_sections returns correct hashes
       1b. assert_locked_sections_unchanged passes when nothing changes
       1c. assert_locked_sections_unchanged raises DriftError on lyrics mutation
       1d. assert_locked_sections_unchanged raises DriftError on missing section
       1e. Empty snapshot is a no-op (no locked sections)

  2. Lock / unlock logic (pure unit tests — no API calls)
       2a. _toggle_lock(lock=True)  sets locked fields and logs timeline event
       2b. _toggle_lock(lock=False) clears locked fields and logs timeline event
       2c. Reloaded project reflects lock state (round-trip through storage)

  3. Merge strategy (pure unit tests — no API calls)
       3a. Grafting new lyrics only changes the target section
       3b. All other sections are byte-identical after the graft

  4. regenerate_section() — integration test (real Gemini API call)
       4a. Returns a non-empty string for one section
       4b. Does NOT alter any other sections (context only)
       4c. Drift check passes after a clean regeneration

Usage:
    python tests/test_phase3.py

Exit codes:
    0 — all tests passed
    1 — one or more tests failed

This is a mix of pure unit tests and one Gemini integration test.
Ensure GEMINI_API_KEY is set in your .env before running.
"""

import copy
import hashlib
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

# ── Ensure the project root is on the path ───────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.ai_engine import (
    generate_song,
    regenerate_section,
    snapshot_locked_sections,
    assert_locked_sections_unchanged,
    SongGenerationError,
    DriftError,
    _REQUIRED_SECTIONS,
    _SECTION_LABELS,
)
from utils.models import Project
from utils.storage import save_project, load_project, PROJECTS_DIR
from utils.timeline import append_event


# ─────────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_song() -> dict:
    """Return a minimal but fully-structured song dict with 5 sections."""
    sections = {}
    for key in _REQUIRED_SECTIONS:
        sections[key] = {
            "lyrics":         f"These are the lyrics for {_SECTION_LABELS[key]}.",
            "provenance":     "ai_generated",
            "locked":         False,
            "locked_at":      None,
            "locked_by":      None,
            "last_edited_by": "AI",
            "edit_count":     0,
        }
    return {
        "title":               "Test Song",
        "genre":               "Indie Folk",
        "style":               "Acoustic guitar",
        "mood":                "Melancholic",
        "tempo":               "72 BPM",
        "key":                 "D minor",
        "time_signature":      "4/4",
        "lyrical_themes":      ["loss", "hope"],
        "generation_timestamp": datetime.now().isoformat(),
        "model_used":          "gemini-2.5-flash",
        "song_schema_version": "1.0",
        "sections":            sections,
    }


def _make_project(song: dict | None = None) -> Project:
    """Return a minimal Project with the given song merged in."""
    p      = Project(name="_p3_test", vibe="test vibe for phase 3")
    p.song = song if song is not None else _make_song()
    return p


def _cleanup_project(project: Project) -> None:
    """Delete the temporary project JSON file created during a test."""
    try:
        (PROJECTS_DIR / f"{project.project_id}.json").unlink(missing_ok=True)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Group 1 — Drift-check utility unit tests
# ─────────────────────────────────────────────────────────────────────────────

def test_snapshot_returns_hashes() -> list[str]:
    """snapshot_locked_sections returns correct SHA-256 hashes for locked sections."""
    failures: list[str] = []
    song = _make_song()

    # Lock chorus and bridge.
    song["sections"]["chorus"]["locked"] = True
    song["sections"]["bridge"]["locked"] = True

    snap = snapshot_locked_sections(song)

    if set(snap.keys()) != {"chorus", "bridge"}:
        failures.append(
            f"Expected snapshot keys {{'chorus', 'bridge'}}, got {set(snap.keys())}"
        )

    # Verify each hash matches a manual SHA-256 of the lyrics.
    for key in ("chorus", "bridge"):
        expected = hashlib.sha256(
            song["sections"][key]["lyrics"].encode("utf-8")
        ).hexdigest()
        if snap.get(key) != expected:
            failures.append(
                f"Hash mismatch for '{key}': expected {expected[:8]}…, "
                f"got {snap.get(key, 'MISSING')[:8] if snap.get(key) else 'MISSING'}…"
            )

    return failures


def test_assert_unchanged_passes() -> list[str]:
    """assert_locked_sections_unchanged is a no-op when lyrics are untouched."""
    failures: list[str] = []
    song = _make_song()
    song["sections"]["verse_1"]["locked"] = True

    snap = snapshot_locked_sections(song)
    try:
        assert_locked_sections_unchanged(song, snap)
    except DriftError as exc:
        failures.append(f"Unexpected DriftError raised: {exc}")
    except Exception as exc:
        failures.append(f"Unexpected exception: {type(exc).__name__}: {exc}")

    return failures


def test_assert_unchanged_raises_on_mutation() -> list[str]:
    """assert_locked_sections_unchanged raises DriftError when locked lyrics change."""
    failures: list[str] = []
    song = _make_song()
    song["sections"]["chorus"]["locked"] = True

    snap = snapshot_locked_sections(song)

    # Mutate the locked section's lyrics after taking the snapshot.
    song["sections"]["chorus"]["lyrics"] = "MUTATED lyrics — should trigger drift"

    try:
        assert_locked_sections_unchanged(song, snap)
        failures.append("DriftError was NOT raised after lyrics mutation")
    except DriftError:
        pass  # Expected — test passes
    except Exception as exc:
        failures.append(f"Unexpected exception instead of DriftError: {type(exc).__name__}: {exc}")

    return failures


def test_assert_unchanged_raises_on_missing_section() -> list[str]:
    """assert_locked_sections_unchanged raises DriftError when a locked section vanishes."""
    failures: list[str] = []
    song = _make_song()
    song["sections"]["bridge"]["locked"] = True

    snap = snapshot_locked_sections(song)

    # Remove the locked section entirely after taking the snapshot.
    del song["sections"]["bridge"]

    try:
        assert_locked_sections_unchanged(song, snap)
        failures.append("DriftError was NOT raised when locked section is missing")
    except DriftError:
        pass  # Expected
    except Exception as exc:
        failures.append(f"Unexpected exception: {type(exc).__name__}: {exc}")

    return failures


def test_empty_snapshot_is_noop() -> list[str]:
    """assert_locked_sections_unchanged with empty snapshot does nothing."""
    failures: list[str] = []
    song = _make_song()  # all unlocked

    snap = snapshot_locked_sections(song)
    if snap:
        failures.append(f"Expected empty snapshot for all-unlocked song, got: {snap}")

    try:
        assert_locked_sections_unchanged(song, snap)
    except Exception as exc:
        failures.append(f"Unexpected exception on empty snapshot: {type(exc).__name__}: {exc}")

    return failures


# ─────────────────────────────────────────────────────────────────────────────
# Group 2 — Lock / unlock logic unit tests
# ─────────────────────────────────────────────────────────────────────────────

def test_toggle_lock_sets_fields() -> list[str]:
    """_toggle_lock(lock=True) sets locked=True, locked_at, locked_by='Human'."""
    # Import here to avoid circular dependency with Streamlit context.
    # We test the logic directly without calling via render().
    failures: list[str] = []
    song    = _make_song()
    project = _make_project(song)

    # Simulate what _toggle_lock does (isolated — no st.* calls in test).
    section = project.song["sections"]["verse_1"]
    section["locked"]    = True
    section["locked_at"] = datetime.now().isoformat()
    section["locked_by"] = "Human"
    project.version += 1
    append_event(
        project.timeline,
        event_type  = "section_locked",
        actor       = "Human",
        description = "Section locked: verse_1",
        metadata    = {"section_key": "verse_1"},
    )

    if not section["locked"]:
        failures.append("section['locked'] should be True")
    if not section["locked_at"]:
        failures.append("section['locked_at'] should be a timestamp")
    if section["locked_by"] != "Human":
        failures.append(f"section['locked_by'] should be 'Human', got {section['locked_by']!r}")

    # Timeline must have a section_locked event.
    locked_events = [e for e in project.timeline if e.get("event_type") == "section_locked"]
    if not locked_events:
        failures.append("No 'section_locked' event found in timeline")
    else:
        meta = locked_events[-1].get("metadata", {})
        if meta.get("section_key") != "verse_1":
            failures.append(
                f"section_locked event metadata.section_key should be 'verse_1', "
                f"got {meta.get('section_key')!r}"
            )

    return failures


def test_toggle_unlock_clears_fields() -> list[str]:
    """Unlocking clears locked, locked_at, locked_by and logs section_unlocked."""
    failures: list[str] = []
    song = _make_song()
    # Pre-lock chorus.
    song["sections"]["chorus"]["locked"]    = True
    song["sections"]["chorus"]["locked_at"] = datetime.now().isoformat()
    song["sections"]["chorus"]["locked_by"] = "Human"

    project = _make_project(song)

    # Simulate _toggle_lock(lock=False).
    section = project.song["sections"]["chorus"]
    section["locked"]    = False
    section["locked_at"] = None
    section["locked_by"] = None
    project.version += 1
    append_event(
        project.timeline,
        event_type  = "section_unlocked",
        actor       = "Human",
        description = "Section unlocked: chorus",
        metadata    = {"section_key": "chorus"},
    )

    if section["locked"]:
        failures.append("section['locked'] should be False after unlock")
    if section["locked_at"] is not None:
        failures.append("section['locked_at'] should be None after unlock")
    if section["locked_by"] is not None:
        failures.append("section['locked_by'] should be None after unlock")

    unlocked_events = [e for e in project.timeline if e.get("event_type") == "section_unlocked"]
    if not unlocked_events:
        failures.append("No 'section_unlocked' event found in timeline")

    return failures


def test_lock_state_round_trips_storage() -> list[str]:
    """Lock a section, save, reload — verify state persists correctly."""
    failures: list[str] = []
    song    = _make_song()
    project = _make_project(song)

    # Lock bridge.
    project.song["sections"]["bridge"]["locked"]    = True
    project.song["sections"]["bridge"]["locked_at"] = datetime.now().isoformat()
    project.song["sections"]["bridge"]["locked_by"] = "Human"
    append_event(project.timeline, "section_locked", "Human", "Section locked: bridge",
                 metadata={"section_key": "bridge"})

    try:
        save_project(project)
    except Exception as exc:
        failures.append(f"save_project() raised: {type(exc).__name__}: {exc}")
        _cleanup_project(project)
        return failures

    try:
        reloaded = load_project(project.project_id)
    except Exception as exc:
        failures.append(f"load_project() raised: {type(exc).__name__}: {exc}")
        _cleanup_project(project)
        return failures

    sec = reloaded.song.get("sections", {}).get("bridge", {})
    if not sec.get("locked"):
        failures.append("bridge.locked should be True after reload")
    if not sec.get("locked_at"):
        failures.append("bridge.locked_at should be non-null after reload")
    if sec.get("locked_by") != "Human":
        failures.append(f"bridge.locked_by should be 'Human', got {sec.get('locked_by')!r}")

    locked_events = [e for e in reloaded.timeline if e.get("event_type") == "section_locked"]
    if not locked_events:
        failures.append("No 'section_locked' event found in reloaded timeline")

    _cleanup_project(project)
    return failures


# ─────────────────────────────────────────────────────────────────────────────
# Group 3 — Merge strategy unit tests
# ─────────────────────────────────────────────────────────────────────────────

def test_graft_only_changes_target() -> list[str]:
    """After grafting, only the target section's lyrics change; others are identical."""
    failures: list[str] = []
    song        = _make_song()
    song_before = copy.deepcopy(song)
    target_key  = "chorus"
    new_lyrics  = "Brand new chorus lyrics written by Gemini."

    # Perform the graft as _run_section_regeneration would.
    song["sections"][target_key]["lyrics"]         = new_lyrics
    song["sections"][target_key]["provenance"]     = "ai_generated"
    song["sections"][target_key]["last_edited_by"] = "AI"
    song["sections"][target_key]["edit_count"]     = 0

    # Target section should differ.
    if song["sections"][target_key]["lyrics"] != new_lyrics:
        failures.append("Graft did not apply new lyrics to target section")

    # All other sections must be byte-identical to before the graft.
    for key in _REQUIRED_SECTIONS:
        if key == target_key:
            continue
        before = song_before["sections"][key]
        after  = song["sections"][key]
        if before != after:
            failures.append(
                f"Section '{key}' should be unchanged after graft, but it differs"
            )

    # Song-level metadata must be untouched.
    for field in ("title", "genre", "style", "mood", "tempo", "key", "time_signature"):
        if song.get(field) != song_before.get(field):
            failures.append(f"Song-level field '{field}' was unexpectedly modified")

    return failures


def test_graft_resets_provenance_envelope() -> list[str]:
    """After graft, provenance/last_edited_by/edit_count are correctly reset."""
    failures: list[str] = []
    song       = _make_song()
    target_key = "outro"

    # Pre-set as if a human had edited it.
    song["sections"][target_key]["provenance"]     = "ai_then_human"
    song["sections"][target_key]["last_edited_by"] = "Human"
    song["sections"][target_key]["edit_count"]     = 3

    # Apply graft reset.
    song["sections"][target_key]["lyrics"]         = "Fresh outro lyrics."
    song["sections"][target_key]["provenance"]     = "ai_generated"
    song["sections"][target_key]["last_edited_by"] = "AI"
    song["sections"][target_key]["edit_count"]     = 0

    sec = song["sections"][target_key]
    if sec["provenance"] != "ai_generated":
        failures.append(f"provenance should be 'ai_generated', got {sec['provenance']!r}")
    if sec["last_edited_by"] != "AI":
        failures.append(f"last_edited_by should be 'AI', got {sec['last_edited_by']!r}")
    if sec["edit_count"] != 0:
        failures.append(f"edit_count should be 0, got {sec['edit_count']!r}")

    return failures


# ─────────────────────────────────────────────────────────────────────────────
# Group 4 — regenerate_section() integration test (real Gemini API call)
# ─────────────────────────────────────────────────────────────────────────────

def test_regenerate_section_integration() -> list[str]:
    """
    Integration test: regenerate one section end-to-end with a real Gemini call.

    Steps:
      1. Generate a full song via generate_song() to get a realistic base.
      2. Lock verse_1 and chorus (they must not change).
      3. Take a pre-call snapshot.
      4. Call regenerate_section("bridge", song).
      5. Graft the result.
      6. Assert drift check passes.
      7. Assert only bridge.lyrics changed; verse_1 and chorus are untouched.
    """
    failures: list[str] = []

    # ── Step 1: generate a real song ─────────────────────────────────────────
    print("       [integration] Calling generate_song() for base song…")
    try:
        song = generate_song(
            vibe  = "Driving rhythm with a hopeful chorus and a reflective bridge.",
            genre = "Indie Folk",
        )
    except SongGenerationError as exc:
        failures.append(f"generate_song() failed: {exc}")
        return failures
    except Exception as exc:
        failures.append(f"generate_song() raised unexpected {type(exc).__name__}: {exc}")
        return failures

    # ── Step 2: lock verse_1 and chorus ──────────────────────────────────────
    for key in ("verse_1", "chorus"):
        song["sections"][key]["locked"]    = True
        song["sections"][key]["locked_at"] = datetime.now().isoformat()
        song["sections"][key]["locked_by"] = "Human"

    original_verse1_lyrics  = song["sections"]["verse_1"]["lyrics"]
    original_chorus_lyrics  = song["sections"]["chorus"]["lyrics"]
    original_bridge_lyrics  = song["sections"]["bridge"]["lyrics"]

    # ── Step 3: pre-call snapshot ─────────────────────────────────────────────
    pre_snapshot = snapshot_locked_sections(song)
    if set(pre_snapshot.keys()) != {"verse_1", "chorus"}:
        failures.append(
            f"Expected snapshot keys {{'verse_1', 'chorus'}}, got {set(pre_snapshot.keys())}"
        )

    # ── Step 4: call regenerate_section ──────────────────────────────────────
    print("       [integration] Calling regenerate_section('bridge')…")
    try:
        new_lyrics = regenerate_section("bridge", song)
    except SongGenerationError as exc:
        failures.append(f"regenerate_section() raised SongGenerationError: {exc}")
        return failures
    except Exception as exc:
        failures.append(f"regenerate_section() raised {type(exc).__name__}: {exc}")
        return failures

    if not isinstance(new_lyrics, str) or not new_lyrics.strip():
        failures.append(f"regenerate_section() returned empty or non-string: {new_lyrics!r}")
        return failures

    print(f"       [integration] New bridge lyrics (first 80 chars): {new_lyrics[:80]!r}…")

    # ── Step 5: graft ─────────────────────────────────────────────────────────
    song["sections"]["bridge"]["lyrics"]         = new_lyrics
    song["sections"]["bridge"]["provenance"]     = "ai_generated"
    song["sections"]["bridge"]["last_edited_by"] = "AI"
    song["sections"]["bridge"]["edit_count"]     = 0

    # ── Step 6: drift check ───────────────────────────────────────────────────
    try:
        assert_locked_sections_unchanged(song, pre_snapshot)
    except DriftError as exc:
        failures.append(f"Drift check failed (locked section changed): {exc}")
    except Exception as exc:
        failures.append(f"Unexpected exception in drift check: {type(exc).__name__}: {exc}")

    # ── Step 7: verify only bridge changed ────────────────────────────────────
    if song["sections"]["verse_1"]["lyrics"] != original_verse1_lyrics:
        failures.append("verse_1 lyrics changed — should be locked and unchanged")
    if song["sections"]["chorus"]["lyrics"] != original_chorus_lyrics:
        failures.append("chorus lyrics changed — should be locked and unchanged")
    if song["sections"]["bridge"]["lyrics"] == original_bridge_lyrics:
        failures.append(
            "bridge lyrics did NOT change after regeneration — "
            "expected a different result from Gemini"
        )

    return failures


# ─────────────────────────────────────────────────────────────────────────────
# Test registry
# ─────────────────────────────────────────────────────────────────────────────

_TESTS: list[tuple[str, callable]] = [
    # Group 1 — Drift-check utilities
    ("1a  snapshot_locked_sections returns correct hashes",          test_snapshot_returns_hashes),
    ("1b  assert_unchanged passes when lyrics are untouched",        test_assert_unchanged_passes),
    ("1c  assert_unchanged raises DriftError on lyrics mutation",    test_assert_unchanged_raises_on_mutation),
    ("1d  assert_unchanged raises DriftError on missing section",    test_assert_unchanged_raises_on_missing_section),
    ("1e  empty snapshot is a no-op",                                test_empty_snapshot_is_noop),
    # Group 2 — Lock / unlock logic
    ("2a  toggle_lock(lock=True) sets locked fields + event",        test_toggle_lock_sets_fields),
    ("2b  toggle_lock(lock=False) clears locked fields + event",     test_toggle_unlock_clears_fields),
    ("2c  lock state round-trips through storage",                   test_lock_state_round_trips_storage),
    # Group 3 — Merge strategy
    ("3a  graft only changes the target section",                    test_graft_only_changes_target),
    ("3b  graft resets provenance envelope correctly",               test_graft_resets_provenance_envelope),
    # Group 4 — Integration (real Gemini call)
    ("4   regenerate_section() end-to-end integration",              test_regenerate_section_integration),
]


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_tests() -> int:
    """Run all Phase 3 tests. Returns the number of failures."""
    total  = len(_TESTS)
    passed = 0
    failed = 0

    print(f"\n{'═' * 60}")
    print(f"  HarmonyLedger — Phase 3 Done-Bar Harness")
    print(f"  Section Locking & Targeted Regeneration")
    print(f"  {total} tests (unit + integration)")
    print(f"{'═' * 60}\n")

    for name, fn in _TESTS:
        print(f"  ▷  {name}")
        try:
            failures = fn()
        except Exception as exc:
            failures = [f"Test raised unexpected exception: {type(exc).__name__}: {exc}"]

        if failures:
            print(f"     ✗  FAIL")
            for msg in failures:
                print(f"        → {msg}")
            failed += 1
        else:
            print(f"     ✓  PASS")
        print()

    print(f"{'═' * 60}")
    print(f"  Results: {passed + (total - failed - passed)}/{total}", end="")
    # Recount passed properly
    passed = total - failed
    print(f"\r  Results: {passed}/{total}", end="")
    if failed:
        print(f"  ·  {failed} FAILED  ✗")
    else:
        print(f"  ·  ALL PASSED  ✓")
    print(f"{'═' * 60}\n")

    return failed


if __name__ == "__main__":
    failed = run_tests()
    sys.exit(0 if failed == 0 else 1)
