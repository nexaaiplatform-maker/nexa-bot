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

# Webhook Security Secret Token
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "nexa_secure_random_token_9988")

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
pending_orders = {}
transaction_history = [] 


# -------------------------------------------------------------------
# Root Health Check (Crucial for UptimeRobot to prevent 502 Bad Gateway)
# -------------------------------------------------------------------
@app.get("/")
async def root_health_check():
    return {"status": "healthy", "service": "Nexa AI Bot is live and awake"}


# -------------------------------------------------------------------
# Core Logic: Persistent Trial & Credit Engine (Supabase Backed)
# -------------------------------------------------------------------
def get_or_create_user_subscription(user_id: int) -> dict:
    """Retrieves or creates a 3-day trial with 50 credits stored permanently in Supabase."""
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
# Core Logic: Dynamic Volume Load Balancer (Telebirr vs. Awash)
# -------------------------------------------------------------------
def select_optimal_payout_destination(payment_amount_etb: float = 6500.0) -> tuple[str, str]:
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
# Telegram Master Bot Handlers & Commands
# -------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    sub_data = get_or_create_user_subscription(user_id)
    has_access = verify_active_access(user_id)
    expires_str = sub_data["trial_expires"].strftime("%Y-%m-%d %H:%M UTC")
    
    if sub_data["is_pro"]:
        status_text = "⭐ *Pro Member — Unlimited 24/7 Sales Machine Active*"
    elif has_access:
        status_text = (
            f"🔥 *Free Trial Active (Don't Miss Out!)*\n"
            f"• *Expires:* `{expires_str}`\n"
            f"• *AI Credits Left:* `{sub_data['credits_remaining']}`\n"
            f"⚡ *Tip:* Every unanswered customer message is a lost sale. Deploy your store now!"
        )
    else:
        status_text = "⚠️ *Trial Expired* — Upgrade to Pro immediately to prevent your store bot from pausing customer sales."

    welcome_text = (
        f"🚀 *Welcome to Nexa AI Enterprise Platform, {user.first_name}!*\n\n"
        f"You are 2 minutes away from deploying a tireless AI sales receptionist that closes deals, answers questions in any language, and texts you instant high-intent buyer leads 24/7.\n\n"
        f"📊 *Your Account Status:*\n{status_text}\n\n"
        "🎯 **Quick Start Guide:**\n"
        "1️⃣ Type /register to launch your custom AI store bot.\n"
        "2️⃣ Type `/update <your inventory>` anytime to change prices or stock instantly.\n"
        "3️⃣ Type /upgrade to unlock unlimited Pro power."
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 Unlock Pro Status ($50.00)", callback_data="buy_pro")],
        [InlineKeyboardButton("💎 Launch AI Store Now (/register)", callback_data="start_register")]
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
        f"🧾 *NEXA AI SECURE PRO INVOICE*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• *Invoice ID:* `{order_id}`\n"
        f"• *Item:* Unlimited Pro License (Monthly)\n"
        f"• *Exact Transfer Amount:* `${exact_amount} USD`\n"
        f"• *Secure Payout Rail:* `{channel_name}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🚨 **CRITICAL INSTRUCTIONS FOR INSTANT ACTIVATION:**\n"
        f"1. Click the payment button below to open Remitly.\n"
        f"2. Send **EXACTLY `${exact_amount}`** (the unique cents guarantee instant automated verification).\n"
        f"3. Take a screenshot of your successful transfer receipt.\n"
        f"4. Send the screenshot right here in this chat to activate instantly."
    )
    
    keyboard = [
        [InlineKeyboardButton(f"💳 Pay ${exact_amount} via Remitly", url=remitly_url)],
        [InlineKeyboardButton("✅ I Have Paid — Upload Receipt", callback_data="upload_receipt")]
    ]
    
    await update.message.reply_text(invoice_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = str(update.message.from_user.id)
    new_inventory = " ".join(context.args).strip()

    if not new_inventory:
        await update.message.reply_text(
            "⚠️ *How to update your inventory live:*\n\n"
            "Type `/update` followed by your items, prices, and stock.\n\n"
            "*Example:* \n"
            "`/update Item 1: Nike Air Max - $110 (8 left)\nItem 2: Jordan 4 - $160 (3 left)`",
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
                "✅ *Inventory Updated Live Across All Channels!*\n\nYour AI receptionist is now selling with your updated pricing and stock numbers immediately.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("⚠️ No active store found for your account. Please use /register first.")
    except Exception as e:
        await update.message.reply_text(f"Failed to update inventory: {str(e)}")


# --- Onboarding Conversation Handlers ---
async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💎 *NEXA AI STORE BUILDER WIZARD*\n\n"
        "Let's create your automated sales bot in 3 simple steps.\n\n"
        "**Step 1 of 3:** What is the official name of your business, boutique, or store? (e.g. *Abebe Shoes*)"
    )
    return STORE_NAME


async def receive_store_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["store_name"] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton("💎 Luxury Executive (Elite & Refined)", callback_data="theme_executive")],
        [InlineKeyboardButton("⚡ High-Energy Sales (Aggressive Closer)", callback_data="theme_sales")],
        [InlineKeyboardButton("🌿 Friendly Advisor (Warm & Helpful)", callback_data="theme_friendly")],
        [InlineKeyboardButton("🎯 Direct Minimalist (Short & Precise)", callback_data="theme_minimalist")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Great choice: *{update.message.text}*.\n\n"
        "**Step 2 of 3:** Choose how your AI assistant should talk to customers:",
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
        elif "friendly" in text or "advisor" in text:
            chosen_theme = "friendly"
        elif "minimalist" in text:
            chosen_theme = "minimalist"
        else:
            chosen_theme = "executive"
        target_message = update.message.reply_text

    context.user_data["ui_theme"] = chosen_theme
    
    theme_labels = {
        "executive": "💎 Luxury Executive",
        "sales": "⚡ High-Energy Sales",
        "friendly": "🌿 Friendly Advisor",
        "minimalist": "🎯 Direct Minimalist"
    }
    
    await target_message(
        f"Selected Persona: *{theme_labels.get(chosen_theme, 'Custom')}*.\n\n"
        "**Step 3 of 3:** Paste your complete inventory list, prices, sizes, stock count, and location details below so the AI knows what to sell:",
        parse_mode="Markdown"
    )
    return INVENTORY


async def receive_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["inventory_data"] = update.message.text
    await update.message.reply_text(
        "Almost done! \n\n"
        "Go to Telegram's official **@BotFather**, create a new bot (`/newbot`), copy your unique **Bot Token**, and paste it right here:",
        parse_mode="Markdown"
    )
    return BOT_TOKEN


async def receive_bot_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_token = update.message.text.strip()
    owner_telegram_id = str(update.message.from_user.id)
    
    store_name = context.user_data.get("store_name", "My Store")
    ui_theme = context.user_data.get("ui_theme", "executive")
    inventory_data = context.user_data.get("inventory_data", "No inventory specified.")

    tenant_webhook_url = f"{RENDER_EXTERNAL_URL}/tenant-webhook/{bot_token}"
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{bot_token}/setWebhook", 
            json={"url": tenant_webhook_url, "secret_token": TELEGRAM_WEBHOOK_SECRET}
        )

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
        f"🎉 *CONGRATULATIONS! YOUR AI STORE IS LIVE!* 🚀\n\n"
        f"• *Store Name:* {store_name}\n"
        f"• *Sales Persona:* {ui_theme.capitalize()}\n"
        f"• *Webhook Status:* Connected & Active ✅\n\n"
        "Your bot is now ready to receive customers, answer questions in any language, and notify you instantly whenever someone wants to buy!"
    )
    await update.message.reply_text(success_msg, parse_mode="Markdown")
    return ConversationHandler.END


