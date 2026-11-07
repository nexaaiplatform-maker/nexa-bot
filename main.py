import os
import httpx
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

# Load Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://nexa-bot-f5al.onrender.com")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Initialize Clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Master Telegram Bot
telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).read_timeout(7).write_timeout(7).build()

# Onboarding Conversation States
STORE_NAME, UI_THEME, INVENTORY, BOT_TOKEN = range(4)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "Welcome to Nexa AI Enterprise Platform. It is an absolute privilege to assist you.\n\n"
        "To launch your own custom AI-powered store receptionist (like BotFather), please use the command /register."
    )
    await update.message.reply_text(welcome_text)

# --- Onboarding Handlers ---
async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to the Nexa AI Merchant Onboarding Suite.\n\n"
        "Let us begin. What is the official name of your boutique or store?"
    )
    return STORE_NAME

async def receive_store_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["store_name"] = update.message.text
    
    # Present Interactive Elite UI Theme Options
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
    store_name = context.user_data.get("store_name")
    ui_theme = context.user_data.get("ui_theme", "executive")
    inventory_data = context.user_data.get("inventory_data")

    if supabase:
        try:
            res = supabase.table("stores").insert({
                "owner_telegram_id": owner_telegram_id,
                "store_name": store_name,
                "bot_token": bot_token,
                "inventory_data": inventory_data,
                "ui_theme": ui_theme,
                "is_active": True
            }).execute()
            
            store_id = res.data[0]["id"]
            webhook_url = f"{RENDER_EXTERNAL_URL}/webhook/{store_id}"
            
            async with httpx.AsyncClient() as client:
                await client.get(f"https://api.telegram.org/bot{bot_token}/setWebhook?url={webhook_url}")
                me_response = await client.get(f"https://api.telegram.org/bot{bot_token}/getMe")
                bot_info = me_response.json()
                
            bot_username = bot_info.get("result", {}).get("username", "")
            bot_link = f"https://t.me/{bot_username}" if bot_username else "Your Custom Bot"
            qr_code_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={bot_link}"

            success_message = (
                f"🎉 *Congratulations! Your store {store_name} is officially live on Nexa AI!*\n\n"
                f"🤖 *Bot Handle:* @{bot_username}\n"
                f"🎨 *Active Theme Style:* {ui_theme.upper()}\n"
                f"🔗 *Direct Link:* {bot_link}\n\n"
                "⚡ *Live Lead Alert:* Whenever a customer asks to buy or order, you will instantly receive a notification right here in Telegram!"
            )
            
            await update.message.reply_text(success_message, parse_mode="Markdown")
            if bot_username:
                await update.message.reply_photo(
                    photo=qr_code_url,
                    caption=f"📱 *Scan QR Code to launch @{bot_username}*",
                    parse_mode="Markdown"
                )
        except Exception as e:
            await update.message.reply_text(f"Error registering store bot: {str(e)}")
    else:
        await update.message.reply_text("Database connection inactive.")

    return ConversationHandler.END

async def cancel_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Registration cancelled. Type /register to restart.")
    return ConversationHandler.END

# Master bot message handler
async def handle_master_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user_text = update.message.text
    response_text = "Welcome to Nexa AI. Use /register to launch your custom store bot."
    if groq_client:
        try:
            completion = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are Nexa AI, an elite executive concierge platform."},
                    {"role": "user", "content": user_text}
                ],
                model="openai/gpt-oss-120b",
            )
            response_text = completion.choices[0].message.content
        except Exception:
            pass
    await update.message.reply_text(response_text)

onboarding_handler = ConversationHandler(
    entry_points=[CommandHandler("register", register_start)],
    states={
        STORE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_store_name)],
        UI_THEME: [CallbackQueryHandler(receive_ui_theme)],
        INVENTORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_inventory)],
        BOT_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bot_token)],
    },
    fallbacks=[CommandHandler("cancel", cancel_registration)],
)

telegram_app.add_handler(onboarding_handler)
telegram_app.add_handler(CommandHandler("start", start_command))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_master_message))

@app.on_event("startup")
async def startup_event():
    await telegram_app.initialize()
    await telegram_app.start()
    
    # Auto-resync webhooks on server boot
    if supabase:
        try:
            stores = supabase.table("stores").select("id, bot_token").eq("is_active", True).execute()
            async with httpx.AsyncClient() as client:
                for store in stores.data:
                    w_url = f"{RENDER_EXTERNAL_URL}/webhook/{store['id']}"
                    await client.get(f"https://api.telegram.org/bot{store['bot_token']}/setWebhook?url={w_url}")
        except Exception as e:
            print(f"Startup resync warning: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    await telegram_app.stop()

@app.get("/")
def home():
    return {"status": "Nexa AI SaaS Multi-Tenant Platform is fully operational."}

@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}

# --- DYNAMIC MULTI-TENANT DISPATCHER ---
@app.post("/webhook/{store_id}")
async def dynamic_store_webhook(store_id: str, request: Request):
    data = await request.json()
    if not supabase:
        return {"ok": False, "error": "Database offline"}

    # Fetch store details
    store_res = supabase.table("stores").select("*").eq("id", store_id).execute()
    if not store_res.data:
        return {"ok": False, "error": "Store not found"}
    
    store = store_res.data[0]
    bot_token = store["bot_token"]
    store_name = store["store_name"]
    inventory_data = store["inventory_data"]
    ui_theme = store.get("ui_theme", "executive")
    owner_telegram_id = store.get("owner_telegram_id")

    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_text = message.get("text")
    username = message.get("from", {}).get("username", "Unknown User")
    first_name = message.get("from", {}).get("first_name", "Customer")

    if not chat_id or not user_text:
        return {"ok": True}

    # Fetch last 3 previous interactions for conversation memory
    history_messages = []
    try:
        chat_history = supabase.table("chats").select("user_message, bot_response").eq("user_id", str(chat_id)).order("created_at", desc=True).limit(3).execute()
        for item in reversed(chat_history.data):
            history_messages.append({"role": "user", "content": item["user_message"]})
            history_messages.append({"role": "assistant", "content": item["bot_response"]})
    except Exception:
        pass

    # Dynamic Theme Prompts
    theme_prompts = {
        "executive": (
            f"You are the world-class executive concierge for {store_name}. "
            "Maintain an ultra-polished, elegant, and high-end tone. Provide structured and refined responses."
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

    # Send response back to customer
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": response_text}
        )

    # Save to database chat log
    try:
        supabase.table("chats").insert({
            "user_id": str(chat_id),
            "user_message": user_text,
            "bot_response": response_text
        }).execute()
    except Exception:
        pass

    # INSTANT LEAD NOTIFICATION TO STORE OWNER
    lead_keywords = ["buy", "order", "price", "how much", "cost", "reserve", "available", "contact", "phone"]
    if any(kw in user_text.lower() for kw in lead_keywords) and owner_telegram_id:
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
