from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class TimelineEvent:

    timestamp: str

    event_type: str

    actor: str

    description: str

    def to_dict(self):
        return asdict(self)


def create_event(event_type, actor, description):

    return TimelineEvent(
        timestamp=datetime.now().isoformat(),
        event_type=event_type,
        actor=actor,
        description=description
    )