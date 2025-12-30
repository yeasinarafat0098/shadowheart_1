import os
import asyncio
import logging
import random
import time
import socket

import discord
from discord.ext import commands

# ─────────────────────────────────────────────
# ENVIRONMENT VARIABLES (SET THESE IN RAILWAY)
# ─────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GUILD_ID = int(os.environ.get("GUILD_ID", "0"))
VC_CHANNEL_ID = int(os.environ.get("VC_CHANNEL_ID", "0"))

if not BOT_TOKEN or not GUILD_ID or not VC_CHANNEL_ID:
    raise RuntimeError("Missing BOT_TOKEN, GUILD_ID, or VC_CHANNEL_ID")

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("voice-manager")

# ─────────────────────────────────────────────
# DISCORD INTENTS (NO PRIVILEGED INTENTS)
# ─────────────────────────────────────────────
intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ─────────────────────────────────────────────
# GLOBAL STATE
# ─────────────────────────────────────────────
voice_lock = asyncio.Lock()
maintain_task: asyncio.Task | None = None
shutdown_flag = False

# ─────────────────────────────────────────────
# PROCESS-LEVEL SINGLETON LOCK
# (PREVENTS MULTIPLE INSTANCES COLLIDING)
# ─────────────────────────────────────────────
def obtain_process_lock(host="127.0.0.1", port=56789):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
        sock.listen(1)
        log.info("[process-lock] acquired on %s:%d", host, port)
        return sock
    except OSError:
        log.error("[process-lock] another instance detected, exiting")
        return None

PROCESS_LOCK = obtain_process_lock()
if PROCESS_LOCK is None:
    raise SystemExit(1)

# ─────────────────────────────────────────────
# VOICE MAINTENANCE TASK
# ─────────────────────────────────────────────
async def maintain_voice():
    backoff = 2.0
    max_backoff = 60.0
    consecutive_4006 = 0
    cooldown_until = 0

    log.info("[maintain_voice] started")

    while not shutdown_flag and not bot.is_closed():
        now = time.time()

        if now < cooldown_until:
            sleep_time = min(30, cooldown_until - now)
            log.info("[maintain_voice] cooldown active, sleeping %.1fs", sleep_time)
            await asyncio.sleep(sleep_time)
            continue

        try:
            guild = bot.get_guild(GUILD_ID)
            if not guild:
                log.warning("[maintain_voice] guild not found")
                await asyncio.sleep(10)
                continue

            vc = guild.voice_client
            if vc and vc.is_connected():
                await asyncio.sleep(10)
                consecutive_4006 = 0
                backoff = 2.0
                continue

            async with voice_lock:
                vc = guild.voice_client
                if vc and vc.is_connected():
                    continue

                channel = bot.get_channel(VC_CHANNEL_ID)
                if not channel:
                    log.warning("[maintain_voice] voice channel not found")
                    await asyncio.sleep(15)
                    continue

                try:
                    log.info("[maintain_voice] connecting to voice channel")
                    await channel.connect(reconnect=True)
                    log.info("[maintain_voice] connected successfully")
                    consecutive_4006 = 0
                    backoff = 2.0

                except discord.errors.ConnectionClosed as e:
                    code = getattr(e, "code", None)
                    log.error("[maintain_voice] ConnectionClosed code=%s", code)

                    if code == 4006:
                        consecutive_4006 += 1
                        if consecutive_4006 >= 3:
                            cooldown_until = time.time() + 600  # 10 minutes
                            log.error("[maintain_voice] 4006 spam detected → 10 min cooldown")
                        else:
                            wait = min(max_backoff, backoff) + random.uniform(0, 2)
                            log.info("[maintain_voice] backing off %.1fs", wait)
                            await asyncio.sleep(wait)
                            backoff *= 2

                except discord.errors.ClientException as e:
                    log.warning("[maintain_voice] client exception: %s", e)

                except Exception:
                    log.exception("[maintain_voice] unexpected error")

            await asyncio.sleep(min(max_backoff, backoff))

        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("[maintain_voice] fatal loop error")
            await asyncio.sleep(5)

    log.info("[maintain_voice] stopped")

# ─────────────────────────────────────────────
# DISCORD EVENTS
# ─────────────────────────────────────────────
@bot.event
async def on_ready():
    global maintain_task
    log.info("Logged in as %s (%s)", bot.user, bot.user.id)

    if maintain_task is None or maintain_task.done():
        maintain_task = asyncio.create_task(maintain_voice())

@bot.event
async def on_voice_state_update(member, before, after):
    if member.id == bot.user.id:
        log.info(
            "[voice_state] before=%s after=%s",
            getattr(before.channel, "name", None),
            getattr(after.channel, "name", None),
        )

# ─────────────────────────────────────────────
# BOT RUNNER
# ─────────────────────────────────────────────
def main():
    try:
        bot.run(BOT_TOKEN)
    finally:
        try:
            PROCESS_LOCK.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
