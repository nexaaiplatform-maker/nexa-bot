import os
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai
from supabase import create_client, Client

# Initialize FastAPI
app = FastAPI()

# Load Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize Supabase & Gemini
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Initialize Telegram Bot Application
telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).read_timeout(7).write_timeout(7).build()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome to Nexa AI Receptionist. How may I assist you with your professional inquiries today?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user_text = update.message.text
    response_text = "Thank you for reaching out. A representative will attend to your inquiry shortly."
    
    if gemini_client:
        try:
            response = gemini_client.models.generate_content(
                model="gemini-3.8-flash",
                contents=(
                    "You are a professional, polite, and formal executive receptionist for Nexa AI. "
                    f"Respond to the client's inquiry with professional business etiquette: {user_text}"
                )
            )
            response_text = response.text
        except Exception as e:
            response_text = f"System Notice: We are currently processing your request. Error details: {str(e)}"

    await update.message.reply_text(response_text)

# Register Handlers
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
    return {"status": "Nexa AI Bot is running live!"}

@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}
