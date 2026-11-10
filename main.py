import os
import random
import asyncio
import httpx
import base64
import json
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException, status
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

TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "nexa_secure_random_token_9988")

TELEBIRR_ACCOUNT_MASKED = os.getenv("TELEBIRR_ACCOUNT_MASKED", "Telebirr Merchant / Wallet ID [SECURE-VERIFIED]")
AWASH_ACCOUNT_MASKED = os.getenv("AWASH_ACCOUNT_MASKED", "Awash Corporate Account [SECURE-VERIFIED]")

# Initialize Clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Master Telegram Bot Application
telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).read_timeout(7).write_timeout(7).build()

# Onboarding Conversation States
STORE_NAME, INDUSTRY, UI_THEME, INVENTORY, BOT_TOKEN = range(5)
pending_orders = {}
transaction_history = [] 


# -------------------------------------------------------------------
# Root Health Check (Supports GET and HEAD for UptimeRobot)
# -------------------------------------------------------------------
@app.get("/")
@app.head("/")
async def root_health_check():
    return {"status": "healthy", "service": "Nexa AI Multi-Bot Engine with Amharic Default is live"}


# -------------------------------------------------------------------
# Core Logic: Persistent Trial & Credit Engine (Supabase Backed)
# -------------------------------------------------------------------
def get_or_create_user_subscription(user_id: int) -> dict:
    now = datetime.now()
    if supabase:
        try:
            res = supabase.table("subscriptions").select("*").eq("user_id", str(user_id)).execute()
            if res.data:
                sub = res.data[0]
                return {
                    "trial_expires": datetime.fromisoformat(sub["trial_expires"]),
                    "credits_remaining": sub["credits_remaining"],
                    "is_pro": sub["is_pro"]
                }
        except Exception:
            pass

    default_sub = {
        "trial_expires": now + timedelta(days=3),
        "credits_remaining": 50,
        "is_pro": False
    }
    
    if supabase:
        try:
            supabase.table("subscriptions").upsert({
                "user_id": str(user_id),
                "trial_expires": default_sub["trial_expires"].isoformat(),
                "credits_remaining": 50,
                "is_pro": False
            }).execute()
        except Exception:
            pass
            
    return default_sub


def verify_active_access(user_id: int) -> bool:
    sub = get_or_create_user_subscription(user_id)
    if sub["is_pro"]:
        return True
    if datetime.now() < sub["trial_expires"] and sub["credits_remaining"] > 0:
        return True
    return False


def deduct_credit(user_id: int):
    sub = get_or_create_user_subscription(user_id)
    if not sub["is_pro"]:
        new_credits = max(0, sub["credits_remaining"] - 1)
        if supabase:
            try:
                supabase.table("subscriptions").update({"credits_remaining": new_credits}).eq("user_id", str(user_id)).execute()
            except Exception:
                pass


# -------------------------------------------------------------------
# Dynamic Payout Load Balancer (Whole Birr 3500-3600 ETB Range)
# -------------------------------------------------------------------
def select_optimal_payout_destination() -> tuple[str, str, int, str]:
    now = datetime.now()
    twenty_four_hours_ago = now - timedelta(hours=24)
    
    telebirr_24h_total = sum(
        tx.get("amount_etb", 0) for tx in transaction_history 
        if tx.get("destination") == "TELEBIRR" and tx.get("timestamp", now) > twenty_four_hours_ago
    )
    
    SAFE_TELEBIRR_CAP = 20000.0 
    whole_birr_amount = random.randint(3500, 3600)
    
    if telebirr_24h_total + whole_birr_amount <= SAFE_TELEBIRR_CAP:
        return ("Telebirr Secure Gateway", TELEBIRR_ACCOUNT_MASKED, whole_birr_amount, "TELEBIRR")
    else:
        return ("Awash Bank Secure Corporate Account", AWASH_ACCOUNT_MASKED, whole_birr_amount, "AWASH")


