import os
import asyncio
import discord
from discord.ext import tasks, commands

# ---------- CONFIG (do NOT hardcode your token here) ----------
TOKEN = os.getenv("BOT_TOKEN")
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
    if not ensure_connected.is_running():
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

        # Check existing voice client
        vc = guild.voice_client

        if vc:
            if vc.is_connected():
                if vc.channel.id != VC_CHANNEL_ID:
                    print("[ensure_connected] Moving to the correct channel...")
                    await vc.move_to(channel)
            else:
                # Connected object exists but not actually connected (stale)
                print("[ensure_connected] Cleanup stale connection...")
                try:
                    await vc.disconnect(force=True)
                except Exception as e:
                    print(f"[ensure_connected] Cleanup error: {e}")
                
                # Reconnect after cleanup
                print("[ensure_connected] Reconnecting to voice channel...")
                await channel.connect(reconnect=True, timeout=60, self_deaf=True)
                print("[ensure_connected] Connected.")
        else:
            # Not connected at all -> connect
            print("[ensure_connected] Connecting to voice channel...")
            await channel.connect(reconnect=True, timeout=60, self_deaf=True)
            print("[ensure_connected] Connected.")

    except Exception as e:
        print(f"[ensure_connected] Exception: {e}")

@bot.event
async def on_voice_state_update(member, before, after):
    # If the bot itself was disconnected, the loop will handle it.
    if member.id == bot.user.id:
        if after.channel is None:
            print("[on_voice_state_update] Bot was disconnected. Waiting for ensure_connected loop...")

if __name__ == "__main__":
    if not TOKEN:
        print("ERROR:
