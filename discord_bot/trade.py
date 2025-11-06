import logging
import traceback
from typing import Callable

from discord import (
    Interaction,
    Embed,
    Color,
    ui,
    User as discordUser,
    InteractionMessage,
    ButtonStyle,
)

from market.exchange import Exchange
from discord_bot.market_description import create_market_embed

LOGGER = logging.getLogger(__name__)


def require_author(func: Callable[["ConfirmView", Interaction, ui.Button], Coroutine]):
    """
    Decorator that checks if the interaction user is the author of the view.
    """

    async def wrapper(self: "ConfirmView", interaction: Interaction, button: ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "You are not authorized to do this.", ephemeral=True
            )
            return
        await func(self, interaction, button)

    return wrapper


class ConfirmView(ui.View):
    def __init__(self, author: discordUser, on_confirm: Callable, invalid_trade: bool):
        super().__init__(timeout=180)  # 3-minute timeout
        self.author = author
        self.on_confirm = on_confirm
        self.message: InteractionMessage | None = None
        if invalid_trade:
            self.confirm.disabled = True

    async def disable_buttons(self):
        for item in self.children:
            item.disabled = True

    async def on_timeout(self):
        if self.message:
            self.disable_buttons()
            await self.message.edit(content="⌛️ **Order Timed Out**", view=self)

    @ui.button(label="Confirm", style=ButtonStyle.green)
    @require_author
    async def confirm(self, interaction: Interaction, button: ui.Button):
        self.disable_buttons()
        await interaction.response.edit_message(view=self)
        self.on_confirm()

    @ui.button(label="Cancel", style=ButtonStyle.red)
    @require_author
    async def cancel(self, interaction: Interaction, button: ui.Button):
        self.disable_buttons()
        await interaction.response.edit_message(
            content="❌ **Order Cancelled.**", view=self, embed=None
        )


async def start_trade_flow(
    interaction: Interaction,
    is_yes_shares: bool,
    quantity: int,
    market_topic_ids: dict[int, int],
    exchange: Exchange,
):
    try:
        try:
            market_id = market_topic_ids[interaction.channel.id]
        except KeyError:
            await interaction.followup.send(
                content="❌ **Invalid location:** You can only trade inside a market topic."
            )
            return

        if market_id not in exchange.markets:
            LOGGER.warning(
                f"Trying to trade in market_id {market_id} which is missing from Exchange {exchange.markets}"
            )
            await interaction.followup.send(
                content="❌ **Could not find market in database:**"
            )
            return

        if quantity == 0:
            await interaction.followup.send(
                content="✅ **Traded zero shares:** To the mind that is still, the whole universe surrenders."
            )
            return

        # TODO: Decorator for actions that require being registered
        market = exchange.markets[market_id]
        user = market.users[market.discord_user_ids[interaction.user.id]]
        no_shares, yes_shares = user.positions.get(market_id, (0, 0))

        new_no_shares = no_shares + (quantity * (not is_yes_shares))
        new_yes_shares = yes_shares + (quantity * is_yes_shares)

        cost, new_yes_price, new_no_price = market.simulate_trade(
            new_no_shares=new_no_shares,
            new_yes_shares=new_yes_shares,
        )
        balance = user.balance
        new_balance = balance + cost

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

        long_desc = market.detailed_criteria
        embed = Embed(
            title=f"Order Preview: {market.question} (#{market.id})",
            description=f"Detailed criteria: *{long_desc}*" if long_desc else None,
            color=Color.red() if invalid_trade else Color.blue(),
        )
        # embed.set_author(name=f"Market #{market['id']} | Status: {market['status']}")

        # Market Info
        embed.add_field(
            name="Current Market Stats",
            value=(
                f"**Current prices:** Yes: $`{market.yes_price:.2f}` | No: $`{no_price:.2f}`\n"
                f"**Volume:** `{market.volume}`"
            ),
            inline=False,
        )

        # User Info
        embed.add_field(
            name="Your Position",
            value=(
                f"**Balance:** `${old_balance:,.2f}`\n"
                f"**Shares:** Yes: `{yes_shares}` | No: `{no_shares}`"
            ),
            inline=False,
        )

        # Trade Info
        embed.add_field(
            name="Proposed Trade",
            value=(
                f"**Action:** {action} `{abs_quantity}` **{trade['shareType']}** shares\n"
                f"**{cost_or_proceeds}:** `${abs(cost):,.2f}`"
            ),
            inline=False,
        )

        # Outcome Info
        embed.add_field(
            name="Projected Outcome",
            value=(
                f"**New Balance:** `${new_balance:,.2f}`\n"
                f"**New Prices:** Yes: $`{new_yes_price:.2f}` | No: $`{new_no_price:.2f}`"
            ),
            inline=False,
        )

        if invalid_trade:
            embed.set_footer(
                text=f"❌ **{invalid_reason}**",
            )

            def on_confirm():
                raise RuntimeError("on_confirm should not be possible")
        else:
            embed.set_footer(
                text="Please confirm your order. This will expire in 3 minutes."
            )

            def on_confirm():
                exchange.ledger.user_trade(
                    author=interaction.author,
                    user_id=user.id,
                    market_id=market.id,
                    share_type="Yes" if is_yes_shares else "No",
                    quantity=quantity,
                    cost=cost,
                    old_balance=balance,
                    new_balance=new_balanace,
                )

        view = ConfirmView(
            author=interaction.user,
            on_confirm=on_confirm,
            invalid_trade=invalid_trade,
        )

        message = await interaction.edit_original_response(
            content="", embed=embed, view=view
        )
        view.message = message

        # Update channel top message
        starter_message = await interaction.channel.fetch_message(
            interaction.channel.id
        )
        if starter_message:
            await starter_message.edit(content="", embed=create_market_embed(market))

    except Exception as e:
        LOGGER.error(
            f"An unexpected error occurred in trade command: {traceback.format_exc()}"
        )
        await interaction.followup.send(content="❌ **An unexpected error occurred.**")
