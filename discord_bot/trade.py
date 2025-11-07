from logging import getLogger
from typing import Callable

from discord import (
    ButtonStyle,
    Color,
    Embed,
    Interaction,
    InteractionMessage,
    ui,
)
from discord import User as discordUser

from discord_bot.market_description import create_market_embed
from discord_bot.permissions import require_author
from market.exchange import Exchange, MarketStatus, Shares

LOGGER = getLogger(__name__)


async def start_trade_flow(
    interaction: Interaction,
    user_id: int,
    market_id: int,
    is_yes_shares: bool,
    quantity: int,
    exchange: Exchange,
):
    LOGGER.debug(f"User considering trading: {interaction.user}")

    if quantity == 0:
        await interaction.followup.send(
            content="✅ **Traded zero shares:** To the mind that is still, the whole universe surrenders."
        )
        return

    # TODO: Decorator for actions that require being registered
    market = exchange.markets[market_id]
    user = exchange.users[user_id]
    balance = user.balance
    no_shares, yes_shares = user.positions.get(market_id, (0, 0))
    yes_price = market.yes_price

    traded_yes_shares = quantity * is_yes_shares
    traded_no_shares = quantity * (not is_yes_shares)

    cost, new_no_price, new_yes_price = market.simulate_trade(
        traded_shares=Shares(no=traded_no_shares, yes=traded_yes_shares)
    )
    new_balance = balance - cost
    new_no_shares = no_shares + traded_no_shares
    new_yes_shares = yes_shares + traded_yes_shares

    # Create detailed embed
    action = "Buy" if quantity >= 0 else "Sell"
    abs_quantity = abs(quantity)
    cost_or_proceeds = "Cost" if quantity > 0 else "Proceeds"

    invalid_trade = False
    invalid_reason = ""
    if new_no_shares < 0 or new_yes_shares < 0:
        invalid_trade = True
        invalid_reason = "Trying to sell more shares than owned"
    elif new_balance < 0:
        invalid_trade = True
        invalid_reason = "Insufficient balance"
    elif market.status != MarketStatus.open:
        invalid_trade = True
        invalid_reason = "Market not open"

    long_desc = market.detailed_criteria
    embed = Embed(
        title=f"Order Preview: {market.question}",
        description=f"Detailed criteria: *{long_desc}*" if long_desc else None,
        color=Color.red() if invalid_trade else Color.green(),
    )

    date_format = "%d-%m-%Y"
    status_text = ""
    if market.status == MarketStatus.open:
        status_text = f"Open {market.open_date.strftime(date_format)} -> {market.close_date.strftime(date_format)} (UTC)"
    else:
        # Incorporate resolved/closed dates
        status_text = market.status.name
    embed.set_author(name=f"Market: #{market.id} | Status: {status_text}")

    # Market Info
    embed.add_field(
        name="Yes Price",
        value=f"${market.yes_price:.2f}",
        inline=True,
    )

    embed.add_field(
        name="No Price",
        value=(f"${market.no_price:.2f}"),
        inline=True,
    )

    embed.add_field(
        name="Volume",
        value=str(market.volume),
        inline=True,
    )

    embed.add_field(name="", value="", inline=False)

    embed.add_field(
        name="Action",
        value=f"{action} {abs_quantity} {'Yes' if is_yes_shares else 'No'} shares",
        inline=True,
    )

    embed.add_field(
        name=cost_or_proceeds,
        value=f"${abs(cost):,.2f}",
        inline=True,
    )

    new_holdings = ""
    if new_no_shares and new_yes_shares:
        new_holdings = f"{new_no_shares} No | {new_yes_shares} Yes"
    elif new_no_shares:
        new_holdings = f"{new_no_shares} No shares"
    else:
        new_holdings = f"{new_yes_shares} Yes shares"

    embed.add_field(
        name="New holdings",
        value=new_holdings,
        inline=True,
    )

    embed.add_field(name="", value="", inline=False)

    embed.add_field(
        name="Δ Balance",
        value=f"{balance:,.2f} → ${new_balance:,.2f}",
        inline=True,
    )

    embed.add_field(
        name="Δ P(yes)",
        value=f"{yes_price:.2f}% → {new_yes_price:.2f}%",
        inline=True,
    )

    embed.add_field(name="", value="", inline=True)

    if invalid_trade:
        embed.set_footer(
            text=f"❌ {invalid_reason}",
        )

        def on_confirm():
            raise RuntimeError("on_confirm should not be possible")
    else:
        embed.set_footer(
            text="Please confirm your order. This will expire in 3 minutes."
        )

        def on_confirm():
            exchange.ledger.user_trade(
                author=interaction.user,
                user_id=user.id,
                market_id=market.id,
                share_type="Yes" if is_yes_shares else "No",
                quantity=quantity,
                cost=cost,
                old_balance=balance,
                new_balance=new_balance,
            )
            # Trigger update by accessing market
            return exchange.markets[market.id], quantity

    view = ConfirmView(
        interaction=interaction,
        on_confirm=on_confirm,
        invalid_trade=invalid_trade,
    )

    await interaction.edit_original_response(content="", embed=embed, view=view)


class ConfirmView(ui.View):
    def __init__(
        self,
        interaction: Interaction,
        on_confirm: Callable,
        invalid_trade: bool,
    ):
        super().__init__(timeout=180)  # 3-minute timeout
        self.interaction = interaction
        self.author = interaction.user
        self.on_confirm = on_confirm
        if invalid_trade:
            for child in self.children:
                if isinstance(child, ui.Button) and child.label == "Confirm":
                    child.disabled = True

    async def on_timeout(self):
        await self.interaction.edit_original_response(view=None)
        await self.interaction.followup.send("⌛️ **Order Timed Out**", ephemeral=True)

    @ui.button(label="Confirm", style=ButtonStyle.green)
    @require_author
    async def confirm(self, interaction: Interaction, button: ui.Button):
        await interaction.response.edit_message(view=None)
        updated_market, shares_traded = self.on_confirm()

        await interaction.followup.send("✅ **Trade successful!**", ephemeral=True)
        starter_message = await interaction.channel.fetch_message(
            interaction.channel.id
        )
        if starter_message:
            await starter_message.edit(embed=create_market_embed(updated_market))
        await interaction.followup.send(
            f"👀 Someone traded {shares_traded} shares", ephemeral=False
        )
        self.stop()

    @ui.button(label="Cancel", style=ButtonStyle.red)
    @require_author
    async def cancel(self, interaction: Interaction, button: ui.Button):
        await interaction.response.edit_message(view=None)
        await interaction.followup.send("❌ **Order Cancelled.**", ephemeral=True)
        self.stop()
