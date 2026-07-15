#Basic Layout
import streamlit as st
from utils.models import Project
from utils.storage import save_project

st.set_page_config(
    page_title="HarmonyLedger",
    page_icon="🎵",
    layout="wide"
)
st.title("🎵 HarmonyLedger")

st.subheader(
    "The Creative Passport for Human-AI Songwriting"
)

st.divider()


#Adding sidebar navigation
# ---------------- Sidebar ---------------- #

st.sidebar.title("🎵 HarmonyLedger")
st.sidebar.markdown("---")

st.sidebar.subheader("📂 Projects")

page = st.sidebar.radio(
    "Choose a page",
    [
        "Create Project",
        "Open Project"
    ]
)

st.sidebar.markdown("---")

st.sidebar.subheader("🎼 Workspace")

st.sidebar.markdown("🔒 Timeline")
st.sidebar.markdown("🔒 Lyrics")

st.sidebar.markdown("---")

st.sidebar.subheader("📊 Analysis")

st.sidebar.markdown("🔒 Contributions")
st.sidebar.markdown("🔒 Creative Passport")

#Adding the projection creation form
if page == "Create Project":

    st.header("Create New Project")

    project_name = st.text_input(
        "Project Name"
    )

    vibe = st.text_area(
        "Song Vibe",
        height=150
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

        path = save_project(project)

        st.success(f"🎉 '{project.name}' was created successfully!")

        st.info("You can now open this project from the 'Open Project' page.")

        st.caption(f"Saved to: {path}")