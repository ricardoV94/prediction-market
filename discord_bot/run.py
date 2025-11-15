import logging
from functools import wraps
from logging import getLogger
from os import getenv
from pathlib import Path
from pprint import pformat
from traceback import format_exc
from typing import Iterable, Literal

from discord import Client, Intents, Interaction, Object, app_commands
from dotenv import load_dotenv

from discord_bot.market_description import create_market_embed
from discord_bot.permissions import check_guild_factory, check_registered_factory
from discord_bot.registration import start_registration_flow
from discord_bot.status import show_balance, show_positions
from discord_bot.trade import start_trade_flow
from market.exchange import Exchange, Ledger


def setup_package_logging(
    package_names: Iterable[str] = ("discord_bot", "market"),
    level: int = logging.DEBUG,
    root_level: int = logging.WARNING,  # Keep libraries quiet (INFO/DEBUG hidden)
    log_file: Path | str | None = None,
):
    formatter = logging.Formatter(
        "%(asctime)s: %(levelname)s: %(name)s: %(message)s",
        datefmt="%d/%m/%Y %H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    file_handler = None
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, mode="a")
        file_handler.setFormatter(formatter)

    # Configure root logger
    root = getLogger()
    root.setLevel(root_level)
    root.handlers.clear()
    root.addHandler(stream_handler)
    if file_handler is not None:
        root.addHandler(file_handler)

    # Configure your package loggers
    for name in package_names:
        logger = getLogger(name)
        logger.setLevel(level)
        logger.handlers.clear()
        logger.propagate = False  # Prevent double-logging to root
        logger.addHandler(stream_handler)
        logger.setLevel(level)
        if file_handler is not None:
            logger.addHandler(file_handler)


setup_package_logging(
    package_names=("discord_bot", "market"),
    level=logging.DEBUG,
    log_file="data/discord_bot.log",
)

LOGGER = getLogger("discord_bot.run")

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


client = Client(intents=Intents.default())
tree = app_commands.CommandTree(client)


@client.event
async def on_ready():
    print("READY")
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
            thread_with_message = await forum_channel.create_thread(
                name=f"{market.question} (#{market.id})", embed=market_embed
            )
            MARKET_TOPIC_IDS[thread_with_message.thread.id] = market_id
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


@tree.command(name="trade", description="Buy or sell shares in this market")
@check_registered
@check_guild
@handle_errors
async def trade(
    interaction: Interaction,
):
    await interaction.response.defer(ephemeral=True)

    try:
        market_id = MARKET_TOPIC_IDS[interaction.channel.id]
    except KeyError:
        # Sometimes on_ready doesn't read the existing topics
        try:
            market_id = int(interaction.channel.name.split("#")[-1][:-1])
        except (IndexError, ValueError):
            LOGGER.debug(
                f"User {interaction.user} tried to trade outside of a market topic"
            )
            await interaction.followup.send(
                content="❌ **Invalid location:** You can only trade inside a market topic."
            )
            return
        else:
            if market_id in EXCHANGE.markets:
                LOGGER.warn(
                    f"User {interaction.user} trading in a market topic {market_id} that was not previously known"
                )
                MARKET_TOPIC_IDS[interaction.channel.id] = market_id
            else:
                LOGGER.error(
                    f"User {interaction.user} trading in a market topic {market_id} that is not in Exchange"
                )
                await interaction.followup.send(
                    content="❌ **Error:** Bot is not aware of this market. Please inform admin."
                )
                return

    await start_trade_flow(
        interaction=interaction,
        exchange=EXCHANGE,
        market_id=market_id,
        user_id=EXCHANGE.discord_user_ids[interaction.user.id],
    )


client.run(DISCORD_BOT_TOKEN)
