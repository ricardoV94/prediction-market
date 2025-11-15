from logging import getLogger

from discord import (
    ButtonStyle,
    Color,
    Embed,
    Interaction,
    ui,
)

from discord_bot.market_description import create_market_embed
from market.exchange import Exchange, Market, MarketStatus, Shares, User

LOGGER = getLogger(__name__)


async def start_trade_flow(
    interaction: Interaction,
    user_id: int,
    market_id: int,
    exchange: Exchange,
):
    LOGGER.debug(f"User considering trading: {interaction.user}")

    view = TradeView(
        exchange=exchange,
        market=exchange.markets[market_id],
        user=exchange.users[user_id],
    )
    await view.update_view(interaction)


class TradeView(ui.View):
    def __init__(
        self,
        exchange: Exchange,
        market: Market,
        user: User,
    ):
        super().__init__(timeout=180)  # 3-minute timeout
        self.exchange = exchange
        self.market = market
        self.user = user
        self.is_yes_shares = True
        self.quantity = 0
        self.last_trade_details = {}

        for child in self.children:
            if isinstance(child, ui.Button):
                if child.label == "Yes shares":
                    self.yes_button = child
                elif child.label == "No shares":
                    self.no_button = child

    def compute_trade_details(self) -> dict:
        market = self.market
        user = self.user
        quantity = self.quantity
        is_yes_shares = self.is_yes_shares

        balance = user.balance
        no_shares, yes_shares = user.positions.get(market.id, (0, 0))
        yes_price = market.yes_price

        traded_yes_shares = quantity * is_yes_shares
        traded_no_shares = quantity * (not is_yes_shares)

        cost, _new_no_price, new_yes_price = market.simulate_trade(
            traded_shares=Shares(no=traded_no_shares, yes=traded_yes_shares)
        )
        new_balance = balance - cost
        new_no_shares = no_shares + traded_no_shares
        new_yes_shares = yes_shares + traded_yes_shares

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

        self.last_trade_details = trade_details = {
            "balance": balance,
            "new_balance": new_balance,
            "no_shares": no_shares,
            "yes_shares": yes_shares,
            "traded_yes_shares": traded_yes_shares,
            "traded_no_shares": traded_no_shares,
            "new_no_shares": new_no_shares,
            "new_yes_shares": new_yes_shares,
            "yes_price": yes_price,
            "new_yes_price": new_yes_price,
            "cost": cost,
            "invalid_trade": invalid_trade,
            "invalid_reason": invalid_reason,
        }
        return trade_details

    def embed(self, trade_details) -> Embed:
        balance = trade_details["balance"]
        new_balance = trade_details["new_balance"]
        new_no_shares = trade_details["new_no_shares"]
        new_yes_shares = trade_details["new_yes_shares"]
        yes_price = trade_details["yes_price"]
        new_yes_price = trade_details["new_yes_price"]
        cost = trade_details["cost"]
        invalid_trade = trade_details["invalid_trade"]
        invalid_reason = trade_details["invalid_reason"]

        is_yes_shares = self.is_yes_shares
        quantity = self.quantity
        market = self.market

        # Create detailed embed
        action = "Buy" if quantity >= 0 else "Sell"
        abs_quantity = abs(quantity)
        cost_or_proceeds = "Cost" if quantity > 0 else "Proceeds"

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
            value=f"{action} **{abs_quantity}** {'Yes' if is_yes_shares else 'No'} shares",
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
        else:
            embed.set_footer(
                text="Please confirm your order. This will expire in 3 minutes."
            )
        return embed

    async def update_view(self, interaction: Interaction):
        trade_details = self.compute_trade_details()
        self.confirm.disabled = trade_details["invalid_trade"]
        embed = self.embed(trade_details)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="Yes shares", style=ButtonStyle.primary, row=0)
    async def select_yes(self, interaction: Interaction, button: ui.Button):
        self.is_yes_shares = True
        self.yes_button.style = ButtonStyle.primary
        self.no_button.style = ButtonStyle.secondary
        await self.update_view(interaction)

    @ui.button(label="No shares", style=ButtonStyle.secondary, row=0)
    async def select_no(self, interaction: Interaction, button: ui.Button):
        self.is_yes_shares = False
        self.yes_button.style = ButtonStyle.secondary
        self.no_button.style = ButtonStyle.primary
        await self.update_view(interaction)

    @ui.button(label="+ 1", style=ButtonStyle.gray, row=1)
    async def add_1(self, interaction: Interaction, button: ui.Button):
        self.quantity += 1
        await self.update_view(interaction)

    @ui.button(label="+ 5", style=ButtonStyle.gray, row=1)
    async def add_5(self, interaction: Interaction, button: ui.Button):
        self.quantity += 5
        await self.update_view(interaction)

    @ui.button(label="+ 10", style=ButtonStyle.gray, row=1)
    async def add_10(self, interaction: Interaction, button: ui.Button):
        self.quantity += 10
        await self.update_view(interaction)

    @ui.button(label="- 5", style=ButtonStyle.gray, row=1)
    async def subtract_5(self, interaction: Interaction, button: ui.Button):
        self.quantity -= 5
        await self.update_view(interaction)

    @ui.button(label="- 1", style=ButtonStyle.gray, row=1)
    async def subtract_1(self, interaction: Interaction, button: ui.Button):
        self.quantity -= 1
        await self.update_view(interaction)

    @ui.button(label="Confirm", style=ButtonStyle.green, row=2)
    async def confirm(self, interaction: Interaction, button: ui.Button):
        await interaction.response.edit_message(view=None)

        info = self.last_trade_details.copy()
        if self.compute_trade_details() != info:
            await self.update_view(interaction)
            await interaction.followup.send(
                "⚠️ **Trade details have changed. Please review and confirm again.**",
                ephemeral=True,
            )
            return

        if info["invalid_trade"]:
            return

        self.stop()

        # TODO: Add lock to avoid race conditions
        self.exchange.ledger.user_trade(
            author=interaction.user,
            user_id=self.user.id,
            market_id=self.market.id,
            share_type="Yes" if self.is_yes_shares else "No",
            quantity=self.quantity,
            cost=info["cost"],
            old_balance=info["balance"],
            new_balance=info["new_balance"],
        )

        await interaction.followup.send("✅ **Trade successful!**", ephemeral=True)
        await interaction.followup.send(
            f"👀 Someone traded {self.quantity} shares. Δ P(yes) {info['yes_price']:.2f}% → {info['new_yes_price']:.2f}%",
            ephemeral=False,
        )
        starter_message = await interaction.channel.fetch_message(
            interaction.channel.id
        )
        if starter_message:
            updated_market = self.exchange.markets[self.market.id]
            await starter_message.edit(embed=create_market_embed(updated_market))

    @ui.button(label="Cancel", style=ButtonStyle.red, row=2)
    async def cancel(self, interaction: Interaction, button: ui.Button):
        self.stop()
        await interaction.response.edit_message(view=None)
        await interaction.followup.send("❌ **Order Cancelled.**", ephemeral=True)
