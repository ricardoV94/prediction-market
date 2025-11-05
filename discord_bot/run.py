import traceback
import os
import discord
from discord import app_commands, ui
import requests
from dotenv import load_dotenv
from pprint import pprint

from market.exchange import Ledger, Exchange
from discord_bot.registration import start_registration_flow


# --- Configuration ---
load_dotenv()
DEBUG = True
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")

if not all([DISCORD_BOT_TOKEN]):
    print("FATAL: Missing one or more required environment variables.")
    exit(1)

# --- Setup ---
LEDGER = Ledger.from_json("data/ledger.json")
EXCHANGE = Exchange.from_ledger(LEDGER)
pprint(EXCHANGE.markets)
pprint(EXCHANGE.users)
pprint(EXCHANGE.discord_user_ids)
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# --- UI Views ---
class ConfirmView(ui.View):
    def __init__(
        self,
        author: discord.User,
        market_id: str,
        share_type: "str",
        quantity: int,
        cost: float,
        question: str,
        current_balance: float,
        user_id: str,
    ):
        super().__init__(timeout=180)  # 3-minute timeout
        self.author = author
        self.market_id = market_id
        self.share_type = share_type
        self.quantity = quantity
        self.cost = cost
        self.question = question
        self.current_balance = current_balance
        self.user_id = user_id
        self.message: discord.InteractionMessage | None = None

    async def on_timeout(self):
        if self.message:
            for item in self.children:
                item.disabled = True
            await self.message.edit(content="⌛️ **Order Timed Out**", view=self)

    @ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "You are not authorized to confirm this order.", ephemeral=True
            )
            return

        # Disable buttons and keep original message
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        # Send a new message for status updates
        status_message = await interaction.followup.send(
            "⏳ Executing trade...", wait=True
        )

        # 2. Execute the trade
        try:
            trade_payload = {
                "userId": self.user_id,
                "marketId": self.market_id,
                "shareType": self.share_type.value,
                "quantity": self.quantity,
                "userEmail": f"{interaction.user.name}@{interaction.user.id}",
            }
            print(f"Requesting trade execution with params: {trade_payload}")
            response = requests.post(
                SCRIPT_URL, json=trade_payload | {"token": API_TOKEN}
            )
            response.raise_for_status()
            trade_result = response.json()

            if trade_result.get("ok"):
                await status_message.edit(content="✅ **Trade Executed!**")
                await interaction.edit_original_response(view=None)
            else:
                error_message = trade_result.get(
                    "error", "An unknown error occurred during the trade."
                )
                await status_message.edit(
                    content=f"❌ **Trade Failed:** {error_message}"
                )
                await interaction.edit_original_response(view=None)

        except requests.exceptions.RequestException as e:
            await status_message.edit(
                content=f"❌ **System Error:** Could not execute the trade. {e}"
            )
            await interaction.edit_original_response(view=None)
        except Exception as e:
            await status_message.edit(
                content=f"❌ **An unexpected error occurred:** {e}"
            )
            await interaction.edit_original_response(view=None)

    @ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "You are not authorized to cancel this order.", ephemeral=True
            )
            return

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="❌ **Order Cancelled.**", view=self, embed=None
        )


# --- Bot Events ---
@client.event
async def on_ready():
    if GUILD_ID:
        guild = discord.Object(id=GUILD_ID)
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
        print(f"Synced commands to guild: {GUILD_ID}")
    else:
        await tree.sync()
        print("Synced commands globally.")
    print(f"Logged in as {client.user.name} ({client.user.id})")
    print("------")


