from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class Project:

    name: str
    vibe: str

    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )

    status: str = "Draft"

    version: int = 1

    timeline: list = field(default_factory=list)

    def to_dict(self):
        """
        Convert Project into a dictionary.
        """
        return asdict(self)