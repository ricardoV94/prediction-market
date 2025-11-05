from json import loads as json_loads, dumps as json_dumps
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone


@dataclass
class Ledger:
    file: Path
    entries: list

    time_format = "%m/%d/%Y %H:%M:%S"
    date_format = "%Y-%m-%d"

    @classmethod
    def from_json(cls, file: str):
        file = Path(file)
        if not file.exists():
            file.touch()
            entries = []
        else:
            entries = [
                json_loads(line)
                for line in file.read_text(encoding="utf-8").splitlines()
            ]
        return cls(file=file, entries=entries)

    def append(self, event: dict):
        json_event = json_dumps(event)
        with self.file.open("a", encoding="utf-8") as f:
            f.write(f"{json_event}\n")
        self.entries.append(json_loads(json_event))

    def update_user(
        self,
        author: str,
        user_id: int,
        user_name: str,
        discord_id: int,
        reason: str = "",
    ):
        event = {
            "#": len(self.entries),
            "timestamp": datetime.now(timezone.utc).strftime(self.time_format),
            "type": "user_update",
            "info": {
                "user_id": user_id,
                "user_name": user_name,
                "discord_id": discord_id,
                "reason": reason,
            },
        }
        self.append(event)