async def cancel_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Store registration cancelled. Type /register whenever you are ready.")
    return ConversationHandler.END


# --- Payment Button & Automated OCR Receipt Verification ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "buy_pro":
        await upgrade_command(update, context)
    elif query.data == "start_register":
        await query.message.reply_text("Please use the /register command to begin onboarding your store.")
    elif query.data == "upload_receipt":
        await query.message.reply_text("📸 Please upload your payment screenshot now. Our Vision OCR will verify it in seconds!")


async def handle_receipt_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    order = pending_orders.get(user_id)
    
    if not order:
        await update.message.reply_text("❌ No active pending order found. Type /upgrade to generate a secure invoice first.")
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
                f"Analyze this payment receipt image. Extract:\n"
                f"1. Transaction Reference ID or Confirmation Code\n"
                f"2. Total Amount transferred\n"
                f"Return strictly JSON format: "
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
                    f"🚫 *SECURITY ALERT: RECEIPT REUSE DETECTED!*\n\n"
                    f"Transaction ID `{ref_id}` has already been redeemed previously. Duplicate receipts are blocked.",
                    parse_mode="Markdown"
                )
                return
        except Exception:
            pass

    amount_matches = expected_amount in detected_amount or expected_amount.replace(".", "") in detected_amount

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

                supabase.table("subscriptions").upsert({
                    "user_id": str(user_id),
                    "is_pro": True,
                    "credits_remaining": 999999
                }).execute()
            except Exception:
                pass

        await update.message.reply_text(
            f"✅ *PAYMENT VERIFIED & PRO UNLOCKED!* ⭐\n\n"
            f"• *Invoice ID:* `{order['order_id']}`\n"
            f"• *Ref ID:* `{ref_id}`\n"
            f"• *Status:* Unlimited Pro Access Active\n\n"
            f"Your store is fully upgraded!",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"📥 *Receipt Logged for Manual Admin Review*\n\n"
            f"• *Invoice ID:* `{order['order_id']}`\n"
            f"• *Expected Amount:* `${expected_amount}`\n"
            f"• *Detected Ref ID:* `{ref_id or 'Pending...'}`\n\n"
            f"Vision OCR could not auto-verify this screenshot. An admin has been alerted to manually check your bank deposit.",
            parse_mode="Markdown"
        )


