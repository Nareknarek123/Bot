# -*- coding: utf-8 -*-
"""
Avtoshuka Telegram Bot
aiogram 3.4.1 + python-dotenv

.env sample:
BOT_TOKEN=...
BOT_USERNAME=Avtoshukahaykakanbot
ADMIN_IDS=7730787881
CHANNEL_ID=@AvtoshukaHaykakan
CHANNEL_URL=https://t.me/AvtoshukaHaykakan
GROUP_ID=@AvtoshukaHaykakan
GROUP_URL=https://t.me/AvtoshukaHaykakan
PAYMENT_TEXT=...
ADMIN_USERNAME=Avtoshukamanager
DB_PATH=avtoshuka.db
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("avtoshuka")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "Avtoshukahaykakanbot").strip().lstrip("@")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x]
CHANNEL_ID = os.getenv("CHANNEL_ID", "@AvtoshukaHaykakan").strip()
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/AvtoshukaHaykakan").strip()
GROUP_ID = os.getenv("GROUP_ID", "@AvtoshukaHaykakan").strip()
GROUP_URL = os.getenv("GROUP_URL", "https://t.me/AvtoshukaHaykakan").strip()
PAYMENT_TEXT = os.getenv("PAYMENT_TEXT", "Ուղարկեք վճարման սքրինշոթը").strip()
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "Avtoshukamanager").strip().lstrip("@")
DB_PATH = os.getenv("DB_PATH", "avtoshuka.db").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required")

ADMIN_URL = f"https://t.me/{ADMIN_USERNAME}"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

DB = sqlite3.connect(DB_PATH, check_same_thread=False)
DB.row_factory = sqlite3.Row


def db(query: str, params: tuple[Any, ...] = (), *, fetchone: bool = False, fetchall: bool = False, commit: bool = True):
    cur = DB.execute(query, params)
    row = cur.fetchone() if fetchone else None
    rows = cur.fetchall() if fetchall else None
    if commit:
        DB.commit()
    if fetchone:
        return row
    if fetchall:
        return rows
    return cur


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def human_ts(value: Optional[str]) -> str:
    dt = parse_iso(value)
    if not dt:
        return "—"
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def normalize_text(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"\s+", " ", value)
    return value


def init_db() -> None:
    db(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            verified INTEGER DEFAULT 0,
            blocked INTEGER DEFAULT 0,
            pending_referrer INTEGER,
            created_at TEXT,
            last_seen TEXT,
            vip_active INTEGER DEFAULT 0,
            vip_mode TEXT DEFAULT '',
            vip_updated_at TEXT,
            ref_count INTEGER DEFAULT 0,
            ref_credits INTEGER DEFAULT 0
        )
        """
    )
    db(
        """
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter_id INTEGER NOT NULL,
            invited_id INTEGER NOT NULL UNIQUE,
            created_at TEXT
        )
        """
    )
    db(
        """
        CREATE TABLE IF NOT EXISTS ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            model TEXT,
            year TEXT,
            engine TEXT,
            mileage TEXT,
            fuel TEXT,
            gearbox TEXT,
            drive TEXT,
            condition TEXT,
            issues TEXT,
            vin TEXT,
            price TEXT,
            phone TEXT,
            extra TEXT,
            photos_json TEXT,
            status TEXT,
            fingerprint TEXT,
            channel_message_ids_json TEXT,
            created_at TEXT,
            updated_at TEXT,
            admin_id INTEGER,
            admin_username TEXT,
            admin_fullname TEXT,
            admin_decision_at TEXT,
            pin_paid INTEGER DEFAULT 0,
            refresh_paid INTEGER DEFAULT 0,
            vip_active INTEGER DEFAULT 0,
            last_refresh_at TEXT
        )
        """
    )
    db(
        """
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ad_id INTEGER,
            package TEXT,
            amount INTEGER,
            screenshot_file_id TEXT,
            status TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    db(
        """
        CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            details TEXT,
            created_at TEXT
        )
        """
    )

    ucols = {r["name"] for r in (db("PRAGMA table_info(users)", fetchall=True, commit=False) or [])}
    for col, ddl in [
        ("vip_active", "INTEGER DEFAULT 0"),
        ("vip_mode", "TEXT DEFAULT ''"),
        ("vip_updated_at", "TEXT"),
        ("ref_count", "INTEGER DEFAULT 0"),
        ("ref_credits", "INTEGER DEFAULT 0"),
    ]:
        if col not in ucols:
            db(f"ALTER TABLE users ADD COLUMN {col} {ddl}")

    acols = {r["name"] for r in (db("PRAGMA table_info(ads)", fetchall=True, commit=False) or [])}
    for col, ddl in [
        ("admin_id", "INTEGER"),
        ("admin_username", "TEXT"),
        ("admin_fullname", "TEXT"),
        ("admin_decision_at", "TEXT"),
        ("pin_paid", "INTEGER DEFAULT 0"),
        ("refresh_paid", "INTEGER DEFAULT 0"),
        ("vip_active", "INTEGER DEFAULT 0"),
        ("last_refresh_at", "TEXT"),
    ]:
        if col not in acols:
            db(f"ALTER TABLE ads ADD COLUMN {col} {ddl}")

    pcols = {r["name"] for r in (db("PRAGMA table_info(payments)", fetchall=True, commit=False) or [])}
    if "ad_id" not in pcols:
        db("ALTER TABLE payments ADD COLUMN ad_id INTEGER")


def log_activity(user_id: int, action: str, details: str = "") -> None:
    db("INSERT INTO activity (user_id, action, details, created_at) VALUES (?, ?, ?, ?)", (user_id, action, details, now_iso()))


def upsert_user(user: Any, referrer_id: Optional[int] = None) -> None:
    existing = db("SELECT user_id FROM users WHERE user_id=?", (user.id,), fetchone=True)
    if existing:
        db(
            "UPDATE users SET username=?, first_name=?, last_seen=?, pending_referrer=COALESCE(pending_referrer, ?) WHERE user_id=?",
            (user.username or "", user.first_name or "", now_iso(), referrer_id, user.id),
        )
    else:
        db(
            """
            INSERT INTO users (user_id, username, first_name, verified, blocked, pending_referrer, created_at, last_seen, vip_active, vip_mode, vip_updated_at, ref_count, ref_credits)
            VALUES (?, ?, ?, 0, 0, ?, ?, ?, 0, '', NULL, 0, 0)
            """,
            (user.id, user.username or "", user.first_name or "", referrer_id, now_iso(), now_iso()),
        )


def get_user(user_id: int):
    return db("SELECT * FROM users WHERE user_id=?", (user_id,), fetchone=True)


def set_user_verified(user_id: int, verified: bool = True) -> None:
    db("UPDATE users SET verified=? WHERE user_id=?", (1 if verified else 0, user_id))


def set_block(user_id: int, blocked: bool) -> None:
    db("UPDATE users SET blocked=? WHERE user_id=?", (1 if blocked else 0, user_id))


def is_blocked(user_id: int) -> bool:
    row = get_user(user_id)
    return bool(row and row["blocked"])


def set_vip(user_id: int, active: bool, mode: str = "") -> None:
    db("UPDATE users SET vip_active=?, vip_mode=?, vip_updated_at=? WHERE user_id=?", (1 if active else 0, mode, now_iso(), user_id))


def is_vip(user_id: int) -> bool:
    row = get_user(user_id)
    return bool(row and row["vip_active"])


def get_ref_count(user_id: int) -> int:
    row = get_user(user_id)
    return int(row["ref_count"] if row else 0)


def get_ref_credits(user_id: int) -> int:
    row = get_user(user_id)
    return int(row["ref_credits"] if row else 0)


def spend_ref_credit(user_id: int) -> bool:
    row = get_user(user_id)
    if not row or int(row["ref_credits"]) <= 0:
        return False
    db("UPDATE users SET ref_credits = ref_credits - 1 WHERE user_id=?", (user_id,))
    return True


def add_referral(inviter_id: int, invited_id: int) -> bool:
    if inviter_id == invited_id:
        return False
    existed = db("SELECT id FROM referrals WHERE invited_id=?", (invited_id,), fetchone=True)
    if existed:
        return False
    db("INSERT INTO referrals (inviter_id, invited_id, created_at) VALUES (?, ?, ?)", (inviter_id, invited_id, now_iso()))
    db("UPDATE users SET ref_count = COALESCE(ref_count, 0) + 1 WHERE user_id=?", (inviter_id,))
    row = get_user(inviter_id)
    if row and int(row["ref_count"]) % 30 == 0:
        db("UPDATE users SET ref_credits = COALESCE(ref_credits, 0) + 1 WHERE user_id=?", (inviter_id,))
    log_activity(inviter_id, "referral_added", f"invited={invited_id}")
    return True


def buy_vip_unlimited(user_id: int) -> None:
    set_vip(user_id, True, "unlimited")
    db("UPDATE ads SET vip_active=1, pin_paid=1, refresh_paid=1 WHERE user_id=?", (user_id,))
    db("UPDATE ads SET vip_active=1, pin_paid=1, refresh_paid=1 WHERE user_id=?", (user_id,))
    db("UPDATE ads SET vip_active=1, pin_paid=1, refresh_paid=1 WHERE user_id=?", (user_id,))


def ad_fingerprint(data: dict[str, Any]) -> str:
    parts = [
        normalize_text(str(data.get("model", ""))),
        normalize_text(str(data.get("year", ""))),
        normalize_text(str(data.get("engine", ""))),
        normalize_text(str(data.get("vin", ""))),
        normalize_text(str(data.get("phone", ""))),
    ]
    return "|".join([p for p in parts if p])


def active_duplicate_exists(fp: str) -> bool:
    row = db("SELECT id FROM ads WHERE fingerprint=? AND status IN ('pending','approved') LIMIT 1", (fp,), fetchone=True)
    return bool(row)


def create_ad(user_id: int, data: dict[str, Any], status: str = "pending") -> int:
    photos_json = json.dumps(data.get("photos", []), ensure_ascii=False)
    fp = ad_fingerprint(data)
    cur = db(
        """
        INSERT INTO ads (
            user_id, model, year, engine, mileage, fuel, gearbox, drive, condition, issues,
            vin, price, phone, extra, photos_json, status, fingerprint, channel_message_ids_json,
            created_at, updated_at, admin_id, admin_username, admin_fullname, admin_decision_at,
            pin_paid, refresh_paid, vip_active, last_refresh_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, 0, 0, 0, NULL)
        """,
        (
            user_id,
            data.get("model", ""),
            data.get("year", ""),
            data.get("engine", ""),
            data.get("mileage", ""),
            data.get("fuel", ""),
            data.get("gearbox", ""),
            data.get("drive", ""),
            data.get("condition", ""),
            data.get("issues", ""),
            data.get("vin", ""),
            data.get("price", ""),
            data.get("phone", ""),
            data.get("extra", ""),
            photos_json,
            status,
            fp,
            json.dumps([], ensure_ascii=False),
            now_iso(),
            now_iso(),
        ),
    )
    return int(cur.lastrowid)


def get_ad(ad_id: int):
    return db("SELECT * FROM ads WHERE id=?", (ad_id,), fetchone=True)


def update_ad_status(ad_id: int, status: str, channel_message_ids: Optional[list[int]] = None) -> None:
    db("UPDATE ads SET status=?, channel_message_ids_json=?, updated_at=? WHERE id=?", (status, json.dumps(channel_message_ids or [], ensure_ascii=False), now_iso(), ad_id))


def set_ad_admin(ad_id: int, admin_user: Any) -> None:
    db(
        "UPDATE ads SET admin_id=?, admin_username=?, admin_fullname=?, admin_decision_at=? WHERE id=?",
        (admin_user.id, admin_user.username or "", getattr(admin_user, "full_name", admin_user.first_name or ""), now_iso(), ad_id),
    )


def mark_ad_vip(ad_id: int, active: bool = True) -> None:
    db("UPDATE ads SET vip_active=? WHERE id=?", (1 if active else 0, ad_id))


def mark_ad_pin_paid(ad_id: int, paid: bool = True) -> None:
    db("UPDATE ads SET pin_paid=? WHERE id=?", (1 if paid else 0, ad_id))


def mark_ad_refresh_paid(ad_id: int, paid: bool = True) -> None:
    db("UPDATE ads SET refresh_paid=? WHERE id=?", (1 if paid else 0, ad_id))


def set_ad_last_refresh(ad_id: int) -> None:
    db("UPDATE ads SET last_refresh_at=? WHERE id=?", (now_iso(), ad_id))


def create_payment(user_id: int, package: str, amount: int, screenshot_file_id: str, ad_id: Optional[int] = None) -> int:
    cur = db(
        "INSERT INTO payments (user_id, ad_id, package, amount, screenshot_file_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
        (user_id, ad_id, package, amount, screenshot_file_id, now_iso(), now_iso()),
    )
    return int(cur.lastrowid)


def get_payment(payment_id: int):
    return db("SELECT * FROM payments WHERE id=?", (payment_id,), fetchone=True)


def set_payment_status(payment_id: int, status: str) -> None:
    db("UPDATE payments SET status=?, updated_at=? WHERE id=?", (status, now_iso(), payment_id))


def get_user_ads(user_id: int, limit: int = 20):
    return db("SELECT * FROM ads WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit), fetchall=True) or []


def get_recent_activity(user_id: int, limit: int = 10):
    return db("SELECT * FROM activity WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit), fetchall=True) or []


def count_table(table: str, where: str = "", params: tuple[Any, ...] = ()) -> int:
    q = f"SELECT COUNT(*) AS c FROM {table}"
    if where:
        q += f" WHERE {where}"
    row = db(q, params, fetchone=True)
    return int(row["c"] if row else 0)


def bot_deep_link(user_id: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start={user_id}"


def build_join_text() -> str:
    return "⚠️ <b>Սկզբում հետևեք ալիքին և միացեք չատին</b>\n\nՀետո սեղմեք <b>Հաստատել</b> կոճակը, որպեսզի բացվի գլխավոր մենյուն։"


def build_welcome_text(user_id: int) -> str:
    vip = "✅ ակտիվ" if is_vip(user_id) else "⛔️ ոչ ակտիվ"
    return (
        "🚗 <b>Բարի գալուստ AutoShuka Bot</b>\n\n"
        f"💎 VIP՝ <b>{vip}</b>\n"
        f"👥 Referral՝ <b>{get_ref_count(user_id)}</b>\n"
        f"🎁 Credit՝ <b>{get_ref_credits(user_id)}</b>\n\n"
        "Այստեղ կարող եք՝\n"
        "• տեղադրել մեքենայի հայտարարություն\n"
        "• տեսնել ձեր հայտարարությունները\n"
        "• ակտիվացնել VIP\n"
        "• ստանալ referral բոնուսներ\n\n"
        "📌 <b>Կանոններ</b>\n"
        "• Նույն մեքենայի կրկնվող հայտարարությունը չի հաստատվում\n"
        "• Վաճառվելուց հետո հայտարարությունը ջնջեք\n"
        "• VIP օգտատերը ստանում է 4 օրը մեկ թարմացում\n"
    )


def build_help_text() -> str:
    return (
        "ℹ️ <b>Օգնություն / կանոններ</b>\n\n"
        "• Հայտարարություն տեղադրելու համար լրացրեք բոլոր պարտադիր դաշտերը\n"
        "• Նկարները չեն պահվում սերվերի վրա, միայն Telegram file_id է պահվում\n"
        "• Եթե մեքենան վաճառվել է, ջնջեք հայտարարությունը\n"
        f"• Խնդիրների կամ համագործակցության համար կապվեք ադմինին՝ <a href=\"{ADMIN_URL}\">@{ADMIN_USERNAME}</a>\n"
    )


def build_vip_text(user_id: int) -> str:
    refs = get_ref_count(user_id)
    credits = get_ref_credits(user_id)
    remaining = 30 - (refs % 30) if refs % 30 != 0 else 30
    return (
        "💎 <b>VIP բաժին</b>\n\n"
        "💰 Գին — <b>30000 դրամ</b>\n"
        "Ստանում եք՝\n"
        "• բոլոր փոստերի զակրեպ\n"
        "• 4 օրը մեկ ավտոմատ թարմացում մինչև վաճառվելը\n"
        "• բոլոր հայտարարությունների վրա VIP նշում\n\n"
        "👥 Հրավերներով բոնուս\n"
        "• Ամեն 30 referral → <b>1 credit</b>\n"
        "• Credit-ը կարող եք օգտագործել որպես <b>զակրեպ</b> կամ <b>թարմացում</b>\n\n"
        f"Քո referral-ը — <b>{refs}</b>\n"
        f"Մնացել է մինչև հաջորդ credit — <b>{remaining}</b>\n"
        f"Քո credit-ը — <b>{credits}</b>\n"
    )


def build_ref_text(user_id: int) -> str:
    refs = get_ref_count(user_id)
    credits = get_ref_credits(user_id)
    link = bot_deep_link(user_id)
    remaining = 30 - (refs % 30) if refs % 30 != 0 else 30
    return (
        "👥 <b>Referral բաժին</b>\n\n"
        f"Քո հրավերները — <b>{refs}</b>\n"
        f"Մնացածը մինչև reward — <b>{remaining}</b>\n"
        f"Referral credit — <b>{credits}</b>\n\n"
        f"Քո link-ը՝\n<code>{html.escape(link)}</code>\n\n"
        "⚠️ Հրավիրված user-ը պետք է մտնի բոտով, հետևի ալիքին ու չատին, հետո սեղմի Հաստատել, որ հաշվվի referral-ը։"
    )


def build_ad_text(data: dict[str, Any], vip_badge: bool = False) -> str:
    model = html.escape(str(data.get("model", "Մեքենա")))
    year = html.escape(str(data.get("year", "—")))
    lines = []
    if vip_badge:
        lines.append("💎 VIP")
    lines.append(f"<b>{model} | {year}</b>")
    lines.append("")
    order = [
        ("engine", "Շարժիչ"),
        ("mileage", "Վազք"),
        ("fuel", "Վառելիք"),
        ("gearbox", "Փոխ. տուփ"),
        ("drive", "Քարշակ"),
        ("condition", "Վիճակ"),
        ("issues", "Խնդիրներ"),
        ("vin", "VIN"),
        ("price", "Գին"),
        ("phone", "Հեռախոս"),
        ("extra", "Լրացուցիչ"),
    ]
    for key, label in order:
        value = data.get(key)
        if value not in (None, ""):
            lines.append(f"• {label}՝ {html.escape(str(value))}")
    return "\n".join(lines)

def safe_user_label(user: Any) -> str:
    name = getattr(user, "full_name", None) or getattr(user, "first_name", None) or getattr(user, "username", None) or "—"
    return html.escape(str(name))


def build_ad_preview_caption(ad_data: dict[str, Any], user: Any) -> str:
    return (
        "📄 <b>Նախադիտում</b>\n\n"
        f"👤 Ուղարկող՝ <b>{safe_user_label(user)}</b>\n"
        f"🆔 ID՝ <code>{user.id}</code>\n"
        f"Username՝ @{html.escape(user.username) if user.username else '—'}\n\n"
        f"{build_ad_text(ad_data, vip_badge=is_vip(user.id))}\n\n"
        "Հաստատվե՞լ, որ տեղադրվի ալիքում։"
    )


def build_admin_ad_caption(ad_id: int, ad_data: dict[str, Any], user: Any) -> str:
    return (
        f"📝 <b>Նոր հայտարարություն</b> #{ad_id}\n\n"
        f"👤 Ուղարկող՝ <b>{safe_user_label(user)}</b>\n"
        f"🆔 ID՝ <code>{user.id}</code>\n"
        f"Username՝ @{html.escape(user.username) if user.username else '—'}\n\n"
        f"{build_ad_text(ad_data, vip_badge=is_vip(user.id))}"
    )


def build_payment_admin_caption(payment_id: int, user: Any, package: str, amount: int, ad_id: Optional[int]) -> str:
    return (
        f"💰 <b>Նոր վճարում</b> #{payment_id}\n\n"
        f"👤 User՝ <b>{safe_user_label(user)}</b>\n"
        f"🆔 ID՝ <code>{user.id}</code>\n"
        f"Username՝ @{html.escape(user.username) if user.username else '—'}\n"
        f"📦 Տեսակ՝ <b>{html.escape(package)}</b>\n"
        f"💵 Գումար՝ <b>{amount}</b> դրամ\n"
        f"📎 Ad ID՝ <code>{ad_id if ad_id else '—'}</code>\n"
    )


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Հայտարարություն")],
            [KeyboardButton(text="📂 Իմ հայտարարությունները"), KeyboardButton(text="💎 VIP")],
            [KeyboardButton(text="👥 Referral"), KeyboardButton(text="📞 Կապ ադմինին")],
            [KeyboardButton(text="ℹ️ Օգնություն")],
        ],
        resize_keyboard=True,
    )


def join_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Ալիք", url=CHANNEL_URL), InlineKeyboardButton(text="💬 Չատ", url=GROUP_URL)],
            [InlineKeyboardButton(text="✅ Հաստատել", callback_data="join_confirm")],
        ]
    )


def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚫 Բլոկել user", callback_data="admin:block")],
            [InlineKeyboardButton(text="✅ Ապաբլոկել user", callback_data="admin:unblock")],
            [InlineKeyboardButton(text="📣 Broadcast", callback_data="admin:broadcast")],
            [InlineKeyboardButton(text="📊 Stats", callback_data="admin:stats")],
            [InlineKeyboardButton(text="👤 User history", callback_data="admin:history")],
            [InlineKeyboardButton(text="⬅️ Main menu", callback_data="admin:back")],
        ]
    )


def admin_ad_kb(ad_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Հաստատել", callback_data=f"adapprove:{ad_id}"),
                InlineKeyboardButton(text="❌ Մերժել", callback_data=f"adreject:{ad_id}"),
            ],
            [InlineKeyboardButton(text="💬 Կապ ադմինին", url=ADMIN_URL)],
        ]
    )



def ad_post_offer_kb(ad_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📌 Զակրեպ — 1000 դրամ", callback_data=f"buy:pin:{ad_id}")],
            [InlineKeyboardButton(text="🔄 Թարմացում — 1000 դրամ", callback_data=f"buy:refresh:{ad_id}")],
            [InlineKeyboardButton(text="🎁 Referral credit", callback_data=f"credit:menu:{ad_id}")],
            [InlineKeyboardButton(text="💎 VIP — 30000 դրամ", callback_data=f"buy:vip:{ad_id}")],
            [InlineKeyboardButton(text="💬 Կապ ադմինին", url=ADMIN_URL)],
        ]
    )


def delete_ads_kb(ads: list[sqlite3.Row]) -> InlineKeyboardMarkup:
    rows = []
    for ad in ads:
        if ad["status"] == "deleted":
            continue
        rows.append([InlineKeyboardButton(text=f"🗑 Ջնջել #{ad['id']}", callback_data=f"addelete:{ad['id']}")])
    rows.append([InlineKeyboardButton(text="⬅️ Վերադառնալ", callback_data="menu:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ad_step_kb(step: dict[str, Any]) -> InlineKeyboardMarkup:
    rows = []
    if step["kind"] == "choice":
        row = []
        for i, choice in enumerate(step["choices"]):
            row.append(InlineKeyboardButton(text=choice, callback_data=f"adchoice:{step['key']}:{i}"))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
    if not step["required"]:
        rows.append([InlineKeyboardButton(text="⏭ Բաց թողնել", callback_data=f"adskip:{step['key']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


AD_STEPS: list[dict[str, Any]] = [
    {"key": "model", "label": "🚗 Մոդել", "prompt": "Գրեք մեքենայի մոդելը (պարտադիր)", "kind": "text", "required": True},
    {"key": "year", "label": "📅 Տարի", "prompt": "Գրեք մեքենայի տարին", "kind": "text", "required": False},
    {"key": "engine", "label": "⚙️ Շարժիչ", "prompt": "Գրեք շարժիչը", "kind": "text", "required": False},
    {"key": "mileage", "label": "🛣 Վազք", "prompt": "Գրեք վազքը", "kind": "text", "required": False},
    {"key": "fuel", "label": "⛽ Վառելիք", "prompt": "Ընտրեք վառելիքը", "kind": "choice", "choices": ["Բենզին", "Գազ", "Դիզել", "Էլեկտրո"], "required": False},
    {"key": "gearbox", "label": "🔧 Փոխ. տուփ", "prompt": "Ընտրեք փոխանցման տուփը", "kind": "choice", "choices": ["Ավտոմատ", "Մեխանիկա"], "required": False},
    {"key": "drive", "label": "🛞 Քարշակ", "prompt": "Ընտրեք քարշակը", "kind": "choice", "choices": ["Առջևի", "Հետևի", "Լիաքարշակ"], "required": False},
    {"key": "condition", "label": "📊 Վիճակ", "prompt": "Ընտրեք մեքենայի վիճակը", "kind": "choice", "choices": ["Գերազանց", "Լավ", "Միջին", "Վատ"], "required": False},
    {"key": "issues", "label": "❗ Խնդիրներ", "prompt": "Գրեք մեքենայի խնդիրները", "kind": "text", "required": False},
    {"key": "vin", "label": "🆔 Vin", "prompt": "Գրեք VIN-ը", "kind": "text", "required": False},
    {"key": "price", "label": "💰 Գին", "prompt": "Գրեք գինը", "kind": "text", "required": False},
    {"key": "phone", "label": "📞 Հեռախոս", "prompt": "Գրեք հեռախոսահամարը (պարտադիր)", "kind": "text", "required": True},
    {"key": "extra", "label": "📝 Լրացուցիչ", "prompt": "Գրեք լրացուցիչ տեղեկությունը", "kind": "text", "required": False},
]


class AdForm(StatesGroup):
    filling = State()
    photos = State()
    preview = State()


class ContactAdmin(StatesGroup):
    waiting_message = State()


class AdminFlow(StatesGroup):
    waiting_user_id = State()
    waiting_broadcast = State()
    waiting_history_user_id = State()


class PaymentFlow(StatesGroup):
    waiting_screenshot = State()


async def is_member(chat_id: Any, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
    except Exception:
        return False


async def user_joined(user_id: int) -> bool:
    return await is_member(CHANNEL_ID, user_id) and await is_member(GROUP_ID, user_id)


async def send_join_screen(target: Message | CallbackQuery) -> None:
    if isinstance(target, CallbackQuery):
        await target.message.answer(build_join_text(), reply_markup=join_kb())
        await target.answer()
    else:
        await target.answer(build_join_text(), reply_markup=join_kb())


async def send_main_menu(target: Message | CallbackQuery, user_id: int, text: Optional[str] = None) -> None:
    msg = text or build_welcome_text(user_id)
    if isinstance(target, CallbackQuery):
        await target.message.answer(msg, reply_markup=main_menu_kb())
        await target.answer()
    else:
        await target.answer(msg, reply_markup=main_menu_kb())


async def send_admin_ad(ad_id: int, ad_data: dict[str, Any], user: Any) -> None:
    caption = build_admin_ad_caption(ad_id, ad_data, user)
    photos = list(ad_data.get("photos", []))
    for admin_id in ADMIN_IDS:
        try:
            if photos:
                await bot.send_photo(admin_id, photos[0], caption=caption, reply_markup=admin_ad_kb(ad_id))
            else:
                await bot.send_message(admin_id, caption, reply_markup=admin_ad_kb(ad_id))
        except Exception:
            pass


async def send_payment_to_admin(payment_id: int) -> None:
    payment = get_payment(payment_id)
    if not payment:
        return
    user = get_user(payment["user_id"])
    caption = build_payment_admin_caption(payment_id, user, payment["package"], payment["amount"], payment["ad_id"])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Հաստատել", callback_data=f"payapprove:{payment_id}"), InlineKeyboardButton(text="❌ Մերժել", callback_data=f"payreject:{payment_id}")],
            [InlineKeyboardButton(text="💬 Կապ ադմինին", url=ADMIN_URL)],
        ]
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(admin_id, payment["screenshot_file_id"], caption=caption, reply_markup=kb)
        except Exception:
            try:
                await bot.send_message(admin_id, caption, reply_markup=kb)
            except Exception:
                pass


async def save_step(message: Message, state: FSMContext, value: Optional[str]) -> None:
    data = await state.get_data()
    idx = int(data.get("step_idx", 0))
    if idx >= len(AD_STEPS):
        return
    step = AD_STEPS[idx]
    ad_data = dict(data.get("ad_data", {}))
    if value in (None, ""):
        if step["required"]:
            await message.answer("Այս դաշտը պարտադիր է։")
            await message.answer(step["prompt"], reply_markup=ad_step_kb(step))
            return
        ad_data[step["key"]] = ""
    else:
        ad_data[step["key"]] = value
    idx += 1
    await state.update_data(step_idx=idx, ad_data=ad_data)
    if idx >= len(AD_STEPS):
        await state.set_state(AdForm.photos)
        await message.answer("📸 Ուղարկեք մեքենայի նկարները (1-ից 10 հատ)\nԱվարտելու համար գրեք /done", reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer(AD_STEPS[idx]["prompt"], reply_markup=ad_step_kb(AD_STEPS[idx]))


async def post_ad_to_channel(ad_id: int, ad_data: dict[str, Any], user: Any) -> list[int]:
    text = build_ad_text(ad_data, vip_badge=is_vip(user.id))
    photos = list(ad_data.get("photos", []))
    if not photos:
        sent = await bot.send_message(CHANNEL_ID, text)
        return [sent.message_id]
    if len(photos) == 1:
        sent = await bot.send_photo(CHANNEL_ID, photos[0], caption=text)
        return [sent.message_id]
    media = [InputMediaPhoto(media=photos[0], caption=text)]
    for p in photos[1:10]:
        media.append(InputMediaPhoto(media=p))
    sent = await bot.send_media_group(CHANNEL_ID, media)
    return [m.message_id for m in sent]


async def refresh_vip_ads_loop() -> None:
    while True:
        try:
            rows = db("SELECT * FROM ads WHERE status='approved' AND (vip_active=1 OR refresh_paid=1)", fetchall=True) or []
            for ad in rows:
                last = parse_iso(ad["last_refresh_at"]) or parse_iso(ad["updated_at"]) or parse_iso(ad["created_at"])
                if not last or now_utc() - last < timedelta(days=4):
                    continue
                try:
                    ad_data = {
                        "model": ad["model"],
                        "year": ad["year"],
                        "engine": ad["engine"],
                        "mileage": ad["mileage"],
                        "fuel": ad["fuel"],
                        "gearbox": ad["gearbox"],
                        "drive": ad["drive"],
                        "condition": ad["condition"],
                        "issues": ad["issues"],
                        "vin": ad["vin"],
                        "price": ad["price"],
                        "phone": ad["phone"],
                        "extra": ad["extra"],
                        "photos": json.loads(ad["photos_json"] or "[]"),
                    }
                    msg_ids = await post_ad_to_channel(ad["id"], ad_data, get_user(ad["user_id"]))
                    db("UPDATE ads SET channel_message_ids_json=?, last_refresh_at=?, updated_at=? WHERE id=?", (json.dumps(msg_ids, ensure_ascii=False), now_iso(), now_iso(), ad["id"]))
                    if ad["pin_paid"] or ad["vip_active"]:
                        try:
                            await bot.pin_chat_message(CHANNEL_ID, msg_ids[0], disable_notification=True)
                        except Exception:
                            pass
                except Exception:
                    continue
        except Exception:
            pass
        await asyncio.sleep(3600)


async def on_startup() -> None:
    init_db()
    me = await bot.get_me()
    global BOT_USERNAME
    if not BOT_USERNAME:
        BOT_USERNAME = me.username or "Avtoshukahaykakanbot"
    logger.info("Started as @%s", BOT_USERNAME)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = message.from_user
    referrer = None
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1:
        raw = parts[1].strip()
        if raw.isdigit():
            referrer = int(raw)
            if referrer == user.id:
                referrer = None
    upsert_user(user, referrer_id=referrer)
    if is_blocked(user.id):
        await message.answer("⛔️ Դուք արգելափակված եք ադմինիստրացիայի կողմից։")
        return
    if await user_joined(user.id):
        set_user_verified(user.id, True)
        if referrer:
            add_referral(referrer, user.id)
        await send_main_menu(message, user.id)
    else:
        await send_join_screen(message)


@router.callback_query(F.data == "join_confirm")
async def join_confirm(callback: CallbackQuery) -> None:
    user = callback.from_user
    upsert_user(user)
    if is_blocked(user.id):
        await callback.answer("Դուք արգելափակված եք", show_alert=True)
        return
    if not await user_joined(user.id):
        await callback.answer("Դեռ պետք է միանաք ալիքին ու չատին", show_alert=True)
        await send_join_screen(callback)
        return
    set_user_verified(user.id, True)
    row = get_user(user.id)
    if row and row["pending_referrer"]:
        ref = int(row["pending_referrer"])
        if add_referral(ref, user.id) and get_ref_count(ref) % 30 == 0:
            db("UPDATE users SET ref_credits = ref_credits + 1 WHERE user_id=?", (ref,))
            try:
                await bot.send_message(ref, "🎉 Ձեր referral-ից ավելացավ 1 credit (30 referral-ի դիմաց)։")
            except Exception:
                pass
    await callback.answer("Հաստատված է ✅")
    await send_main_menu(callback, user.id)


@router.message(F.text == "ℹ️ Օգնություն")
async def help_btn(message: Message) -> None:
    await message.answer(build_help_text())


@router.message(F.text == "📞 Կապ ադմինին")
async def contact_admin_btn(message: Message, state: FSMContext) -> None:
    if is_blocked(message.from_user.id):
        await message.answer("⛔️ Դուք արգելափակված եք ադմինիստրացիայի կողմից։")
        return
    await state.clear()
    await state.set_state(ContactAdmin.waiting_message)
    await message.answer(f"📩 Գրեք ձեր հաղորդագրությունը և այն կուղարկվի ադմինին՝ <a href=\"{ADMIN_URL}\">@{ADMIN_USERNAME}</a>", reply_markup=ReplyKeyboardRemove())


@router.message(StateFilter(ContactAdmin.waiting_message))
async def contact_admin_message(message: Message, state: FSMContext) -> None:
    header = (
        "📩 <b>Նոր հաղորդագրություն user-ից</b>\n"
        f"👤 {safe_user_label(message.from_user)}\n"
        f"🆔 <code>{message.from_user.id}</code>\n"
        f"Username: @{html.escape(message.from_user.username) if message.from_user.username else '—'}\n"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, header)
            await bot.copy_message(admin_id, message.chat.id, message.message_id)
        except Exception:
            pass
    await state.clear()
    await message.answer("✅ Ձեր հաղորդագրությունը ուղարկվեց ադմինին։", reply_markup=main_menu_kb())


@router.message(F.text == "💎 VIP")
async def vip_section(message: Message) -> None:
    if is_blocked(message.from_user.id):
        await message.answer("⛔️ Դուք արգելափակված եք ադմինիստրացիայի կողմից։")
        return
    await message.answer(
        build_vip_text(message.from_user.id),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💎 Գնել VIP", callback_data="vip:buy")],
                [InlineKeyboardButton(text="👥 Referral credit օգտագործել", callback_data="vip:use_ref")],
                [InlineKeyboardButton(text="💬 Կապ ադմինին", url=ADMIN_URL)],
            ]
        ),
    )


@router.message(F.text == "👥 Referral")
async def ref_section(message: Message) -> None:
    if is_blocked(message.from_user.id):
        await message.answer("⛔️ Դուք արգելափակված եք ադմինիստրացիայի կողմից։")
        return
    await message.answer(
        build_ref_text(message.from_user.id),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Իմ invite link-ը", url=bot_deep_link(message.from_user.id))],
                [InlineKeyboardButton(text="💬 Կապ ադմինին", url=ADMIN_URL)],
            ]
        ),
    )


@router.message(F.text == "📂 Իմ հայտարարությունները")
async def my_ads(message: Message) -> None:
    ads = get_user_ads(message.from_user.id)
    if not ads:
        await message.answer("Դեռ հայտարարություն չունեք։", reply_markup=main_menu_kb())
        return
    lines = ["📂 <b>Ձեր հայտարարությունները</b>\n"]
    for ad in ads:
        lines.append(f"#{ad['id']} — <b>{html.escape(ad['model'] or '—')}</b> | {html.escape(ad['status'] or '—')}")
    await message.answer("\n".join(lines), reply_markup=delete_ads_kb(ads))


@router.message(F.text == "➕ Հայտարարություն")
async def add_ad_start(message: Message, state: FSMContext) -> None:
    if is_blocked(message.from_user.id):
        await message.answer("⛔️ Դուք արգելափակված եք ադմինիստրացիայի կողմից։")
        return
    if not await user_joined(message.from_user.id):
        await send_join_screen(message)
        return
    await state.clear()
    await state.update_data(step_idx=0, ad_data={"photos": []})
    await state.set_state(AdForm.filling)
    await message.answer("📝 <b>Լրացրեք հայտարարությունը</b>", reply_markup=ReplyKeyboardRemove())
    await message.answer(AD_STEPS[0]["prompt"], reply_markup=ad_step_kb(AD_STEPS[0]))


@router.message(StateFilter(AdForm.filling), F.contact)
async def ad_phone_contact(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    idx = int(data.get("step_idx", 0))
    if idx < len(AD_STEPS) and AD_STEPS[idx]["key"] == "phone":
        await save_step(message, state, message.contact.phone_number)
    else:
        await message.answer("Օգտագործեք ընթացիկ հարցի կոճակները կամ գրեք պատասխան։")


@router.message(StateFilter(AdForm.filling))
async def ad_text_step(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    idx = int(data.get("step_idx", 0))
    if idx >= len(AD_STEPS):
        await message.answer("Այժմ նկարների փուլն է։")
        return
    if message.text and message.text.startswith("/"):
        await message.answer("Օգտագործեք կոճակները կամ գրեք արժեքը։")
        return
    current = AD_STEPS[idx]
    if current["kind"] == "choice":
        matched = None
        for choice in current["choices"]:
            if normalize_text(choice) == normalize_text(message.text or ""):
                matched = choice
                break
        if matched:
            await save_step(message, state, matched)
        else:
            await message.answer("Օգտագործեք կոճակներից մեկը կամ գրեք նույն տարբերակը։", reply_markup=ad_step_kb(current))
    else:
        await save_step(message, state, (message.text or "").strip())


@router.callback_query(F.data.startswith("adchoice:"))
async def ad_choice(callback: CallbackQuery, state: FSMContext) -> None:
    _, key, idx = callback.data.split(":")
    step = next((s for s in AD_STEPS if s["key"] == key), None)
    if not step:
        await callback.answer("Չգտնվեց", show_alert=True)
        return
    idx = int(idx)
    if idx < 0 or idx >= len(step["choices"]):
        await callback.answer("Սխալ տարբերակ", show_alert=True)
        return
    data = await state.get_data()
    if int(data.get("step_idx", 0)) >= len(AD_STEPS) or AD_STEPS[int(data["step_idx"])] ["key"] != key:
        await callback.answer("Այս քայլը հիմա ակտիվ չէ", show_alert=True)
        return
    await callback.answer()
    await save_step(callback.message, state, step["choices"][idx])


@router.callback_query(F.data.startswith("adskip:"))
async def ad_skip(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":")[1]
    data = await state.get_data()
    idx = int(data.get("step_idx", 0))
    if idx >= len(AD_STEPS) or AD_STEPS[idx]["key"] != key:
        await callback.answer("Այս քայլը հիմա ակտիվ չէ", show_alert=True)
        return
    if AD_STEPS[idx]["required"]:
        await callback.answer("Այս դաշտը պարտադիր է", show_alert=True)
        return
    await callback.answer()
    await save_step(callback.message, state, None)


@router.message(StateFilter(AdForm.photos), F.photo)
async def ad_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    ad_data = dict(data.get("ad_data", {}))
    photos = list(ad_data.get("photos", []))
    if len(photos) >= 10:
        await message.answer("Արդեն 10 նկար կա։ Գրեք /done")
        return
    photos.append(message.photo[-1].file_id)
    ad_data["photos"] = photos
    await state.update_data(ad_data=ad_data)
    await message.answer(f"✅ Նկար ընդունվեց ({len(photos)}/10). Կամ շարունակեք, կամ գրեք /done")


@router.message(StateFilter(AdForm.photos), Command("done"))
async def ad_done(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    ad_data = dict(data.get("ad_data", {}))
    photos = list(ad_data.get("photos", []))
    if not photos:
        await message.answer("Պարտադիր է առնվազն 1 նկար։")
        return
    if not ad_data.get("model") or not ad_data.get("phone"):
        await message.answer("Մոդելն ու հեռախոսը պարտադիր են։")
        return
    preview = build_ad_preview_caption(ad_data, message.from_user)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Տեղադրել", callback_data="ad:confirm")], [InlineKeyboardButton(text="❌ Չեղարկել", callback_data="ad:cancel")]])
    await message.answer_photo(photos[0], caption=preview, reply_markup=kb)
    await state.set_state(AdForm.preview)


@router.message(StateFilter(AdForm.photos))
async def ad_photos_wait(message: Message) -> None:
    await message.answer("Ուղարկեք նկար կամ գրեք /done")


@router.callback_query(F.data == "ad:cancel")
async def ad_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("❌ Հայտարարությունը չեղարկվեց։", reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "ad:confirm")
async def ad_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    user = callback.from_user
    data = await state.get_data()
    ad_data = dict(data.get("ad_data", {}))
    if not ad_data.get("model") or not ad_data.get("phone") or not ad_data.get("photos"):
        await callback.answer("Պարտադիր դաշտերը բացակայում են", show_alert=True)
        return
    fp = ad_fingerprint(ad_data)
    if active_duplicate_exists(fp):
        await callback.answer("Նույն մեքենայի հայտարարությունը արդեն կա համակարգում", show_alert=True)
        await callback.message.answer("⚠️ Նույն մեքենայի հայտարարությունը արդեն առկա է կամ սպասում է հաստատման։", reply_markup=main_menu_kb())
        await state.clear()
        return
    ad_id = create_ad(user.id, ad_data, status="pending")
    await send_admin_ad(ad_id, ad_data, user)
    await state.clear()
    await callback.message.answer(f"✅ Ձեր հայտարարությունը ուղարկվել է ադմինին հաստատման համար։\nAd ID: <code>{ad_id}</code>", reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("adapprove:"))
async def ad_approve(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Ադմինի իրավունք չկա", show_alert=True)
        return
    ad_id = int(callback.data.split(":")[1])
    ad = get_ad(ad_id)
    if not ad:
        await callback.answer("Հայտը չի գտնվել", show_alert=True)
        return
    if ad["status"] != "pending":
        await callback.answer("Արդեն մշակված է", show_alert=True)
        return

    ad_data = {
        "model": ad["model"],
        "year": ad["year"],
        "engine": ad["engine"],
        "mileage": ad["mileage"],
        "fuel": ad["fuel"],
        "gearbox": ad["gearbox"],
        "drive": ad["drive"],
        "condition": ad["condition"],
        "issues": ad["issues"],
        "vin": ad["vin"],
        "price": ad["price"],
        "phone": ad["phone"],
        "extra": ad["extra"],
        "photos": json.loads(ad["photos_json"] or "[]"),
    }
    try:
        msg_ids = await post_ad_to_channel(ad_id, ad_data, get_user(ad["user_id"]))
        update_ad_status(ad_id, "approved", msg_ids)
        set_ad_admin(ad_id, callback.from_user)

        user_is_vip = is_vip(ad["user_id"])
        if user_is_vip:
            db("UPDATE ads SET vip_active=1, pin_paid=1, refresh_paid=1 WHERE id=?", (ad_id,))
        elif int(ad["pin_paid"] or 0) == 1:
            db("UPDATE ads SET pin_paid=1 WHERE id=?", (ad_id,))
        if user_is_vip or int(ad["refresh_paid"] or 0) == 1:
            db("UPDATE ads SET refresh_paid=1 WHERE id=?", (ad_id,))
            set_ad_last_refresh(ad_id)

        if user_is_vip or int(ad["pin_paid"] or 0) == 1:
            try:
                await bot.pin_chat_message(CHANNEL_ID, msg_ids[0], disable_notification=True)
            except Exception:
                pass

        await bot.send_message(
            ad["user_id"],
            "✅ Ձեր հայտարարությունը հաստատվեց ու տեղադրվեց ալիքում։\n\n"
            "Դուք կարող եք հիմա ընտրել՝\n"
            "📌 Զակրեպ — 1000 դրամ\n"
            "🔄 Թարմացում — 1000 դրամ\n"
            "💎 VIP — 30000 դրամ\n\n"
            "Մանրամասների կամ խնդիրների համար կապվեք ադմինին։",
            reply_markup=ad_post_offer_kb(ad_id),
        )
        await callback.answer("Հաստատված է", show_alert=False)
        try:
            await callback.message.edit_caption((callback.message.caption or "") + "\n\n✅ Հաստատված է", reply_markup=None)
        except Exception:
            try:
                await callback.message.edit_text((callback.message.text or "") + "\n\n✅ Հաստատված է", reply_markup=None)
            except Exception:
                pass
    except Exception:
        logger.exception("approve failed")
        await callback.answer("Ալիքում տեղադրելը չստացվեց", show_alert=True)


@router.callback_query(F.data.startswith("adreject:"))
async def ad_reject(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Ադմինի իրավունք չկա", show_alert=True)
        return
    ad_id = int(callback.data.split(":")[1])
    ad = get_ad(ad_id)
    if not ad:
        await callback.answer("Հայտը չի գտնվել", show_alert=True)
        return
    update_ad_status(ad_id, "rejected", [])
    set_ad_admin(ad_id, callback.from_user)
    try:
        await bot.send_message(ad["user_id"], "❌ Ձեր հայտարարությունը մերժվեց ադմինի կողմից։", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Կապ ադմինին", url=ADMIN_URL)]]))
    except Exception:
        pass
    await callback.answer("Մերժված է", show_alert=False)


@router.callback_query(F.data.startswith("buy:"))
async def buy_from_offer(callback: CallbackQuery, state: FSMContext) -> None:
    _, kind, adid = callback.data.split(":")
    ad_id = int(adid)
    await state.clear()
    await state.update_data(pay_package=kind, ad_id=ad_id)
    await state.set_state(PaymentFlow.waiting_screenshot)
    amount = {"pin": 1000, "refresh": 1000, "vip": 30000}[kind]
    title = {"pin": "📌 Զակրեպ", "refresh": "🔄 Թարմացում", "vip": "💎 VIP"}[kind]
    await callback.message.answer(f"{title} — <b>{amount}</b> դրամ\n\n<pre>{html.escape(PAYMENT_TEXT)}</pre>\n\nՎճարելուց հետո ուղարկեք չեկը նկարով։", reply_markup=ReplyKeyboardRemove())
    await callback.answer()


@router.callback_query(F.data == "vip:buy")
async def vip_buy(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(pay_package="vip", ad_id=0)
    await state.set_state(PaymentFlow.waiting_screenshot)
    await callback.message.answer(f"💎 <b>VIP — 30000 դրամ</b>\n\n<pre>{html.escape(PAYMENT_TEXT)}</pre>\n\nՈւղարկեք վճարման չեկը նկարով։", reply_markup=ReplyKeyboardRemove())
    await callback.answer()


def ref_credit_ads_kb(ads: list[sqlite3.Row]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for ad in ads[:8]:
        rows.append([InlineKeyboardButton(text=f"#{ad['id']} — {ad['model'] or '—'}", callback_data=f"credit:menu:{ad['id']}")])
    rows.append([InlineKeyboardButton(text="💬 Կապ ադմինին", url=ADMIN_URL)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ref_credit_action_kb(ad_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📌 Օգտագործել որպես զակրեպ", callback_data=f"credit:apply:pin:{ad_id}")],
            [InlineKeyboardButton(text="🔄 Օգտագործել որպես թարմացում", callback_data=f"credit:apply:refresh:{ad_id}")],
            [InlineKeyboardButton(text="💬 Կապ ադմինին", url=ADMIN_URL)],
        ]
    )


@router.callback_query(F.data == "vip:use_ref")
async def vip_use_ref(callback: CallbackQuery) -> None:
    credits = get_ref_credits(callback.from_user.id)
    if credits <= 0:
        await callback.answer("Դեռ credit չունեք", show_alert=True)
        return
    ads = get_user_ads(callback.from_user.id, 10)
    if not ads:
        await callback.message.answer(
            f"🎁 Ձեր credit-ը՝ <b>{credits}</b>\n\nԴեռ հայտարարություն չունեք։ Տեղադրեք հայտարարություն, հետո կարող եք կիրառել credit-ը։",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Կապ ադմինին", url=ADMIN_URL)]]),
        )
        await callback.answer()
        return
    await callback.message.answer(
        f"🎁 Ձեր credit-ը՝ <b>{credits}</b>\n\nԸնտրեք հայտարարությունը, որի վրա ուզում եք օգտագործել credit-ը։",
        reply_markup=ref_credit_ads_kb(ads),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("credit:menu:"))
async def credit_menu(callback: CallbackQuery) -> None:
    ad_id = int(callback.data.split(":")[2])
    ad = get_ad(ad_id)
    if not ad or ad["user_id"] != callback.from_user.id:
        await callback.answer("Իրավունք չունեք", show_alert=True)
        return
    await callback.message.answer(
        f"🎁 Credit կիրառել հայտարարության համար #{ad_id}",
        reply_markup=ref_credit_action_kb(ad_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("credit:apply:"))
async def credit_apply(callback: CallbackQuery) -> None:
    _, _, kind, adid = callback.data.split(":")
    ad_id = int(adid)
    ad = get_ad(ad_id)
    if not ad or ad["user_id"] != callback.from_user.id:
        await callback.answer("Իրավունք չունեք", show_alert=True)
        return
    if get_ref_credits(callback.from_user.id) <= 0:
        await callback.answer("Credit չկա", show_alert=True)
        return
    if not spend_ref_credit(callback.from_user.id):
        await callback.answer("Չհաջողվեց", show_alert=True)
        return

    if kind == "pin":
        mark_ad_pin_paid(ad_id, True)
        if ad["status"] == "approved":
            try:
                mids = json.loads(ad["channel_message_ids_json"] or "[]")
                if mids:
                    await bot.pin_chat_message(CHANNEL_ID, int(mids[0]), disable_notification=True)
            except Exception:
                pass
        msg = "✅ Ձեր credit-ը օգտագործվեց որպես զակրեպ։"
    else:
        mark_ad_refresh_paid(ad_id, True)
        set_ad_last_refresh(ad_id)
        msg = "✅ Ձեր credit-ը օգտագործվեց որպես թարմացում։"

    try:
        await bot.send_message(
            callback.from_user.id,
            msg,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Կապ ադմինին", url=ADMIN_URL)]]),
        )
    except Exception:
        pass
    await callback.answer("Credit կիրառվեց", show_alert=False)


@router.message(StateFilter(PaymentFlow.waiting_screenshot), F.photo)
async def payment_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    package = data.get("pay_package")
    ad_id = int(data.get("ad_id") or 0)
    amount = {"pin": 1000, "refresh": 1000, "vip": 30000}.get(package, 0)
    payment_id = create_payment(message.from_user.id, package, amount, message.photo[-1].file_id, ad_id=ad_id)
    await send_payment_to_admin(payment_id)
    await state.clear()
    await message.answer("✅ Վճարման չեկը ուղարկվեց ադմինին հաստատման համար։", reply_markup=main_menu_kb())


@router.message(StateFilter(PaymentFlow.waiting_screenshot))
async def payment_need_photo(message: Message) -> None:
    await message.answer("Խնդրում ենք ուղարկել վճարման չեկը նկարով։")


@router.callback_query(F.data.startswith("payapprove:"))
async def pay_approve(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Ադմինի իրավունք չկա", show_alert=True)
        return
    payment_id = int(callback.data.split(":")[1])
    payment = get_payment(payment_id)
    if not payment:
        await callback.answer("Վճարումը չի գտնվել", show_alert=True)
        return
    if payment["status"] != "pending":
        await callback.answer("Արդեն մշակված է", show_alert=True)
        return

    package = payment["package"]
    ad_id = payment["ad_id"]
    user_id = payment["user_id"]

    if package == "vip":
        buy_vip_unlimited(user_id)
        if ad_id:
            db("UPDATE ads SET vip_active=1, pin_paid=1, refresh_paid=1 WHERE id=?", (ad_id,))
    elif package == "pin":
        if ad_id:
            mark_ad_pin_paid(ad_id, True)
            ad = get_ad(ad_id)
            if ad and ad["status"] == "approved":
                try:
                    mids = json.loads(ad["channel_message_ids_json"] or "[]")
                    if mids:
                        await bot.pin_chat_message(CHANNEL_ID, int(mids[0]), disable_notification=True)
                except Exception:
                    pass
    elif package == "refresh":
        if ad_id:
            mark_ad_refresh_paid(ad_id, True)
            set_ad_last_refresh(ad_id)

    set_payment_status(payment_id, "approved")
    try:
        if package == "vip":
            await bot.send_message(user_id, "🎉 Ձեր VIP-ը հաստատվեց և ակտիվացվեց անսահմանափակ ձևով։")
        elif package == "pin":
            await bot.send_message(user_id, "✅ Ձեր զակրեպը հաստատվեց։")
        else:
            await bot.send_message(user_id, "✅ Ձեր թարմացումը հաստատվեց։")
    except Exception:
        pass
    await callback.answer("Հաստատված է", show_alert=False)


@router.callback_query(F.data.startswith("payreject:"))
async def pay_reject(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Ադմինի իրավունք չկա", show_alert=True)
        return
    payment_id = int(callback.data.split(":")[1])
    payment = get_payment(payment_id)
    if not payment:
        await callback.answer("Վճարումը չի գտնվել", show_alert=True)
        return
    set_payment_status(payment_id, "rejected")
    try:
        await bot.send_message(payment["user_id"], "❌ Ձեր վճարումը մերժվեց։ Խնդրում ենք կապվել ադմինին։", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Կապ ադմինին", url=ADMIN_URL)]]))
    except Exception:
        pass
    await callback.answer("Մերժված է", show_alert=False)


@router.callback_query(F.data == "menu:back")
async def menu_back(callback: CallbackQuery) -> None:
    await send_main_menu(callback, callback.from_user.id)


@router.callback_query(F.data == "ads:my:delete")
async def ads_my_delete(callback: CallbackQuery) -> None:
    ads = get_user_ads(callback.from_user.id)
    if not ads:
        await callback.message.answer("Դեռ հայտարարություն չունեք։", reply_markup=main_menu_kb())
        await callback.answer()
        return
    await callback.message.answer("Ընտրեք հայտարարությունը ջնջելու համար:", reply_markup=delete_ads_kb(ads))
    await callback.answer()


@router.callback_query(F.data.startswith("addelete:"))
async def ad_delete_action(callback: CallbackQuery) -> None:
    ad_id = int(callback.data.split(":")[1])
    ad = get_ad(ad_id)
    if not ad:
        await callback.answer("Չգտնվեց", show_alert=True)
        return
    if ad["user_id"] != callback.from_user.id and callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Իրավունք չունեք", show_alert=True)
        return
    try:
        mids = json.loads(ad["channel_message_ids_json"] or "[]")
        for mid in mids:
            try:
                await bot.delete_message(CHANNEL_ID, int(mid))
            except Exception:
                pass
    except Exception:
        pass
    update_ad_status(ad_id, "deleted", [])
    await callback.message.answer("🗑 Հայտարարությունը ջնջվեց։", reply_markup=main_menu_kb())
    await callback.answer("Ջնջված է")


@router.message(Command("admin"))
async def admin_cmd(message: Message) -> None:
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Ադմինի իրավունք չկա")
        return
    await message.answer("🛠 <b>Ադմին մենյու</b>", reply_markup=admin_menu_kb())


@router.callback_query(F.data == "admin:back")
async def admin_back(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Ադմինի իրավունք չկա", show_alert=True)
        return
    await callback.message.answer(build_welcome_text(callback.from_user.id), reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:block")
async def admin_block(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Ադմինի իրավունք չկա", show_alert=True)
        return
    await state.clear()
    await state.update_data(admin_action="block")
    await state.set_state(AdminFlow.waiting_user_id)
    await callback.message.answer("Գրեք user ID-ը, որին ուզում եք բլոկել:")
    await callback.answer()


@router.callback_query(F.data == "admin:unblock")
async def admin_unblock(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Ադմինի իրավունք չկա", show_alert=True)
        return
    await state.clear()
    await state.update_data(admin_action="unblock")
    await state.set_state(AdminFlow.waiting_user_id)
    await callback.message.answer("Գրեք user ID-ը, որին ուզում եք ապաբլոկել:")
    await callback.answer()


@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Ադմինի իրավունք չկա", show_alert=True)
        return
    await state.clear()
    await state.set_state(AdminFlow.waiting_broadcast)
    await callback.message.answer("Գրեք broadcast-ի տեքստը:")
    await callback.answer()


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Ադմինի իրավունք չկա", show_alert=True)
        return
    total_users = count_table("users")
    active_vip = count_table("users", "vip_active=1")
    blocked = count_table("users", "blocked=1")
    pending_ads = count_table("ads", "status='pending'")
    approved_ads = count_table("ads", "status='approved'")
    rejected_ads = count_table("ads", "status='rejected'")
    deleted_ads = count_table("ads", "status='deleted'")
    pending_pay = count_table("payments", "status='pending'")
    await callback.message.answer(
        "📊 <b>Stats</b>\n\n"
        f"Users — <b>{total_users}</b>\n"
        f"Active VIP — <b>{active_vip}</b>\n"
        f"Blocked — <b>{blocked}</b>\n"
        f"Pending ads — <b>{pending_ads}</b>\n"
        f"Approved ads — <b>{approved_ads}</b>\n"
        f"Rejected ads — <b>{rejected_ads}</b>\n"
        f"Deleted ads — <b>{deleted_ads}</b>\n"
        f"Payments pending — <b>{pending_pay}</b>\n"
    )
    await callback.answer()


@router.callback_query(F.data == "admin:history")
async def admin_history(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Ադմինի իրավունք չկա", show_alert=True)
        return
    await state.clear()
    await state.set_state(AdminFlow.waiting_history_user_id)
    await callback.message.answer("Գրեք user ID-ը, որի պատմությունը ուզում եք տեսնել:")
    await callback.answer()


@router.message(StateFilter(AdminFlow.waiting_user_id))
async def admin_user_id(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Գրեք միայն թվային user ID։")
        return
    uid = int(raw)
    action = (await state.get_data()).get("admin_action")
    if action == "block":
        set_block(uid, True)
        await message.answer(f"✅ User {uid} բլոկվեց", reply_markup=admin_menu_kb())
    elif action == "unblock":
        set_block(uid, False)
        await message.answer(f"✅ User {uid} ապաբլոկվեց", reply_markup=admin_menu_kb())
    await state.clear()


@router.message(StateFilter(AdminFlow.waiting_broadcast))
async def admin_broadcast_text(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    users = db("SELECT user_id, blocked FROM users", fetchall=True) or []
    ok = fail = 0
    for u in users:
        if int(u["blocked"]) == 1:
            continue
        try:
            await bot.send_message(int(u["user_id"]), message.text or "")
            ok += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(float(e.retry_after) + 0.2)
            try:
                await bot.send_message(int(u["user_id"]), message.text or "")
                ok += 1
            except Exception:
                fail += 1
        except Exception:
            fail += 1
    await state.clear()
    await message.answer(f"✅ Broadcast ավարտվեց. Առաքված՝ {ok}, սխալ՝ {fail}", reply_markup=admin_menu_kb())


@router.message(StateFilter(AdminFlow.waiting_history_user_id))
async def admin_history_text(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Գրեք միայն թվային user ID։")
        return
    uid = int(raw)
    user = get_user(uid)
    if not user:
        await message.answer("User-ը չի գտնվել", reply_markup=admin_menu_kb())
        await state.clear()
        return
    ads = get_user_ads(uid, 10)
    acts = get_recent_activity(uid, 10)
    text = [
        "👤 <b>User history</b>",
        f"ID: <code>{uid}</code>",
        f"Username: @{html.escape(user['username']) if user['username'] else '—'}",
        f"Name: {html.escape(user['first_name'] or '')}",
        f"Blocked: {'yes' if user['blocked'] else 'no'}",
        f"Verified: {'yes' if user['verified'] else 'no'}",
        f"VIP: {'yes' if user['vip_active'] else 'no'}",
        f"Referrals: {user['ref_count']}",
        f"Referral credits: {user['ref_credits']}",
        "",
        "<b>Ads</b>",
    ]
    if ads:
        for ad in ads:
            text.append(f"#{ad['id']} — {html.escape(ad['model'] or '—')} — {html.escape(ad['status'] or '—')}")
    else:
        text.append("No ads")
    text += ["", "<b>Recent activity</b>"]
    if acts:
        for a in acts:
            text.append(f"• {human_ts(a['created_at'])} | {html.escape(a['action'] or '')} | {html.escape(a['details'] or '')}")
    else:
        text.append("No activity")
    await message.answer("\n".join(text), reply_markup=admin_menu_kb())
    await state.clear()


@router.message()
async def fallback(message: Message) -> None:
    if is_blocked(message.from_user.id):
        await message.answer("⛔️ Դուք արգելափակված եք ադմինիստրացիայի կողմից։")
        return
    if not await user_joined(message.from_user.id):
        await send_join_screen(message)
        return
    await message.answer("Օգտագործեք գլխավոր մենյուի կոճակները։", reply_markup=main_menu_kb())


async def main() -> None:
    await on_startup()
    asyncio.create_task(refresh_vip_ads_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
