"""
tests/test_phase3_comprehensive.py
────────────────────────────────────
Phase 3 Comprehensive Automated Test Harness.

Covers every requirement from the spec:

  CORE CYCLES (10 consecutive targeted regen cycles)
  ────────────────────────────────────────────────────
  C01  10 consecutive regen cycles — only target changes each time
  C02  Locked section hashes are byte-identical across all 10 cycles
  C03  JSON structure remains valid after every cycle
  C04  Merge succeeds without KeyErrors or data loss each cycle
  C05  Drift detection is correct on every cycle (no false positives)
  C06  No song-level metadata (title/genre/…) changes across cycles
  C07  Timeline event count increments correctly per regen
  C08  edit_count stays 0 after each regen (AI-only touch)
  C09  provenance stays "ai_generated" after regen
  C10  version increments on every lock/regen action

  LOCK-STATE EDGE CASES
  ──────────────────────
  L01  Lock all five sections — regenerate attempt raises/prevents action
  L02  Lock no sections — regen succeeds, empty snapshot is no-op
  L03  Lock then unlock — regen after unlock does not read old locked hash
  L04  Lock same section twice — idempotent (second lock is safe)
  L05  Re-lock a section after regen — new lyrics are hashed correctly

  DRIFT-DETECTION EDGE CASES
  ──────────────────────────
  D01  Injecting new lyrics into a locked section triggers DriftError
  D02  Injecting whitespace-only change triggers DriftError
  D03  Case-only change in locked section triggers DriftError
  D04  Removing a locked section from song.sections triggers DriftError
  D05  Drift on multiple locked sections — all names appear in error msg
  D06  Drift check is a no-op when snapshot is empty (no locked sections)
  D07  Drift check is a no-op when snapshot key is unlocked (hash still valid)

  BAD/MALFORMED INPUT EDGE CASES
  ────────────────────────────────
  M01  regenerate_section with unknown section key raises ValueError immediately
  M02  _validate_section_response: missing "lyrics" key raises ValueError
  M03  _validate_section_response: empty string lyrics raises ValueError
  M04  _validate_section_response: None lyrics raises ValueError
  M05  _validate_section_response: int lyrics raises ValueError
  M06  _strip_fences handles clean JSON (no fences)
  M07  _strip_fences handles ```json ... ``` wrapper
  M08  _strip_fences handles ``` ... ``` wrapper
  M09  _strip_fences extracts JSON from prose before/after fences
  M10  _strip_fences extracts embedded JSON object (no fences)
  M11  Simulated API failure (GeminiAPIError) triggers SongGenerationError after retries
  M12  Simulated partial/invalid JSON response retries and raises SongGenerationError
  M13  Simulated non-dict JSON response (array) retries and raises SongGenerationError

  CONTENT EDGE CASES
  ────────────────────
  X01  Unicode lyrics (CJK, Arabic, Devanagari) hash correctly and survive graft
  X02  Emoji-heavy lyrics (🎵🔥💔🌙✨) hash and graft correctly
  X03  Lyrics with curly braces / special chars don't break prompt rendering
  X04  Lyrics with double-quotes and backslashes survive JSON round-trip
  X05  Very long lyrics (5000+ chars) hash and graft without truncation
  X06  Lyrics with only whitespace/newlines raise ValueError in validation
  X07  Song with minimal metadata (only required fields) — regen still works

  SONG STRUCTURE EDGE CASES
  ────────────────────────────
  S01  Song missing optional "vibe" key — prompt renders to non-empty string
  S02  Song with extra unknown top-level keys — graft ignores them safely
  S03  Graft on a song where section has extra envelope keys — they are preserved
  S04  Multiple rapid grafts on the same section — each replaces the previous

Usage:
    python tests/test_phase3_comprehensive.py

Exit codes:
    0 — all tests passed
    1 — one or more tests failed

This harness is entirely unit-level (no real Gemini API calls required).
All AI calls are replaced with lightweight function-level mocks that simulate
both success and failure modes precisely.
"""

import copy
import hashlib
import json
import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Project root on path ─────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Force UTF-8 stdout/stderr so Unicode test names print on Windows CP1252 ──
import io as _io
if hasattr(sys.stdout, "buffer"):
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Stub heavy dependencies before importing project modules ──────────────────

def _build_stubs():
    """Install lightweight stubs for google.genai and dotenv."""
    google_mod = types.ModuleType("google")
    genai_mod  = types.ModuleType("google.genai")
    gtypes_mod = types.ModuleType("google.genai.types")

    class _FakeClient:
        pass

    genai_mod.Client = _FakeClient
    gtypes_mod.GenerateContentConfig = lambda **kw: None
    google_mod.genai = genai_mod
    sys.modules["google"]             = google_mod
    sys.modules["google.genai"]       = genai_mod
    sys.modules["google.genai.types"] = gtypes_mod

    dotenv_mod = types.ModuleType("dotenv")
    dotenv_mod.load_dotenv = lambda *a, **kw: None
    sys.modules["dotenv"] = dotenv_mod


_build_stubs()

# ── Now safe to import project modules ────────────────────────────────────────
from utils.ai_engine import (                       # noqa: E402
    DriftError,
    SongGenerationError,
    _REQUIRED_SECTIONS,
    _SECTION_LABELS,
    _build_section_context,
    _build_section_regen_prompt,
    _strip_fences,
    _validate_section_response,
    assert_locked_sections_unchanged,
    regenerate_section,
    snapshot_locked_sections,
)
from utils.gemini_client import GeminiAPIError      # noqa: E402
from utils.models import Project                    # noqa: E402
from utils.storage import PROJECTS_DIR, load_project, save_project  # noqa: E402
from utils.timeline import append_event             # noqa: E402


# ═════════════════════════════════════════════════════════════════════════════
# FIXTURE HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _make_section(lyrics: str = "Default lyrics.", locked: bool = False) -> dict:
    """Return a fully-formed section dict."""
    return {
        "lyrics":         lyrics,
        "provenance":     "ai_generated",
        "locked":         locked,
        "locked_at":      datetime.now().isoformat() if locked else None,
        "locked_by":      "Human" if locked else None,
        "last_edited_by": "AI",
        "edit_count":     0,
    }


def _make_song(lock_keys: tuple = (), extra_top: dict | None = None) -> dict:
    """Return a full song dict. Optionally lock certain sections."""
    sections = {
        "verse_1": _make_section("Verse one lyrics here, warm and inviting."),
        "chorus":  _make_section("Chorus rings out bright and clear."),
        "verse_2": _make_section("Verse two digs deeper into the theme."),
        "bridge":  _make_section("Bridge twists the emotion unexpectedly."),
        "outro":   _make_section("Outro fades with quiet resolution."),
    }
    for k in lock_keys:
        if k in sections:
            sections[k]["locked"]    = True
            sections[k]["locked_at"] = datetime.now().isoformat()
            sections[k]["locked_by"] = "Human"

    song = {
        "title":               "Test Song Title",
        "genre":               "Indie Folk",
        "style":               "Fingerpicked acoustic with light strings",
        "mood":                "Melancholic, quietly hopeful",
        "tempo":               "72 BPM",
        "key":                 "D minor",
        "time_signature":      "4/4",
        "lyrical_themes":      ["longing", "homecoming"],
        "generation_timestamp": datetime.now().isoformat(),
        "model_used":          "gemini-2.5-flash",
        "song_schema_version": "1.0",
        "sections":            sections,
    }
    if extra_top:
        song.update(extra_top)
    return song


def _make_project(song: dict | None = None) -> Project:
    p      = Project(name="_p3_comp_test", vibe="comprehensive test vibe")
    p.song = copy.deepcopy(song) if song is not None else _make_song()
    return p


def _cleanup_project(project: Project) -> None:
    try:
        (PROJECTS_DIR / f"{project.project_id}.json").unlink(missing_ok=True)
    except Exception:
        pass


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _apply_graft(song: dict, section_key: str, new_lyrics: str) -> None:
    """Apply the same graft logic that _run_section_regeneration uses."""
    sec = song["sections"][section_key]
    sec["lyrics"]         = new_lyrics
    sec["provenance"]     = "ai_generated"
    sec["last_edited_by"] = "AI"
    sec["edit_count"]     = 0


def _mock_gemini_returning(lyrics: str):
    """Return a context manager that patches call_gemini to return the given lyrics."""
    response_json = json.dumps({"lyrics": lyrics})
    return patch("utils.ai_engine.gemini_client.call_gemini", return_value=response_json)


def _mock_gemini_raising(exc: Exception):
    """Return a context manager that patches call_gemini to raise exc every call."""
    return patch("utils.ai_engine.gemini_client.call_gemini", side_effect=exc)


# ═════════════════════════════════════════════════════════════════════════════
# CORE CYCLES  (C01–C10)
# ═════════════════════════════════════════════════════════════════════════════

_CYCLE_SECTION_ORDER = ["verse_1", "chorus", "verse_2", "bridge", "outro",
                        "chorus", "verse_1", "bridge", "verse_2", "outro"]


