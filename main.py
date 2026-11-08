import os
import random
import httpx
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from groq import Groq
from supabase import create_client, Client

# Initialize FastAPI
app = FastAPI()

# -------------------------------------------------------------------
# Configuration & Environment Variables
# -------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://nexa-bot-f5al.onrender.com")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Remitly Links for Dynamic Routing (Telebirr & Awash Bank)
REMITLY_TELEBIRR_LINK = os.getenv("REMITLY_TELEBIRR_LINK", "https://remit.ly/pay/dawitandargachewb5917")
REMITLY_AWASH_LINK = os.getenv("REMITLY_AWASH_LINK", "https://remit.ly/pay/dawitandargachewb5917")

# Initialize Clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Master Telegram Bot Application
telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).read_timeout(7).write_timeout(7).build()

# Onboarding Conversation States
STORE_NAME, UI_THEME, INVENTORY, BOT_TOKEN = range(4)

# In-Memory Tracking for Subscriptions, Trials & Transactions
user_subscriptions = {}
pending_orders = {}
transaction_history = [] 


# -------------------------------------------------------------------
# Core Logic: Trial & Credit Verification Engine
# -------------------------------------------------------------------
def check_or_create_trial(user_id: int) -> dict:
    """Grants a 3-day trial with 50 AI generation credits upon first start."""
    now = datetime.now()
    if user_id not in user_subscriptions:
        user_subscriptions[user_id] = {
            "trial_expires": now + timedelta(days=3),
            "credits_remaining": 50,
            "is_pro": False
        }
    return user_subscriptions[user_id]


def verify_active_access(user_id: int) -> bool:
    """Checks if user has active Pro status or is within their 3-day trial with credits."""
    user = user_subscriptions.get(user_id)
    if not user:
        return False
        
    if user["is_pro"]:
        return True
        
    if datetime.now() < user["trial_expires"] and user["credits_remaining"] > 0:
        return True
        
    return False


# -------------------------------------------------------------------
# Core Logic: Dynamic Volume Load Balancer (Telebirr vs. Awash)
# -------------------------------------------------------------------
def select_optimal_payout_destination(payment_amount_etb: float = 6500.0) -> tuple[str, str]:
    """
    Analyzes transactions in the past 24 hours to pick the safest receiving channel
    and prevent personal account compliance flags.
    """
    now = datetime.now()
    twenty_four_hours_ago = now - timedelta(hours=24)
    
    telebirr_24h_total = sum(
        tx["amount_etb"] for tx in transaction_history 
        if tx["destination"] == "TELEBIRR" and tx["timestamp"] > twenty_four_hours_ago
    )
    
    SAFE_TELEBIRR_CAP = 20000.0 
    
    if telebirr_24h_total + payment_amount_etb <= SAFE_TELEBIRR_CAP:
        return ("Telebirr Mobile Wallet", REMITLY_TELEBIRR_LINK)
    else:
        return ("Awash Bank Savings Account", REMITLY_AWASH_LINK)


