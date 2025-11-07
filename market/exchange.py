from collections import namedtuple
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from math import exp as _exp
from math import log

from market.ledger import Ledger


def exp(x) -> float:
    "Safe exp without overflow error"
    try:
        return _exp(x)
    except OverflowError:
        return float("inf")


Shares = namedtuple("Shares", ["no", "yes"])


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
    _status: MarketStatus
    shares: Shares

    @property
    def status(self) -> MarketStatus:
        if self._status not in (MarketStatus.closed, MarketStatus.open):
            return self._status
        if self.open_date <= datetime.now(timezone.utc) < self.close_date:
            return MarketStatus.open
        else:
            return MarketStatus.closed

    @property
    def volume(self) -> int:
        return sum(self.shares)

    @staticmethod
    def _yes_price(liquidity: int, shares=Shares) -> float:
        no_shares, yes_shares = shares.no, shares.yes
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
    def yes_price(self) -> float:
        return self._yes_price(self.liquidity, self.shares)

    @property
    def no_price(self) -> float:
        return 100 - self.yes_price

    def simulate_trade(self, traded_shares: Shares) -> tuple[float, float, float]:
        # Compute LMSR cost for a trade
        liquidity = self.liquidity
        no_shares, yes_shares = self.shares
        current_score = log(exp(yes_shares / liquidity) + exp(no_shares / liquidity))

        new_no_shares = no_shares + traded_shares.no
        new_yes_shares = yes_shares + traded_shares.yes
        new_score = log(
            exp(new_yes_shares / liquidity) + exp(new_no_shares / liquidity),
        )
        cost = (new_score - current_score) * liquidity * 100

        new_yes_price = self._yes_price(
            liquidity, Shares(no=new_no_shares, yes=new_yes_shares)
        )
        new_no_price = 100 - new_yes_price

        return round(cost, 2), new_no_price, new_yes_price

    def simulate_liquidation_proceeds(self, user_shares: Shares) -> float:
        """Computes total proceeds from unwinding a user position in the current market."""
        user_no_shares, user_yes_shares = user_shares.no, user_shares.yes
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
    def markets(self) -> dict[int, Market]:
        if self._ledger_index != len(self.ledger.entries):
            self.update_from_extended_ledger()
        return self._markets

    @property
    def users(self) -> dict[int, User]:
        if self._ledger_index != len(self.ledger.entries):
            self.update_from_extended_ledger()
        return self._users

    @property
    def discord_user_ids(self) -> dict[int, int]:
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
            open_date = datetime.strptime(info["open_date"], date_format).replace(
                tzinfo=timezone.utc
            )
            close_date = datetime.strptime(info["close_date"], date_format).replace(
                tzinfo=timezone.utc
            )
            resolve_date = (
                datetime.strptime(info["resolve_date"], date_format).replace(
                    tzinfo=timezone.utc
                )
                if info["resolve_date"]
                else None
            )
            match info["status"]:
                # FIXME: This is a bit unfortunate, the ledger is not enough to find the status of a market
                # because we don't issue open/closed status automatically. Figure out nicer API
                case "open":
                    status = MarketStatus.open
                case "closed":
                    status = MarketStatus.closed
                case "resolved_yes":
                    status = MarketStatus.resolved_yes
                case "resolved_no":
                    status = MarketStatus.resolved_no
                case _:
                    raise ValueError(f"Unknown market status: {info['status']}")

            market = Market(
                id=market_id,
                question=info["question"],
                open_date=open_date,
                close_date=close_date,
                resolve_date=resolve_date,
                detailed_criteria=info["detailed_criteria"],
                liquidity=info["liquidity"],
                _status=status,
                shares=Shares(no=0, yes=0),
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
            no_shares, yes_shares = markets[market_id].shares
            if info["share_type"] == "No":
                no_shares += quantity
                assert no_shares >= 0
            else:
                yes_shares += quantity
                assert yes_shares >= 0
            markets[market_id].shares = Shares(no=no_shares, yes=yes_shares)

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
                users[user_id].positions[market_id] = Shares(
                    no=no_shares, yes=yes_shares
                )
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
                case "trade":
                    user_id = info["user_id"]
                    market_id = info["market_id"]
                    new_balance = info["new_balance"]
                    quantity = info["quantity"]
                    share_type = info["share_type"]
                    assert user_id in self._users
                    assert market_id in self._markets
                    assert new_balance >= 0
                    assert share_type in ("Yes", "No")

                    market = self._markets[market_id]
                    new_market_no, new_market_yes = market.shares
                    user = self._users[user_id]
                    user.balance = new_balance
                    new_no, new_yes = user.positions.get(market_id, (0, 0))
                    if share_type == "No":
                        new_market_no += quantity
                        new_no += quantity
                    else:
                        new_market_yes += quantity
                        new_yes += quantity

                    assert (new_market_no >= 0) and (new_market_yes >= 0)
                    assert (new_no >= 0) and (new_yes >= 0)
                    market.shares = Shares(no=new_market_no, yes=new_market_yes)
                    user.positions[market_id] = Shares(no=new_no, yes=new_yes)

                case _:
                    raise NotImplementedError(
                        f"Entry type {entry['type']} not yet supported"
                    )

        self._ledger_index = len(self.ledger.entries)


if __name__ == "__main__":
    from pprint import pprint

    # ledger = Ledger.from_json("data/ledger.json")
    # exchange = Exchange.from_ledger(ledger)
    # pprint(exchange)
    #
    market = Market(
        id=0,
        question="?",
        open_date=datetime.now(timezone.utc),
        close_date=datetime.now(timezone.utc),
        resolve_date=None,
        detailed_criteria="",
        liquidity=10,
        _status=MarketStatus.open,
        shares=Shares(no=0, yes=20),
    )
    pprint(market)
    print(market.yes_price, market.no_price, market.volume)
    print(market.simulate_trade(Shares(no=0, yes=1)))
