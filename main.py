import os
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
            supabase.table("stores").insert({
                "owner_telegram_id": owner_telegram_id,
                "store_name": store_name,
                "bot_token": bot_token,
                "inventory_data": inventory_data,
                "is_active": True
            }).execute()
            
            success_message = (
                f"🎉 Congratulations! Your store *{store_name}* has been successfully registered on Nexa AI.\n\n"
                "Your automated AI receptionist is now fully configured with your inventory data and linked to your bot token. "
                "You may now message your new store bot directly to experience its elite customer service!"
            )
        except Exception as e:
            success_message = f"We encountered an issue saving your store credentials. Please check if this bot token is already registered. (Error: {str(e)})"
    else:
        success_message = "Database connection is currently inactive. Please verify Supabase configuration."

    await update.message.reply_text(success_message, parse_mode="Markdown")
    return ConversationHandler.END

async def cancel_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Registration process has been cancelled. You can restart anytime using /register.")
    return ConversationHandler.END

# General message fallback handler for regular bot queries
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
        
    user_text = update.message.text
    user_id = str(update.message.from_user.id)
    response_text = "Thank you for your valued inquiry. Our executive team is attending to your request with utmost priority."
    
    if groq_client:
        try:
            chat_completion = groq_client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Nexa AI, an elite, world-class executive receptionist for a prestigious global multi-billion dollar corporate enterprise. "
                            "Your responses must be exceptionally fast, impeccably polite, articulate, reassuring, and delivered with top-tier executive refinement."
                        ),
                    },
                    {"role": "user", "content": user_text},
                ],
                model="openai/gpt-oss-120b",
            )
            response_text = chat_completion.choices[0].message.content
        except Exception as e:
            response_text = f"We appreciate your esteemed patience. (Notice: {str(e)})"

    # Save interaction to Supabase database if available
    if supabase:
        try:
            supabase.table("chats").insert({
                "user_id": user_id,
                "user_message": user_text,
                "bot_response": response_text
            }).execute()
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

# Register Handlers
telegram_app.add_handler(onboarding_handler)
telegram_app.add_handler(CommandHandler("start", start_command))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

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

@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}