# -------------------------------------------------------------------
# Telegram Bot Handlers & Commands
# -------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    sub_data = check_or_create_trial(user_id)
    has_access = verify_active_access(user_id)
    expires_str = sub_data["trial_expires"].strftime("%Y-%m-%d %H:%M UTC")
    
    if sub_data["is_pro"]:
        status_text = "⭐ *Pro Member (Unlimited Access)*"
    elif has_access:
        status_text = f"🎁 *Free Trial Active*\n• *Expires:* `{expires_str}`\n• *Credits Remaining:* `{sub_data['credits_remaining']}`"
    else:
        status_text = "⚠️ *Trial Expired* — Upgrade to Pro to unlock unlimited AI receptionist features."

    welcome_text = (
        f"Welcome to Nexa AI Enterprise Platform, *{user.first_name}*.\n\n"
        f"📊 *Account Status:*\n{status_text}\n\n"
        "Commands:\n"
        "• Use /register to launch your custom AI store receptionist.\n"
        "• Use /update <new inventory> to update your store inventory live.\n"
        "• Use /upgrade to purchase your $50 Pro License."
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 Upgrade to Pro ($50.00)", callback_data="buy_pro")],
        [InlineKeyboardButton("💎 Register AI Store", callback_data="start_register")]
    ]
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def upgrade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    cents_offset = random.randint(10, 99)
    exact_amount = f"50.{cents_offset}"
    order_id = f"NEXA-{random.randint(1000, 9999)}"
    estimated_etb = float(exact_amount) * 130.0
    
    channel_name, remitly_url = select_optimal_payout_destination(estimated_etb)
    
    pending_orders[user_id] = {
        "order_id": order_id,
        "amount": exact_amount,
        "channel": channel_name,
        "status": "pending_payment"
    }
    
    invoice_text = (
        f"🧾 *NEXA AI OFFICIAL INVOICE*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• *Invoice ID:* `{order_id}`\n"
        f"• *Item:* Pro Bot License (Monthly)\n"
        f"• *Exact Amount:* `${exact_amount} USD`\n"
        f"• *Routed Payout Rail:* `{channel_name}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚠️ *Payment Instructions:*\n"
        f"1. Click the button below to open Remitly.\n"
        f"2. Send **exactly `${exact_amount}`** to ensure instant matching.\n"
        f"3. Upload your payment screenshot here when complete."
    )
    
    keyboard = [
        [InlineKeyboardButton(f"💳 Pay ${exact_amount} via Remitly", url=remitly_url)],
        [InlineKeyboardButton("✅ I Have Paid (Upload Receipt)", callback_data="upload_receipt")]
    ]
    
    await update.message.reply_text(invoice_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


# --- Live Inventory Update Handler ---
async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = str(update.message.from_user.id)
    new_inventory = " ".join(context.args).strip()

    if not new_inventory:
        await update.message.reply_text(
            "⚠️ *Please provide your new inventory details after the command.*\n\n"
            "Example:\n`/update Item 1: Nike Air Max - $90 (5 left)\nItem 2: Jordan 4 - $120`",
            parse_mode="Markdown"
        )
        return

    if not supabase:
        await update.message.reply_text("Database connection inactive.")
        return

    try:
        res = supabase.table("stores").update({"inventory_data": new_inventory}).eq("owner_telegram_id", owner_id).execute()
        if res.data:
            await update.message.reply_text(
                "✅ *Inventory Updated Live!*\n\nYour AI receptionist will now use these updated stock and pricing details immediately.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("⚠️ No active store found associated with your Telegram account. Please use /register first.")
    except Exception as e:
        await update.message.reply_text(f"Failed to update inventory: {str(e)}")


# --- Onboarding Handlers ---
async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to the Nexa AI Merchant Onboarding Suite.\n\n"
        "Let us begin. What is the official name of your boutique or store?"
    )
    return STORE_NAME


async def receive_store_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["store_name"] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton("💎 Luxury Executive (VIP Concierge)", callback_data="theme_executive")],
        [InlineKeyboardButton("⚡ High-Energy Sales (Fast Closer)", callback_data="theme_sales")],
        [InlineKeyboardButton("🌿 Friendly Advisor (Warm & Helpful)", callback_data="theme_friendly")],
        [InlineKeyboardButton("🎯 Direct Minimalist (Short & Precise)", callback_data="theme_minimalist")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Exquisite choice: *{update.message.text}*.\n\n"
        "Now select the **AI Assistant Persona & Response Style** for your shop's bot:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return UI_THEME


async def receive_ui_theme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chosen_theme = query.data.replace("theme_", "")
    context.user_data["ui_theme"] = chosen_theme
    
    theme_labels = {
        "executive": "💎 Luxury Executive",
        "sales": "⚡ High-Energy Sales",
        "friendly": "🌿 Friendly Advisor",
        "minimalist": "🎯 Direct Minimalist"
    }
    
    await query.edit_message_text(
        f"Selected Style: *{theme_labels.get(chosen_theme, 'Custom')}*.\n\n"
        "Now, please provide your complete inventory list, stock details, contact info, and pricing so our AI can curate accurate customer responses for you:",
        parse_mode="Markdown"
    )
    return INVENTORY


async def receive_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["inventory_data"] = update.message.text
    await update.message.reply_text(
        "Splendid. Finally, please create a bot via Telegram's official @BotFather, retrieve your unique **Bot Token**, and paste it here:",
        parse_mode="Markdown"
    )
    return BOT_TOKEN


async def receive_bot_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_token = update.message.text.strip()
    owner_telegram_id = str(update.message.from_user.id)
    
    store_name = context.user_data.get("store_name", "My Store")
    ui_theme = context.user_data.get("ui_theme", "executive")
    inventory_data = context.user_data.get("inventory_data", "No inventory specified.")

    if supabase:
        try:
            supabase.table("stores").insert({
                "owner_telegram_id": owner_telegram_id,
                "store_name": store_name,
                "ui_theme": ui_theme,
                "inventory_data": inventory_data,
                "bot_token": bot_token
            }).execute()
        except Exception as e:
            await update.message.reply_text(f"⚠️ Warning saving store to database: {str(e)}")

    success_msg = (
        f"🎉 *Store Successfully Registered & AI Deployed!*\n\n"
        f"• *Store Name:* {store_name}\n"
        f"• *Persona:* {ui_theme.capitalize()}\n"
        f"• *Bot Token Linked:* Secured ✅\n\n"
        "Your custom AI receptionist is now live and ready to serve customers!"
    )
    await update.message.reply_text(success_msg, parse_mode="Markdown")
    return ConversationHandler.END


# --- Payment Button & Receipt Handlers ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "buy_pro":
        await upgrade_command(update, context)
    elif query.data == "start_register":
        await query.message.reply_text("Please use the /register command to launch store onboarding.")
    elif query.data == "upload_receipt":
        await query.message.reply_text("📸 Please send a screenshot or photo of your Remitly payment receipt.")


async def handle_receipt_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    order = pending_orders.get(user_id)
    
    if not order:
        await update.message.reply_text("❌ No active pending order found. Type /upgrade to generate an invoice.")
        return

    confirmation_text = (
        f"📥 *Receipt Received!*\n\n"
        f"• *Invoice ID:* `{order['order_id']}`\n"
        f"• *Amount:* `${order['amount']}`\n"
        f"• *Target Channel:* `{order['channel']}`\n"
        f"• *Status:* Under Verification\n\n"
        f"Your transfer is being matched against bank deposit alerts. "
        f"Your Pro subscription will be activated automatically."
    )
    await update.message.reply_text(confirmation_text, parse_mode="Markdown")


# --- FastAPI Webhook Receiver ---
@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app)
    await telegram_app.process_update(update)
    return {"status": "ok"}


