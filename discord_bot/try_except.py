import logging
import traceback
from functools import wraps
from typing import Callable, Coroutine

from discord import Interaction

LOGGER = logging.getLogger(__name__)


def handle_errors(func: Callable[..., Coroutine]):
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
                f"An unexpected error occurred in command '{func.__name__}': {traceback.format_exc()}"
            )
            error_message = "❌ **An unexpected error occurred.**"
            if interaction.response.is_done():
                await interaction.followup.send(error_message, ephemeral=True)
            else:
                await interaction.response.send_message(error_message, ephemeral=True)

    return wrapper


def requires_registration(exchange: Exchange):
    """
    A decorator factory that checks if the interaction user is registered.
    If registered, it passes the User object to the decorated function.
    """

    def decorator(func: Callable[..., Coroutine]):
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
            # Pass the user object to the decorated function
            await func(interaction, *args, user=user, **kwargs)

        return wrapper

    return decorator
