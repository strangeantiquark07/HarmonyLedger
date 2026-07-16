"""
utils/ai_engine.py
──────────────────
Public AI interface for HarmonyLedger.

This is the only module the Streamlit UI (and test harness) should import
when requesting song generation. It owns the complete generation pipeline:

  1. Load the versioned prompt template from prompts/song_starter_v1.txt.
  2. Render the prompt with the user's vibe and the project's genre.
  3. Call gemini_client.call_gemini() to get a raw text response.
  4. Strip any markdown fences Gemini may have added defensively.
  5. Parse the response as JSON.
  6. Validate that every required field is present and well-formed.
  7. Stamp generation_timestamp and model_used (never asked from Gemini).
  8. Add the provenance envelope to every song section.
  9. Retry steps 3–8 up to MAX_RETRIES times on any failure.
 10. Raise SongGenerationError if all attempts are exhausted.

Public interface
────────────────
  generate_song(vibe: str, genre: str = "") -> dict

  Returns a complete, validated song dictionary ready to be merged into
  project.song. Raises SongGenerationError on unrecoverable failure.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from utils import gemini_client
from utils.gemini_client import GeminiAPIError

# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class SongGenerationError(Exception):
    """Raised when song generation fails after all retry attempts.

    The message includes the attempt count and the last error detail so
    the Streamlit UI can surface a meaningful message to the user.
    """


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Total number of generation attempts (first try + retries).
MAX_RETRIES: int = 3

# Model identifier — stamped onto every generated song dict.
_MODEL_NAME: str = "gemini-2.5-flash"

# Song schema version — bumped here when the song JSON contract changes.
# Stored in project.song["song_schema_version"] so Phase 3+ can detect and
# migrate older song objects without walking the full project schema_version.
SONG_SCHEMA_VERSION: str = "1.0"

# Absolute path to the production prompt template, resolved relative to
# this file so it works correctly regardless of the working directory.
_PROMPT_TEMPLATE_PATH: Path = (
    Path(__file__).parent.parent / "prompts" / "song_starter_v1.txt"
)

# The five section keys that every generated song must contain, in
# canonical display order. Phase 3 drift-checking references these by name.
_REQUIRED_SECTIONS: tuple[str, ...] = (
    "verse_1",
    "chorus",
    "verse_2",
    "bridge",
    "outro",
)

# Top-level string fields (excluding sections) that Gemini must produce.
_REQUIRED_STRING_FIELDS: tuple[str, ...] = (
    "title",
    "genre",
    "style",
    "mood",
    "tempo",
    "key",
    "time_signature",
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_prompt_template() -> str:
    """Read and return the raw prompt template text.

    Raises:
        FileNotFoundError: if song_starter_v1.txt does not exist.
    """
    if not _PROMPT_TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"Prompt template not found at: {_PROMPT_TEMPLATE_PATH}\n"
            "Ensure prompts/song_starter_v1.txt exists in the project root."
        )
    return _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")


def _build_prompt(vibe: str, genre: str) -> str:
    """Render the prompt template with the given vibe and genre.

    Args:
        vibe:  The user's song vibe (free-text description).
        genre: The project's genre (e.g. "Chillwave", "Indie Folk").

    Returns:
        The fully rendered prompt string ready to send to Gemini.
    """
    template = _load_prompt_template()
    return template.format(vibe=vibe, genre=genre)


def _strip_fences(raw: str) -> str:
    """Remove markdown code fences and extract JSON from a response string.

    Handles:
      1. Clean JSON (no fences) — returned as-is.
      2. ```json ... ``` wrapper — fence stripped.
      3. ``` ... ``` wrapper — fence stripped.
      4. Prose before/after fences — prose discarded, JSON extracted.
      5. Prose with an embedded JSON object (no fences) — JSON extracted.

    This is a defensive measure because even with response_mime_type=json
    some model versions occasionally add surrounding text.

    Args:
        raw: Raw text as returned by Gemini.

    Returns:
        The extracted JSON string, stripped of surrounding whitespace.
    """
    text = raw.strip()

    # Case 1: already starts and ends with { } — likely clean JSON.
    if text.startswith("{") and text.endswith("}"):
        return text

    # Case 2/3/4: try to extract from a code fence (anywhere in the string).
    fence_match = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL
    )
    if fence_match:
        return fence_match.group(1).strip()

    # Case 5: try to extract a JSON object by finding the first { and last }.
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end > start:
        return text[start: end + 1].strip()

    # Give up — return the original stripped text and let json.loads fail
    # with a clear error message.
    return text


def _validate(song: dict) -> None:
    """Validate that a parsed song dict matches the required schema.

    Checks are intentionally strict: every required field must be present,
    non-empty, and of the correct type. This ensures that downstream
    features (section locking, drift checking, the Creative Passport) always
    receive a complete, well-formed song object.

    Args:
        song: A dict produced by json.loads() from Gemini's response.

    Raises:
        ValueError: with a descriptive message for the first failed check.
    """
    # ── Top-level string fields ───────────────────────────────────────────
    for field in _REQUIRED_STRING_FIELDS:
        if field not in song:
            raise ValueError(f"Missing required field: '{field}'")
        if not isinstance(song[field], str) or not song[field].strip():
            raise ValueError(
                f"Field '{field}' must be a non-empty string, "
                f"got: {type(song[field]).__name__!r} = {song[field]!r}"
            )

    # ── lyrical_themes ────────────────────────────────────────────────────
    if "lyrical_themes" not in song:
        raise ValueError("Missing required field: 'lyrical_themes'")
    themes = song["lyrical_themes"]
    if not isinstance(themes, list) or len(themes) == 0:
        raise ValueError(
            f"Field 'lyrical_themes' must be a non-empty list, got: {themes!r}"
        )
    for i, theme in enumerate(themes):
        if not isinstance(theme, str) or not theme.strip():
            raise ValueError(
                f"'lyrical_themes[{i}]' must be a non-empty string, got: {theme!r}"
            )

    # ── sections ─────────────────────────────────────────────────────────
    if "sections" not in song:
        raise ValueError("Missing required field: 'sections'")
    sections = song["sections"]
    if not isinstance(sections, dict):
        raise ValueError(
            f"Field 'sections' must be a dict, got: {type(sections).__name__!r}"
        )

    missing_sections = [k for k in _REQUIRED_SECTIONS if k not in sections]
    if missing_sections:
        raise ValueError(
            f"Missing required section(s): {missing_sections}. "
            f"Required sections are: {list(_REQUIRED_SECTIONS)}"
        )

    for key in _REQUIRED_SECTIONS:
        section = sections[key]
        if not isinstance(section, dict):
            raise ValueError(
                f"Section '{key}' must be a dict, got: {type(section).__name__!r}"
            )
        lyrics = section.get("lyrics", "")
        if not isinstance(lyrics, str) or not lyrics.strip():
            raise ValueError(
                f"Section '{key}.lyrics' must be a non-empty string, "
                f"got: {lyrics!r}"
            )


def _add_provenance_envelope(sections: dict) -> dict:
    """Add the Phase 2 provenance envelope to each section dict.

    The envelope fields are used by Phase 3 (locking, drift-check) and
    Phase 4 (contribution tracking). They are stamped here — never asked
    from Gemini — so they are always present and always correct.

    Args:
        sections: The validated sections dict from Gemini's response.

    Returns:
        A new dict with the same keys but each section augmented with the
        provenance envelope. The original dict is not mutated.
    """
    envelope: dict = {
        "provenance":     "ai_generated",
        "locked":         False,
        "locked_at":      None,
        "locked_by":      None,
        "last_edited_by": "AI",
        "edit_count":     0,
    }
    return {
        key: {**section, **envelope}
        for key, section in sections.items()
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_song(
    vibe: str,
    genre: str = "",
    locked_sections: dict | None = None,  # noqa: F821  (reserved for Phase 3)
) -> dict:
    """Generate a complete, validated song from a vibe description.

    This is the single entry point for AI song generation. The Streamlit
    UI and the test harness both call this function; nothing else in the
    codebase should import google.generativeai directly.

    Args:
        vibe:             The user's song vibe — a free-text description of
                          the mood, feel, and style of the song they want.
        genre:            The project's genre (e.g. "Chillwave"). Passed into
                          the prompt so Gemini stays on-brief. Defaults to an
                          empty string if the project has no genre set.
        locked_sections:  Reserved for Phase 3 targeted regeneration. When
                          provided, the engine will pass locked section
                          content as context so regenerated sections stay
                          coherent with what the human has approved. Unused
                          in Phase 2 — accepted here to keep the public
                          interface stable across phases.

    Returns:
        A fully validated song dict with the following top-level structure:

            {
              "title":               str,
              "genre":               str,
              "style":               str,
              "mood":                str,
              "tempo":               str,
              "key":                 str,
              "time_signature":      str,
              "lyrical_themes":      list[str],
              "generation_timestamp":str,   # ISO-8601, stamped here
              "model_used":          str,   # "gemini-2.5-flash", stamped here
              "sections": {
                "verse_1": {"lyrics": str, "provenance": "ai_generated",
                            "locked": False, "locked_at": None,
                            "locked_by": None, "last_edited_by": "AI",
                            "edit_count": 0},
                "chorus":  { ... },
                "verse_2": { ... },
                "bridge":  { ... },
                "outro":   { ... },
              }
            }

    Raises:
        SongGenerationError: if all MAX_RETRIES attempts fail. The message
            includes the attempt count and the last error detail.
        FileNotFoundError:   if prompts/song_starter_v1.txt is missing.
    """
    prompt = _build_prompt(vibe=vibe, genre=genre)

    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # ── Step 1: call the API ──────────────────────────────────────
            raw_text = gemini_client.call_gemini(prompt)

            # ── Step 2: strip markdown fences (defensive) ─────────────────
            cleaned = _strip_fences(raw_text)

            # ── Step 3: parse JSON ────────────────────────────────────────
            try:
                song = json.loads(cleaned)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Response is not valid JSON: {exc}\n"
                    f"Raw response (first 500 chars): {cleaned[:500]!r}"
                ) from exc

            if not isinstance(song, dict):
                raise ValueError(
                    f"Expected a JSON object at the top level, "
                    f"got {type(song).__name__!r}"
                )

            # ── Step 4: validate schema ───────────────────────────────────
            _validate(song)

            # ── Step 5: stamp engine-controlled fields ────────────────────
            song["generation_timestamp"]  = datetime.now().isoformat()
            song["model_used"]            = _MODEL_NAME
            song["song_schema_version"]   = SONG_SCHEMA_VERSION

            # ── Step 6: add provenance envelope to every section ──────────
            song["sections"] = _add_provenance_envelope(song["sections"])

            return song

        except Exception as exc:
            last_error = exc
            # Log the attempt for visibility without crashing.
            print(
                f"[ai_engine] Attempt {attempt}/{MAX_RETRIES} failed: "
                f"{type(exc).__name__}: {exc}"
            )
            # If we still have attempts left, loop and try again.
            # If this was the last attempt, fall through to the raise below.

    raise SongGenerationError(
        f"Song generation failed after {MAX_RETRIES} attempt(s). "
        f"Last error — {type(last_error).__name__}: {last_error}"
    )
