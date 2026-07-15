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
    
    @classmethod
    def from_dict(cls, data):
     """
       Create a Project object from a dictionary.
     """

     return cls(
        name=data["name"],
        vibe=data["vibe"],
        created_at=data["created_at"],
        status=data["status"],
        version=data["version"],
        timeline=data["timeline"]
    )