import html as _html
import streamlit as st
from datetime import datetime, timezone

from utils.storage import (
    load_project,
    list_projects,
    ProjectNotFoundError,
    ProjectCorruptedError,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _label(text: str) -> None:
    st.markdown(
        f"<div style='font-size:0.68rem;font-weight:700;text-transform:uppercase;"
        f"letter-spacing:0.09em;color:#71717A;margin-bottom:0.5rem;'>{text}</div>",
        unsafe_allow_html=True,
    )


def _relative_time(iso: str) -> str:
    """Return a human-friendly relative timestamp."""
    try:
        dt  = datetime.fromisoformat(iso)
        now = datetime.now() if dt.tzinfo is None else datetime.now(timezone.utc)
        s   = int((now - dt).total_seconds())
        if s < 60:        return "just now"
        if s < 3600:      m = s // 60;  return f"{m}m ago"
        if s < 86400:     h = s // 3600; return f"{h}h ago"
        if s < 86400 * 7: d = s // 86400; return f"{d}d ago"
        return dt.strftime("%d %b %Y")
    except (ValueError, TypeError):
        return iso


def _status_badge_html(status: str) -> str:
    palette = {
        "Draft":       ("#F59E0B", "#F59E0B18", "#F59E0B40"),
        "In Progress": ("#1DB954", "#1DB95418", "#1DB95440"),
        "Complete":    ("#8B5CF6", "#8B5CF618", "#8B5CF640"),
    }
    tc, bg, br = palette.get(status, ("#71717A", "#71717A18", "#71717A40"))
    esc = _html.escape(status)
    return (
        f"<span style='display:inline-flex;align-items:center;gap:0.2rem;"
        f"background:{bg};border:1px solid {br};border-radius:999px;"
        f"padding:0.12rem 0.55rem;font-size:0.7rem;font-weight:600;color:{tc};'>"
        f"● {esc}</span>"
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
# Project card
# ─────────────────────────────────────────────────────────────────────────────

def _project_card(p: dict, is_active: bool) -> bool:
    """Render one project card. Returns True if the Open button was clicked."""
    name    = _html.escape(p.get("name",    "Untitled"))
    status  = p.get("status", "Draft")
    genre   = _html.escape(p.get("genre",   ""))      # populated after preset selection
    events  = p.get("event_count", 0)
    mod     = _relative_time(p.get("last_modified_at", ""))

    border_col  = "#1DB954"   if is_active else "#2D2D31"
    bg_col      = "#141E17"   if is_active else "#141417"
    border_l    = "3px solid #1DB954" if is_active else "1px solid #2D2D31"
    badge_html  = _status_badge_html(status)

    genre_row = (
        f"<div style='display:inline-flex;align-items:center;gap:0.25rem;"
        f"background:#8B5CF618;border:1px solid #8B5CF630;border-radius:999px;"
        f"padding:0.1rem 0.5rem;font-size:0.68rem;color:#A78BFA;margin-right:0.4rem;'>"
        f"♪ {genre}</div>"
    ) if genre else ""

    events_row = (
        f"<div style='display:inline-flex;align-items:center;gap:0.25rem;"
        f"font-size:0.68rem;color:#52525B;'>"
        f"◷ {events} event{'s' if events != 1 else ''}</div>"
    )

    st.markdown(
        f"<div style='background:{bg_col};"
        f"border:1px solid {border_col};border-left:{border_l};"
        f"border-radius:9px;padding:0.85rem 1rem 0.65rem;"
        f"transition:border-color 0.15s;margin-bottom:0.1rem;'>"
        # title row
        f"<div style='display:flex;justify-content:space-between;"
        f"align-items:flex-start;gap:0.5rem;margin-bottom:0.35rem;'>"
        f"<div style='font-size:0.9rem;font-weight:600;color:#FAFAFA;"
        f"white-space:nowrap;overflow:hidden;text-overflow:ellipsis;' "
        f"title='{name}'>{name}</div>"
        f"{badge_html}</div>"
        # meta row
        f"<div style='display:flex;align-items:center;flex-wrap:wrap;gap:0.3rem;"
        f"margin-bottom:0.45rem;'>{genre_row}{events_row}</div>"
        # modified
        f"<div style='font-size:0.7rem;color:#52525B;'>Modified {mod}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    clicked = st.button(
        "✓ Loaded" if is_active else "Open →",
        key=f"open_{p['project_id']}",
        use_container_width=True,
        type="primary" if is_active else "secondary",
    )
    return clicked


# ─────────────────────────────────────────────────────────────────────────────
# Main render
# ─────────────────────────────────────────────────────────────────────────────

def render() -> None:
    """Render the Project Library page."""

    # ── Guard: ensure all session-state keys exist (blank-page fix) ──────────
    for _k, _v in [("op_search", ""), ("active_project_id", None)]:
        if _k not in st.session_state:
            st.session_state[_k] = _v

    # ── Page heading ──────────────────────────────────────────────────────────
    st.markdown(
        "<div style='margin-bottom:1.2rem;'>"
        "<h1 style='margin:0 0 0.2rem;'>Project Library</h1>"
        "<p style='color:#71717A;font-size:0.875rem;margin:0;'>"
        "All your songwriting projects. Select a card to open the dashboard.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    # ── Load + enrich project list ────────────────────────────────────────────
    raw_projects, problems = list_projects()

    # Enrich each summary dict with song.genre and timeline event count
    # by peeking at the JSON lightweight fields already in the list_projects result.
    # We need the full load only for enrichment; we re-use load_project later
    # anyway for the detail view, so this is the only extra read.
    enriched: list[dict] = []
    for p in raw_projects:
        ep = dict(p)
        ep["genre"]       = ""
        ep["event_count"] = 0
        try:
            import json, pathlib
            from utils.storage import PROJECTS_DIR
            fp = PROJECTS_DIR / f"{p['project_id']}.json"
            if fp.exists():
                with open(fp, encoding="utf-8") as fh:
                    raw = json.load(fh)
                ep["genre"]       = raw.get("song", {}).get("genre", "")
                ep["event_count"] = len(raw.get("timeline", []))
                ep["status"]      = raw.get("status", "Draft")
        except Exception:
            pass
        enriched.append(ep)

    # ── Corrupt file warning ──────────────────────────────────────────────────
    if problems:
        with st.expander(f"⚠️ {len(problems)} file(s) could not be loaded", expanded=False):
            for prob in problems:
                st.warning(f"**{prob['file_name']}** — {prob['reason']}")

    # ── Empty state ───────────────────────────────────────────────────────────
    if not enriched:
        st.markdown(
            "<div style='text-align:center;padding:3.5rem 1rem;'>"
            "<div style='font-size:2.75rem;margin-bottom:0.75rem;'>📭</div>"
            "<div style='font-size:1rem;font-weight:600;color:#71717A;"
            "margin-bottom:0.3rem;'>No projects yet</div>"
            "<div style='font-size:0.8125rem;color:#52525B;'>"
            "Create your first project from <em>New Project</em>.</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        st.button("＋  New Project", type="primary", on_click=lambda: (
            setattr(st.session_state, "page", "Create Project")
        ))
        return

    # ── Search / filter bar ───────────────────────────────────────────────────
    search = st.text_input(
        "Search projects",
        value=st.session_state.op_search,
        placeholder="Filter by name…",
        label_visibility="collapsed",
        key="op_search_input",
    )
    st.session_state.op_search = search

    filtered = (
        [p for p in enriched if search.lower() in p.get("name", "").lower()]
        if search else enriched
    )

    if not filtered:
        st.markdown(
            "<div style='padding:1.5rem;text-align:center;"
            "font-size:0.875rem;color:#52525B;'>No projects match your search.</div>",
            unsafe_allow_html=True,
        )
        return

    # ── Resolve active project id ─────────────────────────────────────────────
    active_id  = st.session_state.active_project_id
    valid_ids  = {p["project_id"] for p in enriched}

    if active_id not in valid_ids:
        # Came from Create Project with a new ID that is valid
        if active_id in {p["project_id"] for p in enriched}:
            pass  # keep it
        else:
            active_id = enriched[0]["project_id"] if enriched else None
        st.session_state.active_project_id = active_id

    # ── Project card grid (3 per row) ─────────────────────────────────────────
    st.markdown("<div style='height:0.2rem;'></div>", unsafe_allow_html=True)

    cols_n = 3
    for row_start in range(0, len(filtered), cols_n):
        row  = filtered[row_start: row_start + cols_n]
        cols = st.columns(cols_n, gap="medium")
        for col, proj in zip(cols, row):
            with col:
                if _project_card(proj, proj["project_id"] == active_id):
                    st.session_state.active_project_id = proj["project_id"]
                    st.rerun()

    # ── Divider before detail ─────────────────────────────────────────────────
    if not active_id:
        return

    st.markdown("<hr style='margin:1.4rem 0 1.1rem;border-color:#2D2D31;'>", unsafe_allow_html=True)

    # ── Load full project ─────────────────────────────────────────────────────
    try:
        project = load_project(active_id)
    except ProjectNotFoundError:
        st.error("Project file not found — it may have been deleted. Select another project.")
        st.session_state.active_project_id = None
        return
    except ProjectCorruptedError as exc:
        st.error(f"Project file is corrupted.\n\nDetail: {exc}")
        return
    except OSError as exc:
        st.error(f"Could not read project: {exc}")
        return

    created  = datetime.fromisoformat(project.created_at)
    modified = datetime.fromisoformat(project.last_modified_at)

    # ─────────────────────────────────────────────────────────────────────────
    # DETAIL VIEW
    # Layout:  hero header · [LEFT 60% vibe+timeline | RIGHT 40% dashboard]
    # ─────────────────────────────────────────────────────────────────────────

    # ── Hero header ───────────────────────────────────────────────────────────
    badge_html = _status_badge_html(project.status)
    genre_html = ""
    if project.song.get("genre"):
        g = _html.escape(project.song["genre"])
        genre_html = (
            f"<span style='display:inline-flex;align-items:center;gap:0.2rem;"
            f"background:#8B5CF618;border:1px solid #8B5CF630;border-radius:999px;"
            f"padding:0.12rem 0.55rem;font-size:0.72rem;color:#A78BFA;"
            f"margin-left:0.35rem;'>♪ {g}</span>"
        )

    st.markdown(
        f"<div style='margin-bottom:1rem;'>"
        f"<div style='display:flex;align-items:center;gap:0.65rem;flex-wrap:wrap;"
        f"margin-bottom:0.3rem;'>"
        f"<h1 style='margin:0;'>{_html.escape(project.name)}</h1>"
        f"{badge_html}{genre_html}"
        f"</div>"
        f"<div style='font-size:0.78rem;color:#52525B;'>"
        f"v{project.version} · Schema v{project.schema_version} · "
        f"Created {created.strftime('%d %b %Y')} · "
        f"Last modified {_relative_time(project.last_modified_at)}"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Back button ───────────────────────────────────────────────────────────
    if st.button("← All Projects", key="back_btn"):
        st.session_state.active_project_id = None
        st.rerun()

    st.markdown("<div style='height:0.6rem;'></div>", unsafe_allow_html=True)

    # ── Two-column detail ─────────────────────────────────────────────────────
    left, right = st.columns([60, 40], gap="large")

    # ════════════════════════════════
    # RIGHT — dashboard panel
    # ════════════════════════════════
    with right:

        # Stats grid
        _label("Project Stats")
        st.markdown(
            "<div style='display:grid;grid-template-columns:1fr 1fr;"
            "gap:0.6rem;margin-bottom:0.75rem;'>",
            unsafe_allow_html=True,
        )
        # 4 metric tiles as HTML (avoids Streamlit metric's inner nesting issues)
        def _tile(label: str, value: str, accent: str = "#1DB954") -> str:
            return (
                f"<div style='background:#18181B;border:1px solid #2D2D31;"
                f"border-radius:9px;padding:0.75rem 0.9rem;"
                f"transition:border-color 0.15s;'>"
                f"<div style='font-size:0.65rem;font-weight:700;text-transform:uppercase;"
                f"letter-spacing:0.08em;color:#52525B;margin-bottom:0.25rem;'>{label}</div>"
                f"<div style='font-size:1.15rem;font-weight:700;color:{accent};'>{value}</div>"
                f"</div>"
            )

        st.markdown(
            _tile("Version",    f"v{project.version}") +
            _tile("Timeline",   f"{len(project.timeline)} event{'s' if len(project.timeline) != 1 else ''}") +
            _tile("Created",    created.strftime("%d %b %Y"),  "#C4C4C8") +
            _tile("Modified",   modified.strftime("%d %b %Y"), "#C4C4C8"),
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

        # Schema / ID card
        st.markdown(
            f"<div style='background:#18181B;border:1px solid #2D2D31;"
            f"border-radius:9px;padding:0.75rem 0.9rem;margin-bottom:0.75rem;'>"
            f"<div style='font-size:0.65rem;font-weight:700;text-transform:uppercase;"
            f"letter-spacing:0.08em;color:#52525B;margin-bottom:0.4rem;'>Schema</div>"
            f"<div style='font-size:0.85rem;color:#C4C4C8;'>v{project.schema_version}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # Project ID expander
        with st.expander("Project ID", expanded=False):
            st.code(project.project_id, language=None)

        # Contribution placeholder (Phase 4)
        st.markdown(
            "<div style='background:#18181B;border:1px solid #2D2D31;"
            "border-left:3px solid #F59E0B;border-radius:9px;"
            "padding:0.75rem 0.9rem;margin-top:0.1rem;'>"
            "<div style='font-size:0.65rem;font-weight:700;text-transform:uppercase;"
            "letter-spacing:0.08em;color:#F59E0B;margin-bottom:0.35rem;'>"
            "Contribution · Phase 4</div>"
            "<div style='display:flex;gap:0.5rem;align-items:center;margin-bottom:0.35rem;'>"
            "<div style='flex:1;height:6px;background:#2D2D31;border-radius:3px;overflow:hidden;'>"
            "<div style='width:0%;height:100%;background:#1DB954;border-radius:3px;'></div></div>"
            "<span style='font-size:0.72rem;color:#52525B;'>Human —</span></div>"
            "<div style='display:flex;gap:0.5rem;align-items:center;'>"
            "<div style='flex:1;height:6px;background:#2D2D31;border-radius:3px;overflow:hidden;'>"
            "<div style='width:0%;height:100%;background:#8B5CF6;border-radius:3px;'></div></div>"
            "<span style='font-size:0.72rem;color:#52525B;'>AI —</span></div>"
            "<div style='font-size:0.72rem;color:#52525B;margin-top:0.45rem;'>"
            "Unlocks when songs are generated.</div>"
            "</div>",
            unsafe_allow_html=True,
        )

    # ════════════════════════════════
    # LEFT — vibe + timeline
    # ════════════════════════════════
    with left:

        # Song Vibe
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

        if not project.timeline:
            st.markdown(
                "<div style='background:#18181B;border:1px solid #2D2D31;"
                "border-radius:9px;padding:2.25rem 1rem;text-align:center;'>"
                "<div style='font-size:1.75rem;margin-bottom:0.55rem;'>📭</div>"
                "<div style='font-size:0.875rem;font-weight:500;color:#71717A;"
                "margin-bottom:0.25rem;'>No timeline events yet</div>"
                "<div style='font-size:0.775rem;color:#52525B;'>"
                "Your songwriting journey will appear here once you start working in Phase 2.</div>"
                "</div>",
                unsafe_allow_html=True,
            )
        else:
            # ── Vertical timeline ─────────────────────────────────────────────
            # Build as one HTML string to avoid per-event widget overhead
            tl = (
                "<div style='position:relative;padding-left:1.6rem;padding-bottom:0.25rem;'>"
                # rail line
                "<div style='position:absolute;left:0.46rem;top:0.7rem;bottom:0;"
                "width:2px;background:linear-gradient(to bottom,#2D2D31,#2D2D3100);"
                "border-radius:1px;'></div>"
            )

            for event in project.timeline:
                actor       = str(event.get("actor", ""))
                etype       = _html.escape(str(event.get("event_type", "")))
                description = _html.escape(str(event.get("description", "")))
                timestamp   = str(event.get("timestamp", ""))
                seq         = event.get("seq", "?")
                icon        = _event_icon(str(event.get("event_type", "")))
                rel         = _relative_time(timestamp)
                abs_ts      = _html.escape(timestamp)

                if actor == "Human":
                    dot_col  = "#1DB954"
                    actor_c  = "#1DB954"
                    actor_bg = "#1DB95418"
                    actor_br = "#1DB95440"
                elif actor == "AI":
                    dot_col  = "#8B5CF6"
                    actor_c  = "#A78BFA"
                    actor_bg = "#8B5CF618"
                    actor_br = "#8B5CF640"
                else:
                    dot_col  = "#52525B"
                    actor_c  = "#71717A"
                    actor_bg = "#52525B18"
                    actor_br = "#52525B40"

                actor_esc = _html.escape(actor)

                tl += (
                    f"<div style='position:relative;margin-bottom:1rem;'>"
                    # dot
                    f"<div style='position:absolute;left:-1.22rem;top:0.85rem;"
                    f"width:11px;height:11px;border-radius:50%;"
                    f"background:{dot_col};border:2px solid #0F0F11;"
                    f"box-shadow:0 0 0 2px {dot_col}30;'></div>"
                    # card
                    f"<div style='background:#18181B;border:1px solid #2D2D31;"
                    f"border-radius:9px;padding:0.8rem 1rem;"
                    f"transition:border-color 0.15s;'>"
                    # header row
                    f"<div style='display:flex;justify-content:space-between;"
                    f"align-items:center;flex-wrap:wrap;gap:0.3rem;margin-bottom:0.35rem;'>"
                    f"<div style='display:flex;align-items:center;gap:0.45rem;'>"
                    f"<span style='font-size:0.95rem;'>{icon}</span>"
                    f"<span style='font-size:0.82rem;font-weight:600;color:#FAFAFA;'>"
                    f"#{seq} · {etype}</span>"
                    f"<span style='display:inline-flex;background:{actor_bg};"
                    f"border:1px solid {actor_br};border-radius:999px;"
                    f"padding:0.08rem 0.45rem;font-size:0.67rem;font-weight:600;"
                    f"color:{actor_c};'>{actor_esc}</span>"
                    f"</div>"
                    # timestamp
                    f"<span style='font-size:0.68rem;color:#52525B;' "
                    f"title='{abs_ts}'>{rel}</span>"
                    f"</div>"
                    # description
                    f"<div style='font-size:0.875rem;color:#C4C4C8;"
                    f"line-height:1.55;'>{description}</div>"
                    f"</div></div>"
                )

            tl += "</div>"
            st.markdown(tl, unsafe_allow_html=True)
