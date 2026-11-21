import asyncio
import html
import logging
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from pyrogram import Client, filters, idle
from pyrogram.enums import ParseMode
from pyrogram.types import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup

import database
import dashboard
from config import (
    API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS, BOT_NAME, MAX_FILE_GB,
    MAX_UPLOAD_BYTES, LINK_RECORD_TTL_DAYS, FILEBEE_WEBSITE, validate_config,
)
from filebee import FileBeeClient, FileBeeError, is_filebee_url

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("filebee-telegram-bot")

app = Client(
    "filebee_telegram_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=8,
    sleep_threshold=60,
    parse_mode=ParseMode.HTML,
)
STORAGE = FileBeeClient()
UPLOAD_LOCKS: dict[int, asyncio.Lock] = {}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def human_size(size: int) -> str:
    value = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} B" if unit == "B" else f"{value:.2f} {unit}"
        value /= 1024
    return f"{size} B"


def fmt_time(timestamp: int | None) -> str:
    if not timestamp:
        return "Not set"
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def time_left(expiry: int | None) -> str:
    if not expiry:
        return "No bot-side expiry configured"
    seconds = expiry - int(time.time())
    if seconds <= 0:
        return "Bot-side tracking expired"
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, _ = divmod(seconds, 60)
    return f"{days}d {hours}h {minutes}m remaining"


def ensure_user(user) -> dict:
    now = int(time.time())
    database.touch_user(user.id, user.username, user.first_name, now)
    return database.get_user(user.id) or {}


def create_record_expiry(now: int) -> int | None:
    return now + LINK_RECORD_TTL_DAYS * 86400 if LINK_RECORD_TTL_DAYS else None


def get_media_info(message):
    media = (message.document or message.video or message.audio or message.animation
             or message.voice or message.video_note or message.photo or message.sticker)
    if not media:
        return None
    if message.photo:
        name = f"telegram_photo_{message.id}.jpg"
    elif message.video_note:
        name = f"video_note_{message.id}.mp4"
    elif message.voice:
        name = f"voice_{message.id}.ogg"
    elif message.sticker:
        name = f"sticker_{message.id}.webp"
    else:
        name = getattr(media, "file_name", None) or f"telegram_file_{message.id}"
    size = int(getattr(media, "file_size", 0) or 0)
    mime = getattr(media, "mime_type", None) or "application/octet-stream"
    return name, size, mime


def user_folder_text(user, row: dict) -> str:
    folder_created = row.get("folder_created") or row.get("joined_at")
    link_expire = row.get("record_expire")
    return (
        "<b>Your FileBee link collection</b>\n\n"
        f"<b>Telegram user ID:</b> <code>{user.id}</code>\n"
        f"<b>Collection folder name:</b> <code>{user.id}</code>\n"
        f"<b>Created:</b> {fmt_time(folder_created)}\n"
        f"<b>Bot-side tracking expiry:</b> {fmt_time(link_expire)}\n"
        f"<b>Tracking time left:</b> {time_left(link_expire)}\n"
        "<b>FileBee provider expiry:</b> Not exposed by a verified public API\n\n"
        "This is a bot-side collection of your FileBee links. It does not create a remote FileBee folder."
    )


@app.on_message(filters.private & filters.command("start"))
async def start_handler(client, message):
    dashboard.touch_update()
    user = message.from_user
    if database.is_banned(user.id):
        return await message.reply_text("Access denied. Contact the bot administrator.")
    row = ensure_user(user)
    api_mode = STORAGE.configured
    text = (
        f"<b>Welcome to {html.escape(BOT_NAME)}</b> 🐝\n\n"
        "Save and manage your FileBee share links in Telegram.\n\n"
        f"<b>Your Telegram ID:</b> <code>{user.id}</code>\n"
        f"<b>Your collection:</b> <code>{user.id}</code>\n"
        f"<b>Created:</b> {fmt_time(row.get('folder_created'))}\n"
        f"<b>Storage mode:</b> {'Configured upload adapter' if api_mode else 'FileBee link mode'}\n\n"
        "Open FileBee, upload your file, then send the resulting FileBee share URL here. "
        "The bot will save it and return a Download button.\n\n"
        f"<b>Configured maximum:</b> {MAX_FILE_GB} GB (actual provider/Telegram limits still apply)\n"
        "Use /help to see all commands."
    )
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🐝 Open FileBee Upload", url=FILEBEE_WEBSITE)],
        [InlineKeyboardButton("📁 My saved links", callback_data="myfiles")],
    ]), disable_web_page_preview=True)


