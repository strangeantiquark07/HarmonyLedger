"""
pages/view_project.py
─────────────────────
Project workspace — the primary page for Phase 2 and beyond.

Responsibilities:
  - Load and display a project identified by st.session_state.active_project_id.
  - Show the Generate Song button when no song has been generated yet.
  - On generation: call ai_engine.generate_song(), merge the result into
    project.song, log an "ai_generated" timeline event, and save atomically.
  - Render the generated song (title, metadata strip, section cards).
  - Handle all errors gracefully with clear, user-friendly messages.

This page is intentionally thin: all AI logic lives in utils/ai_engine.py
and all persistence lives in utils/storage.py. This page only coordinates
between them and renders the result.

Phase 3 note: the section cards rendered here are the natural location for
locking controls and the Regenerate button. They are built with that
extension in mind (each card is self-contained and keyed by section name).
"""

import html as _html
from datetime import datetime, timezone
from uuid import uuid4

import streamlit as st

from utils.ai_engine import generate_song, SongGenerationError
from utils.storage import load_project, save_project, ProjectNotFoundError, ProjectCorruptedError
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
    icons = {
        "project_created":     "🎵",
        "ai_generated":        "🤖",
        "section_locked":      "🔒",
        "section_regenerated": "🔄",
        "human_edit":          "✍️",
        "contribution_computed": "📊",
        "passport_exported":   "🛂",
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
    genre = project.song.get("genre", "")

    with st.spinner("Composing your song with Gemini…"):
        try:
            song_dict = generate_song(vibe=project.vibe, genre=genre)
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
    model_id = song_dict.get("model_used", "gemini-2.5-flash")
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
        save_project(project)
    except OSError as exc:
        st.error(f"**Song generated but could not be saved.**\n\n**Detail:** {exc}")
        return False

    return True


# ─────────────────────────────────────────────────────────────────────────────
# Song rendering helpers
# ─────────────────────────────────────────────────────────────────────────────

def _render_song_header(song: dict) -> None:
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

    # Metadata chips row
    chips = (
        _meta_chip("Mood",      mood,  "#C4C4C8") +
        _meta_chip("Tempo",     tempo, "#C4C4C8") +
        _meta_chip("Key",       key,   "#A78BFA") +
        _meta_chip("Time",      sig,   "#C4C4C8") +
        _meta_chip("Style",     style, "#C4C4C8")
    )
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


def _render_section_card(key: str, label: str, section: dict) -> None:
    """Render one song section card with lyrics and provenance tag."""
    lyrics    = section.get("lyrics", "")
    provenance = section.get("provenance", "ai_generated")
    accent    = _SECTION_COLORS.get(key, "#52525B")

    prov_label = {
        "ai_generated":   "AI Generated",
        "human_written":  "Human Written",
        "ai_then_human":  "AI + Human Edit",
    }.get(provenance, provenance)

    # Escape and convert newlines → <br> for HTML rendering
    lyrics_html = _html.escape(lyrics).replace("\n", "<br>")

    st.markdown(
        f"<div style='background:#18181B;border:1px solid #2D2D31;"
        f"border-left:3px solid {accent};border-radius:9px;"
        f"padding:1rem 1.1rem 0.9rem;margin-bottom:0.75rem;'>"
        # header row
        f"<div style='display:flex;justify-content:space-between;"
        f"align-items:center;margin-bottom:0.65rem;'>"
        f"<span style='font-size:0.72rem;font-weight:700;text-transform:uppercase;"
        f"letter-spacing:0.09em;color:{accent};'>{_html.escape(label)}</span>"
        f"<span style='font-size:0.65rem;font-weight:600;color:#A1A1AA;"
        f"background:#2D2D3160;border-radius:999px;padding:0.1rem 0.5rem;'>"
        f"{_html.escape(prov_label)}</span>"
        f"</div>"
        # lyrics
        f"<div style='font-size:0.9375rem;color:#C8C8CC;line-height:1.75;"
        f"white-space:pre-wrap;'>{lyrics_html}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


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
            dot_col, actor_c, actor_bg, actor_br = "#1DB954", "#1DB954", "#1DB95418", "#1DB95440"
        elif actor == "AI":
            dot_col, actor_c, actor_bg, actor_br = "#8B5CF6", "#A78BFA", "#8B5CF618", "#8B5CF640"
        else:
            dot_col, actor_c, actor_bg, actor_br = "#52525B", "#71717A", "#52525B18", "#52525B40"

        tl += (
            f"<div style='position:relative;margin-bottom:1rem;'>"
            f"<div style='position:absolute;left:-1.22rem;top:0.85rem;"
            f"width:11px;height:11px;border-radius:50%;"
            f"background:{dot_col};border:2px solid #0F0F11;"
            f"box-shadow:0 0 0 2px {dot_col}30;'></div>"
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
    genre = project.song.get("genre", "")
    badge_html = _status_badge_html(project.status)
    genre_html = (
        f"<span style='display:inline-flex;align-items:center;gap:0.2rem;"
        f"background:#8B5CF618;border:1px solid #8B5CF630;border-radius:999px;"
        f"padding:0.12rem 0.55rem;font-size:0.72rem;color:#A78BFA;"
        f"margin-left:0.35rem;'>♪ {_html.escape(genre)}</span>"
    ) if genre else ""

    st.markdown(
        f"<div style='margin-bottom:0.6rem;'>"
        f"<div style='display:flex;align-items:center;gap:0.65rem;"
        f"flex-wrap:wrap;margin-bottom:0.25rem;'>"
        f"<h1 style='margin:0;'>{_html.escape(project.name)}</h1>"
        f"{badge_html}{genre_html}"
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

    # ═══════════════════════════════════════
    # LEFT — Generation or Song Display
    # ═══════════════════════════════════════
    with left:

        has_song = bool(project.song.get("sections"))

        if not has_song:
            # ── Pre-generation state ──────────────────────────────────────────
            st.markdown(
                "<div style='background:#18181B;border:1px solid #2D2D31;"
                "border-left:3px solid #3B82F6;border-radius:9px;"
                "padding:1.4rem 1.2rem;margin-bottom:1.2rem;'>"
                "<div style='font-size:1rem;font-weight:700;color:#FAFAFA;"
                "margin-bottom:0.4rem;'>Ready to generate</div>"
                "<div style='font-size:0.875rem;color:#A1A1AA;line-height:1.6;'>"
                "Google Gemini will compose a complete original song — title, lyrics for all five "
                "sections, mood, tempo, key, and style — based on your vibe above. "
                "Generation takes a few seconds."
                "</div></div>",
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
            _render_song_header(project.song)

            st.markdown(
                "<hr style='margin:0.5rem 0 1rem;border-color:#2D2D31;'>",
                unsafe_allow_html=True,
            )

            # Render each section card in canonical order
            for section_key, section_label in _SECTION_ORDER:
                section = project.song.get("sections", {}).get(section_key)
                if section:
                    _render_section_card(section_key, section_label, section)

            # ── Regenerate button (placeholder for Phase 3) ───────────────────
            st.markdown(
                "<div style='margin-top:0.5rem;background:#18181B;"
                "border:1px solid #2D2D31;border-left:3px solid #F59E0B;"
                "border-radius:9px;padding:0.75rem 1rem;'>"
                "<div style='font-size:0.65rem;font-weight:700;text-transform:uppercase;"
                "letter-spacing:0.08em;color:#F59E0B;margin-bottom:0.25rem;'>"
                "Phase 3 · Section Locking &amp; Regeneration</div>"
                "<div style='font-size:0.8rem;color:#A1A1AA;'>"
                "Lock sections you love and regenerate only what you want to change.</div>"
                "</div>",
                unsafe_allow_html=True,
            )
