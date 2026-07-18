import streamlit as st

from utils.models import Project, PROJECT_NAME_MAX_LENGTH
from utils.storage import save_project, list_projects
from utils.timeline import append_event
from utils.presets import GENRE_PRESETS, VIBE_MODIFIERS


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _label(text: str) -> None:
    """Render an uppercase section label consistent with the rest of the UI."""
    st.markdown(
        f"<div style='font-size:0.68rem;font-weight:700;text-transform:uppercase;"
        f"letter-spacing:0.09em;color:#71717A;margin-bottom:0.45rem;'>{text}</div>",
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Page render
# ─────────────────────────────────────────────────────────────────────────────

def render() -> None:
    """Render the Create Project page."""

    # ── Guard: ensure all session-state keys exist (blank-page fix) ──────────
    for _k, _v in [
        ("cp_vibe_text",    ""),
        ("cp_preset_genre", ""),
        ("cp_error",        ""),
        ("cp_applied_mods", []),
    ]:
        if _k not in st.session_state:
            st.session_state[_k] = _v

    # ── Page heading ──────────────────────────────────────────────────────────
    st.markdown(
        "<div style='margin-bottom:1.4rem;'>"
        "<h1 style='margin:0 0 0.2rem;'>New Project</h1>"
        "<p style='color:#71717A;font-size:0.875rem;margin:0;'>"
        "Start from a blank canvas, or pick a genre preset to jumpstart your vibe.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    # ── Inline error (above form — never below the fold) ─────────────────────
    if st.session_state.cp_error:
        st.error(st.session_state.cp_error)
        st.session_state.cp_error = ""

    # ─────────────────────────────────────────────────────────────────────────
    # Layout:  LEFT 58% — form      RIGHT 42% — preset panel
    # ─────────────────────────────────────────────────────────────────────────
    left_col, right_col = st.columns([58, 42], gap="large")

    # ═════════════════════════════════════════════════
    # RIGHT COLUMN — preset + modifier panel
    # ═════════════════════════════════════════════════
    with right_col:
        st.markdown(
            "<div style='background:#141417;border:1px solid #2D2D31;"
            "border-radius:10px;padding:1.1rem 1rem 0.9rem;'>",
            unsafe_allow_html=True,
        )

        # ── Genre presets ─────────────────────────────
        _label("🎯 Genre Presets")
        st.markdown(
            "<p style='font-size:0.78rem;color:#71717A;margin:-0.2rem 0 0.7rem;'>"
            "One click fills the vibe field. Edit freely after.</p>",
            unsafe_allow_html=True,
        )

        preset_keys = list(GENRE_PRESETS.keys())
        for i in range(0, len(preset_keys), 2):
            c1, c2 = st.columns(2, gap="small")
            for col, key in zip([c1, c2], preset_keys[i: i + 2]):
                with col:
                    is_sel = st.session_state.cp_preset_genre == GENRE_PRESETS[key]["genre"]
                    if st.button(
                        key,
                        key=f"preset_{key}",
                        use_container_width=True,
                        type="primary" if is_sel else "secondary",
                    ):
                        st.session_state.cp_vibe_text    = GENRE_PRESETS[key]["vibe"]
                        st.session_state.cp_preset_genre = GENRE_PRESETS[key]["genre"]
                        # Preset replaces the vibe text, so any applied
                        # modifier textures are gone — clear their toggles too.
                        st.session_state.cp_applied_mods = []
                        st.rerun()

        # Active preset badge
        if st.session_state.cp_preset_genre:
            st.markdown(
                f"<div style='margin-top:0.55rem;display:inline-flex;align-items:center;"
                f"gap:0.3rem;background:#1DB95418;border:1px solid #1DB95440;"
                f"border-radius:999px;padding:0.18rem 0.65rem;"
                f"font-size:0.72rem;color:#1DB954;font-weight:600;'>"
                f"✓ {st.session_state.cp_preset_genre}</div>",
                unsafe_allow_html=True,
            )

        # ── Vibe modifiers ────────────────────────────
        st.markdown(
            "<hr style='margin:0.75rem 0 0.6rem;border-color:#2D2D31;'>",
            unsafe_allow_html=True,
        )
        _label("✦ Vibe Modifiers")
        st.markdown(
            "<p style='font-size:0.78rem;color:#71717A;margin:-0.2rem 0 0.6rem;'>"
            "Appends a texture to your vibe — doesn't replace it.</p>",
            unsafe_allow_html=True,
        )

        # 2-column modifier grid — applied modifiers show green (primary) and
        # click again to remove their texture from the vibe (toggle).
        mod_keys = VIBE_MODIFIERS
        for i in range(0, len(mod_keys), 2):
            mc1, mc2 = st.columns(2, gap="small")
            for col, mod in zip([mc1, mc2], mod_keys[i: i + 2]):
                with col:
                    is_on = mod["label"] in st.session_state.cp_applied_mods
                    if st.button(
                        mod["label"],
                        key=f"mod_{mod['label']}",
                        type="primary" if is_on else "secondary",
                        use_container_width=True,
                    ):
                        if is_on:
                            st.session_state.cp_applied_mods.remove(mod["label"])
                            st.session_state.cp_vibe_text = (
                                st.session_state.cp_vibe_text
                                .replace(mod["text"], "", 1)
                                .replace("  ", " ").strip()
                            )
                        else:
                            st.session_state.cp_applied_mods.append(mod["label"])
                            cur = st.session_state.cp_vibe_text.rstrip()
                            st.session_state.cp_vibe_text = (
                                cur + (" " if cur else "") + mod["text"]
                            )
                        st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)

        # ── Tips card ─────────────────────────────────
        st.markdown(
            "<div style='background:#141417;border:1px solid #2D2D31;"
            "border-left:3px solid #8B5CF6;border-radius:10px;"
            "padding:0.9rem 1rem;margin-top:0.85rem;'>"
            "<div style='font-size:0.68rem;font-weight:700;text-transform:uppercase;"
            "letter-spacing:0.09em;color:#8B5CF6;margin-bottom:0.45rem;'>✦ AI Generation</div>"
            "<p style='font-size:0.825rem;color:#B0B0B8;margin:0;line-height:1.6;'>"
            "Your vibe will be sent to <strong style='color:#EAEAEE;'>Google Gemini</strong> "
            "to generate a complete original song — verse, chorus, bridge, mood, tempo, and key. "
            "Lock any section you love and regenerate only what you don't.</p>"
            "</div>",
            unsafe_allow_html=True,
        )

    # ═════════════════════════════════════════════════
    # LEFT COLUMN — project form
    # ═════════════════════════════════════════════════
    with left_col:

        with st.form("create_project_form", clear_on_submit=False):

            # ── Project name ──────────────────────────
            _label("Project Name")
            project_name = st.text_input(
                "Project Name",
                max_chars=PROJECT_NAME_MAX_LENGTH,
                placeholder='e.g. "City Rain", "Golden Hour Sessions"',
                label_visibility="collapsed",
            )

            # Character counter
            char_count    = len(project_name)
            counter_color = "#EF4444" if char_count >= PROJECT_NAME_MAX_LENGTH else "#71717A"
            st.markdown(
                f"<div style='text-align:right;font-size:0.7rem;color:{counter_color};"
                f"margin-top:-0.45rem;margin-bottom:0.8rem;'>"
                f"{char_count} / {PROJECT_NAME_MAX_LENGTH}</div>",
                unsafe_allow_html=True,
            )

            # ── Song vibe ─────────────────────────────
            _label("Song Vibe")
            vibe = st.text_area(
                "Song Vibe",
                height=230,
                placeholder=(
                    "Describe the mood, genre, emotions, instruments…\n\n"
                    "Or pick a preset on the right →"
                ),
                value=st.session_state.cp_vibe_text,
                label_visibility="collapsed",
            )

            st.markdown("<div style='height:0.4rem;'></div>", unsafe_allow_html=True)

            # ── Submit ────────────────────────────────
            submitted = st.form_submit_button(
                "Create Project  →",
                type="primary",
                use_container_width=True,
            )

        # ── What happens next card (fills the visual gap below the form) ──────
        st.markdown(
            "<div style='background:#141417;border:1px solid #2D2D31;"
            "border-radius:10px;padding:1rem 1.1rem;margin-top:0.85rem;'>"
            "<div style='font-size:0.68rem;font-weight:700;text-transform:uppercase;"
            "letter-spacing:0.09em;color:#A1A1AA;margin-bottom:0.6rem;'>What happens next</div>"
            "<div style='display:flex;flex-direction:column;gap:0.5rem;'>"

            "<div style='display:flex;gap:0.65rem;align-items:flex-start;'>"
            "<span style='font-size:0.85rem;color:#1DB954;margin-top:0.05rem;'>①</span>"
            "<span style='font-size:0.82rem;color:#C0C0C8;line-height:1.5;'>"
            "Your project is saved as a single JSON file — the foundation for everything.</span></div>"

            "<div style='display:flex;gap:0.65rem;align-items:flex-start;'>"
            "<span style='font-size:0.85rem;color:#1DB954;margin-top:0.05rem;'>②</span>"
            "<span style='font-size:0.82rem;color:#C0C0C8;line-height:1.5;'>"
            "Google Gemini turns your vibe into a full structured song — title, lyrics, mood, and tempo.</span></div>"

            "<div style='display:flex;gap:0.65rem;align-items:flex-start;'>"
            "<span style='font-size:0.85rem;color:#1DB954;margin-top:0.05rem;'>③</span>"
            "<span style='font-size:0.82rem;color:#C0C0C8;line-height:1.5;'>"
            "Lock sections you love, regenerate the one you don't — you stay the author.</span></div>"

            "<div style='display:flex;gap:0.65rem;align-items:flex-start;'>"
            "<span style='font-size:0.85rem;color:#1DB954;margin-top:0.05rem;'>④</span>"
            "<span style='font-size:0.82rem;color:#C0C0C8;line-height:1.5;'>"
            "Export a Creative Passport proving what you wrote vs. what the AI wrote.</span></div>"

            "</div></div>",
            unsafe_allow_html=True,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Form submission logic
    # ─────────────────────────────────────────────────────────────────────────
    if submitted:
        name      = project_name.strip()
        vibe_text = vibe.strip()

        # Sync back so a rerun restores the textarea value
        st.session_state.cp_vibe_text = vibe_text

        if not name:
            st.session_state.cp_error = "Please enter a project name."
            st.rerun()
            return

        if not vibe_text:
            st.session_state.cp_error = "Please describe the song vibe."
            st.rerun()
            return

        # Soft duplicate-name warning (non-blocking)
        existing_projects, _ = list_projects()
        existing_names = [p["name"] for p in existing_projects]
        if name in existing_names:
            st.warning(
                f"A project named **{name}** already exists. "
                "This will be saved as a separate project with a unique ID."
            )

        try:
            project = Project(name=name, vibe=vibe_text)
        except ValueError as exc:
            st.session_state.cp_error = f"Invalid project name: {exc}"
            st.rerun()
            return

        # Persist genre from preset
        if st.session_state.cp_preset_genre:
            project.song["genre"] = st.session_state.cp_preset_genre

        append_event(
            project.timeline,
            event_type="project_created",
            actor="Human",
            description="Project created.",
        )

        try:
            save_project(project)
        except OSError as exc:
            st.session_state.cp_error = f"Could not save project: {exc}"
            st.rerun()
            return

        # ── Success — go straight to the new project workspace ────────────
        st.toast(f"'{project.name}' created!", icon="🎉")
        st.session_state.active_project_id = project.project_id
        st.session_state.cp_vibe_text      = ""
        st.session_state.cp_preset_genre   = ""
        st.session_state.cp_applied_mods   = []
        st.session_state.page              = "View Project"
        st.rerun()