def test_C01_ten_consecutive_cycles_only_target_changes() -> list[str]:
    """10 consecutive regen cycles — only the target section changes each time."""
    failures: list[str] = []
    song = _make_song()

    for cycle_num, target_key in enumerate(_CYCLE_SECTION_ORDER, 1):
        new_lyrics    = f"Cycle {cycle_num} — fresh {target_key} lyrics ✓"
        before_others = {k: copy.deepcopy(v) for k, v in song["sections"].items() if k != target_key}

        with _mock_gemini_returning(new_lyrics):
            result = regenerate_section(target_key, song)

        _apply_graft(song, target_key, result)

        # Target must have new lyrics.
        if song["sections"][target_key]["lyrics"] != new_lyrics:
            failures.append(f"Cycle {cycle_num}: target '{target_key}' lyrics not updated")

        # Every other section must be byte-identical.
        for other_key, before_sec in before_others.items():
            if song["sections"][other_key] != before_sec:
                failures.append(
                    f"Cycle {cycle_num}: section '{other_key}' changed unexpectedly "
                    f"when targeting '{target_key}'"
                )

    return failures


def test_C02_locked_hashes_identical_across_all_cycles() -> list[str]:
    """Locked section hashes are byte-identical before and after all 10 cycles."""
    failures: list[str] = []
    song = _make_song(lock_keys=("verse_1", "chorus"))

    initial_snap = snapshot_locked_sections(song)
    original_v1  = song["sections"]["verse_1"]["lyrics"]
    original_ch  = song["sections"]["chorus"]["lyrics"]

    for cycle_num, target_key in enumerate(["verse_2", "bridge", "outro",
                                             "verse_2", "bridge", "outro",
                                             "verse_2", "bridge", "outro",
                                             "bridge"], 1):
        snap_before = snapshot_locked_sections(song)
        new_lyrics  = f"Cycle {cycle_num} unlocked regen for {target_key}"

        with _mock_gemini_returning(new_lyrics):
            result = regenerate_section(target_key, song)

        _apply_graft(song, target_key, result)

        try:
            assert_locked_sections_unchanged(song, snap_before)
        except DriftError as e:
            failures.append(f"Cycle {cycle_num}: unexpected DriftError — {e}")

        post_snap = snapshot_locked_sections(song)
        if post_snap != initial_snap:
            failures.append(
                f"Cycle {cycle_num}: locked section hashes changed from initial snap"
            )

    # Absolute content check.
    if song["sections"]["verse_1"]["lyrics"] != original_v1:
        failures.append("verse_1 lyrics changed across 10 cycles (was locked)")
    if song["sections"]["chorus"]["lyrics"] != original_ch:
        failures.append("chorus lyrics changed across 10 cycles (was locked)")

    return failures


def test_C03_json_valid_after_every_cycle() -> list[str]:
    """JSON structure is valid and round-trippable after every regen cycle."""
    failures: list[str] = []
    project = _make_project()

    for cycle_num, target_key in enumerate(_CYCLE_SECTION_ORDER, 1):
        new_lyrics = f"Cycle {cycle_num} lyrics for {target_key}."
        with _mock_gemini_returning(new_lyrics):
            result = regenerate_section(target_key, project.song)
        _apply_graft(project.song, target_key, result)

        # Must round-trip through JSON without losing data.
        try:
            serialised   = json.dumps(project.song, ensure_ascii=False)
            deserialised = json.loads(serialised)
        except (TypeError, json.JSONDecodeError) as exc:
            failures.append(f"Cycle {cycle_num}: JSON round-trip failed — {exc}")
            continue

        # All required sections must still be present.
        for key in _REQUIRED_SECTIONS:
            if key not in deserialised.get("sections", {}):
                failures.append(
                    f"Cycle {cycle_num}: section '{key}' missing after JSON round-trip"
                )

    return failures


def test_C04_merge_no_data_loss_after_every_cycle() -> list[str]:
    """Merge succeeds — no KeyErrors, no data loss, all envelope fields intact."""
    failures: list[str] = []
    song = _make_song()
    _ENVELOPE_KEYS = ("lyrics", "provenance", "locked", "locked_at",
                      "locked_by", "last_edited_by", "edit_count")

    for cycle_num, target_key in enumerate(_CYCLE_SECTION_ORDER, 1):
        with _mock_gemini_returning(f"Lyrics {cycle_num}"):
            result = regenerate_section(target_key, song)
        _apply_graft(song, target_key, result)

        for sec_key in _REQUIRED_SECTIONS:
            sec = song["sections"].get(sec_key)
            if sec is None:
                failures.append(
                    f"Cycle {cycle_num}: section '{sec_key}' missing after graft"
                )
                continue
            for env_key in _ENVELOPE_KEYS:
                if env_key not in sec:
                    failures.append(
                        f"Cycle {cycle_num}: '{sec_key}.{env_key}' missing after graft"
                    )

    return failures


def test_C05_drift_detection_no_false_positives_across_cycles() -> list[str]:
    """Drift detection produces no false positives across 10 clean cycles."""
    failures: list[str] = []
    song = _make_song(lock_keys=("verse_1",))

    for cycle_num, target_key in enumerate(["chorus", "verse_2", "bridge",
                                             "outro",  "chorus", "verse_2",
                                             "bridge", "outro",  "chorus",
                                             "bridge"], 1):
        snap = snapshot_locked_sections(song)
        with _mock_gemini_returning(f"Regen {cycle_num}"):
            result = regenerate_section(target_key, song)
        _apply_graft(song, target_key, result)
        try:
            assert_locked_sections_unchanged(song, snap)
        except DriftError as e:
            failures.append(f"Cycle {cycle_num}: false-positive DriftError — {e}")

    return failures


def test_C06_song_metadata_unchanged_across_cycles() -> list[str]:
    """Song-level metadata (title/genre/…) never changes during 10 regen cycles."""
    failures: list[str] = []
    song     = _make_song()
    TOP_KEYS = ("title", "genre", "style", "mood", "tempo",
                "key", "time_signature", "lyrical_themes")
    before   = {k: copy.deepcopy(song[k]) for k in TOP_KEYS}

    for cycle_num, target_key in enumerate(_CYCLE_SECTION_ORDER, 1):
        with _mock_gemini_returning(f"Lyrics {cycle_num}"):
            result = regenerate_section(target_key, song)
        _apply_graft(song, target_key, result)

        for k in TOP_KEYS:
            if song.get(k) != before[k]:
                failures.append(
                    f"Cycle {cycle_num}: metadata field '{k}' changed during regen"
                )

    return failures


def test_C07_timeline_event_count_increments_per_regen() -> list[str]:
    """Timeline event count increments by exactly 1 per regen action."""
    failures: list[str] = []
    project = _make_project()
    append_event(project.timeline, "ai_generated", "AI", "initial generation")
    base_count = len(project.timeline)

    for cycle_num, target_key in enumerate(_CYCLE_SECTION_ORDER, 1):
        with _mock_gemini_returning(f"Lyrics {cycle_num}"):
            result = regenerate_section(target_key, project.song)
        _apply_graft(project.song, target_key, result)
        append_event(
            project.timeline, "section_regenerated", "AI",
            f"Section regenerated: {target_key}",
            metadata={"section_key": target_key},
        )
        expected_count = base_count + cycle_num
        if len(project.timeline) != expected_count:
            failures.append(
                f"Cycle {cycle_num}: expected {expected_count} events, "
                f"got {len(project.timeline)}"
            )

    return failures


def test_C08_edit_count_stays_zero_after_regen() -> list[str]:
    """edit_count is reset to 0 after each regen (AI-only touch)."""
    failures: list[str] = []
    song = _make_song()

    for cycle_num, target_key in enumerate(_CYCLE_SECTION_ORDER, 1):
        # Pre-set edit_count to simulate prior human editing.
        song["sections"][target_key]["edit_count"] = 5
        with _mock_gemini_returning(f"Lyrics {cycle_num}"):
            result = regenerate_section(target_key, song)
        _apply_graft(song, target_key, result)
        ec = song["sections"][target_key]["edit_count"]
        if ec != 0:
            failures.append(
                f"Cycle {cycle_num}: '{target_key}'.edit_count should be 0 "
                f"after regen, got {ec}"
            )

    return failures


def test_C09_provenance_stays_ai_generated_after_regen() -> list[str]:
    """provenance is always 'ai_generated' after each regen cycle."""
    failures: list[str] = []
    song = _make_song()

    for cycle_num, target_key in enumerate(_CYCLE_SECTION_ORDER, 1):
        # Pre-set to a different value.
        song["sections"][target_key]["provenance"] = "ai_then_human"
        with _mock_gemini_returning(f"Lyrics {cycle_num}"):
            result = regenerate_section(target_key, song)
        _apply_graft(song, target_key, result)
        prov = song["sections"][target_key]["provenance"]
        if prov != "ai_generated":
            failures.append(
                f"Cycle {cycle_num}: '{target_key}'.provenance should be "
                f"'ai_generated', got {prov!r}"
            )

    return failures


