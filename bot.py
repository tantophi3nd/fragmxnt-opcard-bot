import json
import os
from pathlib import Path

import discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
DATA_FILE = Path(__file__).parent / "data" / "cards.json"

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# ---------- โหลด/จัดการข้อมูลการ์ด ----------

def load_cards() -> list[dict]:
    """โหลดข้อมูลการ์ดจากไฟล์ cards.json ใหม่ทุกครั้งที่เรียก
    เพื่อให้แก้ไขไฟล์แล้วเห็นผลทันทีโดยไม่ต้อง restart บอท"""
    if not DATA_FILE.exists():
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def find_card(code: str) -> dict | None:
    code = code.strip().upper()
    for card in load_cards():
        if card.get("card_code", "").upper() == code:
            return card
    return None


def build_card_embed(card: dict) -> discord.Embed:
    manga = card.get("manga_reference", {}) or {}

    embed = discord.Embed(
        title=f"{card.get('card_name', 'ไม่ทราบชื่อ')} ({card.get('card_code', '-')})",
        color=discord.Color.blue(),
    )
    embed.add_field(name="ประเภทการ์ด", value=card.get("card_type", "-"), inline=True)

    arc = manga.get("arc") or "ยังไม่มีข้อมูล"
    chapter = manga.get("chapter") or "ยังไม่มีข้อมูล"
    description = manga.get("description") or "ยังไม่มีข้อมูล"

    embed.add_field(name="Arc", value=arc, inline=True)
    embed.add_field(name="ตอน/บทที่", value=chapter, inline=True)
    embed.add_field(name="รายละเอียดฉาก", value=description, inline=False)

    image_url = card.get("image_url", "")
    if image_url and image_url.startswith("http"):
        embed.set_image(url=image_url)

    embed.set_footer(text="One Piece TCG Card Lookup")
    return embed


# ---------- Autocomplete ----------

async def card_code_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    current = current.strip().upper()
    choices = []
    for card in load_cards():
        code = card.get("card_code", "")
        name = card.get("card_name", "")
        if current in code.upper() or current in name.upper():
            label = f"{code} - {name}"
            choices.append(app_commands.Choice(name=label[:100], value=code))
        if len(choices) >= 25:  # Discord จำกัดสูงสุด 25 ตัวเลือก
            break
    return choices


# ---------- Slash Command ----------

@tree.command(name="card", description="ค้นหาข้อมูลการ์ดและที่มาจากฉากมังงะ")
@app_commands.describe(code="รหัสการ์ด เช่น OP01-016")
@app_commands.autocomplete(code=card_code_autocomplete)
async def card_command(interaction: discord.Interaction, code: str):
    result = find_card(code)
    if not result:
        await interaction.response.send_message(
            f"ไม่พบการ์ดรหัส `{code}` ในฐานข้อมูลครับ", ephemeral=True
        )
        return

    embed = build_card_embed(result)
    await interaction.response.send_message(embed=embed)


@client.event
async def on_ready():
    await tree.sync()
    print(f"บอทออนไลน์แล้วในชื่อ {client.user}")
    print(f"โหลดข้อมูลการ์ดทั้งหมด {len(load_cards())} ใบ")


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("ไม่พบ DISCORD_TOKEN ใน .env กรุณาตั้งค่าก่อนรันบอท")
    client.run(TOKEN)