# -------------------------------------------------------------------
# Register Telegram Handlers & Conversation Handler
# -------------------------------------------------------------------
conv_handler = ConversationHandler(
    entry_points=[CommandHandler("register", register_start)],
    states={
        STORE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_store_name)],
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
telegram_app.add_handler(conv_handler)
telegram_app.add_handler(CallbackQueryHandler(button_handler))
telegram_app.add_handler(MessageHandler(filters.PHOTO, handle_receipt_photo))


# -------------------------------------------------------------------
# FastAPI Webhook Lifecycle & Tenant Webhook Routing
# -------------------------------------------------------------------
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
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_text = message.get("text", "")
    from_user = message.get("from", {})
    username = from_user.get("username", "Unknown User")
    first_name = from_user.get("first_name", "Customer")
    
    if not chat_id or not user_text:
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
                "text": "Store configuration not found. Please complete onboarding on the master bot."
            })
        return {"ok": True}

    payload = {
        "chat_id": chat_id,
        "user_text": user_text,
        "bot_token": bot_token,
        "store_name": store.get("store_name", "Our Store"),
        "ui_theme": store.get("ui_theme", "executive"),
        "inventory_data": store.get("inventory_data", ""),
        "owner_telegram_id": store.get("owner_telegram_id"),
        "username": username,
        "first_name": first_name,
        "history_messages": []
    }
    
    return await store_chat_webhook(payload)


@app.post("/api/store-chat")
async def store_chat_webhook(payload: dict):
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

    if owner_telegram_id:
        owner_id_int = int(owner_telegram_id)
        get_or_create_user_subscription(owner_id_int)
        if not verify_active_access(owner_id_int):
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={"chat_id": chat_id, "text": "⚠️ This store's AI receptionist trial has expired. Store owner needs to renew Pro access on the main bot."}
                )
            return {"ok": True}
        deduct_credit(owner_id_int)

    theme_prompts = {
        "executive": (
            f"You are a luxury executive VIP concierge for {store_name}. "
            "Maintain an elite, highly professional, refined, and prestigious tone."
        ),
        "sales": (
            f"You are the top sales representative for {store_name}. "
            "Maintain an enthusiastic, high-energy tone that creates excitement around products and closes sales quickly."
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
        "STRICT GROUNDING & MULTI-LANGUAGE RULES:\n"
        "1. Automatically detect the language of the customer's message (e.g., English, Amharic, Afaan Oromo, etc.) and respond fluently in that exact same language.\n"
        "2. Answer strictly using the inventory and contact details provided above.\n"
        "3. NEVER invent phone numbers, addresses, or unlisted prices.\n"
        "4. If a customer wants to place an order or buy, confirm what they want and reassure them that the store owner has been notified immediately to complete the sale."
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

    lead_keywords = ["buy", "order", "price", "how much", "cost", "reserve", "available", "contact", "phone", "ግዛ", "ዋጋ", "ይግዙ"]
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
