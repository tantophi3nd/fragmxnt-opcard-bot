import json
import os
import difflib
import random
import re

import discord
import aiohttp
from bs4 import BeautifulSoup
from discord import app_commands
from discord.ext import commands

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "cards.json")

with open(DATA_PATH, "r", encoding="utf-8") as f:
    _DATA = json.load(f)

CARDS = _DATA["cards"]  # keys are normalized to UPPERCASE at lookup time
DECKS = _DATA["decks"]

COLOR_CHOICES = ["Red", "Green", "Blue", "Purple", "Black", "Yellow"]

# English-format deck-list pages, pulled from onepiecetopdecks.com/deck-list/
# Current meta first (weighted more likely to be picked), older formats after.
DECK_LIST_PAGES = [
    "https://onepiecetopdecks.com/deck-list/english-op17-deck-list-the-worlds-strongest-warriors/",
    "https://onepiecetopdecks.com/deck-list/english-op16-deck-list-the-time-of-battle/",
    "https://onepiecetopdecks.com/deck-list/english-op15-eb04-deck-list-adventure-on-kamis-island/",
    "https://onepiecetopdecks.com/deck-list/english-eb-03-deck-list-one-piece-heroines-edition/",
    "https://onepiecetopdecks.com/deck-list/english-op-14-eb-04-deck-list-the-azure-sea-seven/",
    "https://onepiecetopdecks.com/deck-list/english-op-13-deck-list-carrying-on-his-will/",
    "https://onepiecetopdecks.com/deck-list/english-op-12-deck-list-legacy-of-the-master/",
    "https://onepiecetopdecks.com/deck-list/english-eb-02-deck-list-anime-25th-collection/",
    "https://onepiecetopdecks.com/deck-list/english-op-10-the-royal-bloodline-decks/",
    "https://onepiecetopdecks.com/deck-list/english-op-09-the-new-emperor-decks/",
]


def _parse_dg(dg: str):
    """Parse a 'dg' composition string like '1nOP05-060a4nOP11-070a...' into [{code, qty}]."""
    parts = re.findall(r"(\d+)n([A-Za-z0-9\-]+?)a(?=\d+n|$)", dg + "a")
    return [{"code": code, "qty": int(qty)} for qty, code in parts]


async def _fetch_deck_rows(session: aiohttp.ClientSession, url: str):
    """Fetch one deck-list page and parse its table into a list of deck dicts."""
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        if resp.status != 200:
            return []
        html = await resp.text()

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []

    rows = []
    for tr in table.find_all("tr")[1:]:  # skip header row
        cells = tr.find_all("td")
        if len(cells) < 11:
            continue

        dg_cell_text = cells[0].get_text(strip=True)
        if not dg_cell_text:
            continue

        # Column order: Deck Composition | Details | Deck Color | Deck Profile |
        #               Deck Name | Date | Country | Author | Placement | Tournament | Host
        color = cells[2].get_text(strip=True)
        deck_name = cells[4].get_text(strip=True)
        date = cells[5].get_text(strip=True)
        country = cells[6].get_text(strip=True)
        author = cells[7].get_text(strip=True)
        placement = cells[8].get_text(strip=True)
        tournament = cells[9].get_text(strip=True)
        host = cells[10].get_text(strip=True)

        cards = _parse_dg(dg_cell_text)
        if not cards or not color:
            continue

        rows.append({
            "name": deck_name,
            "color": color,
            "leader_code": cards[0]["code"],
            "cards": cards,
            "total_cards": sum(c["qty"] for c in cards),
            "source": {
                "author": author,
                "placement": placement,
                "date": date,
                "country": country,
                "tournament": tournament,
                "host": host,
                "page": url,
                "site": "onepiecetopdecks.com",
            },
        })
    return rows

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

    embed.set_footer(text=f"Fragmxnt Bot | Developed by Fragmxnt{'' if len(alt_arts)==0 else f' — Art {art_index+1}/{len(alt_arts)+1}'}")
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
    print(f"Logged in as {bot.user} | {len(CARDS)} cards loaded | {len(DECKS)} decks loaded")


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


@bot.tree.command(name="random", description="Pull a random card from the database")
async def random_card(interaction: discord.Interaction):
    match_code = random.choice(list(CARDS.keys()))
    result = CARDS[match_code]

    embed = build_embed(match_code, result, art_index=0)
    has_alt_arts = len(result.get("alt_arts", [])) > 0
    if has_alt_arts:
        view = ArtBrowser(match_code, result, art_index=0)
        await interaction.response.send_message(embed=embed, view=view)
    else:
        await interaction.response.send_message(embed=embed)


