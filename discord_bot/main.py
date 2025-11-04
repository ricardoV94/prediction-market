import os
import discord
from discord import app_commands, ui
import requests
from dotenv import load_dotenv
from computation import simulate_liquidation_proceeds, _round_cents, ShareType

# --- Configuration ---
load_dotenv()
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
SCRIPT_URL = os.getenv("SCRIPT_URL")
API_TOKEN = os.getenv("API_TOKEN")

if not all([DISCORD_BOT_TOKEN, SCRIPT_URL, API_TOKEN]):
    print("FATAL: Missing one or more required environment variables.")
    exit(1)

# --- Bot Setup ---
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# --- UI Views ---
class ConfirmView(ui.View):
    def __init__(
        self,
        author: discord.User,
        market_id: str,
        share_type: ShareType,
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
    share_type: ShareType,
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


@tree.command(
    name="balance", description="Check your current balance and share holdings."
)
async def balance(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    try:
        params = {
            "token": API_TOKEN,
            "action": "getBalance",
            "discordHandle": str(interaction.user),
        }
        response = requests.get(SCRIPT_URL, params=params)
        response.raise_for_status()
        response_data = response.json()

        if response_data.get("ok"):
            user_data = response_data["data"]
            embed = discord.Embed(
                title="Your Portfolio",
                description=f"A summary for {interaction.user.mention}.",
                color=discord.Color.blue(),
            )

            cash_balance = float(user_data["balance"])
            embed.add_field(
                name="💰 Cash Balance", value=f"${cash_balance:,.2f}", inline=False
            )

            holdings = user_data.get("holdings", []) or []
            is_pnl_calculable = holdings and all(
                "liquidity" in h and "userYesCost" in h and "userNoCost" in h
                for h in holdings
            )

            if is_pnl_calculable:
                total_market_value = 0
                for h in holdings:
                    h["market_value"] = simulate_liquidation_proceeds(
                        h.get("pYes", 0.0),
                        h.get("liquidity"),
                        h.get("userYes", 0.0),
                        h.get("userNo", 0.0),
                    )
                    cost_basis = _round_cents(
                        h.get("userYesCost", 0.0) + h.get("userNoCost", 0.0)
                    )
                    h["pnl"] = pnl = _round_cents(h["market_value"] - cost_basis)
                    h["pnl_percent"] = (
                        (pnl / cost_basis) * 100 if cost_basis != 0 else 0
                    )
                    total_market_value += h["market_value"]

                net_worth = _round_cents(cash_balance + total_market_value)
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
                    value="You do not own any shares.",
                    inline=False,
                )
            else:
                try:
                    holdings.sort(key=lambda x: int(x["marketId"]))
                except (ValueError, TypeError):
                    holdings.sort(key=lambda x: x["marketId"])

                for holding in holdings:
                    field_name = f"📊 {holding['question']} (#{holding['marketId']})"
                    field_value = (
                        f"*p(Yes) = `{holding['pYes']:.2f}%` | Volume = `{int(holding['volume'])}`*\n"
                        f"Your Shares: `{holding['userYes']}` Yes / `{holding['userNo']}` No"
                    )

                    if is_pnl_calculable:
                        market_value = holding.get("market_value", 0.0)
                        pnl = holding.get("pnl", 0.0)
                        pnl_percent = holding.get("pnl_percent", 0)
                        pnl_sign = "" if pnl >= 0 else "-"
                        pct_pnl_sign = "+" if pnl >= 0 else ""
                        field_value += f"\nMarket value: `${market_value:,.2f}`"
                        field_value += f"\nUnrealized PnL: `{pnl_sign}${abs(pnl):,.2f} ({pct_pnl_sign}{pnl_percent:.2f}%)`"

                    embed.add_field(name=field_name, value=field_value, inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            error_message = response_data.get(
                "error", "An unknown script error occurred."
            )
            await interaction.followup.send(
                f"❌ **Could not fetch balance:** {error_message}"
            )

    except requests.exceptions.RequestException as e:
        print(f"Error calling Google Apps Script: {e}")
        await interaction.followup.send(
            "❌ **System Error:** Could not communicate with the backend service.",
        )
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        await interaction.followup.send("❌ **An unexpected error occurred.**")


# --- Run the bot ---
client.run(DISCORD_BOT_TOKEN)
