import json
import asyncio
import os
import difflib
import random
import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "cards.json")
DECKS_PATH = os.path.join(os.path.dirname(__file__), "data", "decks.json")
SCHEDULE_PATH = os.path.join(os.path.dirname(__file__), "data", "schedule_state.json")

with open(DATA_PATH, "r", encoding="utf-8") as f:
    CARDS = json.load(f)  # keys are normalized to UPPERCASE at lookup time

if os.path.exists(DECKS_PATH):
    with open(DECKS_PATH, "r", encoding="utf-8") as f:
        DECKS = json.load(f)
else:
    DECKS = []

# Daily deck-of-the-day config
BANGKOK_TZ = datetime.timezone(datetime.timedelta(hours=7))

_DEFAULT_SCHEDULE = {
    "enabled": True,
    "hour": 9,
    "minute": 0,
    "last_posted_date": None,
    "channel_id": 1545851775003922543,  # fallback default; change with /dailydeck setchannel
}


def load_schedule() -> dict:
    if os.path.exists(SCHEDULE_PATH):
        with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # fill in any missing keys with defaults (e.g. after an update)
        for k, v in _DEFAULT_SCHEDULE.items():
            data.setdefault(k, v)
        return data
    return dict(_DEFAULT_SCHEDULE)


def save_schedule(state: dict):
    os.makedirs(os.path.dirname(SCHEDULE_PATH), exist_ok=True)
    with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


SCHEDULE_STATE = load_schedule()

# --- Instagram update notifications (manual — admin pastes a post URL) ---
# No scraping, no login: an admin runs /opnews post or /opnews schedule with a
# real Instagram post URL, and the bot relays it (letting Discord's own link
# preview show the image). Far more reliable than fighting Instagram's
# anti-bot measures.
IG_QUEUE_PATH = os.path.join(os.path.dirname(__file__), "data", "ig_queue.json")