def build_deck_embed(deck: dict) -> discord.Embed:
    _, leader_card = find_card(deck["leader_code"])
    leader_name = leader_card["name"] if isinstance(leader_card, dict) else deck["leader_code"]

    embed = discord.Embed(
        title=f'{deck["name"]} ({deck["color"]})',
        description=f'Leader: **{leader_name}** (`{deck["leader_code"]}`)',
        color=COLOR_MAP.get(deck["color"], 0x888888),
    )

    if isinstance(leader_card, dict) and leader_card.get("image_url"):
        embed.set_thumbnail(url=leader_card["image_url"])

    lines = []
    for entry in deck["cards"]:
        code = entry["code"]
        qty = entry["qty"]
        _, card = find_card(code)
        name = card["name"] if isinstance(card, dict) else "?"
        lines.append(f"`{qty}x` **{code}** — {name}")

    chunk = []
    length = 0
    field_index = 1
    for line in lines:
        if length + len(line) + 1 > 1000:
            embed.add_field(name=f"Decklist ({field_index})", value="\n".join(chunk), inline=False)
            chunk = []
            length = 0
            field_index += 1
        chunk.append(line)
        length += len(line) + 1
    if chunk:
        embed.add_field(
            name=f"Decklist ({field_index})" if field_index > 1 else "Decklist",
            value="\n".join(chunk),
            inline=False,
        )

    src = deck["source"]
    embed.set_footer(
        text=(
            f"{deck['total_cards']} cards | {src['placement']} by {src['author']} "
            f"({src.get('country', '?')}) | {src.get('tournament', '?')} @ {src.get('host', '?')} "
            f"| {src.get('date', '')} | via {src['site']}"
        )
    )
    return embed


@bot.tree.command(name="randomdeck", description="Pull a random tournament decklist from onepiecetopdecks.com by color")
@app_commands.describe(color="Deck color to pick from")
@app_commands.choices(color=[app_commands.Choice(name=c, value=c) for c in COLOR_CHOICES])
async def random_deck(interaction: discord.Interaction, color: app_commands.Choice[str]):
    await interaction.response.defer()  # live scraping can take a few seconds

    matches = []
    urls_to_try = random.sample(DECK_LIST_PAGES, k=min(4, len(DECK_LIST_PAGES)))

    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        for url in urls_to_try:
            try:
                rows = await _fetch_deck_rows(session, url)
            except Exception:
                continue
            matches.extend([r for r in rows if r["color"] == color.value])
            if matches:
                break  # got hits, no need to check more pages

    if not matches:
        await interaction.followup.send(
            f"Couldn't find any {color.value} decks on the pages I checked just now. "
            f"Try again — it samples a few random pages each time.",
            ephemeral=True,
        )
        return

    deck = random.choice(matches)
    embed = build_deck_embed(deck)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="deckbyleader", description="Pull a random tournament decklist for a specific leader")
@app_commands.describe(leader="Leader to search decks for")
async def deck_by_leader(interaction: discord.Interaction, leader: str):
    await interaction.response.defer()  # live scraping can take a few seconds

    matches = []
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        for url in DECK_LIST_PAGES:
            try:
                rows = await _fetch_deck_rows(session, url)
            except Exception:
                continue
            matches.extend([r for r in rows if r["leader_code"] == leader])
            if len(matches) >= 5:  # enough variety, stop early
                break

    if not matches:
        await interaction.followup.send(
            "No decks found for that leader on the pages I checked.", ephemeral=True
        )
        return

    deck = random.choice(matches)
    embed = build_deck_embed(deck)
    await interaction.followup.send(embed=embed)


@deck_by_leader.autocomplete("leader")
async def deck_by_leader_autocomplete(interaction: discord.Interaction, current: str):
    current = current.lower()
    seen_codes = set()
    choices = []
    for deck in DECKS:
        code = deck["leader_code"]
        if code in seen_codes:
            continue
        _, card = find_card(code)
        leader_name = card["name"] if isinstance(card, dict) else code
        label = f"{leader_name} ({code}) — {deck['name']}"
        if current in leader_name.lower() or current in code.lower() or current in deck["name"].lower():
            seen_codes.add(code)
            choices.append(app_commands.Choice(name=label[:100], value=code))
        if len(choices) >= 25:
            break
    return choices


if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("Set DISCORD_BOT_TOKEN environment variable before running.")
    bot.run(token)
