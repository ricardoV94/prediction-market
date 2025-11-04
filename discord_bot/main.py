import os
import discord
from discord.types.embed import EmbedType
import requests
from discord import app_commands
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
@tree.command(name="buy", description="Place an order to buy shares in a market.")
@app_commands.describe(
    market_id="The ID of the market.",
    share_type="The type of share.",
    quantity="The number of shares.",
)
async def buy(
    interaction: discord.Interaction,
    market_id: str,
    share_type: ShareType,
    quantity: int,
):
    await interaction.response.defer()
    reply = (
        f"✅ **Order Received!**\n\n"
        f"You submitted an order to buy **{quantity}** shares of type **'{share_type.value}'** "
        f"for market **'{market_id}'**."
    )
    await interaction.followup.send(reply)


@tree.command(
    name="balance", description="Check your current balance and share holdings."
)
async def balance(interaction: discord.Interaction):
    await interaction.response.defer()

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
            # Check if backend provides the necessary data for PnL calculation
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
                    h["pnl_percent"] = (pnl / cost_basis) * 100
                    total_market_value += h["market_value"]

                net_worth = _round_cents(cash_balance + total_market_value)
                # TODO: Get this from table
                # starting_balance = 10000.0
                # pnl = net_worth - starting_balance
                # pnl_percent = (pnl / starting_balance) * 100
                # embed.add_field(
                #     name="📈 Unrealized PnL",
                #     value=f"${pnl:,.2f} ({pnl_percent:.2f}%)",
                #     inline=True,
                # )

                embed.add_field(
                    name="📈 Market value",
                    value=f"${total_market_value:,.2f}",
                    inline=False,
                )

                embed.add_field(
                    name="💼 Net worth ",
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

            await interaction.followup.send(embed=embed)
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
            "❌ **System Error:** Could not communicate with the backend service."
        )
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        await interaction.followup.send("❌ **An unexpected error occurred.**")


# --- Run the bot ---
client.run(DISCORD_BOT_TOKEN)
