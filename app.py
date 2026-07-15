#Basic Layout
import streamlit as st
from datetime import datetime
from utils.timeline import create_event

from utils.models import Project
from utils.storage import (
    save_project,
    load_project,
    list_projects
)

# -------------------------------------------------
# Page Configuration
# -------------------------------------------------

st.set_page_config(
    page_title="HarmonyLedger",
    page_icon="🎵",
    layout="centered"
)

# -------------------------------------------------
# Header
# -------------------------------------------------

st.title("🎵 HarmonyLedger")
st.subheader("The Creative Passport for Human-AI Songwriting")
st.divider()

# -------------------------------------------------
# Sidebar
# -------------------------------------------------

st.sidebar.title("🎵 HarmonyLedger")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigation",
    [
        "Create Project",
        "Open Project"
    ]
)

st.sidebar.markdown("---")

st.sidebar.subheader("Workspace")
st.sidebar.markdown("🚧 Timeline")
st.sidebar.markdown("🚧 Lyrics")
st.sidebar.markdown("🚧 AI Studio")

st.sidebar.markdown("---")

st.sidebar.subheader("Analysis")
st.sidebar.markdown("🚧 Contributions")
st.sidebar.markdown("🚧 Creative Passport")

# ============================================================
# CREATE PROJECT PAGE
# ============================================================

if page == "Create Project":

    st.header("Create New Project")

    project_name = st.text_input("Project Name")

    vibe = st.text_area(
        "Song Vibe",
        height=150,
        placeholder="Describe the mood, genre, emotions, instruments..."
    )

    if st.button("Create Project"):

        if not project_name.strip():
            st.error("Please enter a project name.")

        elif not vibe.strip():
            st.error("Please enter the song vibe.")

        else:

            project = Project(
                name=project_name,
                vibe=vibe
            )
            project.timeline.append(

            create_event(
               event_type="project_created",
               actor="Human",
               description="Project created." ).to_dict()

)

            path = save_project(project)

            st.success(f"🎉 '{project.name}' created successfully!")

            st.info(
                "You can now open it from the **Open Project** page."
            )

            st.caption(f"Saved to: {path}")

# ============================================================
# OPEN PROJECT PAGE
# ============================================================

elif page == "Open Project":

    st.header("📂 Open Project")

    projects = list_projects()

    if not projects:

        st.info("No saved projects found.")

    else:

        selected = st.selectbox(
            "Choose a project",
            projects
        )

        # Automatically load the selected project
        project = load_project(selected)

        created = datetime.fromisoformat(project.created_at)

        st.success("Project loaded successfully!")

        st.title(f"🎵 {project.name}")

        st.caption(
            f"{project.status} • Version {project.version}"
        )

        st.divider()

        # -----------------------------
        # Song Vibe
        # -----------------------------

        st.subheader("💡 Song Vibe")

        with st.container(border=True):
            st.write(project.vibe)

        st.write("")

        # -----------------------------
        # Project Info
        # -----------------------------

        col1, col2 = st.columns(2)

        with col1:
            st.metric("Status", project.status)

        with col2:
            st.metric("Version", project.version)

        st.write("")

        st.subheader("📅 Created")

        st.write(created.strftime("%d %B %Y"))

        st.caption(created.strftime("%I:%M %p"))

        st.divider()

        # -----------------------------
        # Timeline
        # -----------------------------

        st.subheader("📝 Creative Timeline")

        with st.container(border=True):

            if project.timeline:

                for event in project.timeline:

                  st.markdown(
        f"""
**{event['event_type']}**

{event['description']}

*{event['timestamp']}*
"""
    )

                  st.divider()

            else:

                st.markdown("### 📭 No timeline events yet")

                st.caption(
                    "Your songwriting journey will appear here in Phase 2."
                )