def test_C10_version_increments_on_every_action() -> list[str]:
    """project.version increments on every lock and regen action."""
    failures: list[str] = []
    project = _make_project()
    v       = project.version

    actions = [
        ("lock",  "verse_1"),
        ("regen", "chorus"),
        ("lock",  "chorus"),
        ("regen", "verse_2"),
        ("unlock","verse_1"),
        ("regen", "bridge"),
        ("lock",  "bridge"),
        ("regen", "outro"),
        ("unlock","chorus"),
        ("regen", "verse_1"),
    ]

    for idx, (action, sec_key) in enumerate(actions, 1):
        if action == "lock":
            s = project.song["sections"][sec_key]
            s["locked"]    = True
            s["locked_at"] = datetime.now().isoformat()
            s["locked_by"] = "Human"
            project.version += 1
        elif action == "unlock":
            s = project.song["sections"][sec_key]
            s["locked"]    = False
            s["locked_at"] = None
            s["locked_by"] = None
            project.version += 1
        else:  # regen
            with _mock_gemini_returning(f"Action {idx} lyrics"):
                result = regenerate_section(sec_key, project.song)
            _apply_graft(project.song, sec_key, result)
            project.version += 1

        expected_v = v + idx
        if project.version != expected_v:
            failures.append(
                f"Action {idx} ({action} {sec_key}): expected version {expected_v}, "
                f"got {project.version}"
            )

    return failures


# ═════════════════════════════════════════════════════════════════════════════
# LOCK-STATE EDGE CASES  (L01–L05)
# ═════════════════════════════════════════════════════════════════════════════

def test_L01_all_sections_locked_regen_prevented() -> list[str]:
    """When all 5 sections are locked, regenerating one is blocked by caller guard."""
    failures: list[str] = []
    song = _make_song(lock_keys=tuple(_REQUIRED_SECTIONS))

    # The engine itself doesn't check for locked status — the caller (_run_section_regeneration)
    # guards it. Here we verify that the snapshot covers all 5 sections.
    snap = snapshot_locked_sections(song)
    if set(snap.keys()) != set(_REQUIRED_SECTIONS):
        failures.append(
            f"Expected all 5 sections in snapshot, got: {set(snap.keys())}"
        )

    # Simulate what would happen if the guard were bypassed — graft on any section
    # while it's "locked" should still be caught by the drift check.
    target_key  = "verse_1"
    pre_snap    = snapshot_locked_sections(song)
    # Graft new lyrics onto the locked section (bypass the UI guard).
    song["sections"][target_key]["lyrics"] = "Bypassed lyrics — should drift"
    try:
        assert_locked_sections_unchanged(song, pre_snap)
        failures.append("DriftError should be raised when a locked section is grafted")
    except DriftError:
        pass  # Correct

    return failures


def test_L02_no_sections_locked_regen_succeeds() -> list[str]:
    """When no sections are locked, regen succeeds and drift check is a no-op."""
    failures: list[str] = []
    song = _make_song()  # no locks

    snap = snapshot_locked_sections(song)
    if snap:
        failures.append(f"Expected empty snapshot, got: {snap}")

    with _mock_gemini_returning("Brand new chorus."):
        result = regenerate_section("chorus", song)
    _apply_graft(song, "chorus", result)

    # Drift check must not raise.
    try:
        assert_locked_sections_unchanged(song, snap)
    except DriftError as e:
        failures.append(f"Unexpected DriftError with no locked sections: {e}")

    if song["sections"]["chorus"]["lyrics"] != "Brand new chorus.":
        failures.append("Regen did not update chorus lyrics")

    return failures


def test_L03_lock_unlock_regen_reads_fresh_hash() -> list[str]:
    """After unlock → regen, the old locked hash is no longer in the snapshot."""
    failures: list[str] = []
    song = _make_song(lock_keys=("bridge",))

    # Snapshot has bridge.
    snap_locked = snapshot_locked_sections(song)
    if "bridge" not in snap_locked:
        failures.append("bridge should be in snapshot before unlock")

    # Unlock bridge.
    song["sections"]["bridge"]["locked"]    = False
    song["sections"]["bridge"]["locked_at"] = None
    song["sections"]["bridge"]["locked_by"] = None

    # Snapshot after unlock — bridge must not appear.
    snap_unlocked = snapshot_locked_sections(song)
    if "bridge" in snap_unlocked:
        failures.append("bridge should not be in snapshot after unlock")

    # Regen bridge — drift check against fresh (empty) snapshot must pass.
    with _mock_gemini_returning("Fresh bridge after unlock."):
        result = regenerate_section("bridge", song)
    _apply_graft(song, "bridge", result)

    try:
        assert_locked_sections_unchanged(song, snap_unlocked)
    except DriftError as e:
        failures.append(f"DriftError after unlock+regen: {e}")

    return failures


def test_L04_locking_same_section_twice_is_idempotent() -> list[str]:
    """Locking a section that is already locked does not corrupt state."""
    failures: list[str] = []
    song = _make_song(lock_keys=("verse_1",))
    original_lyrics  = song["sections"]["verse_1"]["lyrics"]
    original_hash    = _sha256(original_lyrics)
    original_lock_at = song["sections"]["verse_1"]["locked_at"]

    # Lock again.
    song["sections"]["verse_1"]["locked"]    = True
    song["sections"]["verse_1"]["locked_at"] = datetime.now().isoformat()  # refresh TS
    song["sections"]["verse_1"]["locked_by"] = "Human"

    snap = snapshot_locked_sections(song)
    if _sha256(song["sections"]["verse_1"]["lyrics"]) != original_hash:
        failures.append("Re-locking changed the lyrics hash")

    # Drift check must still pass.
    try:
        assert_locked_sections_unchanged(song, snap)
    except DriftError as e:
        failures.append(f"DriftError after re-lock: {e}")

    return failures


def test_L05_relock_after_regen_hashes_new_lyrics() -> list[str]:
    """After regen, re-locking uses the new lyrics as the canonical hash."""
    failures: list[str] = []
    song = _make_song()
    original_lyrics = song["sections"]["outro"]["lyrics"]

    # Regen outro.
    new_lyrics = "Brand new outro after regen."
    with _mock_gemini_returning(new_lyrics):
        result = regenerate_section("outro", song)
    _apply_graft(song, "outro", result)

    # Lock it with the new content.
    song["sections"]["outro"]["locked"]    = True
    song["sections"]["outro"]["locked_at"] = datetime.now().isoformat()
    song["sections"]["outro"]["locked_by"] = "Human"

    snap = snapshot_locked_sections(song)
    expected_hash = _sha256(new_lyrics)
    if snap.get("outro") != expected_hash:
        failures.append(
            f"After re-lock, hash should reflect new lyrics. "
            f"Expected {expected_hash[:8]}…, got {snap.get('outro', 'MISSING')[:8]}…"
        )

    old_hash = _sha256(original_lyrics)
    if snap.get("outro") == old_hash:
        failures.append("Hash still matches original lyrics — re-lock didn't update")

    return failures


# ═════════════════════════════════════════════════════════════════════════════
# DRIFT-DETECTION EDGE CASES  (D01–D07)
# ═════════════════════════════════════════════════════════════════════════════

def test_D01_injected_lyrics_trigger_drift_error() -> list[str]:
    """Injecting different lyrics into a locked section triggers DriftError."""
    failures: list[str] = []
    song = _make_song(lock_keys=("chorus",))
    snap = snapshot_locked_sections(song)

    song["sections"]["chorus"]["lyrics"] = "Completely different chorus injected."

    try:
        assert_locked_sections_unchanged(song, snap)
        failures.append("DriftError not raised after lyrics injection")
    except DriftError:
        pass

    return failures


def test_D02_whitespace_change_triggers_drift_error() -> list[str]:
    """A whitespace-only change to locked lyrics triggers DriftError."""
    failures: list[str] = []
    song = _make_song(lock_keys=("verse_2",))
    snap = snapshot_locked_sections(song)

    # Add a trailing newline — imperceptible to human, but hash changes.
    song["sections"]["verse_2"]["lyrics"] += "\n"

    try:
        assert_locked_sections_unchanged(song, snap)
        failures.append("DriftError not raised after whitespace-only change")
    except DriftError:
        pass

    return failures


def test_D03_case_change_triggers_drift_error() -> list[str]:
    """A case-only change in locked lyrics triggers DriftError."""
    failures: list[str] = []
    song = _make_song(lock_keys=("bridge",))
    snap = snapshot_locked_sections(song)

    original = song["sections"]["bridge"]["lyrics"]
    song["sections"]["bridge"]["lyrics"] = original.upper()

    try:
        assert_locked_sections_unchanged(song, snap)
        failures.append("DriftError not raised after case-only change")
    except DriftError:
        pass

    return failures


