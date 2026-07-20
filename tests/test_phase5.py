"""
tests/test_phase5.py
────────────────────
Phase 5 — Audio Preview test suite.

Tests the public contract of utils/audio_engine.py:
  - AudioGenerationError is raised for empty/whitespace lyrics (offline)
  - AudioGenerationError is a proper Exception subclass (offline)
  - Function accepts ambient=None and lang="en" without TypeError (offline)
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

try:
    import pytest
    _PYTEST_AVAILABLE = True
except ImportError:
    _PYTEST_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Offline tests — run in standalone runner, no network required
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

    This does NOT call the gTTS API — it tests only the guard path (empty
    lyrics), which triggers before any network call.  The point is that the
    function does not raise TypeError when ambient=None is passed.
    """
    try:
        generate_audio_preview("", ambient=None)
    except AudioGenerationError:
        pass  # expected — empty lyrics; the parameter was accepted
    except TypeError as exc:
        assert False, f"Function raised TypeError (ambient param rejected): {exc}"


def test_lang_param_accepted():
    """Function signature accepts lang='en' without raising TypeError.

    Same approach as test_ambient_param_accepted: uses the guard path to
    avoid a live network call while still proving the parameter is accepted.
    """
    try:
        generate_audio_preview("", lang="en")
    except AudioGenerationError:
        pass  # expected — empty lyrics; the parameter was accepted
    except TypeError as exc:
        assert False, f"Function raised TypeError (lang param rejected): {exc}"


def test_audio_generation_error_wraps_detail():
    """AudioGenerationError message includes type and detail for empty lyrics."""
    try:
        generate_audio_preview("")
    except AudioGenerationError as exc:
        msg = str(exc)
        # The guard message should mention that lyrics are empty
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
        header = result[:3]
        header2 = result[:2]
        assert (
            header in valid_headers or
            header2 in (b"\xff\xfb", b"\xff\xf3", b"\xff\xfa", b"\xff\xe3")
        ), f"Output does not look like MP3 — first 4 bytes: {result[:4]!r}"

    @pytest.mark.integration
    def test_ambient_none_is_noop():
        """Passing ambient=None does not affect the output (live gTTS call)."""
        result_no_ambient  = generate_audio_preview("The city keeps its name")
        result_with_none   = generate_audio_preview("The city keeps its name", ambient=None)
        # Both should produce non-empty bytes — we don't require them to be
        # byte-identical (gTTS is deterministic but not guaranteed to be so
        # across calls) but both must be valid.
        assert isinstance(result_no_ambient, bytes) and len(result_no_ambient) > 0
        assert isinstance(result_with_none, bytes)  and len(result_with_none) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Offline tests list (standalone runner — no network)
# ─────────────────────────────────────────────────────────────────────────────

_OFFLINE_TESTS = [
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
    print(f"  Audio Preview (utils/audio_engine.py)")
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
