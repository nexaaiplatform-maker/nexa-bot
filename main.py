import os
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
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

# Initialize Telegram Bot Application
telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).read_timeout(7).write_timeout(7).build()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "Welcome to Nexa AI. It is an absolute privilege to assist you. "
        "How may we curate your experience with excellence today?"
    )
    await update.message.reply_text(welcome_text)

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
                model="openai/gpt-oss-120b",  # Updated to valid Groq model
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
    return {"status": "Nexa AI Enterprise Core is fully operational."}

@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}