@app.on_callback_query(filters.regex("^myfiles$"))
async def myfiles_callback(client, query):
    rows = database.recent_files(query.from_user.id, 10)
    if not rows:
        return await query.answer("No saved links yet", show_alert=True)
    await query.answer("Your recent links are available with /myfiles")


@app.on_message(filters.private & filters.command("help"))
async def help_handler(client, message):
    dashboard.touch_update()
    body = (
        "<b>FileBee Telegram Bot — Commands</b>\n\n"
        "<b>User</b>\n"
        "/start — Start bot and create your local collection\n"
        "/upload — Open FileBee upload instructions\n"
        "/myfiles — Show your saved FileBee links\n"
        "/folder — Show your user folder and tracking dates\n"
        "/download URL — Create a download button\n"
        "/status — Live bot status and uptime\n"
        "/id — Show Telegram user ID\n"
        "/help — Help\n\n"
    )
    if is_admin(message.from_user.id):
        body += (
            "<b>Admin</b>\n/admin — Overview\n/stats — Statistics\n/users — Recent users\n"
            "/setexpiry USER_ID DAYS — Set bot-side tracking expiry\n"
            "/ban USER_ID — Ban user\n/unban USER_ID — Unban user\n"
            "/broadcast TEXT — Send announcement\n/filebeecheck — Storage integration status"
        )
    await message.reply_text(body)


@app.on_message(filters.private & filters.command("upload"))
async def upload_handler(client, message):
    dashboard.touch_update()
    mode = "The configured FileBee upload adapter is enabled." if STORAGE.configured else (
        "Automatic upload from Telegram is not enabled because FileBee.live does not currently expose a verified public API contract."
    )
    await message.reply_text(
        "<b>FileBee upload</b>\n\n"
        f"{mode}\n\n"
        "1. Open FileBee using the button below.\n"
        "2. Upload your file on the FileBee website.\n"
        "3. Copy the generated share URL.\n"
        "4. Send that URL to this Telegram bot.\n\n"
        "The bot stores the link under your Telegram user ID and creates a Download button. "
        "Do not send private or sensitive files to a public share service unless you trust its privacy and retention policy.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🐝 Open FileBee", url=FILEBEE_WEBSITE)]]),
        disable_web_page_preview=True,
    )


@app.on_message(filters.private & filters.command("id"))
async def id_handler(client, message):
    dashboard.touch_update()
    ensure_user(message.from_user)
    await message.reply_text(f"Your Telegram ID: <code>{message.from_user.id}</code>")


@app.on_message(filters.private & filters.command("folder"))
async def folder_handler(client, message):
    dashboard.touch_update()
    user = message.from_user
    if database.is_banned(user.id):
        return await message.reply_text("Access denied.")
    row = ensure_user(user)
    await message.reply_text(user_folder_text(user, row), disable_web_page_preview=True)


@app.on_message(filters.private & filters.command("myfiles"))
async def myfiles_handler(client, message):
    dashboard.touch_update()
    if database.is_banned(message.from_user.id):
        return await message.reply_text("Access denied.")
    rows = database.recent_files(message.from_user.id, 15)
    if not rows:
        return await message.reply_text("No saved FileBee links yet. Upload at FileBee and send the resulting HTTPS link here.")
    for item in rows:
        await message.reply_text(
            f"<b>{html.escape(item['file_name'][:180])}</b>\n"
            f"Size: {human_size(item['file_size'])}\nSaved: {fmt_time(item['created_at'])}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬇️ Download", url=item['download_url'])]]),
            disable_web_page_preview=True,
        )


