import streamlit as st

import views.create_project as create_project_page
import views.open_project as open_project_page
import views.view_project as view_project_page

# ─────────────────────────────────────────────────────────────────────────────
# Page configuration  (must be the very first Streamlit call)
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="HarmonyLedger",
    page_icon="🎵",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Session-state bootstrap  — set ALL keys before any widget renders so that
# a hot-reload or first load never leaves a key undefined, which is the root
# cause of the occasional blank page on navigation.
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULTS = {
    "page":              "Create Project",
    "active_project_id": None,
    # create_project page state
    "cp_vibe_text":      "",
    "cp_preset_genre":   "",
    "cp_error":          "",
    # open_project page state
    "op_search":         "",
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ─────────────────────────────────────────────────────────────────────────────
# Global CSS
# One consolidated <style> block.  Covers:
#   • White-strip removal (header / toolbar / deploy button / padding)
#   • Full dark theme
#   • Typography scale
#   • Input, button, metric, alert, expander, scrollbar, divider overrides
#   • Sidebar polish
#   • Hover animations on cards / buttons
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* ═══════════════════════════════════════════════════════
   1. KILL THE WHITE STRIP / STREAMLIT CHROME
   ═══════════════════════════════════════════════════════ */
/* Top toolbar & deploy badge */
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
header[data-testid="stHeader"],
#MainMenu,
footer {
    display: none !important;
    visibility: hidden !important;
    height: 0 !important;
}
/* Remove the default top padding that the hidden header leaves */
.block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 2rem !important;
    padding-left: 2.25rem !important;
    padding-right: 2.25rem !important;
    max-width: 1180px;
}
/* The outermost app wrapper background */
html, body,
[data-testid="stApp"],
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    background-color: #0F0F11 !important;
    color: #D4D4D8;
}

/* ═══════════════════════════════════════════════════════
   2. SIDEBAR
   ═══════════════════════════════════════════════════════ */
[data-testid="stSidebar"] {
    background-color: #111113 !important;
    border-right: 1px solid #2D2D31 !important;
    min-width: 230px !important;
    max-width: 260px !important;
}
[data-testid="stSidebar"] > div:first-child {
    padding-top: 0 !important;
}
/* Keep sidebar scrollable without showing a scrollbar */
[data-testid="stSidebarContent"] {
    padding: 0 !important;
    overflow-y: auto;
    scrollbar-width: none;
}
[data-testid="stSidebarContent"]::-webkit-scrollbar { display: none; }

/* ═══════════════════════════════════════════════════════
   3. TYPOGRAPHY
   ═══════════════════════════════════════════════════════ */
