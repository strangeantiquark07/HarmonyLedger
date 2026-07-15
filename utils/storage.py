import json
from pathlib import Path

# Folder where project JSON files will be stored
PROJECTS_DIR = Path("data/projects")

# Create the folder automatically if it doesn't exist
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def save_project(project):
    """
    Save a Project object as a JSON file.
    """

    file_path = PROJECTS_DIR / f"{project.name}.json"

    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(
            project.to_dict(),
            file,
            indent=4,
            ensure_ascii=False
        )

    return file_path

def load_project(project_name):
    """
    Load a project from a JSON file.
    """

    safe_name = project_name.strip().replace(" ", "_")
    file_path = PROJECTS_DIR / f"{safe_name}.json"

    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)