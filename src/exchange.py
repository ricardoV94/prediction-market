from json import loads as json_loads, dumps as json_dumps
from collections import namedtuple
from math import exp
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from enum import Enum

Shares = namedtuple("Shares", ["No", "Yes"])


@dataclass
class Ledger:
    file: Path
    entries: list

    @classmethod
    def from_file(cls, file: str):
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

    def append(self, event):
        json_event = json_dumps(event)
        with self.file.open("a", encoding="utf-8") as f:
            f.write(json_event)
        return json_event


class MarketStatus(Enum):
    open = 0
    closed = 1
    resolved_yes = 2
    resolved_no = 3


@dataclass
class Market:
    id: int
    question: str
    open_date: datetime
    close_date: datetime
    resolve_date: datetime | None
    detailed_criteria: str
    liquidity: int
    status: MarketStatus
    shares: Shares

    @property
    def volume(self) -> int:
        return self.shares[0] + self.shares[1]

    @property
    def yes_price(self) -> float:
        no_shares, yes_shares = self.shares
        liquidity = self.liquidity
        yes_weight = exp(yes_shares / liquidity)
        no_weight = exp(no_shares / liquidity)
        price = yes_weight / (yes_weight + no_weight)
        # Handle out-of-bounds roundoff errors
        if price < 0:
            price = 0
        elif price > 1:
            price = 1
        return 100 * price

    @property
    def no_price(self) -> float:
        return 100 - self.yes_price


@dataclass
class User:
    id: int
    user_name: str
    discord_name: str
    balance: float
    positions: dict[int, Shares]


@dataclass
class Exchange:
    markets: dict[int, Market]
    users: dict[int, User]

    @staticmethod
    def _markets_from_ledger(ledger):
        date_format = "%Y-%m-%d"
        markets = {}
        # First loop to collect markets data
        for entry in reversed(ledger.entries):
            if entry["type"] != "market_update":
                continue

            info = entry["info"]
            market_id = info["market_id"]
            if market_id in markets:
                continue

            # New market
            match info["status"]:
                case "resolved_yes":
                    status = MarketStatus.resolved_yes
                case "resolved_no":
                    status = MarketStatus.resolved_no
                case "open":
                    # We don't issue a closed event when market goes over close date
                    if (
                        datetime.strptime(info["close_date"], date_format)
                        < datetime.now()
                    ):
                        status = MarketStatus.closed
                    else:
                        status = MarketStatus.open
                case "closed":
                    status = MarketStatus.closed
                case _:
                    raise ValueError(f"Unknown market status: {info['status']}")

            market = Market(
                id=market_id,
                question=info["question"],
                open_date=datetime.strptime(info["open_date"], date_format),
                close_date=datetime.strptime(info["close_date"], date_format),
                resolve_date=(
                    datetime.strptime(info["resolve_date"], date_format)
                    if info["resolve_date"]
                    else None
                ),
                detailed_criteria=info["detailed_criteria"],
                liquidity=info["liquidity"],
                status=status,
                shares=Shares(0, 0),
            )
            markets[market_id] = market

        # Second loop to collect shares
        for entry in reversed(ledger.entries):
            if entry["type"] != "trade":
                # We leave shares unchanged after resolutions, so we can see what the final status was easily
                continue

            info = entry["info"]
            market_id = info["market_id"]
            quantity = info["quantity"]
            yes_shares, no_shares = markets[market_id].shares
            if info["share_type"] == "Yes":
                yes_shares += quantity
                assert yes_shares >= 0
            else:
                no_shares += quantity
                assert no_shares >= 0
            markets[market_id].shares = Shares(yes_shares, no_shares)

        return markets

    @staticmethod
    def _users_from_ledger(ledger):
        users = {}
        # First loop to collect most recent user data
        for entry in reversed(ledger.entries):
            if entry["type"] != "user_update":
                continue
            info = entry["info"]
            user_id = info["user_id"]
            if user_id in users:
                continue
            # new user
            user = User(
                id=user_id,
                user_name=info["user_name"],
                discord_name=info["discord_name"],
                balance=0,
                positions={},
            )
            users[user_id] = user

        # Second loop to update user balances and positions
        # We reply transactions historically
        for entry in ledger.entries:
            if entry["type"] == "balance_update":
                info = entry["info"]
                user_id = info["user_id"]
                users[user_id].balance = info["new_balance"]
            if entry["type"] in ("trade", "resolution"):
                info = entry["info"]
                user_id = info["user_id"]
                market_id = info["market_id"]
                no_shares, yes_shares = users[user_id].positions.get(market_id, (0, 0))
                quantity = info["quantity"]
                if info["share_type"] == "Yes":
                    yes_shares += quantity
                    assert yes_shares >= 0
                else:
                    no_shares += quantity
                    assert no_shares >= 0
                users[user_id].positions[market_id] = Shares(no_shares, yes_shares)
                users[user_id].balance = info["new_balance"]
        return users

    @classmethod
    def from_ledger(cls, ledger: Ledger):
        markets = cls._markets_from_ledger(ledger)
        users = cls._users_from_ledger(ledger)
        return cls(markets=markets, users=users)


if __name__ == "__main__":
    from pprint import pprint

    ledger = Ledger.from_file("data/ledger.json")
    exchange = Exchange.from_ledger(ledger)
    pprint(exchange)