# --- Slash Commands ---
@tree.command(
    name="register",
    description="Register in the Prediction Market with the Discord bot.",
)
async def register(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await start_registration_flow(interaction, EXCHANGE)


@tree.command(name="balance", description="Check your current balance.")
async def balance(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    try:
        try:
            user_id = EXCHANGE.discord_user_ids[interaction.user.id]
        except KeyError:
            if DEBUG:
                print(f"New user trying to check balance: {interaction.user}")
            await interaction.followup.send(
                "Seems like we haven't seen you before. Run `/register` first."
            )
        else:
            if DEBUG:
                print(f"User checking balance: {interaction.user}")
            balance = EXCHANGE.users[user_id].balance
            embed = discord.Embed(color=discord.Color.blue())
            embed.add_field(
                name="💰 Cash Balance:", value=f"${balance:,.2f}", inline=True
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    except Exception as e:
        if DEBUG:
            e = traceback.format_exc()
        print(f"An unexpected error occurred: {e}")
        await interaction.followup.send("❌ **An unexpected error occurred.**")
        raise


@tree.command(name="positions", description="Check your current holdings.")
async def positions(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    try:
        try:
            user_id = EXCHANGE.discord_user_ids[interaction.user.id]
        except KeyError:
            if DEBUG:
                print(f"New user trying to check balance: {interaction.user}")
            await interaction.followup.send(
                "Seems like we haven't seen you before. Run `/register` first."
            )
        else:
            user = EXCHANGE.users[user_id]
            markets = EXCHANGE.markets
            embed = discord.Embed(
                title="Your Portfolio",
                description=f"A summary for {user.user_name}.",
                color=discord.Color.blue(),
            )

            cash_balance = float(user.balance)
            embed.add_field(
                name="💰 Cash Balance", value=f"${cash_balance:,.2f}", inline=False
            )

            total_market_value = 0
            holdings = []
            for market_id, positions in user.positions.items():
                market = markets[market_id]
                market_value = market.simulate_liquidation_proceeds(*positions)
                holdings.append((market, positions, market_value))
                total_market_value += market_value

                # cost_basis = _round_cents(
                #     h.get("userYesCost", 0.0) + h.get("userNoCost", 0.0)
                # )
                # h["pnl"] = pnl = _round_cents(h["market_value"] - cost_basis)
                # h["pnl_percent"] = (
                #     (pnl / cost_basis) * 100 if cost_basis != 0 else 0
                # )

            net_worth = cash_balance + total_market_value
            embed.add_field(
                name="📈 Market Value",
                value=f"${total_market_value:,.2f}",
                inline=False,
            )
            embed.add_field(
                name="💼 Net Worth",
                value=f"${net_worth:,.2f}",
                inline=False,
            )

            if not holdings:
                embed.add_field(
                    name="📈 Share Holdings",
                    value="You do not own any shares. Go buy some!.",
                    inline=False,
                )
            else:
                holdings.sort(key=lambda x: x[0].id)

                for market, (no_positions, yes_positions), market_value in holdings:
                    field_name = f"📊 {market.question} (#{market.id})"
                    field_value = (
                        f"*p(Yes) = `{market.yes_price:.2f}%` | Volume = `{market.volume}`*\n"
                        f"Your Shares: `{yes_positions}` Yes / `{no_positions}` No\n"
                        f"Market value  `${market_value:,.2f}`"
                    )

                    # if is_pnl_calculable:
                    #     pnl = holding.get("pnl", 0.0)
                    #     pnl_percent = holding.get("pnl_percent", 0)
                    #     pnl_sign = "" if pnl >= 0 else "-"
                    #     pct_pnl_sign = "+" if pnl >= 0 else ""
                    #     field_value += f"\nUnrealized PnL: `{pnl_sign}${abs(pnl):,.2f} ({pct_pnl_sign}{pnl_percent:.2f}%)`"

                    embed.add_field(name=field_name, value=field_value, inline=False)

                await interaction.followup.send(embed=embed, ephemeral=True)

    except requests.exceptions.RequestException as e:
        print(f"Error calling Google Apps Script: {e}")
        await interaction.followup.send(
            "❌ **System Error:** Could not communicate with the backend service.",
        )
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        await interaction.followup.send("❌ **An unexpected error occurred.**")


@tree.command(
    name="trade", description="Buy or sell shares. Use a negative quantity to sell."
)
@app_commands.describe(
    market_id="The ID of the market.",
    share_type="The type of share.",
    quantity="Number of shares to trade. Positive to buy, negative to sell.",
)
async def trade(
    interaction: discord.Interaction,
    market_id: str,
    share_type: str,
    quantity: int,
):
    await interaction.response.send_message(
        "⏳ Retrieving trade information...", ephemeral=True
    )

    if quantity == 0:
        await interaction.edit_original_response(
            content="❌ **Invalid Quantity:** Please enter a non-zero number."
        )
        return

    try:
        # 1. Get trade preview data
        params = {
            "action": "getTradePreview",
            "discordHandle": str(interaction.user),
            "marketId": market_id,
            "shareType": share_type.value,
            "quantity": quantity,
        }
        print(f"Requesting trade preview with params: {params}")
        response = requests.get(SCRIPT_URL, params=params | {"token": API_TOKEN})
        print(f"Preview response status: {response.status_code}")
        if response.status_code != 200:
            print(f"Preview response text: {response.text}")
        response.raise_for_status()
        preview_response = response.json()

        if not preview_response.get("ok"):
            error = preview_response.get("error", "Failed to retrieve trade preview.")
            await interaction.edit_original_response(content=f"❌ **Error:** {error}")
            return

        data = preview_response["data"]
        user = data["user"]
        market = data["market"]
        trade = data["trade"]
        simulation = data["simulation"]
        holdings = data["userHoldings"]

        # 2. Create detailed embed
        action = "Buy" if quantity > 0 else "Sell"
        abs_quantity = abs(quantity)
        cost_or_proceeds = "Cost" if quantity > 0 else "Proceeds"

        long_desc = market.get("long_description")
        embed = discord.Embed(
            title=f"Order Preview: {market['description']}",
            description=f"Detailed criteria: *{long_desc}*" if long_desc else None,
            color=discord.Color.blue(),
        )
        embed.set_author(name=f"Market #{market['id']} | Status: {market['status']}")

        # Market Info
        embed.add_field(
            name="Current Market Stats",
            value=(
                f"**Current prices:** Yes: $`{market['pYes']:.2f}` | No: $`{market['pNo']:.2f}`\n"
                f"**Volume:** `{int(market.get('volume', 0))}`"
            ),
            inline=False,
        )

        # User Info
        embed.add_field(
            name="Your Position",
            value=(
                f"**Balance:** `${user['balance']:,.2f}`\n"
                f"**Shares:** Yes: `{holdings['yesShares']}` | No: `{holdings['noShares']}`"
            ),
            inline=False,
        )

        # Trade Info
        embed.add_field(
            name="Proposed Trade",
            value=(
                f"**Action:** {action} `{abs_quantity}` **{trade['shareType']}** shares\n"
                f"**{cost_or_proceeds}:** `${abs(trade['cost']):,.2f}`"
            ),
            inline=False,
        )

        # Outcome Info
        embed.add_field(
            name="Projected Outcome",
            value=(
                f"**New Balance:** `${simulation['newBalance']:,.2f}`\n"
                f"**New Prices:** Yes: $`{simulation['newPYes']:.2f}` | No: $`{simulation['newPNo']:.2f}`"
            ),
            inline=False,
        )

        embed.set_footer(
            text="Please confirm your order. This will expire in 3 minutes."
        )

        # 3. Send confirmation message
        view = ConfirmView(
            author=interaction.user,
            market_id=market_id,
            share_type=share_type,
            quantity=quantity,
            cost=trade["cost"],
            question=market["description"],
            current_balance=user["balance"],
            user_id=user["id"],
        )

        message = await interaction.edit_original_response(
            content="", embed=embed, view=view
        )
        view.message = message

    except requests.exceptions.RequestException as e:
        print(f"Error calling Google Apps Script: {e}")
        await interaction.edit_original_response(
            content="❌ **System Error:** Could not communicate with the backend service."
        )
    except Exception as e:
        print(f"An unexpected error occurred in trade command: {e}")
        await interaction.edit_original_response(
            content="❌ **An unexpected error occurred.**"
        )


# --- Run the bot ---
client.run(DISCORD_BOT_TOKEN)
