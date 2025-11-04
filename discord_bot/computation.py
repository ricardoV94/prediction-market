from enum import Enum
import math
from decimal import Decimal, ROUND_HALF_UP


class ShareType(Enum):
    Yes = "Yes"
    No = "No"


def _round_cents(x: float) -> float:
    """Rounds a float to two decimal places for currency."""
    return float(Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _sell_yes_proceeds_and_update_r(
    r: float, b: float, s: float
) -> tuple[float, float]:
    """Calculates proceeds from selling 's' Yes shares and the new price ratio."""
    if s <= 0 or b <= 0:
        return 0.0, r
    cost = b * math.log((r * math.exp(-s / b) + 1.0) / (r + 1.0)) * 100.0
    proceeds = _round_cents(-cost)
    new_r = r * math.exp(-s / b)
    return proceeds, new_r


def _sell_no_proceeds_and_update_r(r: float, b: float, s: float) -> tuple[float, float]:
    """Calculates proceeds from selling 's' No shares and the new price ratio."""
    if s <= 0 or b <= 0:
        return 0.0, r
    cost = b * math.log((r + math.exp(-s / b)) / (r + 1.0)) * 100.0
    proceeds = _round_cents(-cost)
    new_r = r * math.exp(s / b)
    return proceeds, new_r


def simulate_liquidation_proceeds(
    p_yes_pct: float, liquidity: float, user_yes: float, user_no: float
) -> float:
    """Computes total proceeds from unwinding a position in a single market."""
    if liquidity is None or liquidity <= 0:
        return 0.0

    p_yes = max(1e-9, min(1.0 - 1e-9, float(p_yes_pct) / 100.0))
    r = p_yes / (1.0 - p_yes)

    s_yes = max(0.0, float(user_yes or 0.0))
    s_no = max(0.0, float(user_no or 0.0))

    # Sell Yes, then update pool state for selling No to get an accurate total
    yes_proceeds, r_after_yes = _sell_yes_proceeds_and_update_r(
        r, float(liquidity), s_yes
    )
    no_proceeds, _ = _sell_no_proceeds_and_update_r(r_after_yes, float(liquidity), s_no)

    return _round_cents(yes_proceeds + no_proceeds)


def calculate_trade_cost(
    p_yes_pct: float, liquidity: float, quantity: int, share_type: ShareType
) -> float:
    """
    Calculates the cost of buying a certain number of shares.
    """
    if liquidity is None or liquidity <= 0 or quantity <= 0:
        return 0.0

    p_yes = max(1e-9, min(1.0 - 1e-9, float(p_yes_pct) / 100.0))
    r = p_yes / (1.0 - p_yes)
    b = float(liquidity)
    s = float(quantity)

    if share_type == ShareType.Yes:
        # Cost of buying 's' Yes shares
        cost = b * math.log((r * math.exp(s / b) + 1.0) / (r + 1.0)) * 100.0
    else:  # ShareType.No
        # Cost of buying 's' No shares
        cost = b * math.log((r + math.exp(s / b)) / (r + 1.0)) * 100.0

    return _round_cents(cost)