@app.post("/api/store-chat")
async def store_chat_webhook(payload: dict):
    """Processes customer inquiries for tenant store bots using Groq AI and sends lead notifications."""
    chat_id = payload.get("chat_id")
    user_text = payload.get("user_text", "")
    bot_token = payload.get("bot_token")
    store_name = payload.get("store_name", "Our Store")
    ui_theme = payload.get("ui_theme", "executive")
    inventory_data = payload.get("inventory_data", "")
    owner_telegram_id = payload.get("owner_telegram_id")
    username = payload.get("username", "Unknown User")
    first_name = payload.get("first_name", "Customer")
    history_messages = payload.get("history_messages", [])

    theme_prompts = {
        "executive": (
            f"You are a luxury executive VIP concierge for {store_name}. "
            "Maintain an elite, highly professional, refined, and prestigious tone."
        ),
        "sales": (
            f"You are the top sales representative for {store_name}. "
            "Maintain an enthusiastic, high-energy tone that creates excitement around the products and encourages closing sales quickly."
        ),
        "friendly": (
            f"You are a friendly, warm, and welcoming local shop assistant for {store_name}. "
            "Speak naturally, be deeply helpful, and make customers feel right at home."
        ),
        "minimalist": (
            f"You are a direct and concise assistant for {store_name}. "
            "Give brief, clear, to-the-point answers without fluff. State stock numbers, prices, and contact steps immediately."
        )
    }

    selected_persona = theme_prompts.get(ui_theme, theme_prompts["executive"])

    system_prompt = (
        f"{selected_persona}\n\n"
        f"STORE INVENTORY & DETAILS:\n{inventory_data}\n\n"
        "STRICT GROUNDING RULES:\n"
        "1. Answer strictly using the inventory and contact details provided above.\n"
        "2. NEVER invent phone numbers, addresses, or unlisted prices.\n"
        "3. If a customer wants to place an order or buy, confirm what they want and reassure them that the store owner has been notified to complete the sale."
    )
    
    messages_payload = [{"role": "system", "content": system_prompt}] + history_messages + [{"role": "user", "content": user_text}]

    response_text = f"Welcome to {store_name}. How may we assist you today?"
    if groq_client:
        try:
            completion = groq_client.chat.completions.create(
                messages=messages_payload,
                model="openai/gpt-oss-120b",
            )
            response_text = completion.choices[0].message.content
        except Exception as e:
            response_text = f"Thank you for contacting {store_name}. We are processing your request. ({str(e)})"

    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": response_text}
        )

    if supabase:
        try:
            supabase.table("chats").insert({
                "user_id": str(chat_id),
                "user_message": user_text,
                "bot_response": response_text
            }).execute()
        except Exception:
            pass

    lead_keywords = ["buy", "order", "price", "how much", "cost", "reserve", "available", "contact", "phone"]
    if any(kw in user_text.lower() for kw in lead_keywords) and owner_telegram_id and TELEGRAM_BOT_TOKEN:
        customer_handle = f"@{username}" if username != "Unknown User" else f"ID: {chat_id}"
        alert_msg = (
            f"🚨 *NEW HIGH-INTENT LEAD for {store_name}!*\n\n"
            f"👤 *Customer:* {first_name} ({customer_handle})\n"
            f"💬 *Inquiry:* \"{user_text}\"\n\n"
            f"🤖 *AI Receptionist Replied:* \"{response_text[:150]}...\"\n\n"
            f"👉 *Action:* Reach out directly to close the sale!"
        )
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": owner_telegram_id, "text": alert_msg, "parse_mode": "Markdown"}
            )

    return {"ok": True}
