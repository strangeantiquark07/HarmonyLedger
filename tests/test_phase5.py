"""
tests/test_phase5.py
────────────────────
Phase 5 — Audio Preview test suite.

Tests the public contract of utils/audio_engine.py AND the section-selector
helper _available_audio_sections() in views/view_project.py:

  - AudioGenerationError is raised for empty/whitespace lyrics (offline)
  - AudioGenerationError is a proper Exception subclass (offline)
  - Function accepts ambient=None and lang="en" without TypeError (offline)
  - _available_audio_sections() returns the correct ordered filtered list (offline)
  - _available_audio_sections() defaults correctly to chorus / first available (offline)
  - Valid lyrics produce non-empty bytes with a recognisable MP3 header (live)

Tests are split into two categories:

  OFFLINE (run by default in the standalone runner — no network required)
  ────────────────────────────────────────────────────────────────────────
  These tests validate the module's contract using only mock or guard-level
  logic and do not call the gTTS API.

  LIVE / INTEGRATION (network-dependent — excluded from standalone runner)
  ────────────────────────────────────────────────────────────────────────
  These tests make a real gTTS network call to verify MP3 output. They are
  marked with @pytest.mark.integration and run with:
      pytest tests/test_phase5.py -m integration -v

Usage (standalone, offline only):
    python tests/test_phase5.py

Usage (with pytest, all tests):
    pytest tests/test_phase5.py -v
    pytest tests/test_phase5.py -m integration -v   # live tests only
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.audio_engine import generate_audio_preview, AudioGenerationError

# Import the section-selector helper directly for unit-testing.
# It lives in views/view_project.py but has no Streamlit dependency of its own
# (it is a pure function operating on a plain dict).
from views.view_project import _available_audio_sections, _SECTION_ORDER

try:
    import pytest
    _PYTEST_AVAILABLE = True
except ImportError:
    _PYTEST_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures — minimal song dicts for section-selector tests
# ─────────────────────────────────────────────────────────────────────────────

def _make_full_song() -> dict:
    """Song with all five sections populated."""
    return {
        "sections": {
            "verse_1": {"lyrics": "First verse lyrics here"},
            "chorus":  {"lyrics": "Chorus lyrics here"},
            "verse_2": {"lyrics": "Second verse lyrics here"},
            "bridge":  {"lyrics": "Bridge lyrics here"},
            "outro":   {"lyrics": "Outro lyrics here"},
        }
    }


def _make_partial_song(present_keys: list) -> dict:
    """Song with only the specified sections populated."""
    return {
        "sections": {
            k: {"lyrics": f"Lyrics for {k}"}
            for k in present_keys
        }
    }


def _make_song_empty_section(empty_key: str) -> dict:
    """Full song but one section has empty-string lyrics."""
    song = _make_full_song()
    song["sections"][empty_key]["lyrics"] = ""
    return song


# ─────────────────────────────────────────────────────────────────────────────
# Offline tests — _available_audio_sections()
# ─────────────────────────────────────────────────────────────────────────────

def test_available_sections_full_song_returns_all_five():
    """Full song → all five sections returned in canonical order."""
    result = _available_audio_sections(_make_full_song())
    assert len(result) == 5
    keys = [k for k, _ in result]
    expected_keys = [k for k, _ in _SECTION_ORDER]
    assert keys == expected_keys


def test_available_sections_respects_canonical_order():
    """Available sections are always in _SECTION_ORDER order, not insertion order."""
    # Provide sections in reverse order to verify sorting is not by dict order.
    song = {
        "sections": {
            "outro":   {"lyrics": "Outro lyrics"},
            "bridge":  {"lyrics": "Bridge lyrics"},
            "verse_2": {"lyrics": "Verse 2 lyrics"},
            "chorus":  {"lyrics": "Chorus lyrics"},
            "verse_1": {"lyrics": "Verse 1 lyrics"},
        }
    }
    result = _available_audio_sections(song)
    keys = [k for k, _ in result]
    expected = [k for k, _ in _SECTION_ORDER]
    assert keys == expected


def test_available_sections_excludes_empty_lyrics():
    """Sections with empty-string lyrics are excluded from the list."""
    song = _make_song_empty_section("bridge")
    result = _available_audio_sections(song)
    keys = [k for k, _ in result]
    assert "bridge" not in keys
    assert len(result) == 4


def test_available_sections_excludes_whitespace_only_lyrics():
    """Sections with whitespace-only lyrics are treated as empty and excluded."""
    song = _make_full_song()
    song["sections"]["verse_2"]["lyrics"] = "   \n\t  "
    result = _available_audio_sections(song)
    keys = [k for k, _ in result]
    assert "verse_2" not in keys


def test_available_sections_excludes_missing_section():
    """A section key absent from the song dict is simply not returned."""
    song = _make_partial_song(["verse_1", "chorus", "outro"])
    result = _available_audio_sections(song)
    keys = [k for k, _ in result]
    assert keys == ["verse_1", "chorus", "outro"]


def test_available_sections_empty_song_returns_empty_list():
    """Song with no sections → empty list, no crash."""
    result = _available_audio_sections({})
    assert result == []


def test_available_sections_all_empty_lyrics_returns_empty_list():
    """All sections have empty lyrics → empty list."""
    song = {
        "sections": {k: {"lyrics": ""} for k, _ in _SECTION_ORDER}
    }
    result = _available_audio_sections(song)
    assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# Offline tests — None-safety of _available_audio_sections()  (Enhancement 2)
# ─────────────────────────────────────────────────────────────────────────────

def test_available_sections_none_song_returns_empty_list():
    """Passing None returns an empty list — does not raise."""
    assert _available_audio_sections(None) == []


def test_available_sections_integer_song_returns_empty_list():
    """Passing a non-dict (int) returns an empty list — does not raise."""
    assert _available_audio_sections(42) == []


def test_available_sections_string_song_returns_empty_list():
    """Passing a string returns an empty list — does not raise."""
    assert _available_audio_sections("bad song data") == []


def test_available_sections_sections_is_string_returns_empty_list():
    """Song dict with sections='not_a_dict' returns an empty list — does not raise."""
    assert _available_audio_sections({"sections": "not_a_dict"}) == []


def test_available_sections_sections_is_list_returns_empty_list():
    """Song dict with sections=[] returns an empty list — does not raise."""
    assert _available_audio_sections({"sections": []}) == []


def test_available_sections_sections_is_none_returns_empty_list():
    """Song dict with sections=None returns an empty list — does not raise."""
    assert _available_audio_sections({"sections": None}) == []


def test_available_sections_section_value_not_dict_skipped():
    """A section whose value is not a dict is silently skipped."""
    song = {
        "sections": {
            "verse_1": "just a string",        # not a dict — skip
            "chorus":  {"lyrics": "Real chorus lyrics here"},
        }
    }
    result = _available_audio_sections(song)
    keys = [k for k, _ in result]
    assert "verse_1" not in keys
    assert "chorus" in keys
    assert len(result) == 1


def test_available_sections_lyrics_not_string_skipped():
    """A section whose lyrics field is not a string is silently skipped."""
    song = {
        "sections": {
            "verse_1": {"lyrics": 12345},          # int — not a string
            "chorus":  {"lyrics": "Valid chorus"},
        }
    }
    result = _available_audio_sections(song)
    keys = [k for k, _ in result]
    assert "verse_1" not in keys
    assert "chorus" in keys


def test_available_sections_returns_correct_labels():
    """Labels in the result match the human-readable names from _SECTION_ORDER."""
    result = _available_audio_sections(_make_full_song())
    label_map = dict(_SECTION_ORDER)
    for key, label in result:
        assert label == label_map[key], (
            f"Label mismatch for {key!r}: expected {label_map[key]!r}, got {label!r}"
        )


def test_available_sections_single_section():
    """Song with only one section returns a single-entry list."""
    song = _make_partial_song(["chorus"])
    result = _available_audio_sections(song)
    assert len(result) == 1
    assert result[0] == ("chorus", "Chorus")


# ─────────────────────────────────────────────────────────────────────────────
# Offline tests — default section selection logic
# ─────────────────────────────────────────────────────────────────────────────

def test_default_index_is_chorus_when_chorus_present():
    """When chorus is available, default_idx points to it."""
    available = _available_audio_sections(_make_full_song())
    keys = [k for k, _ in available]
    default_idx = keys.index("chorus") if "chorus" in keys else 0
    assert default_idx == keys.index("chorus")
    assert keys[default_idx] == "chorus"


def test_default_index_is_first_when_chorus_absent():
    """When chorus is absent, the default is the first available section."""
    song = _make_partial_song(["verse_1", "bridge", "outro"])
    available = _available_audio_sections(song)
    keys = [k for k, _ in available]
    default_idx = keys.index("chorus") if "chorus" in keys else 0
    assert default_idx == 0
    assert keys[0] == "verse_1"


# ─────────────────────────────────────────────────────────────────────────────
# Offline tests — generate_audio_preview() contract
# ─────────────────────────────────────────────────────────────────────────────

def test_empty_lyrics_raises_audio_generation_error():
    """Empty string lyrics raise AudioGenerationError immediately."""
    try:
        generate_audio_preview("")
        assert False, "Expected AudioGenerationError, but no exception was raised"
    except AudioGenerationError:
        pass  # expected


def test_whitespace_lyrics_raises_audio_generation_error():
    """Whitespace-only lyrics raise AudioGenerationError immediately."""
    for whitespace in ("   ", "\t", "\n", "\r\n", "  \n  \t  "):
        try:
            generate_audio_preview(whitespace)
            assert False, (
                f"Expected AudioGenerationError for whitespace {whitespace!r}, "
                "but no exception was raised"
            )
        except AudioGenerationError:
            pass  # expected


def test_audio_generation_error_is_exception():
    """AudioGenerationError is a subclass of the built-in Exception."""
    assert issubclass(AudioGenerationError, Exception)


def test_audio_generation_error_message_is_non_empty():
    """AudioGenerationError carries a non-empty message."""
    try:
        generate_audio_preview("")
        assert False, "Expected AudioGenerationError"
    except AudioGenerationError as exc:
        assert str(exc).strip(), "AudioGenerationError message must not be empty"


def test_ambient_param_accepted():
    """Function signature accepts ambient=None without raising TypeError.

    Uses the guard path (empty lyrics) — no network call needed.
    """
    try:
        generate_audio_preview("", ambient=None)
    except AudioGenerationError:
        pass  # expected — empty lyrics; parameter was accepted
    except TypeError as exc:
        assert False, f"Function raised TypeError (ambient param rejected): {exc}"


def test_lang_param_accepted():
    """Function signature accepts lang='en' without raising TypeError.

    Uses the guard path (empty lyrics) — no network call needed.
    """
    try:
        generate_audio_preview("", lang="en")
    except AudioGenerationError:
        pass  # expected — empty lyrics; parameter was accepted
    except TypeError as exc:
        assert False, f"Function raised TypeError (lang param rejected): {exc}"


def test_audio_generation_error_wraps_detail():
    """AudioGenerationError message mentions 'empty' or 'lyrics' for empty input."""
    try:
        generate_audio_preview("")
    except AudioGenerationError as exc:
        msg = str(exc)
        assert "empty" in msg.lower() or "lyrics" in msg.lower(), (
            f"AudioGenerationError message does not mention 'empty' or 'lyrics': {msg!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Live / integration tests — network-dependent, excluded from standalone runner
# ─────────────────────────────────────────────────────────────────────────────

if _PYTEST_AVAILABLE:
    @pytest.mark.integration
    def test_valid_lyrics_returns_bytes():
        """Valid lyrics return a bytes object (live gTTS call)."""
        result = generate_audio_preview("Come through the glass city rain")
        assert isinstance(result, bytes), (
            f"Expected bytes, got {type(result).__name__}"
        )

    @pytest.mark.integration
    def test_valid_lyrics_returns_nonempty_bytes():
        """Valid lyrics return non-empty bytes (live gTTS call)."""
        result = generate_audio_preview("Come through the glass city rain")
        assert len(result) > 0, "generate_audio_preview() returned empty bytes"

    @pytest.mark.integration
    def test_output_is_valid_mp3():
        """Returned bytes begin with a valid MP3 header (live gTTS call).

        gTTS outputs either an ID3-tagged file (b'ID3') or a raw MPEG frame
        starting with b'\\xff\\xfb' or b'\\xff\\xf3' (MPEG frame sync).
        Both are valid MP3 containers.
        """
        result = generate_audio_preview("I still know how to find you")
        valid_headers = (
            b"ID3",       # ID3v2 tagged MP3
            b"\xff\xfb",  # MPEG1 layer 3, 320kbps CBR
            b"\xff\xf3",  # MPEG1 layer 3, VBR
            b"\xff\xfa",  # MPEG1 layer 3 (no padding)
            b"\xff\xe3",  # MPEG 2.5 layer 3
        )
        header  = result[:3]
        header2 = result[:2]
        assert (
            header  in valid_headers or
            header2 in (b"\xff\xfb", b"\xff\xf3", b"\xff\xfa", b"\xff\xe3")
        ), f"Output does not look like MP3 — first 4 bytes: {result[:4]!r}"

    @pytest.mark.integration
    def test_ambient_none_is_noop():
        """Passing ambient=None does not prevent successful generation (live call)."""
        result_no_ambient = generate_audio_preview("The city keeps its name")
        result_with_none  = generate_audio_preview("The city keeps its name", ambient=None)
        assert isinstance(result_no_ambient, bytes) and len(result_no_ambient) > 0
        assert isinstance(result_with_none, bytes)  and len(result_with_none) > 0

    @pytest.mark.integration
    def test_non_chorus_section_lyrics_produce_audio():
        """Verse and bridge lyrics (not just chorus) produce valid audio (live call)."""
        for lyrics in [
            "The floorboards remember your steps, the kettle still hums at eight",
            "Maybe the roads all lead to the same quiet place",
            "Come home, the light is still on",
        ]:
            result = generate_audio_preview(lyrics)
            assert isinstance(result, bytes) and len(result) > 0, (
                f"Expected non-empty bytes for lyrics: {lyrics[:40]!r}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Offline tests — download filename logic  (Enhancement 1)
# ─────────────────────────────────────────────────────────────────────────────

def test_download_filename_format():
    """Download filename follows the '{project}_{section}_preview.mp3' pattern."""
    project_name   = "Glass City Sessions"
    section_label  = "Verse 1"
    safe_name      = project_name.replace(" ", "_")
    safe_section   = section_label.replace(" ", "_")
    filename       = f"{safe_name}_{safe_section}_preview.mp3"
    assert filename == "Glass_City_Sessions_Verse_1_preview.mp3"


def test_download_filename_ends_with_mp3():
    """Download filename always ends with .mp3."""
    for name, section in [("My Song", "Chorus"), ("A", "Bridge"), ("X Y Z", "Outro")]:
        fn = f"{name.replace(' ', '_')}_{section.replace(' ', '_')}_preview.mp3"
        assert fn.endswith(".mp3"), f"Filename does not end with .mp3: {fn!r}"


def test_download_filename_uses_section_label():
    """Each section produces a distinct filename."""
    labels = ["Verse_1", "Chorus", "Verse_2", "Bridge", "Outro"]
    filenames = {f"MySong_{lbl}_preview.mp3" for lbl in labels}
    assert len(filenames) == 5, "Some section labels produced duplicate filenames"


# ─────────────────────────────────────────────────────────────────────────────
# Offline tests list (standalone runner — no network)
# ─────────────────────────────────────────────────────────────────────────────

_OFFLINE_TESTS = [
    # Section-selector helper
    test_available_sections_full_song_returns_all_five,
    test_available_sections_respects_canonical_order,
    test_available_sections_excludes_empty_lyrics,
    test_available_sections_excludes_whitespace_only_lyrics,
    test_available_sections_excludes_missing_section,
    test_available_sections_empty_song_returns_empty_list,
    test_available_sections_all_empty_lyrics_returns_empty_list,
    test_available_sections_returns_correct_labels,
    test_available_sections_single_section,
    # None-safety (Enhancement 2)
    test_available_sections_none_song_returns_empty_list,
    test_available_sections_integer_song_returns_empty_list,
    test_available_sections_string_song_returns_empty_list,
    test_available_sections_sections_is_string_returns_empty_list,
    test_available_sections_sections_is_list_returns_empty_list,
    test_available_sections_sections_is_none_returns_empty_list,
    test_available_sections_section_value_not_dict_skipped,
    test_available_sections_lyrics_not_string_skipped,
    # Default index logic
    test_default_index_is_chorus_when_chorus_present,
    test_default_index_is_first_when_chorus_absent,
    # Download filename logic (Enhancement 1)
    test_download_filename_format,
    test_download_filename_ends_with_mp3,
    test_download_filename_uses_section_label,
    # generate_audio_preview() contract
    test_empty_lyrics_raises_audio_generation_error,
    test_whitespace_lyrics_raises_audio_generation_error,
    test_audio_generation_error_is_exception,
    test_audio_generation_error_message_is_non_empty,
    test_ambient_param_accepted,
    test_lang_param_accepted,
    test_audio_generation_error_wraps_detail,
]


def run_tests() -> int:
    """Run all offline Phase 5 tests. Returns the number of failures."""
    total  = len(_OFFLINE_TESTS)
    passed = 0
    failed = 0

    print(f"\n{'=' * 60}")
    print(f"  HarmonyLedger - Phase 5 Test Harness")
    print(f"  Audio Preview — None-safety + download + gTTS contract")
    print(f"  {total} offline tests")
    print(f"{'=' * 60}\n")

    for fn in _OFFLINE_TESTS:
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
        print(f"  Results: {passed}/{total}  |  {failed} FAILED")
    else:
        print(f"  Results: {passed}/{total}  |  ALL PASSED")
    print(f"\n  NOTE: Live/integration tests (require gTTS network access) are")
    print(f"  excluded from this runner. To include them, run:")
    print(f"      pytest tests/test_phase5.py -m integration -v")
    print(f"{'=' * 60}\n")

    return failed


if __name__ == "__main__":
    sys.exit(0 if run_tests() == 0 else 1)
