#Basic Layout
import streamlit as st

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
st.sidebar.title("Navigation")

page = st.sidebar.radio(
    "Go to",
    [
        "Create Project",
        "Open Project"
    ]
)

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

    st.button("Create Project")