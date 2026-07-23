"""
utils/audio_engine.py
─────────────────────
Phase 5 — Audio Preview.

Converts a lyrics string to an MP3 audio preview using gTTS (Google
Text-to-Speech) and returns the raw bytes entirely in memory.  No file
is written to disk.

Design contract (mirrors utils/passport.py):
  - generate_audio_preview() is a PURE function: no side effects, no
    Streamlit imports, no project mutations.
  - The caller (views/view_project.py) is responsible for:
      • Calling st.audio() on the returned bytes.
      • Logging the "audio_preview_generated" timeline event.
      • Calling save_project() to persist the event.
  - All gTTS exceptions are wrapped in AudioGenerationError so callers
    never need to import gTTS directly.

Future extensibility — ambient music overlay:
  generate_audio_preview() accepts an `ambient` keyword argument
  (default None) that is currently a no-op.  When Phase 5+ adds an
  ambient music layer (mixing speech with a background track), that
  parameter will carry the track identifier without requiring any
  change at the call site in views/view_project.py.
"""

import io

# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class AudioGenerationError(Exception):
    """Raised when audio preview generation fails for any reason.

    Wraps all gTTS exceptions so callers have a single exception type to
    catch and never need to import gTTS directly.  The message always
    includes the original exception type and description for diagnostics.
    """


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Default TTS language code (BCP-47).  Passed to gTTS as the `lang` arg.
# Override per-call via the `lang` parameter; change this constant to shift
# the whole app's default voice locale in one place.
_DEFAULT_LANG: str = "en"

# Maps utils.models.SUPPORTED_LANGUAGES (the project's song-generation
# language) to a gTTS voice language code. Without this mapping, callers
# that don't pass `lang` explicitly always get the English voice reading
# non-English lyrics — which is what generate_audio_preview() calls with
# for every language before this map existed.
_SUPPORTED_LANGUAGE_TO_GTTS: dict[str, str] = {
    "English":  "en",
    "Hindi":    "hi",
    "Marathi":  "mr",
    "Telugu":   "te",
    "Tamil":    "ta",
    "Spanish":  "es",
    "French":   "fr",
    "Japanese": "ja",
}


def gtts_lang_code(language: str) -> str:
    """Map a project's song-generation language to its gTTS voice code.

    Falls back to the English voice for any language not in the map, so a
    caller can always pass this straight through to generate_audio_preview()
    without a KeyError.
    """
    return _SUPPORTED_LANGUAGE_TO_GTTS.get(language, _DEFAULT_LANG)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_audio_preview(
    lyrics: str,
    lang: str = _DEFAULT_LANG,
    ambient=None,  # TODO Phase 5+: mix speech with an ambient audio track
) -> bytes:
    """Generate a spoken MP3 preview of *lyrics* and return raw bytes.

    Uses gTTS (Google Text-to-Speech) to synthesise speech in-memory.
    The entire pipeline runs inside an io.BytesIO buffer — no file is
    written to disk.

    Args:
        lyrics:  The lyrics text to convert to speech.  Must be a
                 non-empty string after stripping whitespace.
        lang:    BCP-47 language code for the TTS voice (default "en").
        ambient: Reserved for a future ambient music overlay feature.
                 Currently unused — any value passed here is silently
                 ignored.  Do not rely on this parameter in Phase 5.

    Returns:
        Raw MP3 bytes starting with an MP3 frame header or ID3 tag.

    Raises:
        AudioGenerationError: if *lyrics* is empty/whitespace, if the
            gTTS network call fails, or if any other gTTS error occurs.
    """
    # Guard: reject empty lyrics immediately — no network call needed.
    if not lyrics or not lyrics.strip():
        raise AudioGenerationError(
            "Cannot generate audio preview: lyrics are empty. "
            "Ensure the selected section contains non-empty text."
        )

    # ambient is intentionally unused in Phase 5.
    # When ambient support is added, this is where the mixing logic goes.
    _ = ambient  # noqa: F841  (suppress unused-variable warnings)

    try:
        from gtts import gTTS  # local import keeps the module loadable even
                                # if gTTS is not installed (ImportError surfaces
                                # as AudioGenerationError with a clear message)
        tts = gTTS(text=lyrics.strip(), lang=lang)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return buf.read()
    except AudioGenerationError:
        raise  # re-raise our own guard error unchanged
    except ImportError as exc:
        raise AudioGenerationError(
            "gTTS is not installed. "
            "Add 'gTTS>=2.4' to requirements.txt and run pip install."
        ) from exc
    except Exception as exc:
        raise AudioGenerationError(
            f"Audio generation failed ({type(exc).__name__}): {exc}"
        ) from exc
