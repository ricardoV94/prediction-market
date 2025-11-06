from typing import Literal
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
    def from_json(cls, file: str | Path):
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
        event = event.copy()
        event["#"] = len(self.entries)
        event["timestamp"] = datetime.now(timezone.utc).strftime(self.time_format)
        json_event = json_dumps(event)
        with self.file.open("a", encoding="utf-8") as f:
            f.write(f"{json_event}\n")
        self.entries.append(json_loads(json_event))

    def update_user(
        self,
        author: str,
        user_id: int,
        user_name: str,
        discord_id: int | str = "",
        reason: str = "",
    ):
        event = {
            "type": "user_update",
            "author": str(author),
            "info": {
                "user_id": int(user_id),
                "user_name": str(user_name),
                "discord_id": discord_id,
                "reason": str(reason),
            },
        }
        self.append(event)

    def update_balance(
        self,
        author: str,
        user_id: int,
        delta: float,
        old_balance: float,
        new_balance: float,
        reason: str = "",
    ):
        event = {
            "type": "balance_update",
            "author": str(author),
            "info": {
                "user_id": int(user_id),
                "delta": float(delta),
                "old_balance": float(old_balance),
                "new_balance": float(new_balance),
                "reason": str(reason),
            },
        }
        self.append(event)

    def user_trade(
        self,
        author: str,
        user_id: int,
        market_id: int,
        share_type: Literal["Yes", "No"],
        quantity: int,
        cost: float,
        old_balance: float,
        new_balance: float,
    ):
        event = {
            "type": "user_trade",
            "author": str(author),
            "info": {
                "user_id": int(user_id),
                "market_id": int(market_id),
                "share_type": str(share_type),
                "quantity": int(quantity),
                "cost": float(cost),
                "old_balance": float(old_balance),
                "new_balance": float(new_balance),
            },
        }
        self.append(event)