def load_ig_queue() -> list:
    if os.path.exists(IG_QUEUE_PATH):
        with open(IG_QUEUE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_ig_queue(queue: list):
    os.makedirs(os.path.dirname(IG_QUEUE_PATH), exist_ok=True)
    with open(IG_QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2)


IG_QUEUE = load_ig_queue()

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


def build_deck_embed(deck: dict) -> discord.Embed:
    _, leader_card = find_card(deck["leader_code"])
    leader_name = leader_card["name"] if isinstance(leader_card, dict) else deck["leader_code"]
    primary_color = deck.get("color", "?")

    lines = [f'Leader: **{leader_name}** (`{deck["leader_code"]}`)', "", "**Decklist**"]
    for entry in deck["cards"]:
        code = entry["code"]
        qty = entry["qty"]
        _, card = find_card(code)
        name = card["name"] if isinstance(card, dict) else "?"
        lines.append(f"`{qty}x` **{code}** — {name}")

    full_text = "\n".join(lines)
    if len(full_text) > 4000:
        full_text = full_text[:3950] + "\n...(list truncated)"

    embed = discord.Embed(
        title=f'{deck["name"]} ({deck.get("color_display", primary_color)})',
        description=full_text,
        color=COLOR_MAP.get(primary_color, 0x888888),
    )

    if isinstance(leader_card, dict) and leader_card.get("image_url"):
        embed.set_thumbnail(url=leader_card["image_url"])

    src = deck["source"]
    embed.set_footer(
        text=(
            f"{deck['total_cards']} cards | {src['placement']} by {src['author']} "
            f"({src.get('country', '?')}) | {src.get('tournament', '?')} @ {src.get('host', '?')} "
            f"| {src.get('date', '')} | via {src['site']}"
        )
    )
    return embed


async def _post_daily_deck():
    if not DECKS:
        print("[daily_deck] no decks available, skipping post")
        return

    channel_id = SCHEDULE_STATE.get("channel_id")
    if not channel_id:
        print("[daily_deck] no channel_id set, skipping post — use /dailydeck setchannel")
        return

    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception as e:
            print(f"[daily_deck] could not fetch channel {channel_id}: {e!r}")
            return

    deck = random.choice(DECKS)
    embed = build_deck_embed(deck)
    await channel.send(
        content="@everyone Today's meta deck pick! 🏴‍☠️",
        embed=embed,
        allowed_mentions=discord.AllowedMentions(everyone=True),
    )
    print(f"[daily_deck] posted '{deck['name']}' ({deck.get('color_display', deck.get('color'))})")


@tasks.loop(seconds=30)
async def daily_deck_scheduler():
    """Checks every 30s whether it's time to post, based on the persisted schedule state."""
    if not SCHEDULE_STATE.get("enabled", False):
        return

    now = datetime.datetime.now(BANGKOK_TZ)
    today_str = now.strftime("%Y-%m-%d")

    if SCHEDULE_STATE.get("last_posted_date") == today_str:
        return  # already posted today

    target_hour = SCHEDULE_STATE.get("hour", 9)
    target_minute = SCHEDULE_STATE.get("minute", 0)

    if now.hour == target_hour and now.minute == target_minute:
        await _post_daily_deck()
        SCHEDULE_STATE["last_posted_date"] = today_str
        save_schedule(SCHEDULE_STATE)


async def _send_ig_post(channel_id: int, url: str):
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception as e:
            print(f"[ig_post] could not fetch channel {channel_id}: {e!r}")
            return False
    # Send the raw URL as plain content — Discord's own link unfurling shows
    # the image/preview automatically, no scraping needed on our end.
    await channel.send(
        content=f"@everyone 📸 New OnePieceTCG Instagram update!\n{url}",
        allowed_mentions=discord.AllowedMentions(everyone=True),
    )
    return True


@tasks.loop(seconds=30)
async def ig_queue_scheduler():
    """Checks every 30s for any queued posts whose scheduled time has arrived."""
    if not IG_QUEUE:
        return

    now = datetime.datetime.now(BANGKOK_TZ)
    due = [item for item in IG_QUEUE if
           now.hour == item["hour"] and now.minute == item["minute"]]

    for item in due:
        sent = await _send_ig_post(item["channel_id"], item["url"])
        if sent:
            print(f"[ig_post] posted scheduled item: {item['url']}")
        IG_QUEUE.remove(item)
        save_ig_queue(IG_QUEUE)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user} | {len(CARDS)} cards loaded | {len(DECKS)} decks loaded")
    print(f"[daily_deck] schedule: {SCHEDULE_STATE}")
    print(f"[ig_post] queue: {len(IG_QUEUE)} pending item(s)")
    if not daily_deck_scheduler.is_running():
        daily_deck_scheduler.start()
    if not ig_queue_scheduler.is_running():
        ig_queue_scheduler.start()


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

RULES_BASE_URL = "https://pub-d626914b5218469c9ec76a9dcdeaec0b.r2.dev/rules"
RULES_TOTAL_PAGES = 17


def build_rules_embed(page: int) -> discord.Embed:
    embed = discord.Embed(
        title="One Piece Card Game — Official Rule Manual (Thai) v1.11",
        color=0xC0272D,
    )
    embed.set_image(url=f"{RULES_BASE_URL}/page_{page:02d}.png")
    embed.set_footer(text=f"Page {page}/{RULES_TOTAL_PAGES}")
    return embed


class RuleBrowser(discord.ui.View):
    """Prev/Next buttons to page through the rule manual, same pattern as ArtBrowser."""

    def __init__(self, page: int = 1):
        super().__init__(timeout=180)
        self.page = page
        self._update_button_state()

    def _update_button_state(self):
        self.prev_button.disabled = self.page <= 1
        self.next_button.disabled = self.page >= RULES_TOTAL_PAGES

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(1, self.page - 1)
        self._update_button_state()
        await interaction.response.edit_message(embed=build_rules_embed(self.page), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(RULES_TOTAL_PAGES, self.page + 1)
        self._update_button_state()
        await interaction.response.edit_message(embed=build_rules_embed(self.page), view=self)


@bot.tree.command(name="rules", description="Browse the official One Piece Card Game rule manual page by page")
@app_commands.describe(page="Page number to start at (default 1)")
async def rules(interaction: discord.Interaction, page: int = 1):
    page = max(1, min(RULES_TOTAL_PAGES, page))
    embed = build_rules_embed(page)
    view = RuleBrowser(page)
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="randomdeck", description="Pull a random tournament decklist right now (any color)")
async def random_deck(interaction: discord.Interaction):
    if not DECKS:
        await interaction.response.send_message("No decks in the database yet.", ephemeral=True)
        return

    deck = random.choice(DECKS)
    embed = build_deck_embed(deck)
    await interaction.response.send_message(embed=embed)