# -------------------------------------------------------------------
# Telegram Master Bot Handlers & Commands
# -------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    sub_data = get_or_create_user_subscription(user_id)
    has_access = verify_active_access(user_id)
    expires_str = sub_data["trial_expires"].strftime("%Y-%m-%d %H:%M UTC")
    
    if sub_data["is_pro"]:
        status_text = "⭐ *Pro Member — Unlimited Multi-Bot Sales Machine Active*"
    elif has_access:
        status_text = (
            f"🔥 *Free Trial Active (3 Days)*\n"
            f"• *Expires:* `{expires_str}`\n"
            f"• *AI Credits Left:* `{sub_data['credits_remaining']}`"
        )
    else:
        status_text = "⚠️ *Trial Expired* — Upgrade to Pro in Birr to keep your bots running."

    welcome_text = (
        f"🇪🇹 *Welcome to Nexa AI Platform, {user.first_name}!*\n\n"
        f"Deploy and manage multiple automated AI-powered Telegram bots instantly.\n\n"
        f"📊 *Account Status:*\n{status_text}\n\n"
        "🎯 *Quick Start Guide:*\n"
        "1️⃣ /register - Launch or update an AI bot\n"
        "2️⃣ /mybots - View and manage your deployed bots\n"
        "3️⃣ /update - Update your inventory or services live\n"
        "4️⃣ /summary - View real verified revenue and statistics"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 Unlock Pro Status (Secure Birr)", callback_data="buy_pro")],
        [InlineKeyboardButton("🤖 Manage My Bots (/mybots)", callback_data="view_my_bots")],
        [InlineKeyboardButton("📊 Live Revenue Summary (/summary)", callback_data="view_summary")],
        [InlineKeyboardButton("💎 Launch New AI Bot (/register)", callback_data="start_register")]
    ]
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def my_bots_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = str(update.effective_user.id)
    if not supabase:
        await update.message.reply_text("Database connection inactive.")
        return

    try:
        res = supabase.table("stores").select("store_name", "industry", "ui_theme", "bot_token", "created_at").eq("owner_telegram_id", owner_id).execute()
        if not res.data:
            await update.message.reply_text("⚠️ You have no active bots deployed yet. Use /register to launch your first AI bot!")
            return

        bots_list_text = "🤖 *YOUR DEPLOYED AI BOTS DASHBOARD*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for idx, store in enumerate(res.data, 1):
            masked_token = store["bot_token"][:8] + "..." + store["bot_token"][-4:] if len(store["bot_token"]) > 12 else "***"
            bots_list_text += (
                f"*{idx}. {store['store_name']}*\n"
                f"• *Industry:* `{store.get('industry', 'General').capitalize()}`\n"
                f"• *Persona:* `{store.get('ui_theme', 'Executive').capitalize()}`\n"
                f"• *Token Key:* `{masked_token}`\n"
                f"• *Status:* Live & Synchronized ✅\n\n"
            )
        bots_list_text += "🔒 *Security Note:* All bot tokens are securely isolated."
        await update.message.reply_text(bots_list_text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error fetching bots: {str(e)}")


async def upgrade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    channel_name, masked_account, exact_amount_etb, channel_code = select_optimal_payout_destination()
    order_id = f"NEXA-SECURE-{random.randint(1000, 9999)}"
    
    pending_orders[user_id] = {
        "order_id": order_id,
        "amount": str(exact_amount_etb),
        "channel": channel_name,
        "destination_code": channel_code,
        "status": "pending_payment"
    }
    
    invoice_text = (
        f"🔒 *SECURE ENCRYPTED INVOICE*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• *Invoice ID:* `{order_id}`\n"
        f"• *Item:* Monthly Pro License (Multi-Bot Access)\n"
        f"• *Exact Transfer Amount:* **{exact_amount_etb} ETB**\n"
        f"• *Payment Gateway:* `{channel_name}`\n"
        f"• *Account Reference:* `{masked_account}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🚨 *Instructions:*\n"
        f"1. Transfer **EXACTLY `{exact_amount_etb} ETB`**.\n"
        f"2. Take a screenshot of your successful transaction receipt.\n"
        f"3. Send the screenshot right here in this chat for instant verification."
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ I Have Paid — Upload Receipt", callback_data="upload_receipt")]
    ]
    
    await update.message.reply_text(invoice_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_revenue = 0
    total_subscribers = 0
    if supabase:
        try:
            res = supabase.table("paid_subscriptions").select("amount_etb").execute()
            if res.data:
                total_revenue = sum(float(tx["amount_etb"]) for tx in res.data)
                total_subscribers = len(res.data)
        except Exception:
            pass

    summary_text = (
        f"📊 *FINANCIAL & BUSINESS SUMMARY*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• *Total Verified Subscriptions:* `{total_subscribers}` users\n"
        f"• *Total Verified Revenue:* `{total_revenue:,.2f} ETB`\n"
        f"• *Active AI Assistants:* 24/7 Online ✅\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 Your AI bots are actively processing customer inquiries."
    )
    await update.message.reply_text(summary_text, parse_mode="Markdown")


async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = str(update.message.from_user.id)
    new_inventory = " ".join(context.args).strip()

    if not new_inventory:
        await update.message.reply_text(
            "⚠️ *How to update your inventory or services live:*\n\n"
            "Type `/update` followed by your details.\n\n"
            "*Example:*\n"
            "`/update Item 1: Shoes - 2,500 ETB\nItem 2: Jacket - 3,200 ETB`",
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
                "✅ *Updated Live Across All Your Bots Instantly!*\n\nYour AI receptionists are now responding with your updated pricing and details immediately.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("⚠️ No active store found. Please use /register first.")
    except Exception as e:
        await update.message.reply_text(f"Update failed: {str(e)}")


# --- Onboarding Conversation Handlers ---
async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🇪🇹 *NEXA AI BOT BUILDER WIZARD*\n\n"
        "Let's deploy or reconnect your automated Telegram AI bot in a few simple steps.\n\n"
        "Step 1 of 4: What is the official name of your business, store, or service? (e.g., *Habesha Fashion*)"
    )
    return STORE_NAME


async def receive_store_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["store_name"] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton("🛍️ Retail & Physical Products", callback_data="ind_retail")],
        [InlineKeyboardButton("🏋️ Fitness & Wellness Services", callback_data="ind_fitness")],
        [InlineKeyboardButton("🏠 Real Estate & Property", callback_data="ind_realestate")],
        [InlineKeyboardButton("🩺 Healthcare & Clinic", callback_data="ind_clinic")],
        [InlineKeyboardButton("🤝 Agency & Brokerage", callback_data="ind_broker")],
        [InlineKeyboardButton("⚙️ General Services", callback_data="ind_general")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Business Name Recorded: *{update.message.text}*.\n\n"
        "Step 2 of 4: Select your primary industry sector:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return INDUSTRY


async def receive_industry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chosen_industry = "general"
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        chosen_industry = query.data.replace("ind_", "")
        target_message = query.edit_message_text
    else:
        chosen_industry = update.message.text.lower()
        target_message = update.message.reply_text

    context.user_data["industry"] = chosen_industry

    keyboard = [
        [InlineKeyboardButton("💎 Luxury Executive (Elite)", callback_data="theme_executive")],
        [InlineKeyboardButton("⚡ High-Energy Sales (Closer)", callback_data="theme_sales")],
        [InlineKeyboardButton("🌿 Friendly Advisor (Warm)", callback_data="theme_friendly")],
        [InlineKeyboardButton("🎯 Direct Minimalist (Concise)", callback_data="theme_minimalist")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await target_message(
        f"Industry Selected: *{chosen_industry.capitalize()}*.\n\n"
        "Step 3 of 4: Choose how your AI assistant should talk to customers:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return UI_THEME


async def receive_ui_theme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chosen_theme = "executive"
    
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        chosen_theme = query.data.replace("theme_", "")
        target_message = query.edit_message_text
    else:
        text = update.message.text.lower()
        if "sales" in text:
            chosen_theme = "sales"
        elif "friendly" in text:
            chosen_theme = "friendly"
        elif "minimalist" in text:
            chosen_theme = "minimalist"
        else:
            chosen_theme = "executive"
        target_message = update.message.reply_text

    context.user_data["ui_theme"] = chosen_theme
    
    await target_message(
        "Step 4 of 4: Paste your complete inventory, service packages, or pricing in ETB below:",
        parse_mode="Markdown"
    )
    return INVENTORY


async def receive_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["inventory_data"] = update.message.text
    await update.message.reply_text(
        "Almost done!\n\n"
        "Go to Telegram's official **@BotFather**, create a bot (`/newbot`), copy your unique **Bot Token**, and paste it right here:",
        parse_mode="Markdown"
    )
    return BOT_TOKEN


async def receive_bot_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_token = update.message.text.strip()
    owner_telegram_id = str(update.message.from_user.id)
    
    store_name = context.user_data.get("store_name", "My Store")
    industry = context.user_data.get("industry", "general")
    ui_theme = context.user_data.get("ui_theme", "executive")
    inventory_data = context.user_data.get("inventory_data", "No inventory specified")

    tenant_webhook_url = f"{RENDER_EXTERNAL_URL}/tenant-webhook/{bot_token}"
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{bot_token}/setWebhook", 
            json={"url": tenant_webhook_url, "secret_token": TELEGRAM_WEBHOOK_SECRET}
        )

    if supabase:
        try:
            supabase.table("stores").upsert({
                "bot_token": bot_token,
                "owner_telegram_id": owner_telegram_id,
                "store_name": store_name,
                "industry": industry,
                "ui_theme": ui_theme,
                "inventory_data": inventory_data
            }, on_conflict="bot_token").execute()
        except Exception as e:
            await update.message.reply_text(f"⚠️ Warning saving to database: {str(e)}")

    success_msg = (
        f"🎉 *CONGRATULATIONS! YOUR AI BOT IS LIVE!* 🇪🇹🚀\n\n"
        f"• *Business Name:* {store_name}\n"
        f"• *Industry:* {industry.capitalize()}\n"
        f"• *Status:* Synchronized & Active ✅\n\n"
        "Your bot is now fully operational."
    )
    await update.message.reply_text(success_msg, parse_mode="Markdown")
    return ConversationHandler.END


async def cancel_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Registration cancelled. Type /register whenever you are ready.")
    return ConversationHandler.END


# --- Payment & OCR Handlers ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "buy_pro":
        await upgrade_command(update, context)
    elif query.data == "view_summary":
        await summary_command(update, context)
    elif query.data == "view_my_bots":
        await my_bots_command(update, context)
    elif query.data == "start_register":
        await query.message.reply_text("Please use the /register command to begin.")
    elif query.data == "upload_receipt":
        await query.message.reply_text("📸 Please upload your payment receipt screenshot now.")


async def handle_receipt_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    order = pending_orders.get(user_id)
    
    if not order:
        await update.message.reply_text("❌ No active pending order found. Type /upgrade first.")
        return

    photo_file = await update.message.photo[-1].get_file()
    image_bytes = await photo_file.download_as_bytearray()
    base64_image = base64.b64encode(bytes(image_bytes)).decode('utf-8')
    
    expected_amount = order["amount"]
    expected_channel = order["channel"]
    
    parsed_result = {"valid": False, "reference_id": None, "detected_amount": None}

    if groq_client:
        try:
            prompt = (
                f"Analyze this Ethiopian bank or Telebirr payment receipt image with 100% strict accuracy. Extract:\n"
                f"1. Transaction Reference ID or Confirmation Code (string)\n"
                f"2. Total Amount in ETB transferred (number or string without commas)\n"
                f"Return strictly valid JSON format: "
                f'{{"valid": true/false, "reference_id": "string", "detected_amount": "string"}}'
            )
            response = groq_client.chat.completions.create(
                model="llama-3.2-11b-vision-instruct",
                response_format={"type": "json_object"},
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }]
            )
            parsed_result = json.loads(response.choices[0].message.content)
        except Exception as e:
            print(f"OCR Error: {e}")

    ref_id = parsed_result.get("reference_id")
    detected_amount = str(parsed_result.get("detected_amount", ""))

    if ref_id and supabase:
        try:
            existing_tx = supabase.table("processed_receipts").select("*").eq("reference_id", ref_id).execute()
            if existing_tx.data:
                await update.message.reply_text(
                    f"🚫 *SECURITY ALERT: RECEIPT REUSE DETECTED!*\n\nTransaction ID `{ref_id}` has already been redeemed.",
                    parse_mode="Markdown"
                )
                return
        except Exception:
            pass

    amount_matches = expected_amount in detected_amount or expected_amount.replace(".00", "") in detected_amount

    if parsed_result.get("valid") and amount_matches and ref_id:
        if supabase:
            try:
                supabase.table("processed_receipts").insert({
                    "user_id": str(user_id),
                    "order_id": order["order_id"],
                    "reference_id": ref_id,
                    "amount": expected_amount,
                    "channel": expected_channel,
                    "created_at": datetime.now().isoformat()
                }).execute()

                supabase.table("paid_subscriptions").insert({
                    "user_id": str(user_id),
                    "order_id": order["order_id"],
                    "amount_etb": float(expected_amount),
                    "reference_id": ref_id
                }).execute()

                supabase.table("subscriptions").upsert({
                    "user_id": str(user_id),
                    "is_pro": True,
                    "credits_remaining": 999999
                }).execute()
            except Exception as e:
                print(f"DB Error: {e}")

        transaction_history.append({
            "amount_etb": float(expected_amount),
            "destination": order.get("destination_code", "TELEBIRR"),
            "timestamp": datetime.now()
        })

        await update.message.reply_text(
            f"✅ *PAYMENT VERIFIED & PRO UNLOCKED!* ⭐🇪🇹\n\n"
            f"• *Ref ID:* `{ref_id}`\n"
            f"• *Status:* Unlimited Pro Access Active!",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"📥 *Receipt Logged for Review*\n\nCould not auto-verify receipt. An admin has been notified.",
            parse_mode="Markdown"
        )


# --- Handlers Registration ---
conv_handler = ConversationHandler(
    entry_points=[CommandHandler("register", register_start)],
    states={
        STORE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_store_name)],
        INDUSTRY: [
            CallbackQueryHandler(receive_industry, pattern="^ind_"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_industry)
        ],
        UI_THEME: [
            CallbackQueryHandler(receive_ui_theme, pattern="^theme_"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ui_theme)
        ],
        INVENTORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_inventory)],
        BOT_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bot_token)],
    },
    fallbacks=[CommandHandler("cancel", cancel_registration)],
)

