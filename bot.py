"""
New commands to add to bot.py: /character and /random
(Your existing /card command — search by code — stays exactly as-is, untouched.)

INTEGRATION NOTES — check these two things before pasting in:
1. `cards` below should be whatever your loaded cards.json dict is called
   (e.g. `self.cards`, `bot.cards`, `CARDS` — rename all references below).
2. `build_card_embed(code, card)` should be your existing embed-builder
   function used by /card. If yours has a different name/signature,
   swap the calls below to match — everything else (color-coding,
   alt art buttons) will keep working as-is.
"""

import random
import discord
from discord import app_commands
from discord.ext import commands


# ── /character — every printing of a given character, code always shown ──

class CharacterResultsView(discord.ui.View):
    """Paginated list of every card matching a character name."""

    PAGE_SIZE = 10

    def __init__(self, query: str, matches: list[tuple[str, dict]]):
        super().__init__(timeout=180)
        self.query = query
        # Sort by set/code so results read in a sane order (ST01, ST02, ... OP01, ...)
        self.matches = sorted(matches, key=lambda m: m[0])
        self.page = 0
        self.max_page = max(0, (len(self.matches) - 1) // self.PAGE_SIZE)
        self._update_buttons()

    def _update_buttons(self):
        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = self.page == self.max_page

    def build_embed(self) -> discord.Embed:
        start = self.page * self.PAGE_SIZE
        chunk = self.matches[start:start + self.PAGE_SIZE]

        embed = discord.Embed(
            title=f'Results for "{self.query}" ({len(self.matches)} card{"s" if len(self.matches) != 1 else ""})',
            color=discord.Color.gold(),
        )
        lines = []
        for code, card in chunk:
            tag = " (Leader)" if card.get("card_type") == "Leader" else ""
            lines.append(
                f"**{code}** — {card['name']} · {card.get('color', '?')} · "
                f"{card.get('set', '?')}{tag}"
            )
        embed.description = "\n".join(lines) if lines else "No results."
        embed.set_footer(text=f"Page {self.page + 1}/{self.max_page + 1} — use the card code with /card for full details")
        return embed

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


@app_commands.command(name="character", description="Show every printing of a character across all sets")
@app_commands.describe(name="Character name (e.g. Luffy, Nami, Charlotte Katakuri)")
async def character(interaction: discord.Interaction, name: str):
    query = name.strip().lower()
    if not query:
        await interaction.response.send_message("Give me a name to search for.", ephemeral=True)
        return

    matches = [
        (code, card)
        for code, card in cards.items()  # <-- rename `cards` to your actual dict
        if query in card["name"].lower()
    ]

    if not matches:
        await interaction.response.send_message(
            f'No cards found matching "{name}". Try a shorter or different spelling.',
            ephemeral=True,
        )
        return

    view = CharacterResultsView(name, matches)
    await interaction.response.send_message(embed=view.build_embed(), view=view)


@character.autocomplete("name")
async def character_autocomplete(interaction: discord.Interaction, current: str):
    current = current.lower()
    seen = set()
    choices = []
    for card in cards.values():  # <-- rename `cards` to your actual dict
        n = card["name"]
        if n not in seen and current in n.lower():
            seen.add(n)
            choices.append(app_commands.Choice(name=n, value=n))
        if len(choices) >= 25:
            break
    return choices


# ── /random — pull a random card, reusing your existing card embed ──

@app_commands.command(name="random", description="Pull a random card from the database")
async def random_card(interaction: discord.Interaction):
    code = random.choice(list(cards.keys()))  # <-- rename `cards` to your actual dict
    card = cards[code]

    embed = build_card_embed(code, card)  # <-- swap to your existing embed builder
    await interaction.response.send_message(embed=embed)


# ── Registration ──
# In your bot setup (wherever you currently do `tree.add_command(card)` etc.):
#
#   tree.add_command(character)
#   tree.add_command(random_card)
#
# Don't forget to re-sync the command tree (or wait for Discord's automatic
# sync) so the new slash commands show up.
