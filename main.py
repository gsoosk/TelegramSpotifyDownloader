"""Telegram Spotify Downloader bot.

A simple Telegram bot that downloads songs, albums, playlists and artists from a
Spotify link using spotDL v4 (which sources the audio from YouTube) and sends the
resulting MP3 files back to the user.

Built on python-telegram-bot v22 (async) and spotdl v4.
"""

import asyncio
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from dotenv import dotenv_values

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
DOWNLOADS_DIR = BASE_DIR / "downloads"

# A Spotify web link or URI for a track, album, playlist or artist.
SPOTIFY_URL_RE = re.compile(
    r"(https?://open\.spotify\.com/(?:intl-\w+/)?(?:track|album|playlist|artist)/\w+"
    r"|spotify:(?:track|album|playlist|artist):\w+)",
    re.IGNORECASE,
)

# spotdl progress markers.
FOUND_RE = re.compile(r"Found (\d+) song", re.IGNORECASE)
DONE_MARKERS = ("Downloaded", "Skipping")

import json


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {"AUTH": {"ENABLE": False, "PASSWORD": "", "OWNER_ID": None, "USERS": []}}


def save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)


config = load_config()
config.setdefault("AUTH", {})
config["AUTH"].setdefault("ENABLE", False)
config["AUTH"].setdefault("PASSWORD", "")
config["AUTH"].setdefault("OWNER_ID", None)
config["AUTH"].setdefault("USERS", [])


def get_token() -> str:
    env = dotenv_values(BASE_DIR / ".env")
    token = env.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError(
            "No Telegram token found. Put TELEGRAM_TOKEN in a .env file "
            "or set it as an environment variable."
        )
    return token


# ---------------------------------------------------------------------------
# Authentication helpers
# ---------------------------------------------------------------------------
def is_authorized(chat_id: int) -> bool:
    if not config["AUTH"]["ENABLE"]:
        return True
    if config["AUTH"]["OWNER_ID"] and chat_id == config["AUTH"]["OWNER_ID"]:
        return True
    return chat_id in config["AUTH"]["USERS"]


def try_login(chat_id: int, text: str) -> bool:
    password = config["AUTH"]["PASSWORD"]
    if password and text.strip() == password:
        if chat_id not in config["AUTH"]["USERS"]:
            config["AUTH"]["USERS"].append(chat_id)
        if not config["AUTH"]["OWNER_ID"]:
            config["AUTH"]["OWNER_ID"] = chat_id
        save_config(config)
        return True
    return False


# ---------------------------------------------------------------------------
# Progress bar
# ---------------------------------------------------------------------------
def render_bar(done: int, total: int, width: int = 20) -> str:
    if total > 0:
        done = min(done, total)
        filled = int(width * done / total)
        bar = "█" * filled + "░" * (width - filled)
        pct = int(100 * done / total)
        return f"[{bar}] {pct}%  ({done}/{total})"
    return f"⏳ Downloading… {done} track(s) done"


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if config["AUTH"]["ENABLE"] and not is_authorized(chat_id):
        await update.message.reply_text(
            "👋 Welcome!\n\nThis bot is private. Please send the password to sign in. "
            "If you don't know it, contact the bot owner."
        )
        return
    await update.message.reply_text(
        "🎵 *Spotify Downloader*\n\n"
        "Send me a Spotify link and I'll fetch the audio for you.\n\n"
        "Supported links:\n"
        "• Track\n• Album\n• Playlist\n• Artist\n\n"
        "Example: `https://open.spotify.com/track/...`",
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Just send a Spotify link (track, album, playlist or artist) and I'll "
        "download it and send the MP3 files back.\n\n"
        "Commands:\n"
        "/start – welcome / sign in\n"
        "/help – this message\n"
        "/logout – sign out (if auth is enabled)"
    )


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in config["AUTH"]["USERS"]:
        config["AUTH"]["USERS"].remove(chat_id)
        save_config(config)
        await update.message.reply_text("👋 You've been signed out.")
    else:
        await update.message.reply_text("You weren't signed in.")


# ---------------------------------------------------------------------------
# Download flow
# ---------------------------------------------------------------------------
async def run_spotdl(url: str, out_dir: Path, progress_cb) -> None:
    """Run spotdl and stream its output, invoking progress_cb(done, total)."""
    output_template = str(out_dir / "{artists} - {title}.{output-ext}")
    cmd = [
        "spotdl",
        "download",
        url,
        "--output",
        output_template,
    ]
    logger.info("Running: %s", " ".join(cmd))

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    total = 0
    done = 0
    assert process.stdout is not None
    async for raw in process.stdout:
        line = raw.decode(errors="ignore").strip()
        if not line:
            continue
        logger.info("[spotdl] %s", line)

        found = FOUND_RE.search(line)
        if found:
            total = int(found.group(1))
            await progress_cb(done, total)
            continue

        if any(line.startswith(marker) for marker in DONE_MARKERS):
            done += 1
            await progress_cb(done, total)

    await process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"spotdl exited with code {process.returncode}")


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat_id = update.effective_chat.id
    text = message.text or ""

    match = SPOTIFY_URL_RE.search(text)

    # Authentication gate.
    if config["AUTH"]["ENABLE"] and not is_authorized(chat_id):
        if try_login(chat_id, text):
            await message.reply_text("✅ Signed in successfully. Enjoy! 🍻")
        else:
            await message.reply_text(
                "⚠️ This bot is private and you're not signed in.\n"
                "Please send the password to sign in."
            )
        return

    if not match:
        await message.reply_text(
            "Please send a valid Spotify link (track, album, playlist or artist)."
        )
        return

    url = match.group(1)
    request_id = uuid.uuid4().hex[:12]
    out_dir = DOWNLOADS_DIR / request_id
    out_dir.mkdir(parents=True, exist_ok=True)

    status = await message.reply_text("🔎 Fetching…")

    last_edit = {"t": 0.0, "text": ""}

    async def progress_cb(done: int, total: int) -> None:
        now = time.monotonic()
        bar = render_bar(done, total)
        # Throttle edits to avoid Telegram rate limits.
        if bar == last_edit["text"] or (now - last_edit["t"] < 1.5 and done != total):
            return
        last_edit["t"] = now
        last_edit["text"] = bar
        try:
            await status.edit_text(f"⬇️ Downloading…\n{bar}")
        except Exception:
            pass

    try:
        await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
        await run_spotdl(url, out_dir, progress_cb)
    except FileNotFoundError:
        await status.edit_text(
            "❌ spotdl is not installed on the server. Run `pip install spotdl`."
        )
        shutil.rmtree(out_dir, ignore_errors=True)
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("Download failed")
        await status.edit_text(f"❌ Download failed: {exc}")
        shutil.rmtree(out_dir, ignore_errors=True)
        return

    mp3_files = sorted(out_dir.rglob("*.mp3"))
    if not mp3_files:
        await status.edit_text(
            "❌ Couldn't find or download the song. It may be unavailable."
        )
        shutil.rmtree(out_dir, ignore_errors=True)
        return

    await status.edit_text(f"📤 Sending {len(mp3_files)} track(s)…")
    sent = 0
    for mp3 in mp3_files:
        title = mp3.stem
        performer = None
        if " - " in title:
            performer, title = title.split(" - ", 1)
        try:
            await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VOICE)
            with open(mp3, "rb") as audio:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=audio,
                    title=title,
                    performer=performer,
                    read_timeout=1000,
                    write_timeout=1000,
                )
            sent += 1
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send %s", mp3)

    shutil.rmtree(out_dir, ignore_errors=True)

    if sent:
        await status.edit_text(f"✅ Done! Sent {sent} track(s). Enjoy 🍻")
    else:
        await status.edit_text("❌ There was a problem sending the audio.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Update caused error", exc_info=context.error)


def main() -> None:
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    token = get_token()

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_error_handler(on_error)

    logger.info("Bot started. Polling…")
    app.run_polling()


if __name__ == "__main__":
    main()