@app.on_message(filters.private & filters.command("download"))
async def download_handler(client, message):
    dashboard.touch_update()
    args = (message.text or "").split(maxsplit=1)
    if len(args) != 2 or not is_filebee_url(args[1].strip()):
        return await message.reply_text("Usage: <code>/download https://new4.filebee.live/file/...</code>\nOnly HTTPS FileBee.live links are accepted.")
    url = args[1].strip()
    await message.reply_text("Open your FileBee download page:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬇️ Download from FileBee", url=url)]]),
        disable_web_page_preview=True)


@app.on_message(filters.private & filters.command("status"))
async def status_handler(client, message):
    dashboard.touch_update()
    stats = database.stats()
    uptime = int(time.time() - dashboard.STATE["started_at"])
    await message.reply_text(
        "<b>Bot status</b>\n"
        f"Telegram: <b>{'Online' if dashboard.STATE['connected'] else 'Connecting'}</b>\n"
        f"Storage mode: <b>{'API adapter configured' if STORAGE.configured else 'Manual FileBee link mode'}</b>\n"
        f"Uptime: <code>{uptime // 86400}d {(uptime % 86400) // 3600}h {(uptime % 3600) // 60}m</code>\n"
        f"Users: <b>{stats['users']}</b> · Saved links: <b>{stats['files']}</b>"
    )


@app.on_message(filters.private & filters.media)
async def media_handler(client, message):
    dashboard.touch_update()
    user = message.from_user
    if not user:
        return
    if database.is_banned(user.id):
        return await message.reply_text("Access denied. Contact the bot administrator.")
    ensure_user(user)
    info = get_media_info(message)
    if not info:
        return
    filename, declared_size, mime_type = info
    if declared_size and declared_size > MAX_UPLOAD_BYTES:
        return await message.reply_text(f"File size {human_size(declared_size)} exceeds this bot's configured maximum of {MAX_FILE_GB} GB.")
    if not STORAGE.configured:
        return await message.reply_text(
            "<b>File received, but automatic transfer is not enabled.</b>\n\n"
            "FileBee.live does not currently publish a verifiable upload API contract for this bot to call. "
            "Open FileBee, upload the file there, then send the generated share URL back here.\n\n"
            "Your Telegram file has not been uploaded to FileBee by this bot.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🐝 Open FileBee Upload", url=FILEBEE_WEBSITE)]]),
            disable_web_page_preview=True,
        )

    lock = UPLOAD_LOCKS.setdefault(user.id, asyncio.Lock())
    async with lock:
        status = await message.reply_text(f"Preparing streaming upload…\n<code>{html.escape(filename[:120])}</code>")
        started = time.monotonic()
        last_shown = 0
        try:
            async def progress(done: int):
                nonlocal last_shown
                if done <= last_shown:
                    return
                last_shown = done
                elapsed = max(0.2, time.monotonic() - started)
                await status.edit_text(
                    "<b>Uploading to configured FileBee endpoint…</b>\n"
                    f"File: <code>{html.escape(filename[:120])}</code>\n"
                    f"Transferred: <b>{human_size(done)}</b> / {human_size(declared_size)}\n"
                    f"Speed: <b>{human_size(int(done / elapsed))}/s</b>"
                )
            result = await STORAGE.upload_stream(
                client.stream_media(message), filename, mime_type, declared_size, progress
            )
            now = int(time.time())
            database.add_file(user.id, filename, int(result.get("size") or declared_size or 0), result["url"], now, "telegram-upload")
            await status.edit_text(
                "<b>Upload completed</b> ✅\n\n"
                f"File: <code>{html.escape(filename[:140])}</code>\n"
                f"Size: {human_size(int(result.get('size') or declared_size or 0))}\n"
                f"Saved: {fmt_time(now)}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬇️ Download from FileBee", url=result["url"])]]),
            )
        except Exception as exc:
            log.exception("FileBee upload adapter error for user %s", user.id)
            await status.edit_text(f"<b>Upload failed</b> ❌\n<code>{html.escape(str(exc)[:650])}</code>")


