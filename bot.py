import json
import os
import difflib

import discord
from discord import app_commands
from discord.ext import commands

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "cards.json")

with open(DATA_PATH, "r", encoding="utf-8") as f:
    CARDS = json.load(f)  # keys are normalized to UPPERCASE at lookup time

COLOR_MAP = {
    "Red": 0xE3352E,
    "Green": 0x3E9E4F,
    "Blue": 0x2E7CE3,
    "Purple": 0x8A3EE3,
    "Black": 0x2B2B2B,
    "Yellow": 0xE3C82E,
}

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


def find_card(code: str):
    code = code.strip().upper()
    if code in CARDS:
        return code, CARDS[code]
    # try close matches for typos
    close = difflib.get_close_matches(code, CARDS.keys(), n=3, cutoff=0.5)
    return None, close


def build_embed(code: str, card: dict, art_index: int = 0) -> discord.Embed:
    # art_index 0 = normal art, 1+ = alt_arts list (1-indexed for humans)
    alt_arts = card.get("alt_arts", [])
    if art_index == 0:
        image_url = card.get("image_url")
        art_label = ""
    else:
        pos = art_index - 1
        if pos < 0 or pos >= len(alt_arts):
            image_url = card.get("image_url")
            art_label = " (alt art not found, showing normal)"
        else:
            image_url = alt_arts[pos]
            art_label = f" [Alt Art {art_index}]"

    embed = discord.Embed(
        title=f"{card['name']} ({code}){art_label}",
        description=card.get("effect") or "No effect text.",
        color=COLOR_MAP.get(card.get("color"), 0x888888),
    )
    if image_url:
        embed.set_thumbnail(url=image_url)
        embed.set_image(url=image_url)

    if card["card_type"] == "Leader":
        embed.add_field(name="Power", value=str(card.get("power", "-")))
        embed.add_field(name="Life", value=str(card.get("life", "-")))
    else:
        embed.add_field(name="Cost", value=str(card.get("cost", "-")))
        embed.add_field(name="Power", value=str(card.get("power", "-")))
        embed.add_field(name="Counter", value=str(card.get("counter", "-")))

    embed.add_field(name="Color", value=card.get("color", "-"))
    embed.add_field(name="Type", value=", ".join(card.get("types", [])) or "-")
    embed.add_field(name="Rarity / Set", value=f"{card.get('rarity','-')} / {card.get('set','-')}")

    if card.get("devil_fruit"):
        embed.add_field(name="Devil Fruit", value=card["devil_fruit"], inline=False)

    if alt_arts and art_index == 0:
        embed.add_field(
            name="Alt Art Available",
            value=f"This card has {len(alt_arts)} alt art version(s). Use the buttons below to browse.",
            inline=False,
        )

    embed.set_footer(text=f"One Piece TCG Card Lookup{'' if len(alt_arts)==0 else f' — Art {art_index+1}/{len(alt_arts)+1}'}")
    return embed


class ArtBrowser(discord.ui.View):
    """Prev/Next buttons to cycle through a card's normal art + alt arts."""

    def __init__(self, code: str, card: dict, art_index: int = 0):
        super().__init__(timeout=180)  # buttons stop working after 3 min idle
        self.code = code
        self.card = card
        self.art_index = art_index
        self.total_arts = len(card.get("alt_arts", [])) + 1  # +1 for normal art
        self._update_button_state()

    def _update_button_state(self):
        # Disable Prev on the first image, Next on the last image
        self.prev_button.disabled = self.art_index == 0
        self.next_button.disabled = self.art_index >= self.total_arts - 1

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.art_index = max(0, self.art_index - 1)
        self._update_button_state()
        embed = build_embed(self.code, self.card, art_index=self.art_index)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.art_index = min(self.total_arts - 1, self.art_index + 1)
        self._update_button_state()
        embed = build_embed(self.code, self.card, art_index=self.art_index)
        await interaction.response.edit_message(embed=embed, view=self)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user} | {len(CARDS)} cards loaded")


@bot.tree.command(name="card", description="Look up a One Piece TCG card by its code (e.g. OP01-016)")
@app_commands.describe(code="Card code, e.g. OP01-016")
async def card(interaction: discord.Interaction, code: str):
    match_code, result = find_card(code)

    if match_code:
        embed = build_embed(match_code, result, art_index=0)
        has_alt_arts = len(result.get("alt_arts", [])) > 0
        if has_alt_arts:
            view = ArtBrowser(match_code, result, art_index=0)
            await interaction.response.send_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed)
    elif result:  # list of close matches
        suggestions = "\n".join(f"• `{c}` — {CARDS[c]['name']}" for c in result)
        await interaction.response.send_message(
            f"Couldn't find `{code}`. Did you mean:\n{suggestions}", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"No card found for `{code}`.", ephemeral=True
        )


if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("Set DISCORD_BOT_TOKEN environment variable before running.")
    bot.run(token)
