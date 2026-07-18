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

Public interface (Phase 2)
──────────────────────────
  generate_song(vibe: str, genre: str = "") -> dict

  Returns a complete, validated song dictionary ready to be merged into
  project.song. Raises SongGenerationError on unrecoverable failure.

Public interface (Phase 3)
──────────────────────────
  regenerate_section(section_key: str, song: dict) -> str

  Regenerates a single section's lyrics using a focused prompt that
  includes only the locked sections as coherence context. Returns the
  new lyrics string. Raises SongGenerationError on failure.

  snapshot_locked_sections(song: dict) -> dict[str, str]

  Returns a SHA-256 hex digest for every currently locked section's
  lyrics. Used by the UI to detect drift before saving.

  assert_locked_sections_unchanged(song: dict, snapshot: dict) -> None

  Re-hashes locked sections and raises DriftError if any digest has
  changed since the snapshot was taken.

  DriftError  — raised when a locked section's content has changed.
"""

import hashlib
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


class DriftError(Exception):
    """Raised when a locked section's lyrics have changed after regeneration.

    This is a safety guard: if Gemini's response somehow modified a locked
    section's content (despite the prompt explicitly forbidding it), the
    regeneration is aborted and this error is raised before any save occurs.

    The message identifies which section(s) drifted so the UI can surface
    a clear, actionable message to the user.
    """


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Total number of generation attempts (first try + retries).
MAX_RETRIES: int = 3

# Model identifier — stamped onto every generated song dict.
_MODEL_NAME: str = "gemini-flash-latest"

# Song schema version — bumped here when the song JSON contract changes.
# Stored in project.song["song_schema_version"] so Phase 3+ can detect and
# migrate older song objects without walking the full project schema_version.
SONG_SCHEMA_VERSION: str = "1.0"

# Absolute path to the full-song prompt template.
_PROMPT_TEMPLATE_PATH: Path = (
    Path(__file__).parent.parent / "prompts" / "song_starter_v1.txt"
)

# Absolute path to the targeted section-regeneration prompt template.
_SECTION_REGEN_TEMPLATE_PATH: Path = (
    Path(__file__).parent.parent / "prompts" / "section_regen_v1.txt"
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

# Human-readable labels for each section key — used when building the
# locked-context block sent to Gemini during targeted regeneration.
_SECTION_LABELS: dict[str, str] = {
    "verse_1": "Verse 1",
    "chorus":  "Chorus",
    "verse_2": "Verse 2",
    "bridge":  "Bridge",
    "outro":   "Outro",
}

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


# =============================================================================
# Phase 3 — Section Locking & Targeted Regeneration
# =============================================================================


# ---------------------------------------------------------------------------
# Phase 3 internal helpers
# ---------------------------------------------------------------------------

def _load_section_regen_template() -> str:
    """Read and return the section-regeneration prompt template.

    Raises:
        FileNotFoundError: if section_regen_v1.txt does not exist.
    """
    if not _SECTION_REGEN_TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"Section-regen prompt template not found at: {_SECTION_REGEN_TEMPLATE_PATH}\n"
            "Ensure prompts/section_regen_v1.txt exists in the project root."
        )
    return _SECTION_REGEN_TEMPLATE_PATH.read_text(encoding="utf-8")


def _build_section_context(song: dict, target_key: str) -> str:
    """Build a formatted block of locked-section lyrics for the regen prompt.

    Only sections that are locked AND are not the target section are included.
    This gives Gemini enough context to write a coherent replacement without
    leaking unlocked sections that may also be regenerated later.

    If no locked sections exist (other than the target), returns an empty
    string so the {locked_context} placeholder is simply omitted from the
    rendered prompt — the song context block is sufficient.

    Args:
        song:       The full project.song dict (must have a "sections" key).
        target_key: The section key being regenerated — excluded from context.

    Returns:
        A multi-line string ready to drop into the {locked_context} placeholder,
        or an empty string when no locked context is available.
    """
    sections = song.get("sections", {})
    lines: list[str] = []

    for key in _REQUIRED_SECTIONS:
        if key == target_key:
            continue
        sec = sections.get(key)
        if not sec:
            continue
        if sec.get("locked"):
            label  = _SECTION_LABELS.get(key, key)
            lyrics = sec.get("lyrics", "").strip()
            lines.append(f"LOCKED — {label}:\n{lyrics}")

    if not lines:
        return (
            "LOCKED SECTIONS FOR CONTEXT: none — all other sections are unlocked "
            "and may change in future cycles.\n\n"
        )

    header = (
        "LOCKED SECTIONS FOR CONTEXT — these sections are approved and must NOT "
        "be reproduced or modified. Use them only to ensure the new "
        f"{_SECTION_LABELS.get(target_key, target_key)} is coherent:\n\n"
    )
    return header + "\n\n".join(lines) + "\n\n"


def _build_section_regen_prompt(section_key: str, song: dict) -> str:
    """Render the section-regeneration prompt template.

    Args:
        section_key: The section to regenerate (e.g. "verse_1").
        song:        The full project.song dict — provides title, genre, etc.

    Returns:
        The fully rendered prompt string ready to send to Gemini.
    """
    template       = _load_section_regen_template()
    section_label  = _SECTION_LABELS.get(section_key, section_key)
    locked_context = _build_section_context(song, target_key=section_key)

    return template.format(
        title          = song.get("title",          ""),
        genre          = song.get("genre",           ""),
        style          = song.get("style",           ""),
        mood           = song.get("mood",            ""),
        vibe           = song.get("vibe",            ""),    # may be absent; "" is fine
        section_key    = section_key,
        section_label  = section_label,
        locked_context = locked_context,
    )


def _validate_section_response(data: dict) -> None:
    """Validate that Gemini returned exactly {"lyrics": "<non-empty string>"}.

    Args:
        data: A dict produced by json.loads() from Gemini's response.

    Raises:
        ValueError: with a descriptive message if validation fails.
    """
    if "lyrics" not in data:
        raise ValueError(
            f"Section response is missing the 'lyrics' key. "
            f"Keys present: {list(data.keys())!r}"
        )
    lyrics = data["lyrics"]
    if not isinstance(lyrics, str) or not lyrics.strip():
        raise ValueError(
            f"Section 'lyrics' must be a non-empty string, "
            f"got {type(lyrics).__name__!r} = {lyrics!r}"
        )


# ---------------------------------------------------------------------------
# Phase 3 public API — targeted section regeneration
# ---------------------------------------------------------------------------

def regenerate_section(section_key: str, song: dict) -> str:
    """Regenerate a single song section's lyrics via a focused Gemini prompt.

    This is the Phase 3 counterpart to generate_song(). It generates new
    lyrics for ONE section only, using the locked sections as coherence
    context. Song-level metadata (title, mood, tempo, etc.) is passed as
    context but is frozen — Gemini is instructed to produce only new lyrics.

    The caller (view_project.py) is responsible for:
      - Taking a pre-call snapshot with snapshot_locked_sections()
      - Grafting the returned lyrics into project.song
      - Running assert_locked_sections_unchanged() after grafting
      - Saving the project only if the drift check passes

    Args:
        section_key: One of the five canonical section keys
                     ("verse_1", "chorus", "verse_2", "bridge", "outro").
        song:        The full project.song dict. Must have at minimum:
                     "title", "genre", "style", "mood", and "sections".

    Returns:
        The new lyrics string (non-empty, unescaped plain text).

    Raises:
        ValueError:          if section_key is not one of _REQUIRED_SECTIONS.
        SongGenerationError: if all MAX_RETRIES attempts fail.
        FileNotFoundError:   if prompts/section_regen_v1.txt is missing.
    """
    # Guard: reject unknown section keys immediately — no point retrying.
    if section_key not in _REQUIRED_SECTIONS:
        raise ValueError(
            f"Unknown section key: {section_key!r}. "
            f"Must be one of: {list(_REQUIRED_SECTIONS)}"
        )

    prompt     = _build_section_regen_prompt(section_key, song)
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # ── Step 1: call the API ──────────────────────────────────────────
            raw_text = gemini_client.call_gemini(prompt)

            # ── Step 2: strip markdown fences (defensive) ─────────────────────
            cleaned = _strip_fences(raw_text)

            # ── Step 3: parse JSON ────────────────────────────────────────────
            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Section response is not valid JSON: {exc}\n"
                    f"Raw response (first 500 chars): {cleaned[:500]!r}"
                ) from exc

            if not isinstance(data, dict):
                raise ValueError(
                    f"Expected a JSON object, got {type(data).__name__!r}"
                )

            # ── Step 4: validate — must be {"lyrics": "<non-empty>"} ──────────
            _validate_section_response(data)

            # Return the validated lyrics string.
            return data["lyrics"].strip()

        except Exception as exc:
            last_error = exc
            print(
                f"[ai_engine] regenerate_section attempt {attempt}/{MAX_RETRIES} "
                f"failed: {type(exc).__name__}: {exc}"
            )

    raise SongGenerationError(
        f"Section regeneration failed after {MAX_RETRIES} attempt(s). "
        f"Last error — {type(last_error).__name__}: {last_error}"
    )


# ---------------------------------------------------------------------------
# Phase 3 public API — drift-check utilities
# ---------------------------------------------------------------------------

def snapshot_locked_sections(song: dict) -> dict[str, str]:
    """Return a SHA-256 hex digest for every currently locked section's lyrics.

    This snapshot must be taken BEFORE calling regenerate_section() and
    passed to assert_locked_sections_unchanged() AFTER the graft. If the
    two snapshots differ, a DriftError is raised and the save is aborted.

    Hashing only the lyrics content (not the full envelope) ensures that
    metadata changes (e.g. stamping locked_at) do not produce false positives.

    Args:
        song: The full project.song dict (must have a "sections" key).

    Returns:
        A dict mapping section_key → sha256_hex for every locked section.
        Returns an empty dict if no sections are locked.
    """
    snapshot: dict[str, str] = {}
    sections = song.get("sections", {})
    for key, sec in sections.items():
        if sec.get("locked"):
            lyrics = sec.get("lyrics", "")
            snapshot[key] = hashlib.sha256(lyrics.encode("utf-8")).hexdigest()
    return snapshot


def assert_locked_sections_unchanged(song: dict, snapshot: dict) -> None:
    """Verify that every locked section's lyrics match the pre-call snapshot.

    Called after the merge graft and before save_project(). If any locked
    section's content has changed — or if a section that was locked before
    the API call is now missing — a DriftError is raised.

    An empty snapshot (no locked sections) is a no-op: the function returns
    immediately without raising.

    Args:
        song:     The full project.song dict after the merge graft.
        snapshot: The dict returned by snapshot_locked_sections() before
                  the regeneration call.

    Raises:
        DriftError: if any locked section's lyrics differ from the snapshot,
                    or if a previously locked section is missing entirely.
    """
    if not snapshot:
        return  # No locked sections — nothing to check.

    sections = song.get("sections", {})
    drifted: list[str] = []

    for key, pre_hash in snapshot.items():
        if key not in sections:
            drifted.append(
                f"{_SECTION_LABELS.get(key, key)!r} is missing after regeneration"
            )
            continue

        lyrics    = sections[key].get("lyrics", "")
        post_hash = hashlib.sha256(lyrics.encode("utf-8")).hexdigest()

        if post_hash != pre_hash:
            drifted.append(
                f"{_SECTION_LABELS.get(key, key)!r} — content changed "
                f"(pre={pre_hash[:8]}…, post={post_hash[:8]}…)"
            )

    if drifted:
        raise DriftError(
            f"Locked section(s) changed during regeneration — aborting save.\n"
            f"Drifted: {'; '.join(drifted)}"
        )
