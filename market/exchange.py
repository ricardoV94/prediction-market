from collections import namedtuple
from math import exp, log
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

from market.ledger import Ledger

Shares = namedtuple("Shares", ["No", "Yes"])


def yes_price(liquidity: int, no_shares: int, yes_shares: int) -> float:
    yes_weight = exp(yes_shares / liquidity)
    no_weight = exp(no_shares / liquidity)
    price = yes_weight / (yes_weight + no_weight)
    # Handle out-of-bounds roundoff errors
    if price < 0:
        price = 0
    elif price > 1:
        price = 1
    return 100 * price


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
        return yes_price(self.liquidity, *self.shares)

    @property
    def no_price(self) -> float:
        return 100 - self.yes_price

    def simulate_trade(
        self, new_no_shares: int, new_yes_shares: int
    ) -> tuple[float, float, float]:
        # Compute LMSR cost for a trade
        liquidity = self.liquidity
        no_shares, yes_shares = self.shares
        current_score = log(exp(yes_shares / liquidity) + exp(no_shares / liquidity))
        new_score = log(
            exp(new_yes_shares / liquidity) + exp(new_no_shares / liquidity),
        )
        cost = (new_score - current_score) * liquidity * 100

        new_yes_price = yes_price(liquidity, new_no_shares, new_yes_shares)
        new_no_price = 100 - new_yes_price

        return round(cost, 2), new_yes__price, new_no_price

    def simulate_liquidation_proceeds(self, user_no_shares, user_yes_shares) -> float:
        """Computes total proceeds from unwinding a user position in the current market."""
        yes_price = self.yes_price
        b = self.liquidity

        p_yes = yes_price / 100
        r = p_yes / (1.0 - p_yes)

        proceeds = 0
        # Simulate selling Yes shares first
        if user_yes_shares:
            cost = b * log((r * exp(-user_yes_shares / b) + 1.0) / (r + 1.0)) * 100
            proceeds = round(-cost, 2)
            r = r * exp(-user_yes_shares / b)
        if user_no_shares:
            cost = b * log((r + exp(-user_no_shares / b)) / (r + 1.0)) * 100
            proceeds += round(-cost, 2)
        return round(proceeds, 2)


@dataclass
class User:
    id: int
    user_name: str
    balance: float
    positions: dict[int, Shares]


@dataclass
class Exchange:
    ledger: Ledger
    _markets: dict[int, Market]
    _users: dict[int, User]
    _discord_user_ids: dict[int, int]
    _ledger_index: int

    @property
    def markets(self):
        if self._ledger_index != len(self.ledger.entries):
            self.update_from_extended_ledger()
        return self._markets

    @property
    def users(self):
        if self._ledger_index != len(self.ledger.entries):
            self.update_from_extended_ledger()
        return self._users

    @property
    def discord_user_ids(self):
        if self._ledger_index != len(self.ledger.entries):
            self.update_from_extended_ledger()
        return self._discord_user_ids

    @staticmethod
    def _markets_from_ledger(ledger):
        date_format = ledger.date_format
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
        discord_user_ids = {}
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
                balance=0,
                positions={},
            )
            users[user_id] = user
            if info["discord_id"]:
                discord_id = int(info["discord_id"])
                discord_user_ids[discord_id] = user_id

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
        return users, discord_user_ids

    @classmethod
    def from_ledger(cls, ledger: Ledger):
        markets = cls._markets_from_ledger(ledger)
        users, discord_user_ids = cls._users_from_ledger(ledger)
        return cls(
            ledger=ledger,
            _markets=markets,
            _users=users,
            _discord_user_ids=discord_user_ids,
            _ledger_index=len(ledger.entries),
        )

    def update_from_extended_ledger(self):
        for entry in self.ledger.entries[self._ledger_index :]:
            info = entry["info"]
            match entry["type"]:
                case "user_update":
                    user_id = info["user_id"]
                    if user_id in self._users:
                        user = self._users[user_id]
                        balance = user.balance
                        positions = user.positions.copy()
                    else:
                        balance = 0
                        positions = {}
                    user = User(
                        id=user_id,
                        user_name=info["user_name"],
                        balance=balance,
                        positions=positions,
                    )
                    self._users[user_id] = user
                    if info["discord_id"]:
                        discord_id = info["discord_id"]
                        self._discord_user_ids[discord_id] = user_id
                case "balance_update":
                    user_id = info["user_id"]
                    new_balance = info["new_balance"]
                    self._users[user_id].balance = new_balance
                case _:
                    raise NotImplementedError(
                        f"Entry type {entry['type']} not yet supported"
                    )

        self._ledger_index = len(self.ledger.entries)


if __name__ == "__main__":
    from pprint import pprint

    ledger = Ledger.from_json("data/ledger.json")
    exchange = Exchange.from_ledger(ledger)
    pprint(exchange)