html { font-size: 15px; }
h1, h2, h3, h4 { color: #FAFAFA !important; letter-spacing: -0.02em; }
h1 { font-size: 1.55rem !important; font-weight: 700 !important; line-height: 1.25 !important; }
h2 { font-size: 1.1rem  !important; font-weight: 600 !important; }
h3 { font-size: 0.975rem !important; font-weight: 600 !important; }
p, li { color: #C8C8CC; font-size: 0.9375rem; line-height: 1.65; }
.stMarkdown p { color: #C8C8CC; }

/* ═══════════════════════════════════════════════════════
   4. INPUTS & TEXTAREAS
   ═══════════════════════════════════════════════════════ */
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea {
    background-color: #1A1A1E !important;
    border: 1px solid #3A3A3F !important;
    border-radius: 7px !important;
    color: #E4E4E8 !important;
    font-size: 0.9375rem !important;
    transition: border-color 0.15s, box-shadow 0.15s;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {
    border-color: #1DB954 !important;
    box-shadow: 0 0 0 3px rgba(29,185,84,0.14) !important;
    outline: none !important;
}
[data-testid="stTextInput"] label,
[data-testid="stTextArea"] label,
[data-testid="stSelectbox"] label {
    color: #A1A1AA !important;
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.07em;
}

/* ═══════════════════════════════════════════════════════
   5. BUTTONS
   ═══════════════════════════════════════════════════════ */
[data-testid="stButton"] > button {
    border-radius: 7px !important;
    font-weight: 500 !important;
    font-size: 0.875rem !important;
    transition: all 0.15s ease !important;
    border: 1px solid #3A3A3F !important;
    background: #222226 !important;
    color: #C4C4C8 !important;
    padding: 0.4rem 0.9rem !important;
}
[data-testid="stButton"] > button:hover {
    background: #2E2E34 !important;
    border-color: #52525B !important;
    color: #FAFAFA !important;
    transform: translateY(-1px);
    box-shadow: 0 2px 8px rgba(0,0,0,0.35) !important;
}
[data-testid="stButton"] > button:active {
    transform: translateY(0) !important;
}
[data-testid="stButton"] > button[kind="primary"] {
    background: #1DB954 !important;
    border-color: #1DB954 !important;
    color: #0A0A0B !important;
    font-weight: 600 !important;
}
[data-testid="stButton"] > button[kind="primary"]:hover {
    background: #1fcc5e !important;
    border-color: #1fcc5e !important;
    box-shadow: 0 2px 12px rgba(29,185,84,0.35) !important;
}
/* Form submit button */
[data-testid="stFormSubmitButton"] > button {
    border-radius: 7px !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    background: #1DB954 !important;
    border-color: #1DB954 !important;
    color: #0A0A0B !important;
    transition: all 0.15s ease !important;
    padding: 0.5rem 1.2rem !important;
}
[data-testid="stFormSubmitButton"] > button:hover {
    background: #1fcc5e !important;
    box-shadow: 0 2px 12px rgba(29,185,84,0.35) !important;
    transform: translateY(-1px);
}

/* ═══════════════════════════════════════════════════════
   6. METRIC CARDS
   ═══════════════════════════════════════════════════════ */
[data-testid="stMetric"] {
    background: #18181B !important;
    border: 1px solid #2D2D31 !important;
    border-radius: 9px !important;
    padding: 0.85rem 1rem !important;
    transition: border-color 0.15s;
}
[data-testid="stMetric"]:hover {
    border-color: #3F3F46 !important;
}
[data-testid="stMetricLabel"] p {
    font-size: 0.72rem !important;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: #A1A1AA !important;
    font-weight: 600 !important;
}
[data-testid="stMetricValue"] {
    font-size: 1.2rem !important;
    font-weight: 700 !important;
    color: #FAFAFA !important;
}

/* ═══════════════════════════════════════════════════════
   7. ALERTS / FEEDBACK BANNERS
   ═══════════════════════════════════════════════════════ */
[data-testid="stAlert"] {
    border-radius: 8px !important;
    border-left-width: 3px !important;
    font-size: 0.875rem !important;
    background: #18181B !important;
}

/* ═══════════════════════════════════════════════════════
   8. EXPANDERS
   ═══════════════════════════════════════════════════════ */
[data-testid="stExpander"] {
    background: #18181B !important;
    border: 1px solid #2D2D31 !important;
    border-radius: 8px !important;
}
[data-testid="stExpander"] summary {
    color: #C4C4C8 !important;
    font-size: 0.875rem !important;
    font-weight: 500 !important;
}
[data-testid="stExpander"] summary:hover {
    color: #FAFAFA !important;
}

/* ═══════════════════════════════════════════════════════
   9. DIVIDERS
   ═══════════════════════════════════════════════════════ */
hr { border-color: #2D2D31 !important; margin: 1rem 0 !important; }

/* ═══════════════════════════════════════════════════════
   10. CAPTIONS
   ═══════════════════════════════════════════════════════ */
small, .stCaption, [data-testid="stCaptionContainer"] p {
    color: #A1A1AA !important;
    font-size: 0.75rem !important;
}

/* ═══════════════════════════════════════════════════════
   11. CODE
   ═══════════════════════════════════════════════════════ */
[data-testid="stCode"] {
    background: #111113 !important;
    border: 1px solid #2D2D31 !important;
    border-radius: 6px !important;
}

/* ═══════════════════════════════════════════════════════
   12. SCROLLBAR
   ═══════════════════════════════════════════════════════ */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #3A3A3F; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #52525B; }

/* ═══════════════════════════════════════════════════════
   13. TOAST
   ═══════════════════════════════════════════════════════ */
[data-testid="stToast"] {
    background: #18181B !important;
    border: 1px solid #2D2D31 !important;
    border-radius: 8px !important;
    color: #E4E4E8 !important;
}

/* ═══════════════════════════════════════════════════════
   14. SELECTBOX
   ═══════════════════════════════════════════════════════ */
[data-testid="stSelectbox"] > div > div {
    background-color: #1A1A1E !important;
    border: 1px solid #3A3A3F !important;
    border-radius: 7px !important;
    color: #E4E4E8 !important;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────

# Pull active project summary lazily (only reads the light list_projects cache)
_active_name    = None
_active_status  = None
_active_version = None
if st.session_state.active_project_id:
    try:
        from utils.storage import list_projects as _lp
        _all_projects, _ = _lp()
        for _p in _all_projects:
            if _p["project_id"] == st.session_state.active_project_id:
                _active_name   = _p.get("name", "Unknown")
                _active_status = _p.get("status", "Draft")
                break
    except Exception:
        pass

with st.sidebar:

    # ── Brand wordmark ────────────────────────────────
    st.markdown("""
    <div style="padding:1.25rem 1.1rem 0.85rem;border-bottom:1px solid #2D2D31;">
        <div style="display:flex;align-items:center;gap:0.55rem;margin-bottom:0.3rem;">
            <span style="font-size:1.3rem;line-height:1;">🎵</span>
            <span style="font-size:1.0rem;font-weight:700;color:#FAFAFA;
                         letter-spacing:-0.02em;line-height:1.2;">HarmonyLedger</span>
        </div>
        <div style="font-size:0.7rem;color:#71717A;padding-left:1.85rem;
                        line-height:1.3;">Creative Passport for Human-AI Songwriting</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Nav section ───────────────────────────────────
    st.markdown("""
    <div style="padding:0.85rem 1.1rem 0.35rem;">
        <span style="font-size:0.65rem;font-weight:700;text-transform:uppercase;
                     letter-spacing:0.1em;color:#71717A;">Workspace</span>
    </div>
    """, unsafe_allow_html=True)

    # New Project button
    _create_active = st.session_state.page == "Create Project"
    if st.button(
        "＋  New Project",
        key="nav_create",
        use_container_width=True,
        type="primary" if _create_active else "secondary",
    ):
        st.session_state.page = "Create Project"
        st.rerun()

    # Project Library button
    _open_active = st.session_state.page == "Open Project"
    if st.button(
        "📂  Project Library",
        key="nav_open",
        use_container_width=True,
        type="primary" if _open_active else "secondary",
    ):
        # Clear active_project_id so the library renders as a plain list —
        # no card is pre-highlighted and no automatic navigation fires.
        st.session_state.active_project_id = None
        st.session_state.page = "Open Project"
        st.rerun()

    # ── Active project card ───────────────────────────
    if _active_name:
        _status_colors = {
            "Draft":       ("#F59E0B", "#F59E0B18"),
            "In Progress": ("#1DB954", "#1DB95418"),
            "Complete":    ("#8B5CF6", "#8B5CF618"),
        }
        _sc, _sbg = _status_colors.get(_active_status, ("#71717A", "#71717A18"))

        st.markdown(f"""
        <div style="margin:0.85rem 1.1rem 0;background:#18181B;
                    border:1px solid #2D2D31;border-radius:8px;
                    padding:0.7rem 0.85rem;">
            <div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;
                        letter-spacing:0.1em;color:#71717A;margin-bottom:0.4rem;">
                Active Project
            </div>
            <div style="font-size:0.875rem;font-weight:600;color:#FAFAFA;
                        white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
                        margin-bottom:0.35rem;" title="{_active_name}">
                🎵 {_active_name}
            </div>
            <span style="display:inline-flex;align-items:center;
                         background:{_sbg};border:1px solid {_sc}40;
                         border-radius:999px;padding:0.1rem 0.55rem;
                         font-size:0.68rem;font-weight:600;color:{_sc};">
                ● {_active_status}
            </span>
        </div>
        """, unsafe_allow_html=True)

    # ── Coming-soon ───────────────────────────────────
    st.markdown("<div style='height:0.5rem;'></div>", unsafe_allow_html=True)
    st.markdown("""
    <div style="padding:0.25rem 1.1rem 0.25rem;">
        <span style="font-size:0.65rem;font-weight:700;text-transform:uppercase;
                     letter-spacing:0.1em;color:#71717A;">Coming in Phase 3+</span>
    </div>
    """, unsafe_allow_html=True)

    for _label in [
        "🔒  Section Locking",
        "🔄  Targeted Regen",
        "📊  Contributions",
        "🛂  Creative Passport",
        "🔊  Audio Preview",
    ]:
        st.markdown(
            f"<div style='font-size:0.8rem;color:#71717A;padding:0.2rem 1.1rem;'>"
            f"{_label}</div>",
            unsafe_allow_html=True,
        )

    # ── Build progress ────────────────────────────────
    st.markdown("""
    <div style="margin:0.75rem 1.1rem 0;padding-top:0.75rem;border-top:1px solid #2D2D31;">
        <span style="font-size:0.65rem;font-weight:700;text-transform:uppercase;
                     letter-spacing:0.1em;color:#71717A;">Build Progress</span>
    </div>
    """, unsafe_allow_html=True)

    _phases    = ["Storage", "AI Engine", "Section Lock", "Passport", "Audio", "Launch"]
    _completed = 2  # Phase 2 done
    for _i, _phase in enumerate(_phases):
        _done   = _i < _completed
        _cur    = _i == _completed
        _col    = "#1DB954" if _done else ("#F59E0B" if _cur else "#3A3A3F")
        _lcol   = "#D4D4D8" if (_done or _cur) else "#71717A"
        _check  = "✓" if _done else ("→" if _cur else "·")
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:0.5rem;"
            f"padding:0.18rem 1.1rem;'>"
            f"<div style='width:7px;height:7px;border-radius:50%;"
            f"background:{_col};flex-shrink:0;'></div>"
            f"<span style='font-size:0.77rem;color:{_lcol};'>"
            f"P{_i+1} {_check} {_phase}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # ── Version footer ────────────────────────────────
    st.markdown("""
    <div style="margin-top:auto;padding:1.25rem 1.1rem 1rem;
                border-top:1px solid #2D2D31;margin-top:1rem;">
        <div style="font-size:0.68rem;color:#71717A;">Phase 2 · v0.2.0</div>
        <div style="font-size:0.68rem;color:#71717A;">Powered by Google Gemini</div>
    </div>
    """, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Page header  — branding strip shown on every page
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<div style="margin-bottom:0.1rem;">
    <div style="font-size:2.1rem;font-weight:800;color:#FAFAFA;
                letter-spacing:-0.04em;line-height:1.15;">🎵 HarmonyLedger</div>
    <div style="font-size:0.9rem;color:#8E8E96;font-weight:400;
                margin-top:0.3rem;letter-spacing:0.01em;">
        The Creative Passport for Human-AI Songwriting
    </div>
</div>
<hr style="margin:0.75rem 0 1.35rem;border-color:#2D2D31;">
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Router  — guard ensures page is always a known value before delegating
# ─────────────────────────────────────────────────────────────────────────────

_VALID_PAGES = {"Create Project", "Open Project", "View Project"}
if st.session_state.page not in _VALID_PAGES:
    st.session_state.page = "Create Project"

if st.session_state.page == "Create Project":
    create_project_page.render()
elif st.session_state.page == "Open Project":
    open_project_page.render()
elif st.session_state.page == "View Project":
    view_project_page.render()