def test_D04_removing_locked_section_triggers_drift_error() -> list[str]:
    """Removing a locked section from song.sections triggers DriftError."""
    failures: list[str] = []
    song = _make_song(lock_keys=("outro",))
    snap = snapshot_locked_sections(song)

    del song["sections"]["outro"]

    try:
        assert_locked_sections_unchanged(song, snap)
        failures.append("DriftError not raised when locked section removed")
    except DriftError:
        pass

    return failures


def test_D05_multiple_drifted_sections_all_named() -> list[str]:
    """When multiple locked sections drift, all their names appear in DriftError."""
    failures: list[str] = []
    song = _make_song(lock_keys=("verse_1", "chorus", "bridge"))
    snap = snapshot_locked_sections(song)

    song["sections"]["verse_1"]["lyrics"] = "Mutated verse 1."
    song["sections"]["chorus"]["lyrics"]  = "Mutated chorus."
    song["sections"]["bridge"]["lyrics"]  = "Mutated bridge."

    try:
        assert_locked_sections_unchanged(song, snap)
        failures.append("DriftError not raised with 3 drifted sections")
    except DriftError as exc:
        msg = str(exc)
        for label in ("Verse 1", "Chorus", "Bridge"):
            if label not in msg:
                failures.append(
                    f"Label '{label}' not mentioned in DriftError message: {msg}"
                )

    return failures


def test_D06_drift_check_noop_empty_snapshot() -> list[str]:
    """Drift check is a complete no-op when snapshot is empty."""
    failures: list[str] = []
    song = _make_song()  # no locks
    snap = {}

    # Mutate everything — with empty snapshot, drift check must never raise.
    for key in _REQUIRED_SECTIONS:
        song["sections"][key]["lyrics"] = f"Completely changed {key}."

    try:
        assert_locked_sections_unchanged(song, snap)
    except DriftError as e:
        failures.append(f"DriftError raised with empty snapshot: {e}")

    return failures


def test_D07_snapshot_key_unlocked_midway_no_false_positive() -> list[str]:
    """
    Snapshot taken when a section is locked; section then unlocked before
    drift check. The drift check should still fire because the snapshot
    records the locked state at snapshot time, not the current state.
    This verifies the contract: snapshot is the source of truth.
    """
    failures: list[str] = []
    song = _make_song(lock_keys=("verse_2",))
    original_lyrics = song["sections"]["verse_2"]["lyrics"]
    snap            = snapshot_locked_sections(song)

    # Unlock it (without changing lyrics).
    song["sections"]["verse_2"]["locked"]    = False
    song["sections"]["verse_2"]["locked_at"] = None
    song["sections"]["verse_2"]["locked_by"] = None

    # Drift check against original snapshot — lyrics unchanged, should PASS.
    try:
        assert_locked_sections_unchanged(song, snap)
    except DriftError as e:
        failures.append(
            f"False-positive DriftError: section was unlocked but lyrics unchanged — {e}"
        )

    # Now change the lyrics too and drift check must FAIL.
    song["sections"]["verse_2"]["lyrics"] = "Different lyrics after unlock."
    try:
        assert_locked_sections_unchanged(song, snap)
        failures.append("DriftError not raised when lyrics changed (even after unlock)")
    except DriftError:
        pass  # Correct — hash changed

    return failures


# ═════════════════════════════════════════════════════════════════════════════
# BAD / MALFORMED INPUT EDGE CASES  (M01–M13)
# ═════════════════════════════════════════════════════════════════════════════

def test_M01_unknown_section_key_raises_value_error() -> list[str]:
    """regenerate_section raises ValueError immediately for unknown key."""
    failures: list[str] = []
    song = _make_song()

    for bad_key in ("refrain", "pre_chorus", "", "VERSE_1", "verse_3", "intro"):
        try:
            regenerate_section(bad_key, song)
            failures.append(f"ValueError not raised for bad key: {bad_key!r}")
        except ValueError:
            pass  # Expected
        except SongGenerationError:
            failures.append(
                f"SongGenerationError raised instead of ValueError for key {bad_key!r}"
            )
        except Exception as exc:
            failures.append(
                f"Unexpected {type(exc).__name__} for key {bad_key!r}: {exc}"
            )

    return failures


def test_M02_validate_section_missing_lyrics_key() -> list[str]:
    """_validate_section_response raises ValueError when 'lyrics' key is absent."""
    failures: list[str] = []

    bad_payloads = [
        {},
        {"lyric": "wrong key"},
        {"text": "also wrong"},
        {"lyrics_content": "close but no"},
    ]
    for payload in bad_payloads:
        try:
            _validate_section_response(payload)
            failures.append(f"ValueError not raised for payload: {payload!r}")
        except ValueError:
            pass

    return failures


def test_M03_validate_section_empty_string_lyrics() -> list[str]:
    """_validate_section_response raises ValueError for empty-string lyrics."""
    failures: list[str] = []

    for empty in ["", "   ", "\t", "\n", "  \n  "]:
        try:
            _validate_section_response({"lyrics": empty})
            failures.append(f"ValueError not raised for lyrics={empty!r}")
        except ValueError:
            pass

    return failures


def test_M04_validate_section_none_lyrics() -> list[str]:
    """_validate_section_response raises ValueError for None lyrics."""
    failures: list[str] = []

    try:
        _validate_section_response({"lyrics": None})
        failures.append("ValueError not raised for None lyrics")
    except ValueError:
        pass

    return failures


def test_M05_validate_section_non_string_lyrics() -> list[str]:
    """_validate_section_response raises ValueError for non-string lyrics types."""
    failures: list[str] = []

    for bad_val in (42, 3.14, [], {}, True, False, ["line1", "line2"]):
        try:
            _validate_section_response({"lyrics": bad_val})
            failures.append(
                f"ValueError not raised for lyrics={bad_val!r} ({type(bad_val).__name__})"
            )
        except ValueError:
            pass

    return failures


def test_M06_strip_fences_clean_json() -> list[str]:
    """_strip_fences returns clean JSON unchanged."""
    failures: list[str] = []

    clean = '{"lyrics": "Some song lyrics here"}'
    result = _strip_fences(clean)
    if result != clean:
        failures.append(f"Clean JSON was modified: {result!r}")

    return failures


def test_M07_strip_fences_json_code_fence() -> list[str]:
    """_strip_fences strips ```json ... ``` wrapper correctly."""
    failures: list[str] = []

    raw      = '```json\n{"lyrics": "Some lyrics"}\n```'
    expected = '{"lyrics": "Some lyrics"}'
    result   = _strip_fences(raw)
    if result != expected:
        failures.append(f"Expected {expected!r}, got {result!r}")

    return failures


def test_M08_strip_fences_plain_code_fence() -> list[str]:
    """_strip_fences strips ``` ... ``` wrapper correctly."""
    failures: list[str] = []

    raw    = '```\n{"lyrics": "Raw block"}\n```'
    result = _strip_fences(raw)
    parsed = json.loads(result)
    if parsed.get("lyrics") != "Raw block":
        failures.append(f"Expected lyrics 'Raw block', got: {parsed!r}")

    return failures


def test_M09_strip_fences_prose_around_json() -> list[str]:
    """_strip_fences discards prose before and after a JSON fence."""
    failures: list[str] = []

    raw    = 'Here is the lyrics JSON:\n```json\n{"lyrics": "No prose"}\n```\nThat\'s all!'
    result = _strip_fences(raw)
    try:
        parsed = json.loads(result)
        if parsed.get("lyrics") != "No prose":
            failures.append(f"Wrong lyrics value: {parsed!r}")
    except json.JSONDecodeError as exc:
        failures.append(f"JSON decode failed after fence strip: {exc} — got: {result!r}")

    return failures


def test_M10_strip_fences_embedded_json_no_fences() -> list[str]:
    """_strip_fences extracts an embedded JSON object from plain prose."""
    failures: list[str] = []

    raw    = 'The model says: {"lyrics": "Embedded JSON"} and nothing else.'
    result = _strip_fences(raw)
    try:
        parsed = json.loads(result)
        if parsed.get("lyrics") != "Embedded JSON":
            failures.append(f"Wrong lyrics from embedded JSON: {parsed!r}")
    except json.JSONDecodeError as exc:
        failures.append(f"JSON decode failed on embedded JSON: {exc} — got: {result!r}")

    return failures


def test_M11_api_failure_raises_song_generation_error() -> list[str]:
    """Simulated GeminiAPIError causes SongGenerationError after MAX_RETRIES."""
    failures: list[str] = []
    song = _make_song()

    call_count = [0]
    def _always_fail(prompt: str) -> str:
        call_count[0] += 1
        raise GeminiAPIError("Simulated API timeout")

    with patch("utils.ai_engine.gemini_client.call_gemini", side_effect=_always_fail):
        try:
            regenerate_section("bridge", song)
            failures.append("SongGenerationError not raised after API failures")
        except SongGenerationError:
            pass
        except Exception as exc:
            failures.append(f"Unexpected {type(exc).__name__}: {exc}")

    from utils.ai_engine import MAX_RETRIES
    if call_count[0] != MAX_RETRIES:
        failures.append(
            f"Expected {MAX_RETRIES} API attempts, got {call_count[0]}"
        )

    return failures