class AdminOnlyGroup(app_commands.Group):
    """Restricts every command in this group to the server owner or members with Administrator.
    Works per-guild automatically, so this stays correct even if the bot joins other servers."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command only works inside a server.", ephemeral=True
            )
            return False

        member = interaction.user
        is_owner = interaction.guild.owner_id == member.id
        is_admin = isinstance(member, discord.Member) and member.guild_permissions.administrator

        if not (is_owner or is_admin):
            await interaction.response.send_message(
                "🚫 Only the server owner or admins can manage the daily deck schedule.",
                ephemeral=True,
            )
            return False
        return True


dailydeck_group = AdminOnlyGroup(
    name="dailydeck",
    description="Manage the automatic daily deck post",
    default_permissions=discord.Permissions(administrator=True),
)


@dailydeck_group.command(name="enable", description="Turn on the automatic daily deck post")
async def dailydeck_enable(interaction: discord.Interaction):
    SCHEDULE_STATE["enabled"] = True
    save_schedule(SCHEDULE_STATE)
    h, m = SCHEDULE_STATE["hour"], SCHEDULE_STATE["minute"]
    await interaction.response.send_message(
        f"✅ Daily deck post enabled — posting at {h:02d}:{m:02d} (GMT+7) every day.",
        ephemeral=True,
    )


@dailydeck_group.command(name="disable", description="Turn off the automatic daily deck post")
async def dailydeck_disable(interaction: discord.Interaction):
    SCHEDULE_STATE["enabled"] = False
    save_schedule(SCHEDULE_STATE)
    await interaction.response.send_message("🛑 Daily deck post disabled.", ephemeral=True)


@dailydeck_group.command(name="settime", description="Set the exact time (GMT+7) the daily deck posts")
@app_commands.describe(hour="Hour (1-12)", minute="Minute (0-59)", ampm="AM or PM")
@app_commands.choices(ampm=[
    app_commands.Choice(name="AM", value="AM"),
    app_commands.Choice(name="PM", value="PM"),
])
async def dailydeck_settime(
    interaction: discord.Interaction,
    hour: app_commands.Range[int, 1, 12],
    minute: app_commands.Range[int, 0, 59],
    ampm: app_commands.Choice[str],
):
    hour_24 = hour % 12  # 12 -> 0
    if ampm.value == "PM":
        hour_24 += 12

    SCHEDULE_STATE["hour"] = hour_24
    SCHEDULE_STATE["minute"] = minute
    SCHEDULE_STATE["last_posted_date"] = None  # allow it to fire today if the new time hasn't passed yet
    save_schedule(SCHEDULE_STATE)

    await interaction.response.send_message(
        f"⏰ Daily deck post time set to {hour:02d}:{minute:02d} {ampm.value} (GMT+7) "
        f"→ {hour_24:02d}:{minute:02d} 24h.",
        ephemeral=True,
    )


@dailydeck_group.command(name="setchannel", description="Set which channel the daily deck post goes to")
@app_commands.describe(channel="Channel to post the daily deck in")
async def dailydeck_setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    SCHEDULE_STATE["channel_id"] = channel.id
    save_schedule(SCHEDULE_STATE)
    await interaction.response.send_message(
        f"📌 Daily deck post channel set to {channel.mention}.",
        ephemeral=True,
    )


@dailydeck_group.command(name="status", description="Show the current daily deck post schedule")
async def dailydeck_status(interaction: discord.Interaction):
    h24 = SCHEDULE_STATE["hour"]
    m = SCHEDULE_STATE["minute"]
    ampm = "AM" if h24 < 12 else "PM"
    h12 = h24 % 12
    if h12 == 0:
        h12 = 12
    enabled = SCHEDULE_STATE.get("enabled", False)
    last_posted = SCHEDULE_STATE.get("last_posted_date") or "never"
    channel_id = SCHEDULE_STATE.get("channel_id")
    channel_mention = f"<#{channel_id}>" if channel_id else "⚠️ not set"

    await interaction.response.send_message(
        f"**Daily deck post status**\n"
        f"- Enabled: {'✅ Yes' if enabled else '🛑 No'}\n"
        f"- Time: {h12:02d}:{m:02d} {ampm} (GMT+7)\n"
        f"- Channel: {channel_mention}\n"
        f"- Last posted: {last_posted}\n"
        f"- Decks in pool: {len(DECKS)}",
        ephemeral=True,
    )


bot.tree.add_command(dailydeck_group)


opnews_group = AdminOnlyGroup(
    name="opnews",
    description="Post or schedule OnePieceTCG Instagram updates",
    default_permissions=discord.Permissions(administrator=True),
)


@opnews_group.command(name="post", description="Post an Instagram URL right now")
@app_commands.describe(url="The Instagram post URL to share", channel="Channel to post in (defaults to this channel)")
async def opnews_post(interaction: discord.Interaction, url: str, channel: discord.TextChannel = None):
    await interaction.response.defer()
    target_channel_id = channel.id if channel else interaction.channel_id
    sent = await _send_ig_post(target_channel_id, url)
    if sent:
        where = channel.mention if channel else "this channel"
        await interaction.followup.send(f"✅ Posted in {where}.", ephemeral=True)
    else:
        await interaction.followup.send("⚠️ Couldn't post — check the bot's channel permissions.", ephemeral=True)


@opnews_group.command(name="schedule", description="Schedule an Instagram URL to post at a specific time")
@app_commands.describe(
    url="The Instagram post URL to share",
    hour="Hour (1-12)",
    minute="Minute (0-59)",
    ampm="AM or PM",
    channel="Channel to post in (defaults to this channel)",
)
@app_commands.choices(ampm=[
    app_commands.Choice(name="AM", value="AM"),
    app_commands.Choice(name="PM", value="PM"),
])
async def opnews_schedule(
    interaction: discord.Interaction,
    url: str,
    hour: app_commands.Range[int, 1, 12],
    minute: app_commands.Range[int, 0, 59],
    ampm: app_commands.Choice[str],
    channel: discord.TextChannel = None,
):
    hour_24 = hour % 12
    if ampm.value == "PM":
        hour_24 += 12

    target_channel_id = channel.id if channel else interaction.channel_id

    IG_QUEUE.append({
        "url": url,
        "channel_id": target_channel_id,
        "hour": hour_24,
        "minute": minute,
    })
    save_ig_queue(IG_QUEUE)

    where = channel.mention if channel else "this channel"
    await interaction.response.send_message(
        f"⏰ Scheduled for {hour:02d}:{minute:02d} {ampm.value} (GMT+7) in {where}.\n{url}",
        ephemeral=True,
    )


@opnews_group.command(name="queue", description="Show pending scheduled Instagram posts")
async def opnews_queue(interaction: discord.Interaction):
    if not IG_QUEUE:
        await interaction.response.send_message("No pending scheduled posts.", ephemeral=True)
        return

    lines = []
    for i, item in enumerate(IG_QUEUE, 1):
        h24, m = item["hour"], item["minute"]
        ampm = "AM" if h24 < 12 else "PM"
        h12 = h24 % 12 or 12
        lines.append(f"`{i}.` {h12:02d}:{m:02d} {ampm} (GMT+7) in <#{item['channel_id']}> — {item['url']}")

    await interaction.response.send_message("**Pending scheduled posts:**\n" + "\n".join(lines), ephemeral=True)


@opnews_group.command(name="cancel", description="Cancel a pending scheduled post by its number from /opnews queue")
@app_commands.describe(number="The number shown next to the item in /opnews queue")
async def opnews_cancel(interaction: discord.Interaction, number: app_commands.Range[int, 1, 100]):
    idx = number - 1
    if idx < 0 or idx >= len(IG_QUEUE):
        await interaction.response.send_message("⚠️ No pending post with that number.", ephemeral=True)
        return

    removed = IG_QUEUE.pop(idx)
    save_ig_queue(IG_QUEUE)
    await interaction.response.send_message(f"🗑️ Cancelled: {removed['url']}", ephemeral=True)


bot.tree.add_command(opnews_group)


if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("Set DISCORD_BOT_TOKEN environment variable before running.")
    bot.run(token)
