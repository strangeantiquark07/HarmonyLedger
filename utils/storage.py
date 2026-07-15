import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from utils.models import Project

# ---------------------------------------------------------------------------
# Path anchored to THIS file's location so it resolves correctly regardless
# of the working directory (app root, test runner, CI, etc.).
# ---------------------------------------------------------------------------
PROJECTS_DIR = Path(__file__).parent.parent / "data" / "projects"


class ProjectNotFoundError(Exception):
    """Raised when a requested project file does not exist."""


class ProjectCorruptedError(Exception):
    """Raised when a project file exists but cannot be parsed or is structurally invalid."""


class ProjectConflictError(Exception):
    """Raised when a save is attempted on a project whose on-disk version has changed.

    Attribute ``disk_version`` carries the version number currently on disk so
    the caller can surface a meaningful message to the user.
    """

    def __init__(self, message: str, disk_version: int):
        super().__init__(message)
        self.disk_version = disk_version


def _write_project_data(data: dict, file_path: Path) -> None:
    """
    Low-level writer: serialise *data* to *file_path* as indented JSON.

    Uses an atomic write: the payload is written to a sibling temp file first,
    then renamed into place via os.replace().  This guarantees the on-disk file
    is always a complete, valid JSON document — never a half-written fragment
    caused by a crash, disk-full event, or unexpected shutdown.

    Used by both save_project() and the auto-migration path in load_project().
    Separated so that the migration path can persist a file without triggering
    the last_modified_at side-effect that save_project() applies.
    """
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        # Write to a temp file in the same directory so os.replace() is atomic
        # (cross-device rename would fail; same directory guarantees same fs).
        fd, tmp_path = tempfile.mkstemp(
            dir=file_path.parent, suffix=".tmp", prefix=file_path.stem + "_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, file_path)
        except Exception:
            # Clean up the orphaned temp file on any failure before re-raising.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError as exc:
        raise OSError(f"Could not write project to {file_path}: {exc}") from exc


def save_project(project: Project, *, check_conflict: bool = False) -> Path:
    """
    Serialise a Project to disk using its project_id as the filename.

    Stamps last_modified_at with the current time *after* a successful write,
    so a failed save never leaves the in-memory object with a timestamp that
    doesn't correspond to any file on disk.

    Args:
        project:        The Project to save.
        check_conflict: When True, read the on-disk version before writing and
                        raise ProjectConflictError if it differs from
                        project.version.  Protects against last-write-wins
                        overwrites in concurrent sessions.

    Returns the path the file was written to.
    Raises OSError if the write fails (e.g. permissions, disk full).
    Raises ProjectConflictError if check_conflict is True and the on-disk
        version has advanced beyond the in-memory project.
    """
    file_path = PROJECTS_DIR / f"{project.project_id}.json"

    if check_conflict and file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                on_disk = json.load(f)
            disk_version = int(on_disk.get("version", 1))
        except (json.JSONDecodeError, OSError, ValueError):
            disk_version = None  # Corrupt/missing — let the write proceed.

        if disk_version is not None and disk_version != project.version:
            raise ProjectConflictError(
                f"Project '{project.name}' has been modified in another session "
                f"(disk version {disk_version}, your version {project.version}). "
                "Reload the project before saving.",
                disk_version=disk_version,
            )

    # Compute the new timestamp but do NOT mutate the object yet.
    new_modified = datetime.now().isoformat()

    data = project.to_dict()
    data["last_modified_at"] = new_modified

    _write_project_data(data, file_path)

    # Only update the object once the write has succeeded.
    project.last_modified_at = new_modified

    return file_path


def load_project(project_id: str) -> Project:
    """
    Load a Project from disk by its project_id.

    If the stored schema_version is older than the current version,
    Project.from_dict() applies the necessary migrations automatically and
    records them in schema_migrations.  The migrated file is then persisted
    via _write_project_data() — intentionally bypassing save_project() so
    that merely opening an old project does not update last_modified_at.

    Raises:
        ProjectNotFoundError  — the file does not exist.
        ProjectCorruptedError — the file exists but contains invalid JSON or
                                is structurally invalid (missing required fields).
        OSError               — a filesystem-level read error occurred.
    """
    file_path = PROJECTS_DIR / f"{project_id}.json"

    if not file_path.exists():
        raise ProjectNotFoundError(
            f"No project file found for id '{project_id}' at {file_path}."
        )

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ProjectCorruptedError(
            f"Project file at {file_path} contains invalid JSON: {exc}"
        ) from exc
    except OSError as exc:
        raise OSError(
            f"Could not read project file at {file_path}: {exc}"
        ) from exc

    try:
        project = Project.from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise ProjectCorruptedError(
            f"Project file at {file_path} is structurally invalid: {exc}"
        ) from exc

    # Auto-persist migrations without touching last_modified_at.
    if data.get("schema_version", 1) < project.schema_version:
        _write_project_data(project.to_dict(), file_path)

    return project


def list_projects() -> tuple[list[dict], list[dict]]:
    """
    Return project summaries and any problem files found in the projects directory.

    Returns a 2-tuple:
        projects  — list of dicts with keys: project_id, name, last_modified_at.
                    Sorted alphabetically by name.
        problems  — list of dicts with keys: file_name, reason.
                    One entry per file that could not be read or parsed.  The
                    caller should surface these to the user rather than hiding them.

    Both lists are always returned; callers decide how to display problems.
    """
    if not PROJECTS_DIR.exists():
        return [], []

    projects: list[dict] = []
    problems: list[dict] = []

    for file_path in PROJECTS_DIR.glob("*.json"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            projects.append({
                "project_id": data.get("project_id", file_path.stem),
                "name": data.get("name", file_path.stem),
                # Fall back to created_at for v1 files not yet migrated on disk.
                "last_modified_at": data.get(
                    "last_modified_at", data.get("created_at", "")
                ),
            })
        except json.JSONDecodeError:
            problems.append({
                "file_name": file_path.name,
                "reason": "invalid JSON — file may be corrupt",
            })
        except OSError as exc:
            problems.append({
                "file_name": file_path.name,
                "reason": f"could not be read: {exc}",
            })
            # Also log to stderr so it appears in server logs / CI output.
            print(
                f"Warning: could not read project file {file_path}: {exc}",
                file=sys.stderr,
            )

    return sorted(projects, key=lambda p: p["name"]), problems
