import os
import sqlite3
import time
import threading
from io import BytesIO

import qrcode
import razorpay
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
RAZORPAY_KEY_ID = os.environ["RAZORPAY_KEY_ID"]
RAZORPAY_KEY_SECRET = os.environ["RAZORPAY_KEY_SECRET"]
RAZORPAY_WEBHOOK_SECRET = os.environ["RAZORPAY_WEBHOOK_SECRET"]
GROUP_INVITE_LINK = os.getenv("GROUP_INVITE_LINK", "")
PORT = int(os.getenv("PORT", "8080"))
DB_PATH = os.getenv("DB_PATH", "bot.db")

rzp = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
app = Flask(__name__)

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        balance_paise INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS payments (
        payment_link_id TEXT PRIMARY KEY,
        telegram_id INTEGER NOT NULL,
        amount_paise INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'created',
        payment_id TEXT UNIQUE
    );
    CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        price_paise INTEGER NOT NULL,
        telegram_file_id TEXT NOT NULL
    );
    """)
    con.commit()
    con.close()

def ensure_user(tg_id):
    con = db()
    con.execute("INSERT OR IGNORE INTO users(telegram_id) VALUES (?)", (tg_id,))
    con.commit()
    con.close()

def money(paise):
    return f"₹{paise/100:.2f}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user.id)
    kb = [
        [InlineKeyboardButton("🎬 Get Video", callback_data="videos")],
        [InlineKeyboardButton("💰 Balance", callback_data="balance"),
         InlineKeyboardButton("➕ Add Balance", callback_data="add_balance")]
    ]
    await update.message.reply_text(
        "Welcome! Choose an option:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ensure_user(q.from_user.id)
    con = db()
    row = con.execute(
        "SELECT balance_paise FROM users WHERE telegram_id=?", (q.from_user.id,)
    ).fetchone()
    con.close()
    await q.message.reply_text(f"💰 Your balance: {money(row['balance_paise'])}")

async def add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = [
        [InlineKeyboardButton("₹10", callback_data="pay:1000"),
         InlineKeyboardButton("₹20", callback_data="pay:2000")],
        [InlineKeyboardButton("₹50", callback_data="pay:5000"),
         InlineKeyboardButton("₹100", callback_data="pay:10000")]
    ]
    await q.message.reply_text(
        "Select amount to add:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def create_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    amount = int(q.data.split(":")[1])
    tg_id = q.from_user.id

    data = {
        "amount": amount,
        "currency": "INR",
        "accept_partial": False,
        "description": f"Balance top-up for Telegram user {tg_id}",
        "reference_id": f"tg_{tg_id}_{amount}_{int(time.time())}",
        "customer": {"name": q.from_user.full_name[:100]},
        "notify": {"sms": False, "email": False},
        "reminder_enable": False
    }
    link = rzp.payment_link.create(data)
    link_id = link["id"]
    short_url = link["short_url"]

    con = db()
    con.execute(
        "INSERT INTO payments(payment_link_id, telegram_id, amount_paise) VALUES (?,?,?)",
        (link_id, tg_id, amount)
    )
    con.commit()
    con.close()

    img = qrcode.make(short_url)
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)

    await q.message.reply_photo(
        photo=bio,
        caption=(
            f"💳 Add {money(amount)}\n\n"
            "Scan the QR and complete payment. "
            "Your balance is credited only after Razorpay confirms the payment."
        ),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Pay / Open", url=short_url)]]
        )
    )

async def show_videos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    con = db()
    rows = con.execute(
        "SELECT id,title,price_paise FROM videos ORDER BY id"
    ).fetchall()
    con.close()
    if not rows:
        await q.message.reply_text("No videos are available yet.")
        return
    kb = [[InlineKeyboardButton(
        f"{r['title']} — {money(r['price_paise'])}",
        callback_data=f"buy:{r['id']}"
    )] for r in rows]
    await q.message.reply_text(
        "🎬 Select a video:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def buy_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tg_id = q.from_user.id
    video_id = int(q.data.split(":")[1])

    con = db()
    user = con.execute(
        "SELECT balance_paise FROM users WHERE telegram_id=?", (tg_id,)
    ).fetchone()
    video = con.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()

    if not user or not video:
        con.close()
        await q.message.reply_text("Something went wrong.")
        return

    if user["balance_paise"] < video["price_paise"]:
        con.close()
        await q.message.reply_text(
            f"❌ Insufficient balance.\n"
            f"Price: {money(video['price_paise'])}\n"
            f"Balance: {money(user['balance_paise'])}"
        )
        return

    con.execute(
        "UPDATE users SET balance_paise=balance_paise-? WHERE telegram_id=?",
        (video["price_paise"], tg_id)
    )
    con.commit()
    con.close()

    await q.message.reply_video(
        video=video["telegram_file_id"],
        caption=f"✅ {video['title']}"
    )

@app.post("/razorpay/webhook")
def razorpay_webhook():
    raw = request.get_data()
    signature = request.headers.get("X-Razorpay-Signature", "")
    try:
        rzp.utility.verify_webhook_signature(
            raw.decode("utf-8"), signature, RAZORPAY_WEBHOOK_SECRET
        )
    except Exception:
        return jsonify({"ok": False}), 400

    payload = request.get_json(silent=True) or {}
    if payload.get("event") != "payment_link.paid":
        return jsonify({"ok": True})

    try:
        pl = payload["payload"]["payment_link"]["entity"]
        payment = payload["payload"]["payment"]["entity"]
        link_id = pl["id"]
        payment_id = payment["id"]
        amount = int(payment["amount"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"ok": False}), 400

    con = db()
    row = con.execute(
        "SELECT * FROM payments WHERE payment_link_id=?", (link_id,)
    ).fetchone()

    if row and row["status"] != "paid":
        con.execute(
            "UPDATE payments SET status='paid', payment_id=? WHERE payment_link_id=?",
            (payment_id, link_id)
        )
        con.execute(
            "UPDATE users SET balance_paise=balance_paise+? WHERE telegram_id=?",
            (amount, row["telegram_id"])
        )
        con.commit()
    con.close()
    return jsonify({"ok": True})

@app.get("/health")
def health():
    return "OK"

if __name__ == "__main__":
    init_db()
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=PORT),
        daemon=True
    ).start()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(balance, pattern="^balance$"))
    application.add_handler(CallbackQueryHandler(add_balance, pattern="^add_balance$"))
    application.add_handler(CallbackQueryHandler(create_payment, pattern=r"^pay:\d+$"))
    application.add_handler(CallbackQueryHandler(show_videos, pattern="^videos$"))
    application.add_handler(CallbackQueryHandler(buy_video, pattern=r"^buy:\d+$"))

    print("TELEGRAM BOT POLLING STARTING...", flush=True)
    application.run_polling()
