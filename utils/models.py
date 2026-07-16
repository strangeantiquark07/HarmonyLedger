from dataclasses import dataclass, field, asdict
from datetime import datetime
from uuid import uuid4

# Maximum allowed length for a project name.  Long enough for any real title;
# short enough to render safely in UI titles, PDF headers, and filenames.
PROJECT_NAME_MAX_LENGTH = 100

# ---------------------------------------------------------------------------
# Schema version history
# ---------------------------------------------------------------------------
#   v1 — Phase 1: project_id, name, vibe, created_at, status, version, song,
#                 timeline, schema_version
#   v2 — Phase 1 (post-review): added last_modified_at, contribution,
#                 passport, collaborators, ext, schema_migrations
#         TimelineEvent gained: seq, ext
#         song sections now carry provenance envelope (populated in Phase 2)
# ---------------------------------------------------------------------------
CURRENT_SCHEMA_VERSION = 2


@dataclass
class Project:

    name: str
    vibe: str

    def __post_init__(self):
        """Enforce invariants that must hold for every Project instance.

        Raises ValueError so callers (including load_project) can catch it
        and surface a consistent error message.
        """
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Project name must be a non-empty string.")
        if len(self.name) > PROJECT_NAME_MAX_LENGTH:
            raise ValueError(
                f"Project name exceeds {PROJECT_NAME_MAX_LENGTH} characters "
                f"({len(self.name)} given)."
            )

    # Stable identity — used as the filename; never changes even if name is edited.
    project_id: str = field(default_factory=lambda: str(uuid4()))

    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )

    # Updated by save_project() on every write.
    last_modified_at: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )

    status: str = "Draft"

    # Incremented by the app on every meaningful user action (not on every save).
    version: int = 1

    # Increment this whenever the schema gains or removes fields so
    # load_project() can apply migrations and never silently corrupt old files.
    schema_version: int = CURRENT_SCHEMA_VERSION

    # Append-only record of every schema migration applied to this file.
    # Each entry: {"from": int, "to": int, "migrated_at": ISO-8601}
    schema_migrations: list = field(default_factory=list)

    # ---------------------------------------------------------------------------
    # Song content — populated by ai_engine.generate_song() in Phase 2.
    #
    # Top-level shape (all fields required after first generation):
    #   {
    #     "title":               str,
    #     "genre":               str,
    #     "style":               str,
    #     "mood":                str,
    #     "tempo":               str,   # e.g. "72 BPM" or "Slow trap"
    #     "key":                 str,   # e.g. "F minor"
    #     "time_signature":      str,   # e.g. "4/4"
    #     "lyrical_themes":      list[str],
    #     "generation_timestamp":str,   # ISO-8601, stamped by ai_engine
    #     "model_used":          str,   # e.g. "gemini-2.5-flash"
    #     "sections": {
    #       "verse_1" | "chorus" | "verse_2" | "bridge" | "outro": {
    #         "lyrics":        str,
    #         "provenance":    "ai_generated" | "human_written" | "ai_then_human",
    #         "locked":        bool,
    #         "locked_at":     ISO-8601 | null,
    #         "locked_by":     "Human" | "AI" | null,
    #         "last_edited_by":"Human" | "AI" | null,
    #         "edit_count":    int   # incremented on every human edit
    #       }
    #     }
    #   }
    #
    # Before first generation: {"genre": str} only (set by create_project.py).
    # ---------------------------------------------------------------------------
    song: dict = field(default_factory=dict)

    timeline: list = field(default_factory=list)

    # ---------------------------------------------------------------------------
    # Contribution cache — populated / refreshed by Phase 4.
    # Storing it here avoids re-walking the full timeline on every render.
    #
    # {
    #   "human_pct":          float,   # 0–100, section-authorship split
    #   "ai_pct":             float,
    #   "direction_score":    float,   # human steering decisions as % of total actions
    #   "computed_at":        ISO-8601,
    #   "methodology_version":int      # bump if the formula changes; old exports stay valid
    # }
    contribution: dict = field(default_factory=dict)

    # ---------------------------------------------------------------------------
    # Creative Passport export state — populated by Phase 4.
    # Storing approved wording here makes re-exports deterministic.
    #
    # {
    #   "exported_at":           ISO-8601 | null,
    #   "export_format":         "pdf" | "json" | "html" | null,
    #   "transparency_statement":str,   # human-approved text
    #   "authorship_line":       str,   # e.g. "Written by Jane + Google Gemini"
    #   "watermark_id":          uuid4 | null   # unique ID per export instance
    # }
    passport: dict = field(default_factory=dict)

    # ---------------------------------------------------------------------------
    # Named contributors (human and AI).
    # The AI model is a collaborator — storing model_id here lets the passport
    # reference exactly which Gemini version wrote which sections.
    #
    # Each entry:
    # {
    #   "collaborator_id":  uuid4,
    #   "name":             str,
    #   "role":             "composer" | "lyricist" | "producer" | "ai_model",
    #   "model_id":         str | null,   # e.g. "gemini-2.5-flash"
    #   "contribution_pct": float | null  # filled by Phase 4
    # }
    collaborators: list = field(default_factory=list)

    # Reserved extension envelope — for external integrations (DAW plugins,
    # rights bodies, third-party tools) that need to attach their own metadata
    # without polluting the core schema fields.
    # NOTE: named 'ext' (not '_ext') to avoid Python name-mangling which would
    # cause asdict() to serialise the key as '_Project__ext', breaking round-trips.
    ext: dict = field(default_factory=dict)

    def to_dict(self):
        """
        Serialise Project to a plain dictionary for JSON storage.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        """
        Deserialise a Project from a stored dictionary.

        Applies forward-compatibility defaults for every field added after
        schema_version 1, so that old project files load cleanly in newer
        versions of the app.  Any schema upgrade is recorded in
        schema_migrations so there is a permanent audit trail of which
        migrations were applied and when.

        All mutable fields (lists, dicts) are defensively copied so that
        mutations on the returned Project never alias into the caller's
        original data dict.
        """
        stored_version = data.get("schema_version", 1)
        migrations = list(data.get("schema_migrations", []))

        # ----------------------------------------------------------------
        # Schema migration — v1 → v2
        # Adds: last_modified_at, contribution, passport, collaborators,
        #       ext, schema_migrations
        # ----------------------------------------------------------------
        if stored_version < 2:
            migrations.append({
                "from": stored_version,
                "to": 2,
                "migrated_at": datetime.now().isoformat(),
            })

        # Validate required scalar fields before constructing, so missing keys
        # raise a descriptive ValueError instead of a bare KeyError.
        _required = ("name", "vibe", "created_at", "status", "version")
        _missing = [k for k in _required if k not in data]
        if _missing:
            raise ValueError(
                f"Project data is missing required field(s): {', '.join(_missing)}"
            )

        name = data["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Project 'name' field must be a non-empty string.")

        created_at = data["created_at"]
        if not isinstance(created_at, str):
            raise ValueError("Project 'created_at' field must be a string.")

        return cls(
            project_id=data.get("project_id", str(uuid4())),
            name=name,
            vibe=data["vibe"],
            created_at=created_at,
            last_modified_at=data.get("last_modified_at", created_at),
            status=data["status"],
            version=data["version"],
            schema_version=CURRENT_SCHEMA_VERSION,
            schema_migrations=migrations,
            song=dict(data.get("song", {})),
            timeline=list(data.get("timeline", [])),
            contribution=dict(data.get("contribution", {})),
            passport=dict(data.get("passport", {})),
            collaborators=list(data.get("collaborators", [])),
            # Accept both 'ext' (v2+) and the legacy '_ext' key written by
            # any files saved before this rename was applied.
            ext=dict(data.get("ext", data.get("_ext", {}))),
        )
