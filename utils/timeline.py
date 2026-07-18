from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class TimelineEvent:

    timestamp: str
    event_type: str
    actor: str
    description: str

    # Monotonically increasing sequence number within a project's timeline.
    # Set to len(project.timeline) before appending — gives a stable sort key
    # for Timeline Replay and lets the Creative Passport show "event N of M".
    # Also makes tampering detectable (gaps in the sequence are suspicious).
    seq: int = 0

    # Free-form payload for event-specific data.
    # Phase 2 AI events will store:      model_id, prompt_version, tokens_used, section_key
    # Phase 3 drift-check events store:  pre_text, post_text, locked_sections
    # Phase 4 contribution events store: section_authorship, direction_score
    # Phase 1 events leave this as an empty dict — old files always deserialise cleanly.
    metadata: dict = field(default_factory=dict)

    # Reserved extension envelope — for external integrations that need to
    # attach their own metadata without polluting the core event fields.
    # NOTE: named 'ext' (not '_ext') to avoid Python name-mangling which would
    # cause asdict() to serialise the key as '_TimelineEvent__ext', breaking round-trips.
    ext: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def create_event(
    event_type: str,
    actor: str,
    description: str,
    seq: int = 0,
    metadata: dict = None,
) -> TimelineEvent:
    """
    Create a TimelineEvent stamped with the current local time.

    Args:
        event_type:  Taxonomy key, e.g. "project_created", "ai_generated",
                     "section_locked", "section_unlocked", "section_regenerated",
                     "human_edit", "section_accepted", "section_rejected",
                     "contribution_computed", "passport_exported".
        actor:       "Human" or "AI".
        description: Human-readable summary of the event.
        seq:         Pass ``len(project.timeline)`` before appending so the
                     sequence number reflects the event's position in the log.
                     Prefer ``append_event()`` which sets this automatically.
        metadata:    Optional dict of event-specific structured data (default: {}).
    """
    return TimelineEvent(
        timestamp=datetime.now().isoformat(),
        event_type=event_type,
        actor=actor,
        description=description,
        seq=seq,
        metadata=metadata or {},
    )


def append_event(
    timeline: list,
    event_type: str,
    actor: str,
    description: str,
    metadata: dict = None,
) -> TimelineEvent:
    """
    Create a TimelineEvent, assign the correct seq number, append it to
    *timeline* (as a plain dict), and return the event.

    This is the preferred way to add events in Phase 2+ code because it makes
    the seq number contract impossible to skip or get wrong — the caller never
    has to remember to pass ``seq=len(project.timeline)``.

    Args:
        timeline:    The project's ``timeline`` list (mutated in-place).
        event_type:  Taxonomy key (see create_event for valid values).
        actor:       "Human" or "AI".
        description: Human-readable summary of the event.
        metadata:    Optional dict of event-specific structured data (default: {}).

    Returns the created TimelineEvent (already appended to *timeline*).
    """
    event = create_event(
        event_type=event_type,
        actor=actor,
        description=description,
        seq=len(timeline),
        metadata=metadata,
    )
    timeline.append(event.to_dict())
    return event
