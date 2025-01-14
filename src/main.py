#!/usr/local/bin/python3
# coding: utf-8

# ytdlbot - new.py
# 8/14/21 14:37
#

__author__ = "Benny <benny.think@gmail.com>"

import contextlib
import logging
import re
import threading
import time
import typing
from io import BytesIO
from typing import Any

import psutil
import pyrogram.errors
import yt_dlp
from apscheduler.schedulers.background import BackgroundScheduler
from pyrogram import Client, enums, filters, types

from config import (
    APP_HASH,
    APP_ID,
    AUTHORIZED_USER,
    BOT_TOKEN,
    ENABLE_ARIA2,
    ENABLE_FFMPEG,
    ENABLE_VIP,
    OWNER,
    PROVIDER_TOKEN,
    TOKEN_PRICE,
    BotText,
)
from database.model import (
    get_format_settings,
    get_free_quota,
    get_paid_quota,
    get_quality_settings,
    init_user,
    reset_free,
    set_user_settings,
)
from engine import youtube_entrance
from utils import extract_url_and_name, sizeof_fmt, timeof_fmt

logging.info("Authorized users are %s", AUTHORIZED_USER)
logging.getLogger("apscheduler.executors.default").propagate = False


def create_app(name: str, workers: int = 64) -> Client:
    return Client(
        name,
        APP_ID,
        APP_HASH,
        bot_token=BOT_TOKEN,
        workers=workers,
        # max_concurrent_transmissions=max(1, WORKERS // 2),
        # https://github.com/pyrogram/pyrogram/issues/1225#issuecomment-1446595489
    )


app = create_app("main")


def private_use(func):
    def wrapper(client: Client, message: types.Message):
        chat_id = getattr(message.from_user, "id", None)

        # message type check
        if message.chat.type != enums.ChatType.PRIVATE and not getattr(message, "text", "").lower().startswith("/ytdl"):
            logging.debug("%s, it's annoying me...🙄️ ", message.text)
            return

        # authorized users check
        if AUTHORIZED_USER:
            users = [int(i) for i in AUTHORIZED_USER.split(",")]
        else:
            users = []

        if users and chat_id and chat_id not in users:
            message.reply_text("BotText.private", quote=True)
            return

        return func(client, message)

    return wrapper


@app.on_message(filters.command(["start"]))
def start_handler(client: Client, message: types.Message):
    from_id = message.chat.id
    init_user(from_id)
    logging.info("%s welcome to youtube-dl bot!", message.from_user.id)
    client.send_chat_action(from_id, enums.ChatAction.TYPING)
    free, paid = get_free_quota(from_id), get_paid_quota(from_id)
    client.send_message(
        from_id,
        BotText.start + f"You have {free} free and {paid} paid quota.",
        disable_web_page_preview=True,
    )


