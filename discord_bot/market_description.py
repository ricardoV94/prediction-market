from datetime import datetime

import discord

from market.exchange import Market, MarketStatus


async def update_market_top_post(thread, market: Market):
    starter_message = await thread.fetch_message(thread.id)
    await starter_message.edit(
        content=market_sentiment(market),
        embed=create_market_embed(market),
    )


def market_sentiment(market: Market) -> str:
    price_yes = market.yes_price
    if price_yes < 5:
        sentiment = "Not happening"
    elif price_yes < 20:
        sentiment = "Strong no"
    elif price_yes < 40:
        sentiment = "Leaning no"
    elif price_yes <= 60:
        sentiment = "Toss-up"
    elif price_yes <= 80:
        sentiment = "Leaning yes"
    elif price_yes <= 95:
        sentiment = "Strong yes"
    else:
        sentiment = "Sure thing"
    return sentiment


def color_for_market(market: Market):
    if market.status == MarketStatus.resolved_yes:
        return 0x0000FF  # Pure blue
    if market.status == MarketStatus.resolved_no:
        return 0xFF0000  # Pure red

    price_yes = market.yes_price
    if price_yes < 20:
        return 0xFF0000  # Pure red
    elif price_yes < 40:
        return 0xFFCCCB  # Light Red
    elif price_yes <= 60:
        return 0x808080  # Gray
    elif price_yes <= 80:
        return 0xADD8E6  # Light Blue
    else:
        return 0x0000FF  # Pure Blue


def create_market_embed(market: Market) -> discord.Embed:
    """Creates a Discord Embed for a given market."""

    embed = discord.Embed(
        title=market.question,
        description=market.detailed_criteria,
        color=color_for_market(market),
        timestamp=datetime.now(),  # Shows when it was last updated
    )

    # Add price and volume fields
    embed.add_field(name="P(Yes)%", value=f"{market.yes_price:.2f}", inline=True)
    embed.add_field(name="Volume", value=str(market.volume), inline=True)

    # Add status and close date
    embed.add_field(name="Status", value=market.status.name.title(), inline=True)
    embed.add_field(
        name="Opens", value=market.open_date.strftime("%b %d, %Y"), inline=True
    )
    embed.add_field(
        name="Closes", value=market.close_date.strftime("%b %d, %Y"), inline=True
    )
    embed.set_footer(text=f"Market ID: {market.id} | Last Updated")

    return embed