@app.on_message(filters.private & filters.text)
async def capture_filebee_link(client, message):
    """Capture FileBee URLs sent as ordinary messages."""
    text = message.text or ""
    if text.startswith("/"):
        return
    parts = text.split()
    url = next((part.strip("<>()[]{}.,!?") for part in parts if is_filebee_url(part.strip("<>()[]{}.,!?"))), None)
    if not url:
        return
    dashboard.touch_update()
    user = message.from_user
    if not user or database.is_banned(user.id):
        return
    ensure_user(user)
    name = "FileBee shared link"
    database.add_file(user.id, name, 0, url, int(time.time()), "shared-link")
    await message.reply_text(
        "<b>FileBee link saved successfully</b> ✅\n\nYour link is now stored in your user collection.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬇️ Download", url=url)],
                                           [InlineKeyboardButton("📂 View saved links", callback_data="myfiles")]]),
        disable_web_page_preview=True,
    )


async def admin_guard(message) -> bool:
    if not message.from_user or not is_admin(message.from_user.id):
        await message.reply_text("This command is for administrators only.")
        return False
    dashboard.touch_update()
    return True


@app.on_message(filters.private & filters.command("filebeecheck"))
async def filebeecheck_handler(client, message):
    if not await admin_guard(message):
        return
    await message.reply_text(
        "<b>FileBee integration status</b>\n"
        f"Website: <code>{FILEBEE_WEBSITE}</code>\n"
        f"Upload adapter configured: <b>{'Yes' if STORAGE.configured else 'No'}</b>\n"
        f"Mode: <b>{'Streaming adapter' if STORAGE.configured else 'Manual link saving'}</b>\n\n"
        "The upload adapter only works after its endpoint, authentication and response format are confirmed by FileBee. "
        "No guessed endpoint is enabled by default."
    )


@app.on_message(filters.private & filters.command("admin"))
async def admin_handler(client, message):
    if not await admin_guard(message):
        return
    s = database.stats()
    await message.reply_text(
        "<b>Admin dashboard</b>\n"
        f"Users: {s['users']}\nBanned: {s['banned']}\nSaved links/files: {s['files']}\n"
        f"Bytes known: {human_size(s['bytes'])}\n"
        f"Storage mode: {'API adapter' if STORAGE.configured else 'Manual links'}"
    )


@app.on_message(filters.private & filters.command("stats"))
async def stats_handler(client, message):
    if not await admin_guard(message):
        return
    s = database.stats()
    await message.reply_text(f"Users: {s['users']}\nBanned: {s['banned']}\nSaved links: {s['files']}\nKnown bytes: {human_size(s['bytes'])}")


@app.on_message(filters.private & filters.command("users"))
async def users_handler(client, message):
    if not await admin_guard(message):
        return
    rows = database.list_users(30)
    lines = ["<b>Recent users</b>"]
    for row in rows:
        name = "@" + row["username"] if row.get("username") else (row.get("first_name") or "No name")
        lines.append(f"<code>{row['user_id']}</code> — {html.escape(name)} — {'banned' if row['banned'] else 'active'}")
    await message.reply_text("\n".join(lines))


