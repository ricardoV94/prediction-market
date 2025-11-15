from functools import wraps
from logging import getLogger
from typing import Callable, Coroutine

from discord import Interaction, ui

from market.exchange import Exchange

LOGGER = getLogger(__name__)


def check_guild_factory(guild_id: int):
    def decorator(func):
        @wraps(func)
        async def wrapper(interaction: Interaction, *args, **kwargs):
            if interaction.guild_id != guild_id:
                await interaction.response.send_message(
                    "This bot cannot be used on this server.", ephemeral=True
                )
                return
            else:
                return await func(interaction, *args, **kwargs)

        return wrapper

    return decorator


def check_registered_factory(exchange: Exchange):
    """
    A decorator factory that checks if the interaction user is registered.
    If registered, it passes the User object to the decorated function.
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(interaction: Interaction, *args, **kwargs):
            try:
                user_id = exchange.discord_user_ids[interaction.user.id]
                user = exchange.users[user_id]
            except KeyError:
                LOGGER.debug(
                    f"Unregistered user {interaction.user} tried to use '{func.__name__}'"
                )
                # Ensure the interaction is responded to before sending a followup
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
                await interaction.followup.send(
                    "Seems like we haven't seen you before. Run `/register` first.",
                    ephemeral=True,
                )
                return

            await func(interaction, *args, **kwargs)

        return wrapper

    return decorator