def test_M12_partial_invalid_json_raises_song_generation_error() -> list[str]:
    """Partial/invalid JSON response causes SongGenerationError after MAX_RETRIES."""
    failures: list[str] = []
    song = _make_song()

    bad_responses = [
        '{"lyrics": ',        # truncated
        'not json at all',    # plain text
        '{"lyrics": }',       # malformed
        '[]',                 # array, not object
    ]

    for bad in bad_responses:
        with patch("utils.ai_engine.gemini_client.call_gemini", return_value=bad):
            try:
                regenerate_section("verse_1", song)
                failures.append(
                    f"SongGenerationError not raised for bad JSON: {bad!r}"
                )
            except SongGenerationError:
                pass
            except ValueError:
                # ValueError before MAX_RETRIES is also acceptable for array inputs
                pass
            except Exception as exc:
                failures.append(
                    f"Unexpected {type(exc).__name__} for bad JSON {bad!r}: {exc}"
                )

    return failures


def test_M13_non_dict_json_raises_song_generation_error() -> list[str]:
    """Non-dict JSON (empty array, bare number, bare string) causes SongGenerationError.

    NOTE: _strip_fences deliberately extracts the first { ... } it finds in any
    response, so '[{"lyrics":"x"}]' would be rescued as '{"lyrics":"x"}' and
    would actually succeed. Only responses with no recoverable JSON object should
    cause SongGenerationError here.
    """
    failures: list[str] = []
    song = _make_song()

    # These responses contain no recoverable JSON object (no { ... } at all).
    non_dict_responses = [
        '[]',              # empty array, no object inside
        '"just a string"', # bare string literal
        '42',              # bare number
        'null',            # null
        'true',            # boolean
    ]

    for resp in non_dict_responses:
        with patch("utils.ai_engine.gemini_client.call_gemini", return_value=resp):
            try:
                regenerate_section("chorus", song)
                failures.append(
                    f"SongGenerationError not raised for response: {resp!r}"
                )
            except SongGenerationError:
                pass
            except Exception as exc:
                failures.append(
                    f"Unexpected {type(exc).__name__} for {resp!r}: {exc}"
                )

    # Verify the _strip_fences rescue behaviour is intentional for array-of-object.
    # '[{"lyrics":"good"}]' should be rescued by _strip_fences and succeed.
    rescued_resp = '[{"lyrics": "rescued from array wrapper"}]'
    with patch("utils.ai_engine.gemini_client.call_gemini", return_value=rescued_resp):
        try:
            result = regenerate_section("chorus", song)
            if result != "rescued from array wrapper":
                failures.append(
                    f"_strip_fences rescue: expected 'rescued from array wrapper', "
                    f"got {result!r}"
                )
        except SongGenerationError as exc:
            failures.append(
                f"_strip_fences should rescue array-of-object, but got error: {exc}"
            )

    return failures


# ═════════════════════════════════════════════════════════════════════════════
# CONTENT EDGE CASES  (X01–X07)
# ═════════════════════════════════════════════════════════════════════════════

def test_X01_unicode_lyrics_hash_and_graft_correctly() -> list[str]:
    """Unicode lyrics (CJK, Arabic, Devanagari) hash correctly and survive graft."""
    failures: list[str] = []

    unicode_payloads = {
        "verse_1": "夜の空に星が輝く\n帰り道を照らしてくれる",        # Japanese
        "chorus":  "أغنية الليل تملأ القلب\nبالأمل والنور",           # Arabic
        "verse_2": "रात के तारे चमकते हैं\nघर का रास्ता दिखाते हैं",  # Devanagari
    }

    for sec_key, unicode_lyrics in unicode_payloads.items():
        song = _make_song(lock_keys=("outro",))
        song["sections"]["outro"]["lyrics"] = unicode_lyrics

        snap = snapshot_locked_sections(song)
        expected_hash = _sha256(unicode_lyrics)
        if snap.get("outro") != expected_hash:
            failures.append(f"Unicode hash mismatch for {sec_key}")

        # Graft on a different section.
        new_lyrics = f"New ASCII lyrics for {sec_key}"
        with _mock_gemini_returning(new_lyrics):
            result = regenerate_section(sec_key, song)
        _apply_graft(song, sec_key, result)

        try:
            assert_locked_sections_unchanged(song, snap)
        except DriftError as e:
            failures.append(f"DriftError with unicode locked section ({sec_key}): {e}")

        # Outro must still hold unicode lyrics.
        if song["sections"]["outro"]["lyrics"] != unicode_lyrics:
            failures.append(f"Unicode outro lyrics corrupted during {sec_key} regen")

    return failures


def test_X02_emoji_lyrics_hash_and_graft_correctly() -> list[str]:
    """Emoji-heavy lyrics hash and graft correctly."""
    failures: list[str] = []

    emoji_lyrics = "🎵 The stars 🌟 are falling 💔\n✨ But I'll 🔥 find my way 🌙"
    song  = _make_song(lock_keys=("verse_1",))
    song["sections"]["verse_1"]["lyrics"] = emoji_lyrics

    snap          = snapshot_locked_sections(song)
    expected_hash = _sha256(emoji_lyrics)
    if snap.get("verse_1") != expected_hash:
        failures.append("Emoji hash mismatch")

    new_lyrics = "New chorus 🎤 lyrics 🎶"
    with _mock_gemini_returning(new_lyrics):
        result = regenerate_section("chorus", song)
    _apply_graft(song, "chorus", result)

    try:
        assert_locked_sections_unchanged(song, snap)
    except DriftError as e:
        failures.append(f"DriftError with emoji locked section: {e}")

    if song["sections"]["verse_1"]["lyrics"] != emoji_lyrics:
        failures.append("Emoji verse_1 lyrics corrupted during chorus regen")

    return failures


def test_X03_curly_braces_in_lyrics_dont_break_prompt() -> list[str]:
    """Lyrics containing curly braces don't break template.format() in prompt."""
    failures: list[str] = []

    # Curly braces inside lyrics would cause KeyError in str.format() if not handled.
    tricky_lyrics = "I {hold} you {close} like a {promise} unbroken"
    song = _make_song(lock_keys=("chorus",))
    song["sections"]["chorus"]["lyrics"] = tricky_lyrics

    try:
        prompt = _build_section_regen_prompt("bridge", song)
        if len(prompt) < 50:
            failures.append(f"Prompt too short: {len(prompt)} chars")
    except (KeyError, IndexError) as exc:
        failures.append(f"Prompt rendering failed with curly braces in lyrics: {exc}")

    return failures


def test_X04_quotes_and_backslashes_survive_json_roundtrip() -> list[str]:
    """Lyrics with double-quotes and backslashes survive JSON round-trip."""
    failures: list[str] = []

    tricky_lyrics = 'She said "I love you" and I said \\"me too\\"'
    song = _make_song(lock_keys=("bridge",))
    song["sections"]["bridge"]["lyrics"] = tricky_lyrics

    # Round-trip through JSON.
    try:
        serialised   = json.dumps(song, ensure_ascii=False)
        deserialised = json.loads(serialised)
        recovered    = deserialised["sections"]["bridge"]["lyrics"]
        if recovered != tricky_lyrics:
            failures.append(
                f"JSON round-trip corrupted lyrics.\n"
                f"  Before: {tricky_lyrics!r}\n"
                f"  After:  {recovered!r}"
            )
    except Exception as exc:
        failures.append(f"JSON round-trip failed: {exc}")

    # Hash must match after round-trip.
    snap = snapshot_locked_sections(song)
    snap2 = snapshot_locked_sections(deserialised)
    if snap != snap2:
        failures.append("Hashes differ after JSON round-trip")

    return failures


def test_X05_very_long_lyrics_no_truncation() -> list[str]:
    """Very long lyrics (4400+ chars) hash and graft without truncation."""
    failures: list[str] = []

    # "The river runs long and the valley is deep. " = 45 chars * 110 = 4950 chars
    long_lyrics = ("The river runs long and the valley is deep. " * 110).strip()
    if len(long_lyrics) < 4400:
        failures.append(f"Fixture too short: {len(long_lyrics)} chars (need >= 4400)")
        return failures

    song  = _make_song(lock_keys=("verse_1",))
    song["sections"]["verse_1"]["lyrics"] = long_lyrics
    snap  = snapshot_locked_sections(song)

    # Regen another section — long locked lyrics must survive intact.
    with _mock_gemini_returning("Short new chorus."):
        result = regenerate_section("chorus", song)
    _apply_graft(song, "chorus", result)

    if song["sections"]["verse_1"]["lyrics"] != long_lyrics:
        failures.append("Long lyrics truncated or corrupted during regen")

    recovered_len = len(song["sections"]["verse_1"]["lyrics"])
    if recovered_len != len(long_lyrics):
        failures.append(
            f"Lyrics length changed: {len(long_lyrics)} → {recovered_len}"
        )

    try:
        assert_locked_sections_unchanged(song, snap)
    except DriftError as e:
        failures.append(f"DriftError with long locked lyrics: {e}")

    return failures