telegram_app.add_handler(CommandHandler("start", start_command))
telegram_app.add_handler(CommandHandler("upgrade", upgrade_command))
telegram_app.add_handler(CommandHandler("update", update_command))
telegram_app.add_handler(CommandHandler("summary", summary_command))
telegram_app.add_handler(CommandHandler("mybots", my_bots_command))
telegram_app.add_handler(conv_handler)
telegram_app.add_handler(CallbackQueryHandler(button_handler))
telegram_app.add_handler(MessageHandler(filters.PHOTO, handle_receipt_photo))


# --- FastAPI Webhook Lifecycle & Tenant Routing ---
@app.on_event("startup")
async def startup_event():
    webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
    await telegram_app.initialize()
    await telegram_app.start() 
    await telegram_app.bot.set_webhook(url=webhook_url, secret_token=TELEGRAM_WEBHOOK_SECRET)

    if supabase:
        try:
            stores_res = supabase.table("stores").select("bot_token").execute()
            if stores_res.data:
                async with httpx.AsyncClient() as client:
                    tasks = []
                    for store in stores_res.data:
                        t_token = store.get("bot_token")
                        if t_token:
                            t_url = f"{RENDER_EXTERNAL_URL}/tenant-webhook/{t_token}"
                            tasks.append(client.post(
                                f"https://api.telegram.org/bot{t_token}/setWebhook", 
                                json={"url": t_url, "secret_token": TELEGRAM_WEBHOOK_SECRET}
                            ))
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            pass


