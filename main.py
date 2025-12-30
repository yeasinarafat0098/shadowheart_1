import os
import asyncio
import logging
import random
import discord
from discord.ext import commands

# --- config from env ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GUILD_ID = int(os.environ.get("GUILD_ID", "0"))
VC_CHANNEL_ID = int(os.environ.get("VC_CHANNEL_ID", "0"))

# --- logging ---
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("voice-manager")

# --- intents ---
intents = discord.Intents.default()
intents.message_content = True   # if you need it; enable in dev portal too
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- concurrency control & state ---
voice_lock = asyncio.Lock()
maintain_task: asyncio.Task | None = None
_shutdown = False

async def maintain_voice():
    """
    Background task that ensures the bot is connected to the desired VC.
    Uses a lock to avoid concurrent connect attempts and applies backoff on failure.
    """
    backoff = 1.0
    MAX_BACKOFF = 60.0

    log.info("[maintain_voice] started")
    while not _shutdown and not bot.is_closed():
        try:
            guild = bot.get_guild(GUILD_ID)
            if guild is None:
                log.warning("[maintain_voice] guild %s not found; retrying in 10s", GUILD_ID)
                await asyncio.sleep(10)
                continue

            # quick check: if already connected, wait and continue
            vc = guild.voice_client  # preferred: single guild client
            if vc and getattr(vc, "is_connected", lambda: False)():
                # we're connected - sleep a bit and check again
                await asyncio.sleep(10)
                backoff = 1.0
                continue

            # Acquire lock so only one task attempts connect at a time
            async with voice_lock:
                # double-check inside the lock
                vc = guild.voice_client
                if vc and getattr(vc, "is_connected", lambda: False)():
                    continue

                channel = bot.get_channel(VC_CHANNEL_ID)
                if channel is None:
                    log.warning("[maintain_voice] channel %s not found; retrying in 20s", VC_CHANNEL_ID)
                    await asyncio.sleep(20)
                    continue

                try:
                    log.info("[maintain_voice] attempting to connect to channel %s", VC_CHANNEL_ID)
                    # reconnect=True can be used but repeated connect attempts are guarded by lock
                    await channel.connect(reconnect=True)
                    log.info("[maintain_voice] connected successfully")
                    backoff = 1.0
                except discord.errors.ClientException as e:
                    # often "Already connected" or similar; log and continue
                    log.warning("[maintain_voice] ClientException while connecting: %s", e)
                except discord.errors.ConnectionClosed as e:
                    code = getattr(e, "code", None)
                    log.error("[maintain_voice] ConnectionClosed while connecting (code=%s): %s", code, e)
                    # If Discord returns 4006, give it more time
                    if code == 4006:
                        backoff = min(MAX_BACKOFF, backoff * 2.0) or 5.0
                        jitter = random.uniform(0, 2.0)
                        wait = backoff + jitter
                        log.info("[maintain_voice] 4006 detected – backing off for %.1fs", wait)
                        await asyncio.sleep(wait)
                        continue
                except Exception as e:
                    log.exception("[maintain_voice] unexpected error while connecting: %s", e)

            # if not connected yet, wait with exponential backoff + jitter
            if not (guild.voice_client and getattr(guild.voice_client, "is_connected", lambda: False)()):
                jitter = random.uniform(0, 1.0)
                wait = min(MAX_BACKOFF, backoff) + jitter
                log.info("[maintain_voice] not connected yet -> sleeping %.1fs (backoff %.1f)", wait, backoff)
                await asyncio.sleep(wait)
                backoff = min(MAX_BACKOFF, backoff * 2.0) if backoff > 0 else 1.0
            else:
                # connected - short sleep
                await asyncio.sleep(10)
                backoff = 1.0

        except asyncio.CancelledError:
            log.info("[maintain_voice] cancelled")
            break
        except Exception:
            log.exception("[maintain_voice] unexpected top-level error; sleeping 5s")
            await asyncio.sleep(5)

    log.info("[maintain_voice] exiting")

@bot.event
async def on_ready():
    global maintain_task
    log.info("Logged in as %s (id: %s)", bot.user, bot.user.id)
    # start the maintainer task only once
    if maintain_task is None or maintain_task.done():
        maintain_task = bot.loop.create_task(maintain_voice())

@bot.event
async def on_voice_state_update(member, before, after):
    # Do NOT attempt reconnects here. Just log for observability.
    if member.id == bot.user.id:
        log.info("[on_voice_state_update] bot voice state changed: before=%s after=%s", getattr(before, "channel", None), getattr(after, "channel", None))

async def _shutdown_gracefully():
    global _shutdown
    _shutdown = True
    if maintain_task and not maintain_task.done():
        maintain_task.cancel()
        try:
            await maintain_task
        except Exception:
            pass
    # disconnect if connected
    guild = bot.get_guild(GUILD_ID)
    if guild and guild.voice_client:
        try:
            await guild.voice_client.disconnect()
        except Exception:
            pass

# optional: handle SIGTERM to gracefully stop
def run_bot():
    try:
        bot.run(BOT_TOKEN)
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt, shutting down")
    finally:
        # nothing blocking here - we let tasks clean up on process exit
        pass

if __name__ == "__main__":
    run_bot()