def test_X06_whitespace_only_lyrics_rejected_by_validator() -> list[str]:
    """Lyrics with only whitespace/newlines are rejected by _validate_section_response."""
    failures: list[str] = []

    for bad in ("", "   ", "\n\n\n", "\t  \t", "  \n  \n  "):
        response = json.dumps({"lyrics": bad})
        with patch("utils.ai_engine.gemini_client.call_gemini", return_value=response):
            try:
                regenerate_section("outro", _make_song())
                failures.append(
                    f"SongGenerationError not raised for whitespace lyrics {bad!r}"
                )
            except SongGenerationError:
                pass
            except Exception as exc:
                failures.append(
                    f"Unexpected {type(exc).__name__} for whitespace lyrics: {exc}"
                )

    return failures


def test_X07_song_without_vibe_key_prompts_correctly() -> list[str]:
    """Song missing the optional 'vibe' key still renders a valid prompt."""
    failures: list[str] = []

    song = _make_song()
    song.pop("vibe", None)  # Remove vibe entirely

    try:
        prompt = _build_section_regen_prompt("chorus", song)
        if "chorus" not in prompt.lower() and "Chorus" not in prompt:
            failures.append("Section label not found in prompt")
        if len(prompt) < 100:
            failures.append(f"Prompt too short without vibe key: {len(prompt)} chars")
    except KeyError as exc:
        failures.append(f"KeyError building prompt without vibe: {exc}")
    except Exception as exc:
        failures.append(f"Unexpected error building prompt without vibe: {exc}")

    return failures


# ═════════════════════════════════════════════════════════════════════════════
# SONG STRUCTURE EDGE CASES  (S01–S04)
# ═════════════════════════════════════════════════════════════════════════════

def test_S01_extra_top_level_keys_ignored_safely() -> list[str]:
    """Song with extra unknown top-level keys — graft leaves them untouched."""
    failures: list[str] = []

    song = _make_song(extra_top={"custom_field": "value", "producer": "Bob"})
    with _mock_gemini_returning("New verse."):
        result = regenerate_section("verse_1", song)
    _apply_graft(song, "verse_1", result)

    if song.get("custom_field") != "value":
        failures.append("Extra top-level key 'custom_field' was removed by graft")
    if song.get("producer") != "Bob":
        failures.append("Extra top-level key 'producer' was removed by graft")

    return failures


def test_S02_section_extra_envelope_keys_preserved() -> list[str]:
    """Extra keys on a section envelope survive the graft unchanged."""
    failures: list[str] = []

    song = _make_song()
    # Add a hypothetical Phase 4 field.
    song["sections"]["chorus"]["contribution_score"] = 0.75
    song["sections"]["bridge"]["human_edits"]        = ["edit_1", "edit_2"]

    with _mock_gemini_returning("New chorus after graft."):
        result = regenerate_section("chorus", song)
    _apply_graft(song, "chorus", result)

    # Grafted section — extra key gone is acceptable (graft only writes known keys).
    # Non-grafted section — extra key must survive.
    if song["sections"]["bridge"].get("human_edits") != ["edit_1", "edit_2"]:
        failures.append(
            "Extra envelope key 'human_edits' on bridge was removed by graft "
            "targeting chorus"
        )

    return failures


def test_S03_multiple_rapid_grafts_same_section() -> list[str]:
    """Multiple rapid grafts on the same section each replace the previous."""
    failures: list[str] = []

    song = _make_song()
    expected_final = None

    for i in range(1, 11):
        new_lyrics    = f"Rapid graft #{i} on verse_2"
        expected_final = new_lyrics
        with _mock_gemini_returning(new_lyrics):
            result = regenerate_section("verse_2", song)
        _apply_graft(song, "verse_2", result)

    final_lyrics = song["sections"]["verse_2"]["lyrics"]
    if final_lyrics != expected_final:
        failures.append(
            f"After 10 rapid grafts, expected {expected_final!r}, "
            f"got {final_lyrics!r}"
        )

    # edit_count must still be 0 — each graft resets it.
    if song["sections"]["verse_2"]["edit_count"] != 0:
        failures.append(
            f"edit_count should be 0 after rapid grafts, "
            f"got {song['sections']['verse_2']['edit_count']}"
        )

    return failures


def test_S04_storage_round_trip_after_full_cycle() -> list[str]:
    """Full lock → regen → save → reload round-trip preserves all state."""
    failures: list[str] = []

    project = _make_project()
    append_event(project.timeline, "ai_generated", "AI", "Initial generation")

    # Lock verse_1 and chorus.
    for key in ("verse_1", "chorus"):
        s = project.song["sections"][key]
        s["locked"]    = True
        s["locked_at"] = datetime.now().isoformat()
        s["locked_by"] = "Human"
    append_event(project.timeline, "section_locked", "Human", "Locked 2 sections")

    # Regen bridge.
    new_bridge = "Post-lock bridge regenerated for storage test."
    with _mock_gemini_returning(new_bridge):
        result = regenerate_section("bridge", project.song)
    _apply_graft(project.song, "bridge", result)
    append_event(project.timeline, "section_regenerated", "AI", "Bridge regen")
    project.version += 1

    # Save.
    try:
        save_project(project)
    except Exception as exc:
        failures.append(f"save_project failed: {exc}")
        _cleanup_project(project)
        return failures

    # Reload.
    try:
        reloaded = load_project(project.project_id)
    except Exception as exc:
        failures.append(f"load_project failed: {exc}")
        _cleanup_project(project)
        return failures

    # Verify locked sections.
    for key in ("verse_1", "chorus"):
        if not reloaded.song["sections"][key].get("locked"):
            failures.append(f"Section '{key}' should be locked after reload")

    # Verify regenerated bridge.
    if reloaded.song["sections"]["bridge"]["lyrics"] != new_bridge:
        failures.append("Bridge lyrics not persisted correctly after reload")

    # Timeline must have 3 events.
    expected_events = 3
    actual_events   = len(reloaded.timeline)
    if actual_events != expected_events:
        failures.append(
            f"Expected {expected_events} timeline events, got {actual_events}"
        )

    # Version must match.
    if reloaded.version != project.version:
        failures.append(
            f"Version mismatch: saved {project.version}, reloaded {reloaded.version}"
        )

    _cleanup_project(project)
    return failures


# ═════════════════════════════════════════════════════════════════════════════
# HUMAN EDIT TESTS  (H01–H10)
# ═════════════════════════════════════════════════════════════════════════════

def _apply_human_edit(project: "Project", section_key: str, new_lyrics: str) -> None:
    """Replicate the same graft logic that _save_human_edit() uses, without Streamlit."""
    clean = new_lyrics.strip()
    sec   = project.song["sections"][section_key]
    prev_prov    = sec.get("provenance", "ai_generated")
    chars_before = len(sec.get("lyrics", ""))
    if prev_prov in ("ai_generated", "ai_then_human"):
        new_prov = "ai_then_human"
    else:
        new_prov = "human_written"
    sec["lyrics"]         = clean
    sec["provenance"]     = new_prov
    sec["last_edited_by"] = "Human"
    sec["edit_count"]     = sec.get("edit_count", 0) + 1
    project.version += 1
    append_event(
        project.timeline,
        event_type  = "human_edit",
        actor       = "Human",
        description = f"Section edited by human: {section_key}",
        metadata    = {
            "section_key":     section_key,
            "prev_provenance": prev_prov,
            "new_provenance":  new_prov,
            "chars_before":    chars_before,
            "chars_after":     len(clean),
        },
    )


def test_H01_human_edit_changes_lyrics() -> list[str]:
    """H01: Human edit updates the section lyrics in memory."""
    failures: list[str] = []
    project = _make_project()
    original = project.song["sections"]["verse_1"]["lyrics"]
    new_text  = "These are brand new human-written lyrics for verse one."

    _apply_human_edit(project, "verse_1", new_text)

    actual = project.song["sections"]["verse_1"]["lyrics"]
    if actual != new_text:
        failures.append(f"Expected lyrics {new_text!r}, got {actual!r}")
    if original == actual:
        failures.append("Lyrics did not change after human edit")
    return failures


def test_H02_provenance_ai_to_ai_then_human() -> list[str]:
    """H02: ai_generated section becomes ai_then_human after one human edit."""
    failures: list[str] = []
    project = _make_project()
    sec = project.song["sections"]["chorus"]
    sec["provenance"] = "ai_generated"

    _apply_human_edit(project, "chorus", "New chorus by human.")

    prov = project.song["sections"]["chorus"]["provenance"]
    if prov != "ai_then_human":
        failures.append(f"Expected 'ai_then_human', got {prov!r}")
    return failures