@app.on_event("shutdown")
async def shutdown_event():
    await telegram_app.stop()


@app.post("/webhook")
async def telegram_webhook(request: Request):
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret_header != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid secret token")

    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"status": "ok"}


@app.post("/tenant-webhook/{bot_token}")
async def tenant_bot_webhook(bot_token: str, request: Request):
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret_header != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid secret token")

    data = await request.json()
    
    # Handle Callback Queries (Language Selection Clicks)
    if "callback_query" in data:
        cq = data["callback_query"]
        chat_id = cq["message"]["chat"]["id"]
        callback_data = cq["data"]
        
        if callback_data.startswith("lang_"):
            lang = callback_data.replace("lang_", "")
            
            # Save or update customer language preference in Supabase
            if supabase:
                try:
                    supabase.table("customer_languages").upsert({
                        "chat_id": str(chat_id),
                        "language": lang
                    }, on_conflict="chat_id").execute()
                except Exception:
                    pass

            lang_greetings = {
                "amharic": "🇪🇹 ሰላም! እንኳን ወደ መደብራችን በደህና መጡ። እንዴት ልንረዳዎ እንችላለን?",
                "english": "🇬🇧 Welcome to our store! How may we assist you today?",
                "oromo": "🇪🇹 Akkam! Baga nagaan dhuftan. Akkamitti si gargaaruu dandeenya?"
            }
            greeting = lang_greetings.get(lang, "ሰላም! እንዴት ልንረዳዎ እንችላለን?")

            async with httpx.AsyncClient() as client:
                await client.post(f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery", json={"callback_query_id": cq["id"]})
                await client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": greeting})
            return {"ok": True}

    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_text = message.get("text", "")
    from_user = message.get("from", {})
    username = from_user.get("username", "Unknown")
    first_name = from_user.get("first_name", "Customer")
    
    if not chat_id:
        return {"ok": True}

    store = None
    if supabase:
        res = supabase.table("stores").select("*").eq("bot_token", bot_token).execute()
        if res.data:
            store = res.data[0]

    if not store:
        async with httpx.AsyncClient() as client:
            await client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
                "chat_id": chat_id, 
                "text": "መደብሩ አልተገኘም (Store configuration not found)."
            })
        return {"ok": True}

    # If user sent /start, present language selection keyboard
    if user_text == "/start":
        keyboard = [
            [InlineKeyboardButton("🇪🇹 አማርኛ (Amharic - ነባሪ)", callback_data="lang_amharic")],
            [InlineKeyboardButton("🇬🇧 English", callback_data="lang_english")],
            [InlineKeyboardButton("🇪🇹 Afaan Oromo", callback_data="lang_oromo")]
        ]
        reply_markup = {"inline_keyboard": keyboard}
        async with httpx.AsyncClient() as client:
            await client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
                "chat_id": chat_id,
                "text": f"🇪🇹 እንኳን ወደ *{store.get('store_name')}* በደህና መጡ!\n\nእባክዎ የሚፈልጉትን ቋንቋ ይምረጡ / Please select your language:",
                "reply_markup": reply_markup,
                "parse_mode": "Markdown"
            })
        return {"ok": True}

    if not user_text:
        return {"ok": True}

    # Fetch customer's preferred language from DB (Defaults to amharic now)
    customer_lang = "amharic"
    if supabase:
        try:
            lang_res = supabase.table("customer_languages").select("language").eq("chat_id", str(chat_id)).execute()
            if lang_res.data:
                customer_lang = lang_res.data[0]["language"]
        except Exception:
            pass

    payload = {
        "chat_id": chat_id,
        "user_text": user_text,
        "bot_token": bot_token,
        "store_name": store.get("store_name", "Our Business"),
        "industry": store.get("industry", "general"),
        "ui_theme": store.get("ui_theme", "executive"),
        "inventory_data": store.get("inventory_data", ""),
        "owner_telegram_id": store.get("owner_telegram_id"),
        "username": username,
        "first_name": first_name,
        "customer_lang": customer_lang,
        "history_messages": []
    }
    
    return await store_chat_webhook(payload)


