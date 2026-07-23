"""
tests/test_multilingual.py
───────────────────────────
Multilingual song generation test suite.

Verifies every aspect of the language feature end-to-end:
  - models.py constants are correct
  - Project.language defaults and backward compat
  - language survives to_dict / from_dict round-trip
  - prompt templates inject language correctly
  - storage save/load preserves language
  - generate_song() and regenerate_section() accept language param
  - regenerate_section stays in language even when sections are locked

Usage:
    python tests/test_multilingual.py

Exit codes:
    0 — all tests passed
    1 — one or more tests failed
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.models import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE, Project
from utils.ai_engine import (
    _build_prompt,
    _build_section_regen_prompt,
    regenerate_section,
    SongGenerationError,
)
from utils.storage import save_project, load_project, PROJECTS_DIR


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _result(name: str, passed: bool, detail: str = "") -> bool:
    status = "[PASS]" if passed else "[FAIL]"
    print(f"  {status}  {name}" + (f"\n         {detail}" if detail else ""))
    return passed


def _make_song() -> dict:
    return {
        "title": "Test Song",
        "genre": "Indie Folk",
        "style": "Acoustic",
        "mood": "Hopeful",
        "vibe": "test",
        "sections": {
            "verse_1": {"lyrics": "verse 1 lyrics", "locked": False},
            "chorus":  {"lyrics": "chorus lyrics",  "locked": True},
            "verse_2": {"lyrics": "verse 2 lyrics", "locked": False},
            "bridge":  {"lyrics": "bridge lyrics",  "locked": False},
            "outro":   {"lyrics": "outro lyrics",   "locked": False},
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Test functions
# ─────────────────────────────────────────────────────────────────────────────

def test_supported_languages_constant() -> bool:
    expected = ("English", "Hindi", "Marathi", "Telugu", "Tamil", "Spanish", "French", "Japanese")
    ok = SUPPORTED_LANGUAGES == expected
    return _result("SUPPORTED_LANGUAGES has all 8 correct entries", ok,
                   f"Got: {SUPPORTED_LANGUAGES}" if not ok else "")


def test_default_language_is_english() -> bool:
    ok = DEFAULT_LANGUAGE == "English"
    return _result("DEFAULT_LANGUAGE is 'English'", ok,
                   f"Got: {DEFAULT_LANGUAGE!r}" if not ok else "")


def test_project_default_language() -> bool:
    p = Project(name="Test", vibe="test vibe")
    ok = p.language == "English"
    return _result("Project.language defaults to 'English'", ok,
                   f"Got: {p.language!r}" if not ok else "")


def test_project_from_dict_explicit_language() -> bool:
    failures = []
    for lang in SUPPORTED_LANGUAGES:
        data = {"name": "T", "vibe": "v", "created_at": "2024-01-01",
                "status": "Draft", "version": 1, "language": lang}
        p = Project.from_dict(data)
        if p.language != lang:
            failures.append(f"Expected {lang!r}, got {p.language!r}")
    ok = not failures
    return _result("Project.from_dict preserves every supported language", ok,
                   "; ".join(failures) if failures else "")


def test_backward_compat_no_language_field() -> bool:
    data = {"name": "T", "vibe": "v", "created_at": "2024-01-01",
            "status": "Draft", "version": 1}
    p = Project.from_dict(data)
    ok = p.language == "English"
    return _result("Old project without 'language' field defaults to English", ok,
                   f"Got: {p.language!r}" if not ok else "")


def test_unknown_language_defaults_to_english() -> bool:
    data = {"name": "T", "vibe": "v", "created_at": "2024-01-01",
            "status": "Draft", "version": 1, "language": "Klingon"}
    p = Project.from_dict(data)
    ok = p.language == "English"
    return _result("Unsupported language value defaults to English", ok,
                   f"Got: {p.language!r}" if not ok else "")


def test_language_in_to_dict() -> bool:
    failures = []
    for lang in SUPPORTED_LANGUAGES:
        p = Project(name="T", vibe="v")
        p.language = lang
        d = p.to_dict()
        if d.get("language") != lang:
            failures.append(f"{lang}: to_dict gave {d.get('language')!r}")
    ok = not failures
    return _result("Project.to_dict() includes language for every supported language", ok,
                   "; ".join(failures) if failures else "")


def test_language_roundtrip_to_from_dict() -> bool:
    failures = []
    for lang in SUPPORTED_LANGUAGES:
        p = Project(name="T", vibe="v")
        p.language = lang
        p2 = Project.from_dict(p.to_dict())
        if p2.language != lang:
            failures.append(f"{lang}: after round-trip got {p2.language!r}")
    ok = not failures
    return _result("Language survives to_dict → from_dict round-trip for all 8 languages", ok,
                   "; ".join(failures) if failures else "")


def test_storage_roundtrip_language() -> bool:
    failures = []
    for lang in SUPPORTED_LANGUAGES:
        p = Project(name=f"StorageTest-{lang}", vibe="test vibe")
        p.language = lang
        try:
            save_project(p)
            p2 = load_project(p.project_id)
            if p2.language != lang:
                failures.append(f"{lang}: after storage got {p2.language!r}")
        finally:
            (PROJECTS_DIR / f"{p.project_id}.json").unlink(missing_ok=True)
    ok = not failures
    return _result("Language survives save_project → load_project for all 8 languages", ok,
                   "; ".join(failures) if failures else "")


def test_build_prompt_injects_language() -> bool:
    failures = []
    for lang in SUPPORTED_LANGUAGES:
        prompt = _build_prompt(vibe="Test vibe", genre="Indie Folk", language=lang)
        if lang not in prompt:
            failures.append(f"{lang} not found in rendered prompt")
    ok = not failures
    return _result("_build_prompt() injects all 8 languages into the prompt template", ok,
                   "; ".join(failures) if failures else "")


def test_build_section_regen_prompt_injects_language() -> bool:
    song = _make_song()
    failures = []
    for lang in SUPPORTED_LANGUAGES:
        prompt = _build_section_regen_prompt("verse_1", song, language=lang)
        if lang not in prompt:
            failures.append(f"{lang} not found in section regen prompt")
    ok = not failures
    return _result("_build_section_regen_prompt() injects all 8 languages", ok,
                   "; ".join(failures) if failures else "")


def test_build_section_regen_prompt_default_language() -> bool:
    """Default language param should be English."""
    song = _make_song()
    prompt = _build_section_regen_prompt("verse_1", song)
    ok = "English" in prompt
    return _result("_build_section_regen_prompt() defaults to English when no language arg", ok)


def test_generate_song_default_language_param() -> bool:
    """generate_song() signature must accept a language kwarg without error (mock path)."""
    import unittest.mock as mock
    # We only test that the language kwarg is passed into the prompt correctly
    # without making a real API call.
    with mock.patch("utils.gemini_client.call_gemini") as mock_call:
        mock_call.side_effect = Exception("mock stop")
        try:
            from utils.ai_engine import generate_song
            generate_song(vibe="test", genre="Pop", language="French")
        except SongGenerationError:
            # Expected — the mock raised, retried 3x, then SongGenerationError
            pass
        # Check that every call used a prompt containing "French"
        ok = all("French" in str(c.args[0]) for c in mock_call.call_args_list)
        return _result("generate_song() passes language='French' into every prompt attempt", ok,
                       f"Prompt calls: {[str(c.args[0])[:80] for c in mock_call.call_args_list]}" if not ok else "")


def test_regenerate_section_default_language_param() -> bool:
    """regenerate_section() must pass language into every retry attempt (mock path)."""
    import unittest.mock as mock
    song = _make_song()
    with mock.patch("utils.gemini_client.call_gemini") as mock_call:
        mock_call.side_effect = Exception("mock stop")
        try:
            regenerate_section("bridge", song, language="Telugu")
        except SongGenerationError:
            pass
        ok = all("Telugu" in str(c.args[0]) for c in mock_call.call_args_list)
        return _result("regenerate_section() passes language='Telugu' into every prompt attempt", ok,
                       f"Calls: {[str(c.args[0])[:80] for c in mock_call.call_args_list]}" if not ok else "")


def test_regenerate_section_locked_section_untouched() -> bool:
    """After a regen, locked sections must remain untouched."""
    import unittest.mock as mock
    song = _make_song()
    original_chorus = song["sections"]["chorus"]["lyrics"]
    assert song["sections"]["chorus"]["locked"] is True

    good_response = '{"lyrics": "brand new bridge lyrics here"}'
    with mock.patch("utils.gemini_client.call_gemini", return_value=good_response):
        new_lyrics = regenerate_section("bridge", song, language="Hindi")

    # bridge got new lyrics
    ok_bridge = new_lyrics == "brand new bridge lyrics here"
    # chorus (locked) was not changed by regenerate_section (it only returns lyrics)
    ok_chorus = song["sections"]["chorus"]["lyrics"] == original_chorus
    ok = ok_bridge and ok_chorus
    return _result("regenerate_section() returns new lyrics; locked section untouched in song", ok,
                   f"bridge={new_lyrics!r} chorus={song['sections']['chorus']['lyrics']!r}" if not ok else "")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

_TESTS = [
    test_supported_languages_constant,
    test_default_language_is_english,
    test_project_default_language,
    test_project_from_dict_explicit_language,
    test_backward_compat_no_language_field,
    test_unknown_language_defaults_to_english,
    test_language_in_to_dict,
    test_language_roundtrip_to_from_dict,
    test_storage_roundtrip_language,
    test_build_prompt_injects_language,
    test_build_section_regen_prompt_injects_language,
    test_build_section_regen_prompt_default_language,
    test_generate_song_default_language_param,
    test_regenerate_section_default_language_param,
    test_regenerate_section_locked_section_untouched,
]


def run_tests() -> int:
    total  = len(_TESTS)
    passed = 0
    failed = 0

    print()
    print("=" * 60)
    print("  HarmonyLedger - Multilingual Feature Test Suite")
    print(f"  {total} tests")
    print("=" * 60)
    print()

    for fn in _TESTS:
        ok = fn()
        if ok:
            passed += 1
        else:
            failed += 1

    print()
    print("=" * 60)
    if failed:
        print(f"  Results: {passed}/{total} passed  |  {failed} FAILED")
    else:
        print(f"  Results: {passed}/{total} passed  |  ALL PASSED")
    print("=" * 60)
    print()

    return failed


if __name__ == "__main__":
    sys.exit(0 if run_tests() == 0 else 1)