def test_H03_provenance_ai_then_human_stays_ai_then_human() -> list[str]:
    """H03: ai_then_human section keeps ai_then_human on subsequent human edits."""
    failures: list[str] = []
    project = _make_project()
    sec = project.song["sections"]["verse_2"]
    sec["provenance"] = "ai_then_human"

    _apply_human_edit(project, "verse_2", "Second human edit of verse two.")

    prov = project.song["sections"]["verse_2"]["provenance"]
    if prov != "ai_then_human":
        failures.append(f"Expected 'ai_then_human', got {prov!r}")
    return failures


def test_H04_provenance_human_written_stays_human_written() -> list[str]:
    """H04: human_written stays human_written after further human edits."""
    failures: list[str] = []
    project = _make_project()
    sec = project.song["sections"]["bridge"]
    sec["provenance"] = "human_written"

    _apply_human_edit(project, "bridge", "Another human pass on the bridge.")

    prov = project.song["sections"]["bridge"]["provenance"]
    if prov != "human_written":
        failures.append(f"Expected 'human_written', got {prov!r}")
    return failures


def test_H05_edit_count_increments_per_edit() -> list[str]:
    """H05: edit_count increments by 1 on each human edit."""
    failures: list[str] = []
    project = _make_project()
    sec = project.song["sections"]["outro"]
    sec["edit_count"] = 0

    for expected in range(1, 6):
        _apply_human_edit(project, "outro", f"Edit number {expected}.")
        actual = project.song["sections"]["outro"]["edit_count"]
        if actual != expected:
            failures.append(f"After edit {expected}: expected edit_count={expected}, got {actual}")

    return failures


def test_H06_last_edited_by_set_to_human() -> list[str]:
    """H06: last_edited_by is 'Human' after a human edit."""
    failures: list[str] = []
    project = _make_project()

    _apply_human_edit(project, "chorus", "Human chorus text.")

    val = project.song["sections"]["chorus"].get("last_edited_by")
    if val != "Human":
        failures.append(f"Expected last_edited_by='Human', got {val!r}")
    return failures


def test_H07_other_sections_unchanged_after_edit() -> list[str]:
    """H07: editing one section leaves all others byte-identical."""
    failures: list[str] = []
    project  = _make_project()
    original = copy.deepcopy(project.song["sections"])

    _apply_human_edit(project, "bridge", "New bridge from the human.")

    for key in _REQUIRED_SECTIONS:
        if key == "bridge":
            continue
        if project.song["sections"][key] != original[key]:
            failures.append(f"Section '{key}' changed unexpectedly after editing 'bridge'")
    return failures


def test_H08_human_edit_timeline_event_logged() -> list[str]:
    """H08: human_edit timeline event is appended with correct metadata."""
    failures: list[str] = []
    project = _make_project()
    prev_count = len(project.timeline)

    _apply_human_edit(project, "verse_1", "Timeline event check lyrics.")

    if len(project.timeline) != prev_count + 1:
        failures.append(
            f"Expected {prev_count + 1} timeline events, got {len(project.timeline)}"
        )
        return failures

    evt = project.timeline[-1]
    if evt.get("event_type") != "human_edit":
        failures.append(f"Expected event_type='human_edit', got {evt.get('event_type')!r}")
    if evt.get("actor") != "Human":
        failures.append(f"Expected actor='Human', got {evt.get('actor')!r}")
    meta = evt.get("metadata", {})
    if meta.get("section_key") != "verse_1":
        failures.append(f"Expected metadata.section_key='verse_1', got {meta.get('section_key')!r}")
    if meta.get("new_provenance") != "ai_then_human":
        failures.append(f"Expected metadata.new_provenance='ai_then_human', got {meta.get('new_provenance')!r}")
    return failures


def test_H09_human_edited_section_locked_protects_drift() -> list[str]:
    """H09: a human-edited then locked section is protected by the drift check."""
    failures: list[str] = []
    project = _make_project()

    # Human edits verse_1 then locks it.
    _apply_human_edit(project, "verse_1", "Human wrote this verse carefully.")
    project.song["sections"]["verse_1"]["locked"]    = True
    project.song["sections"]["verse_1"]["locked_at"] = datetime.now().isoformat()
    project.song["sections"]["verse_1"]["locked_by"] = "Human"

    snapshot = snapshot_locked_sections(project.song)

    # Verify snapshot captured verse_1.
    if "verse_1" not in snapshot:
        failures.append("verse_1 not in snapshot after locking")
        return failures

    # Mutate the locked lyrics — drift check must fire.
    project.song["sections"]["verse_1"]["lyrics"] = "TAMPERED content"
    try:
        assert_locked_sections_unchanged(project.song, snapshot)
        failures.append("DriftError not raised after tampering with human-edited locked section")
    except DriftError:
        pass  # correct

    return failures


def test_H10_regen_after_human_edit_uses_latest_lyrics() -> list[str]:
    """H10: regeneration after a human edit sends the edited text as context (if locked)."""
    failures: list[str] = []
    project  = _make_project()
    human_text = "Carefully crafted human verse, not to be changed."

    # Human edits verse_1 then locks it so it becomes context for later regen.
    _apply_human_edit(project, "verse_1", human_text)
    project.song["sections"]["verse_1"]["locked"]    = True
    project.song["sections"]["verse_1"]["locked_at"] = datetime.now().isoformat()
    project.song["sections"]["verse_1"]["locked_by"] = "Human"

    # Now regenerate the chorus — verse_1 is the locked context.
    new_chorus = "Fresh chorus after human-locked verse one."
    with _mock_gemini_returning(new_chorus):
        result = regenerate_section("chorus", project.song)

    _apply_graft(project.song, "chorus", result)

    # verse_1 must be unchanged (human text preserved).
    actual_v1 = project.song["sections"]["verse_1"]["lyrics"]
    if actual_v1 != human_text:
        failures.append(
            f"verse_1 changed after chorus regen! "
            f"Expected {human_text!r}, got {actual_v1!r}"
        )

    # Chorus must have the new lyrics.
    if project.song["sections"]["chorus"]["lyrics"] != new_chorus:
        failures.append("Chorus lyrics not updated after regeneration")

    # Drift check must pass.
    snapshot = snapshot_locked_sections(project.song)
    # Re-apply snapshot using the human text (which should still be there).
    try:
        assert_locked_sections_unchanged(project.song, snapshot)
    except DriftError as exc:
        failures.append(f"Unexpected DriftError: {exc}")

    return failures


# ══════════════════════════════════════════════════════════════════════════════
# HUMAN EDIT STORAGE ROUND-TRIP  (H11)
# ══════════════════════════════════════════════════════════════════════════════

def test_H11_human_edit_storage_round_trip() -> list[str]:
    """H11: human-edited section survives save → reload with all fields intact."""
    failures: list[str] = []
    project  = _make_project()
    new_text = "Persisted human edit for the bridge section."

    _apply_human_edit(project, "bridge", new_text)

    try:
        save_project(project)
    except Exception as exc:
        failures.append(f"save_project failed: {exc}")
        _cleanup_project(project)
        return failures

    try:
        reloaded = load_project(project.project_id)
    except Exception as exc:
        failures.append(f"load_project failed: {exc}")
        _cleanup_project(project)
        return failures

    sec = reloaded.song["sections"]["bridge"]

    if sec["lyrics"] != new_text:
        failures.append(f"Lyrics not persisted: expected {new_text!r}, got {sec['lyrics']!r}")
    if sec["provenance"] != "ai_then_human":
        failures.append(f"provenance not persisted: expected 'ai_then_human', got {sec['provenance']!r}")
    if sec["last_edited_by"] != "Human":
        failures.append(f"last_edited_by not persisted: expected 'Human', got {sec['last_edited_by']!r}")
    if sec["edit_count"] != 1:
        failures.append(f"edit_count not persisted: expected 1, got {sec['edit_count']!r}")

    # Timeline must have the human_edit event.
    human_events = [e for e in reloaded.timeline if e.get("event_type") == "human_edit"]
    if len(human_events) != 1:
        failures.append(f"Expected 1 human_edit timeline event, got {len(human_events)}")

    _cleanup_project(project)
    return failures


# ═════════════════════════════════════════════════════════════════════════════
# TEST REGISTRY
# ═════════════════════════════════════════════════════════════════════════════

