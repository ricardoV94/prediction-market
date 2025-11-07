from logging import getLogger

from discord import Color, Embed, Interaction

from market.exchange import Exchange


LOGGER = getLogger(__name__)


async def show_balance(interaction: Interaction, user_id: int, exchange: Exchange):
    LOGGER.debug(f"User checking balance: {interaction.user}")
    balance = exchange.users[user_id].balance
    embed = Embed(color=Color.blue())
    embed.add_field(name="💰 Cash Balance:", value=f"${balance:,.2f}", inline=True)
    await interaction.followup.send(embed=embed)


def get_price_color_code(price: float) -> str:
    """Returns the ANSI color code based on the market price."""
    if price < 20:
        return "[1;31m"  # Red (bold)
    elif price < 40:
        return "[0;31m"  # Red
    elif price < 60:
        return "[0;90m"  # Gray
    elif price < 80:
        return "[0;34m"  # Blue
    else:
        return "[1;34m"  # Blue (bold)


async def show_positions(interaction: Interaction, user_id: int, exchange: Exchange):
    LOGGER.debug(f"User checking positions: {interaction.user}")
    user = exchange.users[user_id]
    markets = exchange.markets
    cash_balance = user.balance

    total_shares = 0
    total_market_value = 0
    holdings = []
    for market_id, (no_shares, yes_shares) in user.positions.items():
        market = markets[market_id]
        market_value = market.simulate_liquidation_proceeds(no_shares, yes_shares)
        holdings.append((market, (no_shares, yes_shares), market_value))
        total_shares += no_shares + yes_shares
        total_market_value += market_value

        # cost_basis = _round_cents(
        #     h.get("userYesCost", 0.0) + h.get("userNoCost", 0.0)
        # )
        # h["pnl"] = pnl = _round_cents(h["market_value"] - cost_basis)
        # h["pnl_percent"] = (
        #     (pnl / cost_basis) * 100 if cost_basis != 0 else 0
        # )

    net_worth = cash_balance + total_market_value

    embed = Embed(
        title="Your Portfolio",
    )

    embed.add_field(
        name="**💰 Cash**",
        value=f"${cash_balance:,.2f}",
        inline=True,
    )
    embed.add_field(
        name="**📈 Shares**",
        value=f"{total_shares} (${total_market_value:,.2f})",
        inline=True,
    )
    embed.add_field(
        name="**💼 Net Worth**",
        value=f"${net_worth:,.2f}",
        inline=True,
    )

    # Add a separator line before listing the holdings
    if not holdings:
        embed.add_field(
            name="**🔮 Share Holdings",
            value="You do not own any shares. Go buy some!",
            inline=False,
        )
    else:
        # Add a separator line in a field with a zero-width name
        embed.add_field(name="\u200b", value="** 🔮Share Holdings**", inline=False)

        holdings.sort(key=lambda x: x[0].id)

        for market, (no_positions, yes_positions), market_value in holdings:
            field_name = f"• **{market.question}** (#{market.id})"

            yes_price = market.yes_price
            price_color = get_price_color_code(yes_price)

            yes_str = f"[0;34m{yes_positions} Yes[0m"
            no_str = f"[0;31m{no_positions} No[0m"
            if yes_positions and no_positions:
                shares_line = f"{no_str} | {yes_str}"
            elif yes_positions:
                shares_line = yes_str
            elif no_positions:
                shares_line = no_str
            else:
                shares_line = "0"

            field_value = (
                f"```ansi\n"
                f"P(yes): {price_color}{market.yes_price:.1f}%[0m | Volume: {market.volume}\n"
                f"Shares: {shares_line}\n"
                f"Value : ${market_value:,.2f}"
                "```"
            )

            # if is_pnl_calculable:
            #     pnl = holding.get("pnl", 0.0)
            #     pnl_percent = holding.get("pnl_percent", 0)
            #     pnl_sign = "" if pnl >= 0 else "-"
            #     pct_pnl_sign = "+" if pnl >= 0 else ""
            #     field_value += f"\nUnrealized PnL: `{pnl_sign}${abs(pnl):,.2f} ({pct_pnl_sign}{pnl_percent:.2f}%)`"

            embed.add_field(name=field_name, value=field_value, inline=False)

    await interaction.followup.send(embed=embed, ephemeral=True)
