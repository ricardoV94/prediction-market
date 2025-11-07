import logging
from functools import wraps
from logging import getLogger
from os import getenv
from pathlib import Path
from pprint import pformat
from traceback import format_exc
from typing import Iterable

from discord import Client, Object, Intents, Interaction, app_commands
from dotenv import load_dotenv

from discord_bot.market_description import create_market_embed
from discord_bot.permissions import check_guild_factory, check_registered_factory
from discord_bot.status import show_balance, show_positions
from discord_bot.registration import start_registration_flow
from discord_bot.trade import start_trade_flow
from market.exchange import Ledger, Exchange


def setup_package_logging(
    package_names: Iterable[str] = ("discord_bot", "market"),
    level: int = logging.DEBUG,
    root_level: int = logging.WARNING,  # Keep libraries quiet (INFO/DEBUG hidden)
):
    # Configure root logger (affects all third-party libs)
    root = getLogger()
    root.setLevel(root_level)
    if not root.handlers:
        # Add a default StreamHandler for root if nothing is configured yet
        root_handler = logging.StreamHandler()
        root_handler.setLevel(root_level)
        root_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s: %(levelname)s: %(name)s: %(message)s",
                datefmt="%d/%m/%Y %H:%M:%S",
            )
        )
        root.addHandler(root_handler)

    # Configure your package loggers with their own handler at DEBUG
    for name in package_names:
        logger = getLogger(name)
        logger.setLevel(level)
        handler = logging.StreamHandler()
        handler.setLevel(level)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s: %(levelname)s: %(name)s: %(message)s",
                datefmt="%d/%m/%Y %H:%M:%S",
            )
        )
        # Optional: avoid duplicate handlers if this runs more than once
        logger.handlers.clear()
        logger.addHandler(handler)
        # Prevent records from bubbling to root (which might re-log them)
        logger.propagate = False


setup_package_logging(
    package_names=("discord_bot", "market"),
    level=logging.DEBUG,
)

LOGGER = getLogger(__name__)

load_dotenv()
DISCORD_BOT_TOKEN = getenv("DISCORD_BOT_TOKEN")
GUILD_ID = int(getenv("GUILD_ID"))
CHANNEL_ID = int(getenv("CHANNEL_ID"))

if not all([DISCORD_BOT_TOKEN, GUILD_ID, CHANNEL_ID]):
    LOGGER.error("FATAL: Missing one or more required environment variables.")
    exit(1)

ledger_path = Path("data/ledger.json")
ledger_path.parent.mkdir(parents=True, exist_ok=True)
ledger_path.touch(exist_ok=True)
LEDGER = Ledger.from_json(ledger_path)
del ledger_path
EXCHANGE = Exchange.from_ledger(LEDGER)
MARKET_TOPIC_IDS: dict[int, int] = {}

LOGGER.info(pformat(EXCHANGE.markets))
LOGGER.info(pformat(EXCHANGE.users))
LOGGER.info(pformat(f"{EXCHANGE.discord_user_ids=}"))


check_guild = check_guild_factory(GUILD_ID)
check_registered = check_registered_factory(EXCHANGE)


def handle_errors(func):
    """
    A decorator to handle exceptions in Discord bot commands.
    It logs the error and sends a generic error message to the user.
    """

    @wraps(func)
    async def wrapper(interaction: Interaction, *args, **kwargs):
        try:
            await func(interaction, *args, **kwargs)
        except Exception:
            LOGGER.error(
                f"An unexpected error occurred in command '{func.__name__}': {format_exc()}"
            )
            error_message = "❌ **An unexpected error occurred.**"
            if interaction.response.is_done():
                await interaction.followup.send(error_message, ephemeral=True)
            else:
                await interaction.response.send_message(error_message, ephemeral=True)

    return wrapper


intents = Intents.default()
client = Client(intents=intents)
tree = app_commands.CommandTree(client)


@client.event
async def on_ready():
    guild = Object(id=GUILD_ID)
    tree.copy_global_to(guild=guild)
    await tree.sync(guild=guild)
    LOGGER.info(f"Synced commands to guild: {GUILD_ID}")
    LOGGER.info(f"Logged in as {client.user.name} ({client.user.id})")

    forum_channel = client.get_channel(CHANNEL_ID)
    if not forum_channel:
        LOGGER.critical("Forum channel not found!")
        return

    # Get existing market threads
    exchange_markets = EXCHANGE.markets
    markets_with_threads = set()
    for thread in forum_channel.threads:
        try:
            market_id = int(thread.name.split("#")[-1][:-1])
            if market_id in exchange_markets:
                MARKET_TOPIC_IDS[thread.id] = market_id
                markets_with_threads.add(market_id)
            else:
                LOGGER.warning(
                    f"Found a market thread with id {market_id} that is not in the Exchange"
                )
        except (IndexError, ValueError):
            continue

    # Create threads for new markets
    for market_id, market in sorted(EXCHANGE.markets.items()):
        if market_id not in markets_with_threads:
            market_embed = create_market_embed(market)
            new_thread = await forum_channel.create_thread(
                name=f"{market.question} (#{market.id})", embed=market_embed
            )
            MARKET_TOPIC_IDS[new_thread.id] = market_id
            LOGGER.info(f"Created thread for market {market_id}")

    LOGGER.info(f"{MARKET_TOPIC_IDS=}")


@tree.command(
    name="register",
    description="Register in the Prediction Market with the Discord bot.",
)
@check_guild
@handle_errors
async def register(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    await start_registration_flow(interaction=interaction, exchange=EXCHANGE)


@tree.command(name="balance", description="Check your current balance.")
@check_registered
@check_guild
@handle_errors
async def balance(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    await show_balance(
        interaction=interaction,
        user_id=EXCHANGE.discord_user_ids[interaction.user.id],
        exchange=EXCHANGE,
    )


@tree.command(name="positions", description="Check your current holdings.")
@check_registered
@check_guild
@handle_errors
async def positions(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    await show_positions(
        interaction=interaction,
        user_id=EXCHANGE.discord_user_ids[interaction.user.id],
        exchange=EXCHANGE,
    )


@tree.command(
    name="trade", description="Buy shares in this market. Use negative quantity to sell"
)
@app_commands.describe(
    yes_shares="True: Yes shares, False: No shares",
    quantity="Number of shares to buy.",
)
@check_registered
@check_guild
@handle_errors
async def trade(
    interaction: Interaction,
    yes_shares: bool,
    quantity: int,
):
    await interaction.response.defer(ephemeral=True)
    await start_trade_flow(
        interaction=interaction,
        user_id=EXCHANGE.discord_user_ids[interaction.user.id],
        is_yes_shares=yes_shares,
        quantity=quantity,
        market_topic_ids=MARKET_TOPIC_IDS,
        exchange=EXCHANGE,
    )


client.run(DISCORD_BOT_TOKEN)
