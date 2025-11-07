from logging import getLogger

from discord import ButtonStyle, Interaction, InteractionMessage, ui

from discord_bot.permissions import require_author
from market.exchange import Exchange

OLD_SIGNUP_BONUS = 5_000.0
NEW_SIGNUP_BALANCE = 10_000.0

LOGGER = getLogger(__name__)


async def start_registration_flow(
    interaction: Interaction,
    exchange: Exchange,
):
    if interaction.user.id in exchange.discord_user_ids:
        LOGGER.debug(
            f"Registered user tried to register again: {interaction.user} with id {interaction.user.id}"
        )
        await interaction.followup.send(
            "You are already registered. "
            "Use `/balance`, or `/positions` to check your status."
        )
    else:
        LOGGER.info(f"Registering new user: {interaction.user}")
        view = RegistrationView(interaction, exchange=exchange)
        await interaction.followup.send(
            "Were you already registered in the old Google Spreadsheet?",
            view=view,
        )


class RegistrationView(ui.View):
    def __init__(
        self,
        interaction: Interaction,
        exchange: Exchange,
    ):
        super().__init__()
        self.author = interaction.user
        self.exchange = exchange

    @ui.button(label="Yes", style=ButtonStyle.green)
    @require_author
    async def yes(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_modal(
            SpreadSheetRegistrationModel(exchange=self.exchange)
        )

    @ui.button(label="No", style=ButtonStyle.red)
    @require_author
    async def no(self, interaction: Interaction, button: ui.Button):
        for item in self.children:
            item.disabled = True

        new_user_id = len(self.exchange.users) + 1

        self.exchange.ledger.update_user(
            author=interaction.user,
            user_id=new_user_id,
            user_name=self.author.name,
            discord_id=interaction.user.id,
            reason="registered on discord",
        )

        self.exchange.ledger.update_balance(
            author=interaction.user,
            user_id=new_user_id,
            delta=NEW_SIGNUP_BALANCE,
            old_balance=0.0,
            new_balance=NEW_SIGNUP_BALANCE,
            reason="initial balance",
        )

        await interaction.response.send_message(
            (
                "✅ You are now registered. "
                f"You have been granted an initial balance of ${int(NEW_SIGNUP_BALANCE):,}. "
                "Go wild (with calibration)!"
            ),
            ephemeral=True,
        )


class SpreadSheetRegistrationModel(ui.Modal, title="Registered in old Spreadsheet"):
    id_text_field = ui.TextInput(
        label="Id or username in the old SpreadSheet?",
        required=True,
    )

    def __init__(self, exchange: Exchange):
        super().__init__()
        self.exchange = exchange

    async def on_submit(self, interaction: Interaction):
        old_id_or_username = self.id_text_field.value
        current_users = self.exchange.users
        LOGGER.debug(f"Trying to find old user {old_id_or_username}")
        try:
            old_id = int(old_id_or_username.strip())
        except Exception:
            old_id = None

        if old_id in current_users:
            # Success
            old_user = current_users[old_id]

        else:
            registered_discord_ids = self.exchange.discord_user_ids
            old_username = old_id_or_username.strip().lower()
            # Try to check if any user name matches provided (case isensitive)
            for old_id, old_user in current_users.items():
                if old_id in registered_discord_ids:
                    # Skip previously registered Ids
                    continue
                if old_user.user_name.lower() == old_username:
                    break  # match
            else:  # no-break
                LOGGER.info(
                    f"Failed to find user {old_id_or_username}. Could be missing are already registered"
                )
                await interaction.response.send_message(
                    "❌ Failed to find username or id in current database.",
                    ephemeral=True,
                )
                return

        self.exchange.ledger.update_user(
            author=interaction.user,
            user_id=old_user.id,
            user_name=old_user.user_name,
            discord_id=interaction.user.id,
            reason="re-registered on discord",
        )

        self.exchange.ledger.update_balance(
            author=interaction.user,
            user_id=old_user.id,
            delta=OLD_SIGNUP_BONUS,
            old_balance=old_user.balance,
            new_balance=old_user.balance + OLD_SIGNUP_BONUS,
            reason="re-registered bonus",
        )

        await interaction.response.send_message(
            (
                f"✅ Welcome back {old_user.user_name}. All your positions are restored."
                f"You have been granted an additional bonus of ${int(OLD_SIGNUP_BONUS):,}. "
                "Go wild (with calibration)!"
            ),
            ephemeral=True,
        )
