# Prediction Market

A prediction market project with a Discord bot integration.

## Repository layout
```
.
├─ discord_bot/           # Discord bot package (Python module)
├─ legacy_spreadsheets/   # Historical/legacy spreadsheet assets and notes
├─ market/                # Core market Python package
└─ pyproject.toml
```

- Packaging: Setuptools (via [pyproject.toml](https://github.com/ricardoV94/prediction-market/blob/main/pyproject.toml))
- Python: >= 3.11
- Libraries: discord, dotenv

## Quick start

Clone and install
```bash
git clone https://github.com/ricardoV94/prediction-market.git
cd prediction-market

# Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate

# Install the project (-e is optional)
pip install -e .
```

## Configuration

Set needed environment variables.

Example using an `.env` file:
```bash
# Discord bot
DISCORD_BOT_TOKEN=your-bot-token-here
DISCORD_GUILD_ID=
DISCORD_CHANNEL_ID=
```

TODO: Instructions for how to create a bot app on discord, invite, permissions needed, how to find guild/channel ids...

## Running

Run the Discord bot (from the repo root, after activating your venv and setting .env):
```bash
python discord_bot/run.py
```
