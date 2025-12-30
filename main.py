import os
import asyncio
import discord
from discord.ext import tasks, commands

# ---------- CONFIG (do NOT hardcode your token here) ----------
TOKEN = os.getenv("BOT_TOKEN")  # set this in Railway secrets (do not put token in code)
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
VC_CHANNEL_ID = int(os.getenv("VC_CHANNEL_ID", "0"))
# ---------------------------------------------------------------

intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id: {bot.user.id})")
    ensure_connected.start()

@tasks.loop(seconds=20)
async def ensure_connected():
    """Keep bot connected to the desired voice channel. Reconnect if missing."""
    try:
        guild = bot.get_guild(GUILD_ID)
        if guild is None:
            print(f"[ensure_connected] Guild {GUILD_ID} not found.")
            return

        channel = guild.get_channel(VC_CHANNEL_ID)
        if channel is None:
            print(f"[ensure_connected] Channel {VC_CHANNEL_ID} not found in guild.")
            return

        # If already connected to that guild's voice, ensure it's the same channel
        vc = discord.utils.get(bot.voice_clients, guild=guild)
        if vc and vc.is_connected():
            if vc.channel.id != VC_CHANNEL_ID:
                print("[ensure_connected] Moving to the correct channel...")
                await vc.move_to(channel)
            return

        # Not connected -> connect
        print("[ensure_connected] Connecting to voice channel...")
        await channel.connect(reconnect=True, timeout=60)
        print("[ensure_connected] Connected.")
    except Exception as e:
        print(f"[ensure_connected] Exception: {e}")

@bot.event
async def on_voice_state_update(member, before, after):
    # If the bot itself was disconnected, try to reconnect
    if member.id == bot.user.id:
        if after.channel is None:
            print("[on_voice_state_update] Bot was disconnected -> trying to reconnect")
            await ensure_connected()

if __name__ == "__main__":
    if not TOKEN:
        print("ERROR: BOT_TOKEN environment variable not set. Exiting.")
        raise SystemExit(1)
    bot.run(TOKEN)
