import os
import httpx
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from groq import Groq
from supabase import create_client, Client

# Initialize FastAPI
app = FastAPI()

# Load Environment Variables from Render
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://nexa-bot-f5al.onrender.com")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Initialize Supabase & Groq
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Initialize Master Telegram Bot Application
telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).read_timeout(7).write_timeout(7).build()

# Conversation States for Merchant Onboarding
STORE_NAME, INVENTORY, BOT_TOKEN = range(3)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "Welcome to Nexa AI Enterprise Platform. It is an absolute privilege to assist you.\n\n"
        "To launch your own custom AI-powered store receptionist (like BotFather), please use the command /register."
    )
    await update.message.reply_text(welcome_text)

# --- Onboarding Flow Handlers ---
async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to the Nexa AI Merchant Onboarding Suite.\n\n"
        "Let us begin. What is the official name of your boutique or store?"
    )
    return STORE_NAME

async def receive_store_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["store_name"] = update.message.text
    await update.message.reply_text(
        f"Exquisite choice: *{update.message.text}*.\n\n"
        "Now, please provide your complete inventory list, stock details, and pricing so our AI can curate accurate customer responses for you:",
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
    inventory_data = context.user_data.get("inventory_data")

    # Save to Supabase stores table
    if supabase:
        try:
            res = supabase.table("stores").insert({
                "owner_telegram_id": owner_telegram_id,
                "store_name": store_name,
                "bot_token": bot_token,
                "inventory_data": inventory_data,
                "is_active": True
            }).execute()
            
            store_id = res.data[0]["id"]
            
            # Automatically set webhook for the merchant's new bot pointing to our dynamic dispatcher
            webhook_url = f"{RENDER_EXTERNAL_URL}/webhook/{store_id}"
            async with httpx.AsyncClient() as client:
                await client.get(f"https://api.telegram.org/bot{bot_token}/setWebhook?url={webhook_url}")

            success_message = (
                f"🎉 Congratulations! Your store *{store_name}* has been successfully registered on Nexa AI.\n\n"
                "Your automated AI receptionist is now fully configured with your inventory data and linked to your custom bot. "
                "You may now message your new store bot directly on Telegram!"
            )
        except Exception as e:
            success_message = f"We encountered an issue saving your store credentials. Please check if this bot token is valid/unique. (Error: {str(e)})"
    else:
        success_message = "Database connection is currently inactive. Please verify Supabase configuration."

    await update.message.reply_text(success_message, parse_mode="Markdown")
    return ConversationHandler.END

async def cancel_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Registration process has been cancelled. You can restart anytime using /register.")
    return ConversationHandler.END

# General message handler for Master Bot (/start and general queries)
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

# Set up Conversation Handler for Onboarding
onboarding_handler = ConversationHandler(
    entry_points=[CommandHandler("register", register_start)],
    states={
        STORE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_store_name)],
        INVENTORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_inventory)],
        BOT_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bot_token)],
    },
    fallbacks=[CommandHandler("cancel", cancel_registration)],
)

# Register Handlers on Master Bot
telegram_app.add_handler(onboarding_handler)
telegram_app.add_handler(CommandHandler("start", start_command))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_master_message))

@app.on_event("startup")
async def startup_event():
    await telegram_app.initialize()
    await telegram_app.start()

@app.on_event("shutdown")
async def shutdown_event():
    await telegram_app.stop()

@app.get("/")
def home():
    return {"status": "Nexa AI SaaS Multi-Tenant Platform is fully operational."}

# Master Bot Webhook Endpoint
@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}

# --- DYNAMIC MULTI-TENANT STORE BOT DISPATCHER ---
@app.post("/webhook/{store_id}")
async def dynamic_store_webhook(store_id: str, request: Request):
    data = await request.json()
    
    if not supabase:
        return {"ok": False, "error": "Database offline"}

    # 1. Fetch store details from Supabase using store_id
    store_res = supabase.table("stores").select("*").eq("id", store_id).execute()
    if not store_res.data:
        return {"ok": False, "error": "Store not found"}
    
    store = store_res.data[0]
    bot_token = store["bot_token"]
    store_name = store["store_name"]
    inventory_data = store["inventory_data"]

    # 2. Extract customer message from incoming Telegram update
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_text = message.get("text")

    if not chat_id or not user_text:
        return {"ok": True}

    # 3. Generate customized AI response using Groq with the merchant's exact inventory
    response_text = f"Welcome to {store_name}. How may we assist you today?"
    if groq_client:
        try:
            completion = groq_client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"You are the elite, world-class AI customer service receptionist for {store_name}. "
                            f"Here is your exact store inventory and stock data provided by the owner: {inventory_data}. "
                            "Answer customer inquiries strictly and accurately based on this inventory data with impeccable executive polish, politeness, and speed."
                        ),
                    },
                    {"role": "user", "content": user_text},
                ],
                model="openai/gpt-oss-120b",
            )
            response_text = completion.choices[0].message.content
        except Exception as e:
            response_text = f"We appreciate your patience while we process your request. (Notice: {str(e)})"

    # 4. Reply back to the customer using the merchant's unique bot token via Telegram API
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": response_text}
        )

    # 5. Log chat to database
    try:
        supabase.table("chats").insert({
            "user_id": str(chat_id),
            "user_message": user_text,
            "bot_response": response_text
        }).execute()
    except Exception:
        pass

    return {"ok": True}
