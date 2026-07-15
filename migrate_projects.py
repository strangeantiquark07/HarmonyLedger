"""
One-time migration script: converts old name-based project files to UUID-based filenames
and adds schema_version, song, and metadata fields introduced in Phase 1 architecture review.
Safe to run multiple times — already-migrated files are skipped.
"""
import json
import uuid
from pathlib import Path

DIR = Path(__file__).parent / "data" / "projects"

errors = []

for f in list(DIR.glob("*.json")):
    try:
        with open(f, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        errors.append((f.name, f"invalid JSON, skipping: {exc}"))
        continue
    except OSError as exc:
        errors.append((f.name, f"could not read, skipping: {exc}"))
        continue

    existing_id = data.get("project_id", "")

    # Skip if already migrated (filename == project_id)
    if f.stem == existing_id:
        print(f"Already migrated: {f.name}")
        continue

    # Assign a UUID if the field is missing
    if not existing_id:
        data["project_id"] = str(uuid.uuid4())

    # Add fields introduced in the architecture review
    data.setdefault("schema_version", 1)
    data.setdefault("song", {})

    # Patch existing timeline events to include the metadata field
    for event in data.get("timeline", []):
        event.setdefault("metadata", {})

    new_path = DIR / (data["project_id"] + ".json")

    # Write the new file first; only unlink the old file after a confirmed
    # successful write.  This prevents data loss if the write fails mid-way.
    try:
        with open(new_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=4, ensure_ascii=False)
    except OSError as exc:
        errors.append((f.name, f"could not write {new_path.name}, skipping: {exc}"))
        continue

    # New file is confirmed on disk — safe to remove the old one.
    try:
        if f != new_path:
            f.unlink()
    except OSError as exc:
        errors.append((f.name, f"migrated to {new_path.name} but could not remove original: {exc}"))
        continue

    print(f"Migrated: {f.name} -> {new_path.name}")

print("Migration complete.")

if errors:
    print(f"\n{len(errors)} file(s) had errors:")
    for name, reason in errors:
        print(f"  {name}: {reason}")
