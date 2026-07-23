"""
views/view_project.py
─────────────────────
Project workspace — the primary page for Phase 2 and beyond.

Responsibilities:
  - Load and display a project identified by st.session_state.active_project_id.
  - Show the Generate Song button when no song has been generated yet.
  - On generation: call ai_engine.generate_song(), merge the result into
    project.song, log an "ai_generated" timeline event, and save atomically.
  - Render the generated song (title, metadata strip, section cards).
  - Handle all errors gracefully with clear, user-friendly messages.

Phase 3 additions:
  - Lock/unlock toggle per section card (_toggle_lock).
  - Targeted single-section regeneration (_run_section_regeneration).
  - Drift-check guard: locked sections verified before save.
  - New timeline event types: section_locked, section_unlocked, section_regenerated.

Phase 4 (human editing) additions:
  - Inline edit mode per section card (_save_human_edit).
  - Edit button opens a text_area; Save/Cancel controls close it.
  - Provenance transitions: ai_generated → ai_then_human; human_written stays.
  - edit_count incremented and last_edited_by set to "Human" on every save.
  - human_edit timeline event logged on every successful save.
  - Locked sections cannot be edited (Edit button hidden while locked).
"""

import html as _html
from datetime import datetime, timezone
from uuid import uuid4

import streamlit as st

from utils.ai_engine import (
    generate_song,
    regenerate_section,
    snapshot_locked_sections,
    assert_locked_sections_unchanged,
    SongGenerationError,
    DriftError,
)
from utils.audio_engine import generate_audio_preview, AudioGenerationError, gtts_lang_code
from utils.contribution import compute_contribution
from utils.passport import build_passport_pdf, compute_record_hash
from utils.storage import (
    load_project, save_project, ProjectNotFoundError, ProjectCorruptedError,
    ProjectConflictError,
)
from utils.timeline import append_event


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Canonical section display order and human-readable labels.
_SECTION_ORDER: tuple[tuple[str, str], ...] = (
    ("verse_1", "Verse 1"),
    ("chorus",  "Chorus"),
    ("verse_2", "Verse 2"),
    ("bridge",  "Bridge"),
    ("outro",   "Outro"),
)

