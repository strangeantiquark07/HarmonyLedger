import html as _html
import json
import streamlit as st
from datetime import datetime, timezone

from utils.storage import list_projects, PROJECTS_DIR

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
        f"font-size:0.68rem;color:#A1A1AA;'>"
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
        f"<div style='font-size:0.7rem;color:#A1A1AA;'>Modified {mod}</div>"
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
        "<p style='color:#A1A1AA;font-size:0.875rem;margin:0;'>"
        "All your songwriting projects. Click <em>Open →</em> on any card to open its workspace.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    # ── Load + enrich project list ────────────────────────────────────────────
    raw_projects, problems = list_projects()

    # Enrich each summary dict with song.genre, timeline event count, and status
    # by reading the full JSON file. list_projects() only returns the summary fields.
    enriched: list[dict] = []
    for p in raw_projects:
        ep = dict(p)
        ep["genre"]       = ""
        ep["event_count"] = 0
        try:
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
            "<div style='font-size:1rem;font-weight:600;color:#C4C4C8;"
            "margin-bottom:0.3rem;'>No projects yet</div>"
            "<div style='font-size:0.8125rem;color:#A1A1AA;'>"
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
            "font-size:0.875rem;color:#A1A1AA;'>No projects match your search.</div>",
            unsafe_allow_html=True,
        )
        return

    # ── Project card grid (3 per row) ─────────────────────────────────────────
    # active_project_id is used only to highlight the card that was last opened;
    # it never triggers automatic navigation. The user must click Open → explicitly.
    active_id = st.session_state.active_project_id
    valid_ids = {p["project_id"] for p in enriched}

    # If the stored active id no longer exists (deleted project), clear it so
    # no card appears highlighted and no stale navigation occurs.
    if active_id not in valid_ids:
        active_id = None
        st.session_state.active_project_id = None

    st.markdown("<div style='height:0.2rem;'></div>", unsafe_allow_html=True)

    cols_n = 3
    for row_start in range(0, len(filtered), cols_n):
        row  = filtered[row_start: row_start + cols_n]
        cols = st.columns(cols_n, gap="medium")
        for col, proj in zip(cols, row):
            with col:
                if _project_card(proj, proj["project_id"] == active_id):
                    st.session_state.active_project_id = proj["project_id"]
                    st.session_state.page = "View Project"
                    st.rerun()

    # Each card's Open → button navigates to View Project via st.rerun().
    # No inline detail view is rendered here — that lives in view_project.py.