@app.on_message(filters.private & filters.command("setexpiry"))
async def setexpiry_handler(client, message):
    if not await admin_guard(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 3:
        return await message.reply_text("Usage: <code>/setexpiry USER_ID DAYS</code> (0 disables tracking expiry)")
    try:
        user_id, days = int(parts[1]), int(parts[2])
    except ValueError:
        return await message.reply_text("USER_ID and DAYS must be integers.")
    if not database.get_user(user_id):
        return await message.reply_text("User not found.")
    if not 0 <= days <= 3650:
        return await message.reply_text("DAYS must be between 0 and 3650.")
    expiry = int(time.time()) + days * 86400 if days else None
    database.set_record_expiry(user_id, expiry)
    await message.reply_text(
        f"Bot-side link tracking expiry updated for <code>{user_id}</code>: {fmt_time(expiry)}.\n"
        "This does not delete or expire files hosted by FileBee."
    )


@app.on_message(filters.private & filters.command("ban"))
async def ban_handler(client, message):
    if not await admin_guard(message):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdigit() or not database.get_user(int(parts[1])):
        return await message.reply_text("Usage: <code>/ban USER_ID</code> (existing user only)")
    database.set_banned(int(parts[1]), True)
    await message.reply_text(f"User <code>{parts[1]}</code> banned.")


@app.on_message(filters.private & filters.command("unban"))
async def unban_handler(client, message):
    if not await admin_guard(message):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdigit() or not database.get_user(int(parts[1])):
        return await message.reply_text("Usage: <code>/unban USER_ID</code> (existing user only)")
    database.set_banned(int(parts[1]), False)
    await message.reply_text(f"User <code>{parts[1]}</code> unbanned.")


@app.on_message(filters.private & filters.command("broadcast"))
async def broadcast_handler(client, message):
    if not await admin_guard(message):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        return await message.reply_text("Usage: <code>/broadcast MESSAGE</code>")
    user_ids = database.all_user_ids()
    result = await message.reply_text(f"Broadcast running for {len(user_ids)} users…")
    sent = failed = 0
    for user_id in user_ids:
        try:
            await client.send_message(user_id, parts[1])
            sent += 1
            await asyncio.sleep(0.04)
        except Exception:
            failed += 1
    await result.edit_text(f"Broadcast completed.\nSent: {sent}\nFailed: {failed}")


async def register_commands() -> None:
    user_commands = [
        BotCommand("start", "Start bot"),
        BotCommand("upload", "Open FileBee upload instructions"),
        BotCommand("myfiles", "Show saved links"),
        BotCommand("folder", "Show user collection dates"),
        BotCommand("download", "Create a FileBee download button"),
        BotCommand("status", "Show bot status and uptime"),
        BotCommand("id", "Show Telegram ID"),
        BotCommand("help", "Show help"),
    ]
    admin_commands = user_commands + [
        BotCommand("admin", "Admin overview"),
        BotCommand("stats", "Usage statistics"),
        BotCommand("users", "Recent users"),
        BotCommand("setexpiry", "Set bot-side link tracking expiry"),
        BotCommand("ban", "Ban a user"),
        BotCommand("unban", "Unban a user"),
        BotCommand("broadcast", "Send an announcement"),
        BotCommand("filebeecheck", "Check FileBee integration mode"),
    ]
    try:
        await app.set_bot_commands(user_commands)
        log.info("Registered public Telegram bot commands")
    except Exception:
        log.exception("User command menu registration failed; handlers remain active")
    try:
        from pyrogram.types import BotCommandScopeChat
        for admin_id in ADMIN_IDS:
            try:
                await app.set_bot_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
            except Exception as exc:
                log.warning("Could not register admin command menu for %s: %s", admin_id, exc)
    except Exception:
        log.exception("Admin command scope registration failed; admin handlers remain active")


async def main() -> None:
    validate_config()
    database.init_db()
    dashboard.start_dashboard_thread()
    await STORAGE.start()
    await app.start()
    me = await app.get_me()
    dashboard.set_connected(True, me.username)
    await register_commands()
    log.info("Bot started as @%s", me.username)
    if not STORAGE.configured:
        log.warning("FileBee API not configured; manual FileBee share-link mode is active")
    try:
        await idle()
    finally:
        dashboard.set_connected(False)
        await app.stop()
        await STORAGE.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Stopped by user")