# Accent colours for each section type — gives the song a visual rhythm.
_SECTION_COLORS: dict[str, str] = {
    "verse_1": "#1DB954",   # green
    "chorus":  "#3B82F6",   # blue — chorus is the centrepiece
    "verse_2": "#1DB954",   # green (matches verse_1)
    "bridge":  "#F59E0B",   # amber — transitional
    "outro":   "#8B5CF6",   # purple — closing
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _label(text: str) -> None:
    """Render an uppercase section label consistent with the rest of the UI."""
    st.markdown(
        f"<div style='font-size:0.68rem;font-weight:700;text-transform:uppercase;"
        f"letter-spacing:0.09em;color:#71717A;margin-bottom:0.5rem;'>{text}</div>",
        unsafe_allow_html=True,
    )


def _relative_time(iso: str) -> str:
    """Return a human-friendly relative timestamp string."""
    try:
        dt  = datetime.fromisoformat(iso)
        now = datetime.now() if dt.tzinfo is None else datetime.now(timezone.utc)
        s   = int((now - dt).total_seconds())
        if s < 60:        return "just now"
        if s < 3600:      return f"{s // 60}m ago"
        if s < 86400:     return f"{s // 3600}h ago"
        if s < 86400 * 7: return f"{s // 86400}d ago"
        return dt.strftime("%d %b %Y")
    except (ValueError, TypeError):
        return iso


def _status_badge_html(status: str) -> str:
    """Return an HTML span for the project status badge."""
    palette = {
        "Draft":       ("#F59E0B", "#F59E0B18", "#F59E0B40"),
        "In Progress": ("#1DB954", "#1DB95418", "#1DB95440"),
        "Complete":    ("#8B5CF6", "#8B5CF618", "#8B5CF640"),
    }
    tc, bg, br = palette.get(status, ("#71717A", "#71717A18", "#71717A40"))
    return (
        f"<span style='display:inline-flex;align-items:center;gap:0.2rem;"
        f"background:{bg};border:1px solid {br};border-radius:999px;"
        f"padding:0.12rem 0.55rem;font-size:0.7rem;font-weight:600;color:{tc};'>"
        f"● {_html.escape(status)}</span>"
    )


def _meta_chip(label: str, value: str, color: str = "#C4C4C8") -> str:
    """Return an HTML metadata chip (label: value) for the song header strip."""
    return (
        f"<div style='display:inline-flex;flex-direction:column;"
        f"background:#18181B;border:1px solid #2D2D31;border-radius:8px;"
        f"padding:0.4rem 0.75rem;min-width:80px;'>"
        f"<span style='font-size:0.6rem;font-weight:700;text-transform:uppercase;"
        f"letter-spacing:0.08em;color:#A1A1AA;margin-bottom:0.15rem;'>{_html.escape(label)}</span>"
        f"<span style='font-size:0.85rem;font-weight:600;color:{color};'>{_html.escape(value)}</span>"
        f"</div>"
    )


def _event_icon(event_type: str) -> str:
    """Return an emoji icon for a timeline event type."""
    icons = {
        "project_created":         "🎵",
        "ai_generated":            "🤖",
        "section_locked":          "🔒",
        "section_unlocked":        "🔓",
        "section_regenerated":     "🔄",
        "human_edit":              "✍️",
        "section_accepted":        "✓",
        "section_rejected":        "✕",
        "contribution_computed":   "📊",
        "passport_exported":       "🛂",
        "audio_preview_generated": "🔊",
    }
    return icons.get(event_type, "◈")


# ─────────────────────────────────────────────────────────────────────────────
# Generation action
# ─────────────────────────────────────────────────────────────────────────────

def _run_generation(project) -> bool:
    """
    Run song generation for the given project.

    Calls ai_engine.generate_song(), merges the result into project.song,
    adds the Gemini collaborator entry, logs the ai_generated timeline event,
    updates project status and version, and saves atomically.

    Returns True on success, False on failure (error already displayed).
    """
    genre    = project.song.get("genre", "")
    language = getattr(project, "language", "English") or "English"

    with st.spinner("Composing your song with Gemini…"):
        try:
            song_dict = generate_song(vibe=project.vibe, genre=genre, language=language)
        except SongGenerationError as exc:
            st.error(
                f"**Song generation failed.** Gemini returned an invalid response "
                f"after 3 attempts.\n\n**Detail:** {exc}"
            )
            return False
        except FileNotFoundError as exc:
            st.error(
                f"**Prompt template missing.** The generation prompt file could not "
                f"be found.\n\n**Detail:** {exc}"
            )
            return False
        except Exception as exc:
            st.error(
                f"**Unexpected error during generation.**\n\n**Detail:** {exc}"
            )
            return False

    # ── Merge song_dict into project.song, preserving the existing genre ──────
    # genre was set at project creation and is the authoritative value; the
    # engine echoes it back through Gemini but we always use the stored version.
    project.song = {**song_dict, "genre": genre}

    # ── Add Gemini model as a collaborator (idempotent) ───────────────────────
    model_id = song_dict.get("model_used", "gemini-flash-latest")
    already_listed = any(
        c.get("model_id") == model_id
        for c in project.collaborators
    )
    if not already_listed:
        project.collaborators.append({
            "collaborator_id": str(uuid4()),
            "name":            "Google Gemini",
            "role":            "ai_model",
            "model_id":        model_id,
            "contribution_pct": None,   # populated in Phase 4
        })

    # ── Update project state ──────────────────────────────────────────────────
    project.status  = "In Progress"
    project.version += 1

    # ── Log timeline event ────────────────────────────────────────────────────
    append_event(
        project.timeline,
        event_type  = "ai_generated",
        actor       = "AI",
        description = f"Song generated: \"{song_dict.get('title', 'Untitled')}\"",
        metadata    = {
            "model_id":       model_id,
            "prompt_version": "song_starter_v1",
            "section_count":  len(song_dict.get("sections", {})),
            "song_schema_version": song_dict.get("song_schema_version", "1.0"),
        },
    )

    # ── Save atomically ───────────────────────────────────────────────────────
    try:
        save_project(project, check_conflict=True)
    except (OSError, ProjectConflictError) as exc:
        st.error(f"**Song generated but could not be saved.**\n\n**Detail:** {exc}")
        return False

    return True


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — Lock / Unlock action
# ─────────────────────────────────────────────────────────────────────────────

def _toggle_lock(project, section_key: str, lock: bool) -> bool:
    """Set or clear the lock on a single song section.

    Mutates project.song["sections"][section_key] in-place, logs the
    appropriate timeline event, increments project.version, and saves
    atomically.  No Streamlit calls — this is pure state logic.

    Args:
        project:     The loaded Project object.
        section_key: One of the five canonical section keys.
        lock:        True to lock, False to unlock.

    Returns:
        True on success, False if save_project() raised (error already shown).
    """
    sections = project.song.get("sections", {})
    section  = sections.get(section_key)
    if section is None:
        st.error(f"Section '{section_key}' not found in song.")
        return False

    if lock:
        section["locked"]    = True
        section["locked_at"] = datetime.now().isoformat()
        section["locked_by"] = "Human"
        event_type  = "section_locked"
        description = f"Section locked: {section_key}"
    else:
        section["locked"]    = False
        section["locked_at"] = None
        section["locked_by"] = None
        event_type  = "section_unlocked"
        description = f"Section unlocked: {section_key}"

    project.version += 1
    append_event(
        project.timeline,
        event_type  = event_type,
        actor       = "Human",
        description = description,
        metadata    = {"section_key": section_key},
    )

    try:
        save_project(project, check_conflict=True)
    except (OSError, ProjectConflictError) as exc:
        st.error(f"**Could not save lock state.**\n\n**Detail:** {exc}")
        return False

    return True


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4 — Human edit action
# ─────────────────────────────────────────────────────────────────────────────

def _save_human_edit(project, section_key: str, new_lyrics: str) -> bool:
    """Persist a human-authored lyrics change for one section.

    Mutates project.song["sections"][section_key] in-place:
      - lyrics         → new_lyrics (stripped)
      - provenance     → "ai_then_human" if previously AI-touched, else "human_written"
      - last_edited_by → "Human"
      - edit_count     → incremented by 1

    Appends a "human_edit" timeline event, increments project.version, and
    saves atomically.  No Streamlit calls — pure state logic.

    Args:
        project:     The loaded Project object.
        section_key: One of the five canonical section keys.
        new_lyrics:  The edited lyrics string (must be non-empty after strip).

    Returns:
        True on success, False if validation fails or save_project() raises.
    """
    clean = new_lyrics.strip()
    if not clean:
        st.error("Lyrics cannot be empty. Please enter some text before saving.")
        return False

    sections = project.song.get("sections", {})
    section  = sections.get(section_key)
    if section is None:
        st.error(f"Section '{section_key}' not found in song.")
        return False

    if section.get("locked"):
        st.error("Cannot edit a locked section. Unlock it first.")
        return False

    prev_provenance = section.get("provenance", "ai_generated")
    chars_before    = len(section.get("lyrics", ""))

    # Provenance transition
    if prev_provenance in ("ai_generated", "ai_then_human"):
        new_provenance = "ai_then_human"
    else:
        # already "human_written" or any unexpected value — keep human ownership
        new_provenance = "human_written"

    section["lyrics"]         = clean
    section["provenance"]     = new_provenance
    section["last_edited_by"] = "Human"
    section["edit_count"]     = section.get("edit_count", 0) + 1

    project.version += 1
    append_event(
        project.timeline,
        event_type  = "human_edit",
        actor       = "Human",
        description = f"Section edited by human: {section_key}",
        metadata    = {
            "section_key":      section_key,
            "prev_provenance":  prev_provenance,
            "new_provenance":   new_provenance,
            "chars_before":     chars_before,
            "chars_after":      len(clean),
        },
    )

    try:
        save_project(project, check_conflict=True)
    except (OSError, ProjectConflictError) as exc:
        st.error(f"**Edit saved in memory but could not be written to disk.**\n\n**Detail:** {exc}")
        return False

    return True


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — Targeted section regeneration action
# ─────────────────────────────────────────────────────────────────────────────

def _run_section_regeneration(project, section_key: str) -> bool:
    """Regenerate a single unlocked section and merge the result.

    Workflow:
      1. Snapshot locked-section lyrics hashes (pre-call).
      2. Call ai_engine.regenerate_section() — returns new lyrics string.
      3. Graft new lyrics into project.song (only target section changed).
      4. Run post-graft drift check — abort + don't save if any locked
         section's content changed.
      5. Log section_regenerated timeline event.
      6. Save atomically.

    Args:
        project:     The loaded Project object.
        section_key: The section to regenerate (must be unlocked).

    Returns:
        True on success, False on any failure (error already shown).
    """
    sections = project.song.get("sections", {})
    section  = sections.get(section_key)
    if section is None:
        st.error(f"Section '{section_key}' not found in song.")
        return False

    if section.get("locked"):
        st.error("Cannot regenerate a locked section. Unlock it first.")
        return False

    # ── Step 1: snapshot locked sections before any API call ─────────────────
    pre_snapshot = snapshot_locked_sections(project.song)

    # ── Step 2: call the targeted regeneration engine ────────────────────────
    language = getattr(project, "language", "English") or "English"
    with st.spinner(f"Regenerating {section_key.replace('_', ' ').title()} with Gemini…"):
        try:
            new_lyrics = regenerate_section(
                section_key = section_key,
                song        = project.song,
                language    = language,
            )
        except SongGenerationError as exc:
            st.error(
                f"**Section regeneration failed.** Gemini returned an invalid "
                f"response after 3 attempts.\n\n**Detail:** {exc}"
            )
            return False
        except FileNotFoundError as exc:
            st.error(
                f"**Prompt template missing.**\n\n**Detail:** {exc}"
            )
            return False
        except Exception as exc:
            st.error(
                f"**Unexpected error during regeneration.**\n\n**Detail:** {exc}"
            )
            return False

    # ── Step 3: graft new lyrics into the target section only ─────────────────
    # All other sections are untouched at this point.
    section["lyrics"]         = new_lyrics
    section["provenance"]     = "ai_generated"
    section["last_edited_by"] = "AI"
    section["edit_count"]     = 0
    # locked / locked_at / locked_by remain as-is (section was unlocked)

    # ── Step 4: post-graft drift check ────────────────────────────────────────
    # If Gemini somehow changed a locked section's content the graft is already
    # applied in memory — but we have NOT saved yet.  Detect drift and abort.
    try:
        assert_locked_sections_unchanged(project.song, pre_snapshot)
    except DriftError as exc:
        st.error(
            f"**Drift detected — regeneration aborted.**\n\n"
            f"A locked section's content changed unexpectedly. "
            f"No changes have been saved.\n\n**Detail:** {exc}"
        )
        # In-memory state is now inconsistent with disk.  Force a reload by
        # returning False — the caller will st.rerun() which reloads from disk.
        return False

    # ── Step 5: log timeline event ────────────────────────────────────────────
    model_id = project.song.get("model_used", "gemini-flash-latest")
    project.version += 1
    append_event(
        project.timeline,
        event_type  = "section_regenerated",
        actor       = "AI",
        description = f"Section regenerated: {section_key}",
        metadata    = {
            "section_key":    section_key,
            "model_id":       model_id,
            "prompt_version": "section_regen_v1",
        },
    )

    # ── Step 6: save atomically ───────────────────────────────────────────────
    try:
        save_project(project, check_conflict=True)
    except (OSError, ProjectConflictError) as exc:
        st.error(
            f"**Section regenerated but could not be saved.**\n\n**Detail:** {exc}"
        )
        return False

    return True


# ─────────────────────────────────────────────────────────────────────────────
# Song rendering helpers
# ─────────────────────────────────────────────────────────────────────────────

def _render_song_header(song: dict, language: str = "English") -> None:
    """Render the song title, metadata chips, and lyrical themes."""
    title  = song.get("title",          "Untitled")
    mood   = song.get("mood",           "—")
    tempo  = song.get("tempo",          "—")
    key    = song.get("key",            "—")
    sig    = song.get("time_signature", "—")
    style  = song.get("style",          "—")
    themes = song.get("lyrical_themes", [])
    model  = song.get("model_used",     "")
    ts     = song.get("generation_timestamp", "")
    schema = song.get("song_schema_version", "")

    # Title
    st.markdown(
        f"<h2 style='margin:0 0 0.85rem;font-size:1.65rem;font-weight:800;"
        f"color:#FAFAFA;letter-spacing:-0.03em;'>🎵 {_html.escape(title)}</h2>",
        unsafe_allow_html=True,
    )

    # Metadata chips row — always in English; language chip shown separately
    chips = (
        _meta_chip("Mood",      mood,  "#C4C4C8") +
        _meta_chip("Tempo",     tempo, "#C4C4C8") +
        _meta_chip("Key",       key,   "#A78BFA") +
        _meta_chip("Time",      sig,   "#C4C4C8") +
        _meta_chip("Style",     style, "#C4C4C8")
    )
    # Language chip — only shown when it differs from English to avoid clutter
    if language and language != "English":
        chips += _meta_chip("Language", language, "#22D3EE")
    st.markdown(
        f"<div style='display:flex;flex-wrap:wrap;gap:0.5rem;"
        f"margin-bottom:0.9rem;'>{chips}</div>",
        unsafe_allow_html=True,
    )

    # Lyrical themes
    if themes:
        pills = "".join(
            f"<span style='display:inline-flex;background:#8B5CF618;"
            f"border:1px solid #8B5CF630;border-radius:999px;"
            f"padding:0.15rem 0.6rem;font-size:0.72rem;color:#A78BFA;"
            f"margin-right:0.3rem;margin-bottom:0.3rem;'>"
            f"{_html.escape(str(t))}</span>"
            for t in themes
        )
        st.markdown(
            f"<div style='margin-bottom:0.85rem;'>"
            f"<span style='font-size:0.65rem;font-weight:700;text-transform:uppercase;"
            f"letter-spacing:0.08em;color:#A1A1AA;margin-right:0.5rem;'>Themes</span>"
            f"{pills}</div>",
            unsafe_allow_html=True,
        )

    # Generation provenance line
    if model or ts or schema:
        parts = []
        if model:
            parts.append(f"Generated by {_html.escape(model)}")
        if ts:
            parts.append(_relative_time(ts))
        if schema:
            parts.append(f"song schema v{_html.escape(schema)}")
        st.markdown(
            f"<div style='font-size:0.72rem;color:#71717A;margin-bottom:1.1rem;'>"
            f"{' · '.join(parts)}</div>",
            unsafe_allow_html=True,
        )


def _render_section_card(key: str, label: str, section: dict, project) -> None:
    """Render one interactive section card with lock toggle, Edit, and Regenerate.

    Header and lyrics are emitted as ONE continuous HTML card (same width,
    joined corners), with every action button in a single row below it.  When
    the user clicks "✏️", the card switches to an inline edit mode that
    shows a st.text_area pre-filled with the lyrics and Save / Cancel buttons.

    Locked sections:
      - Amber left border + 🔒 badge
      - Action row is just "🔓 Unlock" (cannot modify while locked)

    Unlocked sections (view mode) — one action row:
      - AI-touched:    Edit / Regenerate / Accept / Reject / Lock
      - human_written: Edit / Regenerate / Lock (nothing to accept/reject)

    Unlocked sections (edit mode):
      - st.text_area pre-filled with current lyrics
      - "💾 Save Edit" and "✕ Cancel" buttons (no lock while editing)
      - Saving calls _save_human_edit() then exits edit mode

    Session-state keys:
      - f"editing_{key}"  — bool: whether this section is in edit mode
      - f"edit_draft_{key}" — not used (text_area manages its own state via key)

    Args:
        key:     Section key (e.g. "verse_1").
        label:   Human-readable label (e.g. "Verse 1").
        section: The section dict from project.song["sections"].
        project: The full Project object — needed by all action callbacks.
    """
    lyrics     = section.get("lyrics", "")
    provenance = section.get("provenance", "ai_generated")
    is_locked  = bool(section.get("locked"))

    # Ensure per-section edit-mode flag exists in session state.
    edit_key = f"editing_{key}"
    if edit_key not in st.session_state:
        st.session_state[edit_key] = False
    is_editing = st.session_state[edit_key]

    # Locked sections get an amber left border; unlocked keep their accent colour.
    accent = "#F59E0B" if is_locked else _SECTION_COLORS.get(key, "#52525B")

    prov_label = {
        "ai_generated":   "AI Generated",
        "human_written":  "Human Written",
        "ai_then_human":  "AI + Human Edit",
    }.get(provenance, provenance)

    # Build the lock badge shown in the card header.
    lock_badge = (
        "<span style='font-size:0.65rem;font-weight:700;color:#F59E0B;"
        "background:#F59E0B18;border:1px solid #F59E0B40;border-radius:999px;"
        "padding:0.1rem 0.5rem;margin-left:0.4rem;'>🔒 Locked</span>"
        if is_locked else ""
    )

    # ── Card header — full-width strip, rendered joined to the body below ────
    # Header and body are emitted in ONE st.markdown call so they form a
    # single continuous card: same width, no column gap between them.
    header_html = (
        f"<div style='background:#18181B;border:1px solid #2D2D31;"
        f"border-left:3px solid {accent};border-radius:9px 9px 0 0;"
        f"padding:0.75rem 1.1rem 0.5rem;'>"
        f"<div style='display:flex;justify-content:space-between;"
        f"align-items:center;'>"
        f"<span style='font-size:0.72rem;font-weight:700;text-transform:uppercase;"
        f"letter-spacing:0.09em;color:{accent};'>"
        f"{_html.escape(label)}{lock_badge}</span>"
        f"<span style='font-size:0.65rem;font-weight:600;color:#A1A1AA;"
        f"background:#2D2D3160;border-radius:999px;padding:0.1rem 0.5rem;'>"
        f"{_html.escape(prov_label)}</span>"
        f"</div></div>"
    )

    # ── Body: edit mode or view mode ─────────────────────────────────────────
    if is_editing and not is_locked:
        # ── Edit mode: text_area + Save / Cancel ──────────────────────────────
        st.markdown(
            header_html +
            f"<div style='background:#18181B;border:1px solid #2D2D31;"
            f"border-top:none;"
            f"padding:0.6rem 1.1rem 0.3rem;margin-bottom:0;'>"
            f"<div style='font-size:0.72rem;color:#A1A1AA;margin-bottom:0.35rem;'>"
            f"Editing <strong style='color:#FAFAFA;'>{_html.escape(label)}</strong> "
            f"— make your changes below, then click Save.</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        draft = st.text_area(
            label       = f"Lyrics — {label}",
            value       = lyrics,
            height      = max(120, min(500, lyrics.count("\n") * 22 + 120)),
            key         = f"edit_draft_{key}",
            label_visibility = "collapsed",
        )
        save_col, cancel_col, _ = st.columns([2, 2, 3])
        with save_col:
            if st.button("💾 Save Edit", key=f"edit_save_{key}",
                         type="primary", use_container_width=True):
                success = _save_human_edit(project, key, draft)
                if success:
                    st.session_state[edit_key] = False
                    st.rerun()
        with cancel_col:
            if st.button("✕ Cancel", key=f"edit_cancel_{key}",
                         use_container_width=True):
                st.session_state[edit_key] = False
                st.rerun()

    else:
        # ── View mode: header + lyrics as one continuous card ─────────────────
        lyrics_html = _html.escape(lyrics).replace("\n", "<br>")
        st.markdown(
            header_html +
            f"<div style='background:#18181B;border:1px solid #2D2D31;"
            f"border-top:none;border-radius:0 0 9px 9px;"
            f"padding:0.6rem 1.1rem 0.9rem;margin-bottom:0.1rem;'>"
            f"<div style='font-size:0.9375rem;color:#C8C8CC;line-height:1.75;"
            f"white-space:pre-wrap;'>{lyrics_html}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # ── Action row: every control in one line ─────────────────────────────
        # Locked      → just Unlock.
        # human_written → Edit / Regenerate / Lock (nothing to accept/reject).
        # AI-touched  → Edit / Regenerate / Accept / Reject / Lock.
        if is_locked:
            cols = st.columns(4)
            with cols[0]:
                if st.button("🔓", key=f"lock_{key}",
                             help="Unlock this section",
                             use_container_width=True):
                    st.session_state[edit_key] = False
                    if _toggle_lock(project, key, lock=False):
                        st.rerun()
        else:
            show_accept_reject = provenance in ("ai_generated", "ai_then_human")
            cols = st.columns(5) if show_accept_reject else st.columns(3)

            with cols[0]:
                if st.button(
                    "✏️",
                    key=f"edit_{key}",
                    help="Manually edit the lyrics",
                    use_container_width=True,
                ):
                    st.session_state[edit_key] = True
                    st.rerun()
            with cols[1]:
                if st.button(
                    "↻",
                    key=f"regen_{key}",
                    help="Rewrite this section",
                    use_container_width=True,
                ):
                    success = _run_section_regeneration(project, key)
                    if success:
                        st.rerun()

            if show_accept_reject:
                with cols[2]:
                    if st.button(
                        "✓",
                        key=f"accept_{key}",
                        help="Approve this draft",
                        use_container_width=True,
                    ):
                        # Idempotency guard: if this section's most recent
                        # event is already an acceptance, repeat clicks are a
                        # no-op. Without this, mashing Accept could trivially
                        # inflate the direction_score in the Passport, since
                        # it counts raw event frequency (utils/contribution.py).
                        last_for_section = next(
                            (e for e in reversed(project.timeline)
                             if e.get("metadata", {}).get("section_key") == key),
                            None,
                        )
                        if last_for_section and last_for_section.get("event_type") == "section_accepted":
                            st.toast("Already accepted — no change needed.", icon="✅")
                        else:
                            project.version += 1
                            append_event(
                                project.timeline,
                                event_type  = "section_accepted",
                                actor       = "Human",
                                description = f"Section accepted: {key}",
                                metadata    = {"section_key": key},
                            )
                            try:
                                save_project(project, check_conflict=True)
                            except (OSError, ProjectConflictError) as exc:
                                st.error(f"**Could not save after accept.**\n\n{exc}")
                            else:
                                st.rerun()
                with cols[3]:
                    if st.button(
                        "✕",
                        key=f"reject_{key}",
                        help="Reject and regenerate",
                        use_container_width=True,
                    ):
                        project.version += 1
                        append_event(
                            project.timeline,
                            event_type  = "section_rejected",
                            actor       = "Human",
                            description = f"Section rejected: {key}",
                            metadata    = {"section_key": key},
                        )
                        # Save the rejection first — the human's decision must
                        # survive even if the regeneration call below fails.
                        try:
                            save_project(project, check_conflict=True)
                        except (OSError, ProjectConflictError) as exc:
                            st.error(f"**Could not save rejection.**\n\n{exc}")
                        # Rejection immediately triggers regeneration.
                        success = _run_section_regeneration(project, key)
                        if success:
                            st.rerun()

            with cols[4] if show_accept_reject else cols[2]:
                if st.button("🔒", key=f"lock_{key}",
                             help="Freeze this section",
                             use_container_width=True):
                    st.session_state[edit_key] = False
                    if _toggle_lock(project, key, lock=True):
                        st.rerun()

    # Bottom margin spacer
    st.markdown("<div style='margin-bottom:0.65rem;'></div>",
                unsafe_allow_html=True)


def _render_timeline(timeline: list) -> None:
    """Render the vertical creative timeline."""
    if not timeline:
        st.markdown(
            "<div style='background:#18181B;border:1px solid #2D2D31;"
            "border-radius:9px;padding:1.75rem 1rem;text-align:center;'>"
            "<div style='font-size:0.875rem;color:#A1A1AA;'>No events yet.</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    tl = (
        "<div style='position:relative;padding-left:1.6rem;"
        "padding-bottom:0.25rem;'>"
        "<div style='position:absolute;left:0.46rem;top:0.7rem;bottom:0;"
        "width:2px;background:linear-gradient(to bottom,#2D2D31,#2D2D3100);"
        "border-radius:1px;'></div>"
    )
    for event in timeline:
        actor       = str(event.get("actor", ""))
        etype       = _html.escape(str(event.get("event_type", "")))
        description = _html.escape(str(event.get("description", "")))
        timestamp   = str(event.get("timestamp", ""))
        seq         = event.get("seq", "?")
        icon        = _event_icon(str(event.get("event_type", "")))
        rel         = _relative_time(timestamp)
        abs_ts      = _html.escape(timestamp)

        if actor == "Human":
            # Electric lime — human creative decisions.
            dot_col, actor_c, actor_bg, actor_br = "#A3E635", "#A3E635", "#A3E63518", "#A3E63540"
        elif actor == "AI":
            # Electric cyan — AI-generated actions.
            dot_col, actor_c, actor_bg, actor_br = "#22D3EE", "#22D3EE", "#22D3EE18", "#22D3EE40"
        else:
            dot_col, actor_c, actor_bg, actor_br = "#52525B", "#71717A", "#52525B18", "#52525B40"

        tl += (
            f"<div style='position:relative;margin-bottom:1rem;'>"
            f"<div style='position:absolute;left:-1.22rem;top:0.85rem;"
            f"width:11px;height:11px;border-radius:50%;"
            f"background:{dot_col};border:2px solid #0F0F11;"
            f"box-shadow:0 0 8px {dot_col}99,0 0 0 2px {dot_col}30;'></div>"
            f"<div style='background:#18181B;border:1px solid #2D2D31;"
            f"border-radius:9px;padding:0.8rem 1rem;'>"
            f"<div style='display:flex;justify-content:space-between;"
            f"align-items:center;flex-wrap:wrap;gap:0.3rem;margin-bottom:0.35rem;'>"
            f"<div style='display:flex;align-items:center;gap:0.45rem;'>"
            f"<span style='font-size:0.95rem;'>{icon}</span>"
            f"<span style='font-size:0.82rem;font-weight:600;color:#FAFAFA;'>"
            f"#{seq} · {etype}</span>"
            f"<span style='display:inline-flex;background:{actor_bg};"
            f"border:1px solid {actor_br};border-radius:999px;"
            f"padding:0.08rem 0.45rem;font-size:0.67rem;font-weight:600;"
            f"color:{actor_c};'>{_html.escape(actor)}</span>"
            f"</div>"
            f"<span style='font-size:0.68rem;color:#A1A1AA;' "
            f"title='{abs_ts}'>{rel}</span>"
            f"</div>"
            f"<div style='font-size:0.875rem;color:#C4C4C8;"
            f"line-height:1.55;'>{description}</div>"
            f"</div></div>"
        )
    tl += "</div>"
    st.markdown(tl, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Contribution Dashboard
# ─────────────────────────────────────────────────────────────────────────────

def _render_contribution_dashboard(project) -> None:
    """Render the Contribution Dashboard card and cache the result on first compute.

    Called from render() inside the right column, below the Creative Timeline.
    If the project has no sections yet, shows a placeholder instead.

    Staleness: recomputes whenever project.contribution is empty or its
    computed_at is older than the last timeline event's timestamp.
    """
    has_song = bool(project.song.get("sections"))

    _label("◎ Contribution")

    if not has_song:
        st.markdown(
            "<div style='background:#18181B;border:1px solid #2D2D31;"
            "border-radius:9px;padding:1.1rem 1rem;text-align:center;"
            "margin-bottom:1rem;'>"
            "<div style='font-size:0.8rem;color:#A1A1AA;'>Generate a song first.</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    # ── Staleness check ───────────────────────────────────────────────────────
    # Compare against the last *creative* event — ignoring contribution_computed
    # and passport_exported, which are derived/export events, not creative actions.
    # Without this, a contribution_computed event would always make the cache look
    # fresh and prevent any future recompute after a real action.
    _DERIVED_EVENTS = {"contribution_computed", "passport_exported"}
    creative_events = [
        e for e in project.timeline
        if e.get("event_type") not in _DERIVED_EVENTS
    ]
    cached      = project.contribution or {}
    computed_at = cached.get("computed_at", "")
    last_ts     = creative_events[-1]["timestamp"] if creative_events else ""
    is_stale    = (not computed_at) or (last_ts and computed_at < last_ts)

    if is_stale:
        result = compute_contribution(project)
        project.contribution = result
        # Set contribution_pct on any AI collaborator entries.
        for collab in project.collaborators:
            if collab.get("role") == "ai_model":
                collab["contribution_pct"] = result["ai_pct"]
        project.version += 1
        append_event(
            project.timeline,
            event_type  = "contribution_computed",
            actor       = "AI",
            description = "Contribution split computed",
            metadata    = {
                "human_pct":       result["human_pct"],
                "ai_pct":          result["ai_pct"],
                "direction_score": result["direction_score"],
                "methodology_version": result["methodology_version"],
            },
        )
        try:
            save_project(project, check_conflict=True)
        except (OSError, ProjectConflictError) as exc:
            st.warning(f"Could not cache contribution data: {exc}")
        cached = result

    human_pct       = cached.get("human_pct",       0.0)
    ai_pct          = cached.get("ai_pct",           0.0)
    direction_score = cached.get("direction_score",  0.0)

    # ── Render ────────────────────────────────────────────────────────────────
    # Two-segment authorship bar.
    human_w = max(human_pct, 0)
    ai_w    = max(ai_pct,    0)

    bar_html = (
        "<div style='display:flex;height:8px;border-radius:4px;overflow:hidden;"
        "margin:0.5rem 0 0.85rem;'>"
        f"<div style='flex:{human_w};background:#1DB954;'></div>"
        f"<div style='flex:{ai_w};background:#8B5CF6;'></div>"
        "</div>"
    )

    st.markdown(
        f"<div style='background:#18181B;border:1px solid #2D2D31;"
        f"border-left:3px solid #3B82F6;border-radius:9px;"
        f"padding:0.9rem 1.05rem;margin-bottom:0.5rem;'>"
        f"<div style='display:flex;justify-content:space-between;"
        f"margin-bottom:0.15rem;'>"
        f"<span style='font-size:0.78rem;color:#1DB954;font-weight:600;'>"
        f"Human {human_pct}%</span>"
        f"<span style='font-size:0.78rem;color:#8B5CF6;font-weight:600;'>"
        f"AI {ai_pct}%</span>"
        f"</div>"
        f"{bar_html}"
        f"<div style='font-size:0.75rem;color:#A1A1AA;margin-top:0.3rem;'>"
        f"Direction score <span style='color:#FAFAFA;font-weight:600;'>"
        f"{direction_score}%</span> &nbsp;·&nbsp; "
        f"<span style='font-size:0.68rem;'>How much you steered the AI</span>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    # Non-legal disclaimer — visible in the dashboard alongside the numbers.
    st.markdown(
        "<div style='font-size:0.68rem;color:#71717A;line-height:1.5;"
        "margin-bottom:1rem;font-style:italic;'>"
        "Contribution percentages are a transparent accounting model based on "
        "recorded creative actions. They are not a legal determination of "
        "copyright ownership."
        "</div>",
        unsafe_allow_html=True,
    )

    # ── Export Passport button ────────────────────────────────────────────────
    if st.button(
        "🛂  Export Passport",
        key="export_passport",
        help="Download a Creative Passport PDF with the full timeline and contribution data",
        use_container_width=True,
        disabled=not has_song,
    ):
        # Stamp the watermark and export timestamp into project.passport BEFORE
        # building the PDF — build_passport_pdf() reads these fields to print
        # them on the page, so they must be present at build time.
        #
        # compute_record_hash() is called AFTER stamping watermark_id and
        # exported_at so the hash covers those stable export-identity values.
        watermark = str(uuid4())
        project.passport.update({
            "exported_at":    datetime.now().isoformat(),
            "export_format":  "pdf",
            "watermark_id":   watermark,
            # Never overwrite human-approved wording.
            "transparency_statement": project.passport.get("transparency_statement", ""),
            "authorship_line":        project.passport.get("authorship_line", ""),
        })
        # Compute the integrity hash now that all passport identity fields are
        # stamped.  The hash covers project_id, version, language, song
        # provenance, timeline, contribution accounting, watermark_id, and
        # exported_at — everything that makes this Passport instance unique and
        # auditable.  See utils/passport.canonical_record() for the exact spec.
        project.passport["record_hash"] = compute_record_hash(project)

        try:
            pdf_bytes = build_passport_pdf(project)
        except Exception as exc:
            st.error(f"**Passport generation failed.**\n\n{exc}")
        else:
            project.version += 1
            append_event(
                project.timeline,
                event_type  = "passport_exported",
                actor       = "Human",
                description = "Creative Passport exported as PDF",
                metadata    = {
                    "export_format": "pdf",
                    "watermark_id":  watermark,
                },
            )
            try:
                save_project(project, check_conflict=True)
            except (OSError, ProjectConflictError) as exc:
                st.warning(f"Passport built but could not save metadata: {exc}")

            file_name = f"{project.name.replace(' ', '_')}_passport.pdf"
            st.download_button(
                label     = "⬇ Download Creative Passport",
                data      = pdf_bytes,
                file_name = file_name,
                mime      = "application/pdf",
                key       = "download_passport",
                use_container_width=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 5 — Audio Preview
# ─────────────────────────────────────────────────────────────────────────────

def _available_audio_sections(song) -> list[tuple[str, str]]:
    """Return an ordered list of (section_key, label) for sections that have
    non-empty lyrics, in canonical display order.

    Sections with empty or missing lyrics are excluded — there is nothing
    meaningful to speak.  The list respects _SECTION_ORDER so the selector
    always presents sections in the same sequence as the song cards above.

    None-safe: any falsy, non-dict, or structurally invalid song value
    returns an empty list rather than raising.  This keeps callers simple
    and makes the function safe against un-generated or corrupted projects.

    Args:
        song: The project.song dict (should have a "sections" key).
              Accepts None, empty dict, or any non-dict without raising.

    Returns:
        A list of (key, label) tuples.  Empty list when no section has lyrics
        or when song/sections data is absent or malformed.
    """
    # Guard: reject None, non-dict, or any falsy value immediately.
    if not song or not isinstance(song, dict):
        return []
    sections = song.get("sections", {})
    # Guard: sections must be a dict (not a string, list, None, etc.).
    if not isinstance(sections, dict):
        return []
    result: list[tuple[str, str]] = []
    for key, label in _SECTION_ORDER:
        sec = sections.get(key)
        if not isinstance(sec, dict):
            continue
        lyrics = sec.get("lyrics", "")
        if lyrics and isinstance(lyrics, str) and lyrics.strip():
            result.append((key, label))
    return result


def _render_audio_preview(project) -> None:
    """Render the Audio Preview card at the bottom of the left column.

    The user selects any available song section via a radio control; the
    default is Chorus when present, otherwise the first available section.
    Generated MP3 bytes are cached in session state keyed by both project_id
    and section_key — switching section or project invalidates the cache
    immediately, so the player never shows stale audio.

    Stale-audio guard: if the session state holds bytes from a different
    project or a different section, they are silently cleared before rendering.

    Args:
        project: The loaded Project object. Must already have a generated
                 song (caller checks has_song before calling this function).
    """
    # ── Build the ordered list of previewable sections ─────────────────────
    available = _available_audio_sections(project.song)

    # ── Section header ─────────────────────────────────────────────────────
    st.markdown(
        "<hr style='margin:0.75rem 0 0.5rem;border-color:#2D2D31;'>",
        unsafe_allow_html=True,
    )
    _label("🔊 Audio Preview")

    # ── No sections guard ──────────────────────────────────────────────────
    if not available:
        st.warning(
            "No section lyrics are available for audio preview. "
            "Generate a song first, or ensure at least one section is not empty."
        )
        return

    # ── Section selector ───────────────────────────────────────────────────
    # Default: chorus if available, else the first section in canonical order.
    avail_keys   = [k for k, _ in available]
    avail_labels = [lbl for _, lbl in available]
    default_idx  = avail_keys.index("chorus") if "chorus" in avail_keys else 0

    # st.radio rendered horizontally — all labels on one line, compact.
    # The widget key is stable so Streamlit keeps the selected value across
    # re-renders; the default_idx only applies on the very first render.
    selected_label = st.radio(
        "Select section",
        options     = avail_labels,
        index       = default_idx,
        horizontal  = True,
        key         = "vp_audio_section_radio",
        label_visibility = "collapsed",
    )
    selected_key = avail_keys[avail_labels.index(selected_label)]

    # ── Stale-audio guard ──────────────────────────────────────────────────
    # Clear cached bytes when project or selected section has changed.
    cached_pid = st.session_state.get("vp_audio_project_id")
    cached_sec = st.session_state.get("vp_audio_section")
    if cached_pid != project.project_id or cached_sec != selected_key:
        st.session_state["vp_audio_bytes"]      = None
        st.session_state["vp_audio_project_id"] = project.project_id
        st.session_state["vp_audio_section"]    = selected_key

    # ── Extract the chosen section's lyrics ────────────────────────────────
    section_lyrics = (
        project.song
        .get("sections", {})
        .get(selected_key, {})
        .get("lyrics", "")
        .strip()
    )

    # ── Section accent colour (matches section card colours above) ─────────
    accent = _SECTION_COLORS.get(selected_key, "#52525B")

    # ── Player or Generate button ──────────────────────────────────────────
    audio_bytes = st.session_state.get("vp_audio_bytes")

    if audio_bytes is not None:
        # ── Playback mode: player + Download + Clear ───────────────────────
        st.markdown(
            f"<div style='background:#18181B;border:1px solid #2D2D31;"
            f"border-left:3px solid {accent};border-radius:9px;"
            f"padding:0.75rem 1.05rem 0.5rem;margin-bottom:0.5rem;'>"
            f"<div style='font-size:0.72rem;color:#A1A1AA;margin-bottom:0.4rem;'>"
            f"Spoken preview of <strong style='color:#FAFAFA;'>"
            f"{_html.escape(selected_label)}</strong> — generated by gTTS.</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.audio(audio_bytes, format="audio/mp3")

        # Download filename: "{project_name}_{section_label}.mp3"
        # Spaces replaced with underscores; non-ASCII kept as-is (browsers handle it).
        _safe_name = project.name.replace(" ", "_")
        _safe_section = selected_label.replace(" ", "_")
        _dl_filename = f"{_safe_name}_{_safe_section}_preview.mp3"

        dl_col, clear_col = st.columns(2)
        with dl_col:
            st.download_button(
                label     = "⬇  Download Audio (.mp3)",
                data      = audio_bytes,
                file_name = _dl_filename,
                mime      = "audio/mpeg",
                key       = "vp_audio_download",
                use_container_width=True,
            )
        with clear_col:
            if st.button(
                "✕  Clear Preview",
                key="vp_audio_clear",
                use_container_width=True,
            ):
                st.session_state["vp_audio_bytes"] = None
                st.rerun()

    else:
        # ── Generate mode: description card + button ───────────────────────
        st.markdown(
            f"<div style='background:#18181B;border:1px solid #2D2D31;"
            f"border-radius:9px;padding:0.75rem 1.05rem;margin-bottom:0.6rem;'>"
            f"<div style='font-size:0.82rem;color:#C4C4C8;line-height:1.6;'>"
            f"Generate a spoken preview of <strong style='color:#FAFAFA;'>"
            f"{_html.escape(selected_label)}</strong> using Google Text-to-Speech.</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        if st.button(
            f"🔊  Preview {selected_label}",
            key="vp_audio_preview",
            type="primary",
            use_container_width=True,
        ):
            with st.spinner(f"Generating {selected_label} audio preview…"):
                try:
                    mp3_bytes = generate_audio_preview(
                        section_lyrics,
                        lang=gtts_lang_code(getattr(project, "language", "") or "English"),
                    )
                except AudioGenerationError as exc:
                    st.error(
                        f"**Audio preview failed.**\n\n"
                        f"gTTS could not generate speech for **{selected_label}**. "
                        f"Check your internet connection and try again.\n\n"
                        f"**Detail:** {exc}"
                    )
                    return
                except Exception as exc:
                    st.error(
                        f"**Unexpected error during audio generation.**\n\n"
                        f"**Detail:** {exc}"
                    )
                    return

            # ── Store bytes in session state ───────────────────────────────
            st.session_state["vp_audio_bytes"]      = mp3_bytes
            st.session_state["vp_audio_project_id"] = project.project_id
            st.session_state["vp_audio_section"]    = selected_key

            # ── Log timeline event ─────────────────────────────────────────
            project.version += 1
            append_event(
                project.timeline,
                event_type  = "audio_preview_generated",
                actor       = "Human",
                description = f"{selected_label} audio preview generated via gTTS",
                metadata    = {
                    "section_key":  selected_key,
                    "section_label": selected_label,
                    "tts_provider": "gTTS",
                    "lang":         "en",
                    "char_count":   len(section_lyrics),
                },
            )

            # ── Save timeline event ────────────────────────────────────────
            try:
                save_project(project, check_conflict=True)
            except (OSError, ProjectConflictError) as exc:
                # Audio is already in session state and will play — a save
                # failure here is non-fatal; just warn the user.
                st.warning(
                    f"Audio generated but the timeline event could not be "
                    f"saved: {exc}"
                )

            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Main render
# ─────────────────────────────────────────────────────────────────────────────

def render() -> None:
    """Render the project workspace page."""

    # ── Guard: session state ──────────────────────────────────────────────────
    if "active_project_id" not in st.session_state:
        st.session_state.active_project_id = None

    project_id = st.session_state.active_project_id
    if not project_id:
        st.warning("No project selected. Please open a project from the library.")
        if st.button("← Back to Library"):
            st.session_state.page = "Open Project"
            st.rerun()
        return

    # ── Load project ──────────────────────────────────────────────────────────
    try:
        project = load_project(project_id)
    except ProjectNotFoundError:
        st.error("Project not found — it may have been deleted.")
        st.session_state.active_project_id = None
        st.session_state.page = "Open Project"
        st.rerun()
        return
    except ProjectCorruptedError as exc:
        st.error(f"**Project file is corrupted.**\n\nDetail: {exc}")
        return
    except OSError as exc:
        st.error(f"**Could not read project.**\n\nDetail: {exc}")
        return

    # ── Header ────────────────────────────────────────────────────────────────
    genre    = project.song.get("genre", "")
    language = getattr(project, "language", "English") or "English"
    badge_html = _status_badge_html(project.status)
    genre_html = (
        f"<span style='display:inline-flex;align-items:center;gap:0.2rem;"
        f"background:#8B5CF618;border:1px solid #8B5CF630;border-radius:999px;"
        f"padding:0.12rem 0.55rem;font-size:0.72rem;color:#A78BFA;"
        f"margin-left:0.35rem;'>♪ {_html.escape(genre)}</span>"
    ) if genre else ""
    lang_html = (
        f"<span style='display:inline-flex;align-items:center;gap:0.2rem;"
        f"background:#22D3EE18;border:1px solid #22D3EE30;border-radius:999px;"
        f"padding:0.12rem 0.55rem;font-size:0.72rem;color:#22D3EE;"
        f"margin-left:0.35rem;'>🌐 {_html.escape(language)}</span>"
    ) if language and language != "English" else ""

    st.markdown(
        f"<div style='margin-bottom:0.6rem;'>"
        f"<div style='display:flex;align-items:center;gap:0.65rem;"
        f"flex-wrap:wrap;margin-bottom:0.25rem;'>"
        f"<h1 style='margin:0;'>{_html.escape(project.name)}</h1>"
        f"{badge_html}{genre_html}{lang_html}"
        f"</div>"
        f"<div style='font-size:0.78rem;color:#A1A1AA;'>"
        f"v{project.version} · "
        f"Last modified {_relative_time(project.last_modified_at)}"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    # ── Navigation ────────────────────────────────────────────────────────────
    if st.button("← Project Library", key="vp_back"):
        st.session_state.page = "Open Project"
        st.rerun()

    st.markdown("<hr style='margin:0.75rem 0 1.1rem;border-color:#2D2D31;'>",
                unsafe_allow_html=True)

    # ── Two-column layout: LEFT 62% song workspace | RIGHT 38% meta panel ────
    left, right = st.columns([62, 38], gap="large")

    # ═══════════════════════════════════════
    # RIGHT — Song Vibe + Timeline
    # ═══════════════════════════════════════
    with right:

        # Song Vibe card
        _label("✦ Song Vibe")
        st.markdown(
            f"<div style='background:#18181B;border:1px solid #2D2D31;"
            f"border-left:3px solid #1DB954;border-radius:9px;"
            f"padding:0.9rem 1.05rem;margin-bottom:1.1rem;"
            f"font-size:0.9125rem;color:#C4C4C8;line-height:1.7;'>"
            f"{_html.escape(project.vibe)}"
            f"</div>",
            unsafe_allow_html=True,
        )

        # Creative Timeline
        _label("◷ Creative Timeline")
        _render_timeline(project.timeline)

        # Contribution Dashboard
        _render_contribution_dashboard(project)

    # ═══════════════════════════════════════
    # LEFT — Generation or Song Display
    # ═══════════════════════════════════════
    with left:

        has_song = bool(project.song.get("sections"))

        if not has_song:
            # ── Pre-generation state ──────────────────────────────────────────
            lang_display = getattr(project, "language", "English") or "English"
            st.markdown(
                f"<div style='background:#18181B;border:1px solid #2D2D31;"
                f"border-left:3px solid #3B82F6;border-radius:9px;"
                f"padding:1.4rem 1.2rem;margin-bottom:1.2rem;'>"
                f"<div style='font-size:1rem;font-weight:700;color:#FAFAFA;"
                f"margin-bottom:0.4rem;'>Ready to generate</div>"
                f"<div style='font-size:0.875rem;color:#A1A1AA;line-height:1.6;'>"
                f"Google Gemini will compose a complete original song in "
                f"<strong style='color:#22D3EE;'>{_html.escape(lang_display)}</strong>"
                f" — title, lyrics for all five sections, mood, tempo, key, and style — "
                f"based on your vibe. Generation takes a few seconds."
                f"</div></div>",
                unsafe_allow_html=True,
            )

            if st.button(
                "🎵  Generate Song",
                key="vp_generate",
                type="primary",
                use_container_width=True,
            ):
                success = _run_generation(project)
                if success:
                    st.rerun()

        else:
            # ── Song display ──────────────────────────────────────────────────
            _label("🎵 Generated Song")
            _render_song_header(project.song, language=language)

            st.markdown(
                "<hr style='margin:0.5rem 0 1rem;border-color:#2D2D31;'>",
                unsafe_allow_html=True,
            )

            # Render each section card in canonical order.
            # Pass `project` so the lock/regen buttons can act on it directly.
            for section_key, section_label in _SECTION_ORDER:
                section = project.song.get("sections", {}).get(section_key)
                if section:
                    _render_section_card(section_key, section_label, section, project)

            # ── Phase 5: Audio Preview (below last section card) ──────────────
            _render_audio_preview(project)
