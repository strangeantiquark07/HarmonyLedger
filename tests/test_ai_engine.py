"""
tests/test_ai_engine.py
───────────────────────
Phase 2 Done-Bar Harness — 10-vibe integration test.

Verifies that generate_song() returns a complete, valid song dict for ten
deliberately different vibes spanning all ten genres in utils/presets.py,
and that each result can round-trip through the project JSON storage layer
without any modification.

Usage:
    python tests/test_ai_engine.py

Exit codes:
    0 — all 10 vibes passed
    1 — one or more vibes failed

This is an integration test: it makes real Gemini API calls. Ensure
GEMINI_API_KEY is set in your .env file before running.
"""

import json
import sys
import copy
from pathlib import Path

# ── Ensure the project root is on the path so utils imports work ─────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.ai_engine import (
    generate_song,
    SongGenerationError,
    _REQUIRED_SECTIONS,
    _REQUIRED_STRING_FIELDS,
    SONG_SCHEMA_VERSION,
)
from utils.models import Project
from utils.storage import save_project, load_project
from utils.timeline import append_event


# ─────────────────────────────────────────────────────────────────────────────
# Test cases — one per genre from utils/presets.py, deliberately varied
# ─────────────────────────────────────────────────────────────────────────────

_TEST_CASES: list[dict] = [
    {
        "genre": "Indie Folk",
        "vibe":  (
            "Acoustic guitar-driven, intimate storytelling. "
            "Warm, melancholic mood with a sense of quiet hope. "
            "Tempo: slow to mid. Instruments: fingerpicked guitar, cello, "
            "brushed drums, sparse piano. Emotional register: vulnerable, honest."
        ),
    },
    {
        "genre": "Dark R&B",
        "vibe":  (
            "Moody, sensual atmosphere. Late-night feel with reverb-heavy vocals. "
            "Minor key, synth pads, 808 bass, sparse snare. "
            "Tempo: slow. Emotional register: longing, introspection."
        ),
    },
    {
        "genre": "Alt-Pop",
        "vibe":  (
            "Explosive chorus energy with a cinematic build. "
            "Layered synths, punchy drums, anthemic hook. "
            "Tempo: mid-fast. Emotional register: empowerment, catharsis."
        ),
    },
    {
        "genre": "Neo-Soul",
        "vibe":  (
            "Rich chord progressions, jazz-influenced harmony. "
            "Warm Rhodes, smooth bass, light percussion. "
            "Tempo: slow to mid. Emotional register: soulful, romantic."
        ),
    },
    {
        "genre": "Chillwave",
        "vibe":  (
            "Hazy, nostalgic texture. Tape-saturated drums, detuned synths, "
            "relaxed groove. Tempo: slow. "
            "Emotional register: dreamy, introspective, comfortable."
        ),
    },
    {
        "genre": "Trap Soul",
        "vibe":  (
            "Minimalist trap beat with soulful vocal melody. "
            "Hi-hat rolls, 808s, pitched harmonies. "
            "Tempo: slow trap. Emotional register: vulnerability, confidence."
        ),
    },
    {
        "genre": "Ethereal Pop",
        "vibe":  (
            "Lush, otherworldly soundscape. Reverb-soaked vocals, shimmering "
            "arpeggios, ambient pads. Tempo: floating. "
            "Emotional register: wonder, escapism."
        ),
    },
    {
        "genre": "Jazz / Noir",
        "vibe":  (
            "Smoky, cinematic, late-night. Muted trumpet, upright bass, brushed "
            "snare, sparse piano comping. "
            "Tempo: mid-slow swing. Emotional register: mysterious, melancholic."
        ),
    },
    {
        "genre": "Cinematic / Orchestral",
        "vibe":  (
            "Sweeping strings, brass swells, deep percussion. "
            "Epic emotional arc with a quiet intimate opening and a soaring climax. "
            "Tempo: slow build to dramatic. Emotional register: heroic, bittersweet."
        ),
    },
    {
        "genre": "Afrobeats",
        "vibe":  (
            "Infectious groove with layered percussion, talking drum, and bass-heavy "
            "production. Bright, celebratory energy. "
            "Tempo: mid-fast. Emotional register: joyful, vibrant, communal."
        ),
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Assertion helpers
# ─────────────────────────────────────────────────────────────────────────────

def _assert_song_schema(song: dict, vibe_num: int) -> list[str]:
    """
    Validate a song dict against the full approved schema.

    Returns a list of failure messages (empty if all checks pass).
    """
    failures: list[str] = []

    # ── Top-level string fields ───────────────────────────────────────────────
    for field in _REQUIRED_STRING_FIELDS:
        if field not in song:
            failures.append(f"Missing field: '{field}'")
        elif not isinstance(song[field], str) or not song[field].strip():
            failures.append(f"Field '{field}' is empty or not a string")

    # ── lyrical_themes ────────────────────────────────────────────────────────
    themes = song.get("lyrical_themes")
    if not isinstance(themes, list) or len(themes) == 0:
        failures.append("'lyrical_themes' must be a non-empty list")
    else:
        for i, t in enumerate(themes):
            if not isinstance(t, str) or not t.strip():
                failures.append(f"'lyrical_themes[{i}]' is not a non-empty string")

    # ── Stamped fields ────────────────────────────────────────────────────────
    if not song.get("generation_timestamp", "").strip():
        failures.append("'generation_timestamp' is missing or empty")
    if not song.get("model_used", "").strip():
        failures.append("'model_used' is missing or empty")
    if song.get("song_schema_version") != SONG_SCHEMA_VERSION:
        failures.append(
            f"'song_schema_version' expected '{SONG_SCHEMA_VERSION}', "
            f"got {song.get('song_schema_version')!r}"
        )

    # ── sections ─────────────────────────────────────────────────────────────
    sections = song.get("sections")
    if not isinstance(sections, dict):
        failures.append("'sections' is missing or not a dict")
        return failures  # can't check individual sections without the dict

    for key in _REQUIRED_SECTIONS:
        if key not in sections:
            failures.append(f"Missing section: '{key}'")
            continue
        sec = sections[key]
        if not isinstance(sec, dict):
            failures.append(f"Section '{key}' is not a dict")
            continue

        lyrics = sec.get("lyrics", "")
        if not isinstance(lyrics, str) or not lyrics.strip():
            failures.append(f"Section '{key}.lyrics' is empty or missing")

        # Provenance envelope
        if sec.get("provenance") != "ai_generated":
            failures.append(
                f"Section '{key}.provenance' expected 'ai_generated', "
                f"got {sec.get('provenance')!r}"
            )
        if sec.get("locked") is not False:
            failures.append(f"Section '{key}.locked' should be False")
        if sec.get("edit_count") != 0:
            failures.append(f"Section '{key}.edit_count' should be 0")

    return failures


def _assert_storage_roundtrip(song: dict, genre: str) -> list[str]:
    """
    Verify the song can be saved into a Project and reloaded without modification.

    Creates a temporary Project, merges the song, saves it, reloads it, and
    compares the song dicts. Returns a list of failure messages.
    """
    failures: list[str] = []

    # Build a minimal project with the song merged in
    project = Project(name="_test_roundtrip", vibe="test vibe")
    project.song = {**song, "genre": genre}
    append_event(project.timeline, "ai_generated", "AI", "Test generation")

    try:
        save_project(project)
    except Exception as exc:
        failures.append(f"save_project() raised: {type(exc).__name__}: {exc}")
        return failures

    try:
        reloaded = load_project(project.project_id)
    except Exception as exc:
        failures.append(f"load_project() raised: {type(exc).__name__}: {exc}")
        return failures
    finally:
        # Clean up the temporary project file
        try:
            from utils.storage import PROJECTS_DIR
            (PROJECTS_DIR / f"{project.project_id}.json").unlink(missing_ok=True)
        except Exception:
            pass

    # Compare song dicts — must be identical after the round-trip
    saved_song   = project.song
    reloaded_song = reloaded.song

    if saved_song != reloaded_song:
        # Find which keys differ for a useful diagnostic
        all_keys = set(saved_song) | set(reloaded_song)
        for k in sorted(all_keys):
            sv = saved_song.get(k)
            rv = reloaded_song.get(k)
            if sv != rv:
                failures.append(f"Round-trip mismatch on key '{k}': saved={sv!r}, reloaded={rv!r}")

    return failures


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_tests() -> int:
    """
    Run all 10 vibe tests. Returns the number of failures.
    """
    total   = len(_TEST_CASES)
    passed  = 0
    failed  = 0

    print(f"\n{'═' * 60}")
    print(f"  HarmonyLedger — Phase 2 Done-Bar Harness")
    print(f"  {total} vibes × full schema + storage round-trip")
    print(f"{'═' * 60}\n")

    for i, case in enumerate(_TEST_CASES, start=1):
        genre = case["genre"]
        vibe  = case["vibe"]

        print(f"[{i:02d}/{total}] Genre: {genre}")
        print(f"       Vibe:  {vibe[:72]}{'…' if len(vibe) > 72 else ''}")

        failures: list[str] = []

        # ── Generation ────────────────────────────────────────────────────────
        try:
            song = generate_song(vibe=vibe, genre=genre)
        except SongGenerationError as exc:
            failures.append(f"generate_song() raised SongGenerationError: {exc}")
            _print_result(i, genre, failures)
            failed += 1
            continue
        except Exception as exc:
            failures.append(f"generate_song() raised unexpected {type(exc).__name__}: {exc}")
            _print_result(i, genre, failures)
            failed += 1
            continue

        # ── Schema validation ─────────────────────────────────────────────────
        schema_failures = _assert_song_schema(song, i)
        failures.extend(schema_failures)

        # ── Storage round-trip ────────────────────────────────────────────────
        if not schema_failures:   # only round-trip if schema is valid
            rt_failures = _assert_storage_roundtrip(song, genre)
            failures.extend(rt_failures)

        _print_result(i, genre, failures, song)

        if failures:
            failed += 1
        else:
            passed += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'═' * 60}")
    print(f"  Results: {passed}/{total} passed", end="")
    if failed:
        print(f"  ·  {failed} FAILED  ✗")
    else:
        print(f"  ·  ALL PASSED  ✓")
    print(f"{'═' * 60}\n")

    return failed


def _print_result(
    num: int,
    genre: str,
    failures: list[str],
    song: dict | None = None,
) -> None:
    if failures:
        print(f"       ✗  FAIL")
        for msg in failures:
            print(f"          → {msg}")
    else:
        title = song.get("title", "?") if song else "?"
        print(f"       ✓  PASS — \"{title}\"")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    failed = run_tests()
    sys.exit(0 if failed == 0 else 1)