@app.on_message(filters.command(["help"]))
def help_handler(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    client.send_message(chat_id, BotText.help, disable_web_page_preview=True)


@app.on_message(filters.command(["about"]))
def about_handler(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    client.send_message(chat_id, BotText.about)


@app.on_message(filters.command(["ping"]))
def ping_handler(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)

    def send_message_and_measure_ping():
        start_time = int(round(time.time() * 1000))
        reply: types.Message | typing.Any = client.send_message(chat_id, "Starting Ping...")

        end_time = int(round(time.time() * 1000))
        ping_time = int(round(end_time - start_time))
        message_sent = True
        if message_sent:
            message.reply_text(f"Ping: {ping_time:.2f} ms", quote=True)
        time.sleep(0.5)
        client.edit_message_text(chat_id=reply.chat.id, message_id=reply.id, text="Ping Calculation Complete.")
        time.sleep(1)
        client.delete_messages(chat_id=reply.chat.id, message_ids=reply.id)

    thread = threading.Thread(target=send_message_and_measure_ping)
    thread.start()


@app.on_message(filters.command(["stats"]))
def stats_handler(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    cpu_usage = psutil.cpu_percent()
    total, used, free, disk = psutil.disk_usage("/")
    swap = psutil.swap_memory()
    memory = psutil.virtual_memory()
    boot_time = psutil.boot_time()

    owner_stats = (
        "\n\n⌬─────「 Stats 」─────⌬\n\n"
        f"<b>╭🖥️ **CPU Usage »**</b>  __{cpu_usage}%__\n"
        f"<b>├💾 **RAM Usage »**</b>  __{memory.percent}%__\n"
        f"<b>╰🗃️ **DISK Usage »**</b>  __{disk}%__\n\n"
        f"<b>╭📤Upload:</b> {sizeof_fmt(psutil.net_io_counters().bytes_sent)}\n"
        f"<b>╰📥Download:</b> {sizeof_fmt(psutil.net_io_counters().bytes_recv)}\n\n\n"
        f"<b>Memory Total:</b> {sizeof_fmt(memory.total)}\n"
        f"<b>Memory Free:</b> {sizeof_fmt(memory.available)}\n"
        f"<b>Memory Used:</b> {sizeof_fmt(memory.used)}\n"
        f"<b>SWAP Total:</b> {sizeof_fmt(swap.total)} | <b>SWAP Usage:</b> {swap.percent}%\n\n"
        f"<b>Total Disk Space:</b> {sizeof_fmt(total)}\n"
        f"<b>Used:</b> {sizeof_fmt(used)} | <b>Free:</b> {sizeof_fmt(free)}\n\n"
        f"<b>Physical Cores:</b> {psutil.cpu_count(logical=False)}\n"
        f"<b>Total Cores:</b> {psutil.cpu_count(logical=True)}\n\n"
        f"<b>🤖Bot Uptime:</b> {timeof_fmt(time.time() - botStartTime)}\n"
        f"<b>⏲️OS Uptime:</b> {timeof_fmt(time.time() - boot_time)}\n"
    )

    user_stats = (
        "\n\n⌬─────「 Stats 」─────⌬\n\n"
        f"<b>╭🖥️ **CPU Usage »**</b>  __{cpu_usage}%__\n"
        f"<b>├💾 **RAM Usage »**</b>  __{memory.percent}%__\n"
        f"<b>╰🗃️ **DISK Usage »**</b>  __{disk}%__\n\n"
        f"<b>╭📤Upload:</b> {sizeof_fmt(psutil.net_io_counters().bytes_sent)}\n"
        f"<b>╰📥Download:</b> {sizeof_fmt(psutil.net_io_counters().bytes_recv)}\n\n\n"
        f"<b>Memory Total:</b> {sizeof_fmt(memory.total)}\n"
        f"<b>Memory Free:</b> {sizeof_fmt(memory.available)}\n"
        f"<b>Memory Used:</b> {sizeof_fmt(memory.used)}\n"
        f"<b>Total Disk Space:</b> {sizeof_fmt(total)}\n"
        f"<b>Used:</b> {sizeof_fmt(used)} | <b>Free:</b> {sizeof_fmt(free)}\n\n"
        f"<b>🤖Bot Uptime:</b> {timeof_fmt(time.time() - botStartTime)}\n"
    )

    if message.from_user.id in OWNER:
        message.reply_text(owner_stats, quote=True)
    else:
        message.reply_text(user_stats, quote=True)


@app.on_message(filters.command(["settings"]))
def settings_handler(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    markup = types.InlineKeyboardMarkup(
        [
            [  # First row
                types.InlineKeyboardButton("send as document", callback_data="document"),
                types.InlineKeyboardButton("send as video", callback_data="video"),
                types.InlineKeyboardButton("send as audio", callback_data="audio"),
            ],
            [  # second row
                types.InlineKeyboardButton("High Quality", callback_data="high"),
                types.InlineKeyboardButton("Medium Quality", callback_data="medium"),
                types.InlineKeyboardButton("Low Quality", callback_data="low"),
            ],
        ]
    )

    quality = get_quality_settings(chat_id)
    send_type = get_format_settings(chat_id)
    client.send_message(chat_id, BotText.settings.format(quality, send_type), reply_markup=markup)


@app.on_message(filters.command(["spdl"]))
def spdl_handler(client: Client, message: types.Message):
    chat_id = message.from_user.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    message_text = message.text
    url, new_name = extract_url_and_name(message_text)
    logging.info("spdl start %s", url)
    if url is None or not re.findall(r"^https?://", url.lower()):
        message.reply_text("Something wrong 🤔.\nCheck your URL and send me again.", quote=True)
        return

    bot_msg = message.reply_text("Request received.", quote=True)
    spdl_download_entrance(client, bot_msg, url)


@app.on_message(filters.command(["leech"]))
def leech_handler(client: Client, message: types.Message):
    if not ENABLE_ARIA2:
        message.reply_text("Aria2 Not Enabled.", quote=True)
        return

    chat_id = message.from_user.id
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    message_text = message.text
    url, new_name = extract_url_and_name(message_text)
    logging.info("leech using aria2 start %s", url)
    if url is None or not re.findall(r"^https?://", url.lower()):
        message.reply_text("Send me a correct LINK.", quote=True)
        return

    bot_msg = message.reply_text("Request received.", quote=True)
    leech_download_entrance(client, bot_msg, url)


@app.on_message(filters.command(["ytdl"]))
def ytdl_handler(client: Client, message: types.Message):
    # for group usage
    chat_id = message.from_user.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    message_text = message.text
    url, new_name = extract_url_and_name(message_text)
    logging.info("ytdl start %s", url)
    if url is None or not re.findall(r"^https?://", url.lower()):
        message.reply_text("Something wrong 🤔.\nCheck your URL and send me again.", quote=True)
        return

    bot_msg = message.reply_text("Request received.", quote=True)
    youtube_entrance(client, bot_msg, url)


def check_link(url: str):
    ytdl = yt_dlp.YoutubeDL()
    if re.findall(r"^https://www\.youtube\.com/channel/", url) or "list" in url:
        # TODO maybe using ytdl.extract_info
        raise ValueError("Playlist or channel download are not supported at this moment.")

    if re.findall(r"m3u8|\.m3u8|\.m3u$", url.lower()):
        raise ValueError("m3u8 links are not supported.")

    with contextlib.suppress(yt_dlp.utils.DownloadError):
        # TODO remove it or try 'match_filter': '!is_live',
        if ytdl.extract_info(url, download=False).get("live_status") == "is_live":
            raise ValueError("Live stream links are disabled. Please engine it after the stream ends.")


@app.on_message(filters.incoming & filters.text)
@private_use
def download_handler(client: Client, message: types.Message):
    chat_id = message.from_user.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    url = message.text
    logging.info("start %s", url)

    try:
        check_link(url)
        # raise pyrogram.errors.exceptions.FloodWait(10)
        bot_msg: types.Message | Any = message.reply_text("Task received.", quote=True)
        client.send_chat_action(chat_id, enums.ChatAction.UPLOAD_VIDEO)
        youtube_entrance(client, bot_msg, url)
    except pyrogram.errors.Flood as e:
        f = BytesIO()
        f.write(str(e).encode())
        f.write(b"Your job will be done soon. Just wait!")
        f.name = "Please wait.txt"
        message.reply_document(f, caption=f"Flood wait! Please wait {e} seconds...", quote=True)
        f.close()
        client.send_message(OWNER, f"Flood wait! 🙁 {e} seconds....")
        time.sleep(e.value)
    except ValueError as e:
        message.reply_text(e.__str__(), quote=True)
    except Exception as e:
        message.reply_text(f"❌ Download failed: {e}", quote=True)


@app.on_callback_query(filters.regex(r"document|video|audio"))
def format_callback(client: Client, callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    data = callback_query.data
    logging.info("Setting %s file type to %s", chat_id, data)
    callback_query.answer(f"Your send type was set to {callback_query.data}")
    set_user_settings(chat_id, "format", data)


@app.on_callback_query(filters.regex(r"high|medium|low"))
def quality_callback(client: Client, callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    data = callback_query.data
    logging.info("Setting %s download quality to %s", chat_id, data)
    callback_query.answer(f"Your default engine quality was set to {callback_query.data}")
    set_user_settings(chat_id, "quality", data)


if __name__ == "__main__":
    botStartTime = time.time()
    scheduler = BackgroundScheduler()
    scheduler.add_job(reset_free, "cron", hour=0, minute=0)
    scheduler.start()
    banner = f"""
▌ ▌         ▀▛▘     ▌       ▛▀▖              ▜            ▌
▝▞  ▞▀▖ ▌ ▌  ▌  ▌ ▌ ▛▀▖ ▞▀▖ ▌ ▌ ▞▀▖ ▌  ▌ ▛▀▖ ▐  ▞▀▖ ▝▀▖ ▞▀▌
 ▌  ▌ ▌ ▌ ▌  ▌  ▌ ▌ ▌ ▌ ▛▀  ▌ ▌ ▌ ▌ ▐▐▐  ▌ ▌ ▐  ▌ ▌ ▞▀▌ ▌ ▌
 ▘  ▝▀  ▝▀▘  ▘  ▝▀▘ ▀▀  ▝▀▘ ▀▀  ▝▀   ▘▘  ▘ ▘  ▘ ▝▀  ▝▀▘ ▝▀▘

By @BennyThink, VIP Mode: {ENABLE_VIP} 
    """
    print(banner)
    app.run()