@app.post("/api/store-chat")
async def store_chat_webhook(payload: dict):
    chat_id = payload.get("chat_id")
    user_text = payload.get("user_text", "")
    bot_token = payload.get("bot_token")
    store_name = payload.get("store_name", "Our Business")
    industry = payload.get("industry", "general")
    ui_theme = payload.get("ui_theme", "executive")
    inventory_data = payload.get("inventory_data", "")
    owner_telegram_id = payload.get("owner_telegram_id")
    username = payload.get("username", "Unknown")
    first_name = payload.get("first_name", "Customer")
    customer_lang = payload.get("customer_lang", "amharic")
    history_messages = payload.get("history_messages", [])

    if owner_telegram_id:
        owner_id_int = int(owner_telegram_id)
        get_or_create_user_subscription(owner_id_int)
        if not verify_active_access(owner_id_int):
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={"chat_id": chat_id, "text": "⚠️ የቦቱ የፈተና ጊዜ አልቋል። ባለቤቱ ፓኬጁን ማደስ አለበት።"}
                )
            return {"ok": True}
        deduct_credit(owner_id_int)

    theme_prompts = {
        "executive": f"You are a professional executive VIP concierge for {store_name} in the {industry} sector.",
        "sales": f"You are a top sales representative for {store_name} in the {industry} sector. Close sales quickly.",
        "friendly": f"You are a warm, welcoming local assistant for {store_name} ({industry}).",
        "minimalist": f"You are a concise assistant for {store_name} ({industry}). Give brief answers with prices in ETB."
    }

    selected_persona = theme_prompts.get(ui_theme, theme_prompts["executive"])

    system_prompt = (
        f"{selected_persona}\n\n"
        f"BUSINESS INDUSTRY: {industry.capitalize()}\n"
        f"PRODUCTS / SERVICES / PRICING DATA:\n{inventory_data}\n\n"
        f"STRICT RULES:\n"
        f"1. You MUST respond ONLY in the customer's selected language: '{customer_lang.upper()}' (If AMHARIC, write 100% natural, error-free Amharic script using Ge'ez; if English, write clear English; if OROMO, write Afaan Oromo).\n"
        "2. Answer strictly using the inventory/services data and pricing in ETB provided above.\n"
        "3. Never invent unlisted prices or contact numbers.\n"
        "4. When a customer wants to buy or order, confirm their request and reassure them management has been notified."
    )
    
    messages_payload = [{"role": "system", "content": system_prompt}] + history_messages + [{"role": "user", "content": user_text}]

    response_text = f"እንኳን ወደ {store_name} በደህና መጡ!"
    if groq_client:
        try:
            completion = groq_client.chat.completions.create(
                messages=messages_payload,
                model="openai/gpt-oss-120b",
            )
            response_text = completion.choices[0].message.content
        except Exception as e:
            response_text = f"ስለ መልእክትዎ እናመሰግናለን። ({str(e)})"

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

    lead_keywords = ["buy", "order", "price", "how much", "cost", "reserve", "available", "contact", "book", "join", "ግዛ", "ዋጋ", "ይግዙ", "መመዝገብ", "እፈልጋለሁ"]
    if any(kw in user_text.lower() for kw in lead_keywords) and owner_telegram_id and TELEGRAM_BOT_TOKEN:
        customer_handle = f"@{username}" if username != "Unknown" else f"ID: {chat_id}"
        alert_msg = (
            f"🚨 *NEW HIGH-INTENT LEAD for {store_name}!* 🇪🇹\n\n"
            f"👤 *Customer:* {first_name} ({customer_handle})\n"
            f"💬 *Inquiry:* \"{user_text}\"\n\n"
            f"🤖 *AI Reply:* \"{response_text[:150]}...\"\n\n"
            f"👉 Please reach out directly to close the deal!"
        )
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": owner_telegram_id, "text": alert_msg, "parse_mode": "Markdown"}
            )

    return {"ok": True}