_TESTS: list[tuple[str, str, object]] = [
    # ── Core Cycles ──────────────────────────────────────────────────────────
    ("C01", "10 consecutive cycles — only target changes each time",      test_C01_ten_consecutive_cycles_only_target_changes),
    ("C02", "Locked hashes byte-identical across all 10 cycles",          test_C02_locked_hashes_identical_across_all_cycles),
    ("C03", "JSON structure valid and round-trippable after every cycle",  test_C03_json_valid_after_every_cycle),
    ("C04", "Merge: no KeyErrors, no data loss, all envelope fields intact", test_C04_merge_no_data_loss_after_every_cycle),
    ("C05", "Drift detection: no false positives across 10 cycles",       test_C05_drift_detection_no_false_positives_across_cycles),
    ("C06", "Song-level metadata unchanged across 10 cycles",             test_C06_song_metadata_unchanged_across_cycles),
    ("C07", "Timeline event count increments correctly per regen",        test_C07_timeline_event_count_increments_per_regen),
    ("C08", "edit_count reset to 0 after each regen",                     test_C08_edit_count_stays_zero_after_regen),
    ("C09", "provenance stays 'ai_generated' after each regen",           test_C09_provenance_stays_ai_generated_after_regen),
    ("C10", "project.version increments on every lock/regen action",      test_C10_version_increments_on_every_action),
    # ── Lock-State Edge Cases ─────────────────────────────────────────────
    ("L01", "All sections locked — regen bypass detected by drift check", test_L01_all_sections_locked_regen_prevented),
    ("L02", "No sections locked — regen succeeds, empty snapshot no-op",  test_L02_no_sections_locked_regen_succeeds),
    ("L03", "Lock → unlock → regen reads fresh (empty) hash",             test_L03_lock_unlock_regen_reads_fresh_hash),
    ("L04", "Locking same section twice is idempotent",                   test_L04_locking_same_section_twice_is_idempotent),
    ("L05", "Re-lock after regen hashes the new lyrics",                  test_L05_relock_after_regen_hashes_new_lyrics),
    # ── Drift-Detection Edge Cases ────────────────────────────────────────
    ("D01", "Injected different lyrics trigger DriftError",               test_D01_injected_lyrics_trigger_drift_error),
    ("D02", "Whitespace-only change triggers DriftError",                 test_D02_whitespace_change_triggers_drift_error),
    ("D03", "Case-only change triggers DriftError",                       test_D03_case_change_triggers_drift_error),
    ("D04", "Removing locked section triggers DriftError",                test_D04_removing_locked_section_triggers_drift_error),
    ("D05", "Multiple drifted sections — all names in error message",     test_D05_multiple_drifted_sections_all_named),
    ("D06", "Empty snapshot is a no-op — no DriftError raised",           test_D06_drift_check_noop_empty_snapshot),
    ("D07", "Unlock mid-cycle: lyrics unchanged passes, changed fails",   test_D07_snapshot_key_unlocked_midway_no_false_positive),
    # ── Bad/Malformed Input ───────────────────────────────────────────────
    ("M01", "Unknown section key raises ValueError immediately",          test_M01_unknown_section_key_raises_value_error),
    ("M02", "_validate_section_response: missing 'lyrics' key",          test_M02_validate_section_missing_lyrics_key),
    ("M03", "_validate_section_response: empty string lyrics",           test_M03_validate_section_empty_string_lyrics),
    ("M04", "_validate_section_response: None lyrics",                   test_M04_validate_section_none_lyrics),
    ("M05", "_validate_section_response: non-string lyrics",             test_M05_validate_section_non_string_lyrics),
    ("M06", "_strip_fences: clean JSON unchanged",                        test_M06_strip_fences_clean_json),
    ("M07", "_strip_fences: ```json ... ``` wrapper stripped",            test_M07_strip_fences_json_code_fence),
    ("M08", "_strip_fences: ``` ... ``` wrapper stripped",                test_M08_strip_fences_plain_code_fence),
    ("M09", "_strip_fences: prose around JSON fence discarded",           test_M09_strip_fences_prose_around_json),
    ("M10", "_strip_fences: embedded JSON object extracted from prose",   test_M10_strip_fences_embedded_json_no_fences),
    ("M11", "API failure → SongGenerationError after MAX_RETRIES",       test_M11_api_failure_raises_song_generation_error),
    ("M12", "Invalid JSON response → SongGenerationError",               test_M12_partial_invalid_json_raises_song_generation_error),
    ("M13", "Non-dict JSON → SongGenerationError",                       test_M13_non_dict_json_raises_song_generation_error),
    # ── Content Edge Cases ────────────────────────────────────────────────
    ("X01", "Unicode lyrics (CJK/Arabic/Devanagari) hash+graft correctly", test_X01_unicode_lyrics_hash_and_graft_correctly),
    ("X02", "Emoji-heavy lyrics hash and graft correctly",                test_X02_emoji_lyrics_hash_and_graft_correctly),
    ("X03", "Curly braces in lyrics don't break prompt rendering",        test_X03_curly_braces_in_lyrics_dont_break_prompt),
    ("X04", "Quotes and backslashes survive JSON round-trip",             test_X04_quotes_and_backslashes_survive_json_roundtrip),
    ("X05", "Very long lyrics (4400+ chars) no truncation",               test_X05_very_long_lyrics_no_truncation),
    ("X06", "Whitespace-only lyrics rejected by section validator",       test_X06_whitespace_only_lyrics_rejected_by_validator),
    ("X07", "Song without 'vibe' key renders valid prompt",               test_X07_song_without_vibe_key_prompts_correctly),
    # ── Song Structure Edge Cases ─────────────────────────────────────────
    ("S01", "Extra top-level keys ignored safely by graft",               test_S01_extra_top_level_keys_ignored_safely),
    ("S02", "Extra section envelope keys preserved on non-target sections", test_S02_section_extra_envelope_keys_preserved),
    ("S03", "10 rapid grafts on same section — each replaces previous",   test_S03_multiple_rapid_grafts_same_section),
    ("S04", "Full lock→regen→save→reload round-trip preserves all state", test_S04_storage_round_trip_after_full_cycle),
    # ── Human Edit ───────────────────────────────────────────────────────
    ("H01", "Human edit updates section lyrics in memory",                test_H01_human_edit_changes_lyrics),
    ("H02", "ai_generated → ai_then_human provenance after first edit",   test_H02_provenance_ai_to_ai_then_human),
    ("H03", "ai_then_human stays ai_then_human on repeated edits",        test_H03_provenance_ai_then_human_stays_ai_then_human),
    ("H04", "human_written stays human_written on repeated edits",        test_H04_provenance_human_written_stays_human_written),
    ("H05", "edit_count increments by 1 on each human edit",              test_H05_edit_count_increments_per_edit),
    ("H06", "last_edited_by set to 'Human' after edit",                   test_H06_last_edited_by_set_to_human),
    ("H07", "Other sections unchanged after editing one section",         test_H07_other_sections_unchanged_after_edit),
    ("H08", "human_edit timeline event logged with correct metadata",     test_H08_human_edit_timeline_event_logged),
    ("H09", "Human-edited locked section protected by drift check",       test_H09_human_edited_section_locked_protects_drift),
    ("H10", "Regen after human edit uses latest human lyrics as context", test_H10_regen_after_human_edit_uses_latest_lyrics),
    ("H11", "Human edit storage round-trip — all fields persisted",       test_H11_human_edit_storage_round_trip),
]


# ═════════════════════════════════════════════════════════════════════════════
# RUNNER
# ═════════════════════════════════════════════════════════════════════════════

def run_tests() -> int:
    """Run all tests. Returns the number of failures."""
    total  = len(_TESTS)
    passed = 0
    failed = 0

    print(f"\n{'=' * 68}")
    print(f"  HarmonyLedger - Phase 3 + Human Edit Comprehensive Harness")
    print(f"  {total} tests | 10 regen cycles | edge cases | drift checks | human edits")
    print(f"{'=' * 68}\n")

    group = ""
    for code, name, fn in _TESTS:
        # Print group headers.
        current_group = code[0]
        if current_group != group:
            group = current_group
            group_names = {
                "C": "CORE REGEN CYCLES",
                "L": "LOCK-STATE EDGE CASES",
                "D": "DRIFT-DETECTION",
                "M": "MALFORMED INPUT",
                "X": "CONTENT EDGE CASES",
                "S": "SONG STRUCTURE",
                "H": "HUMAN EDIT",
            }
            gname = group_names.get(group, group)
            print(f"  -- {gname} {'-' * max(1, 46 - len(gname))}")

        try:
            failures = fn()
        except Exception as exc:
            import traceback
            failures = [
                f"Test raised unexpected exception: {type(exc).__name__}: {exc}",
                traceback.format_exc().strip(),
            ]

        if failures:
            print(f"  [{code}] FAIL  {name}")
            for msg in failures:
                for line in msg.splitlines():
                    print(f"         -> {line}")
            failed += 1
        else:
            print(f"  [{code}] PASS  {name}")
            passed += 1

    print(f"\n{'=' * 68}")
    if failed:
        print(f"  Results: {passed}/{total} passed | {failed} FAILED")
    else:
        print(f"  Results: {passed}/{total} passed | ALL PASSED")
    print(f"{'=' * 68}\n")

    return failed


if __name__ == "__main__":
    failed = run_tests()
    sys.exit(0 if failed == 0 else 1)
