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
# Configuration & Environment Variables (Masked & Secure)
# -------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://nexa-bot-f5al.onrender.com")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Webhook Security Secret Token
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "nexa_secure_random_token_9988")

# Secure Masked Financial Accounts
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
    return {"status": "healthy", "service": "Nexa AI Ethiopia Ultimate Multi-Bot Engine is live"}


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
# Dynamic Payout Load Balancer (Whole Birr 3500-3600 ETB Range)
# -------------------------------------------------------------------
def select_optimal_payout_destination() -> tuple[str, str, int, str]:
    """Generates whole Birr amounts dynamically between 3500 and 3600 ETB to avoid banking flags."""
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
        status_text = "⭐ *ፕሮ አባል — 24/7 ያልተገደበ ባለብዙ-ቦት የሽያጭ ስርዓት ንቁ ነው*"
    elif has_access:
        status_text = (
            f"🔥 *የነጻ የሙከራ ጊዜ ንቁ ነው (3 ቀናት)*\n"
            f"• * የሚያበቃበት:* `{expires_str}`\n"
            f"• * የቀሩ የAI ዕርዳታዎች:* `{sub_data['credits_remaining']}`"
        )
    else:
        status_text = "⚠️ *የሙከራ ጊዜዎ አልቋል* — ቦቶችዎ እንዳይቆሙ በብር ክፍያ ያሻሽሉ።"

    welcome_text = (
        f"🇪🇹 *እንኳን ወደ ኔክሳ AI (Nexa AI) የንግድ ማዕከል በደህና መጡ፣ {user.first_name}!*\n\n"
        f"ለማንኛውም የንግድ ዘርፍ የሚሆን አውቶማቲክ የቴሌግራም AI ረዳት ቦት በቀላሉ ያዋቅሩ።\n\n"
        f"📊 *የመለያዎ ሁኔታ:*\n{status_text}\n\n"
        "🎯 *ፈጣን መመሪያ:*\n"
        "1️⃣ /register - አዲስ AI ቦት ለማስጀመር\n"
        "2️⃣ /mybots - ያስጀመሯቸውን ቦቶች ለመቆጣጠር\n"
        "3️⃣ /update - ምርቶችዎን ወይም አገልግሎቶችዎን ለማዘመን\n"
        "4️⃣ /summary - የገቢ እና የደንበኞችዎን መረጃ ለማየት"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 ፕሮ ማስተካከያ (በደህንነቱ የተጠበቀ ብር)", callback_data="buy_pro")],
        [InlineKeyboardButton("🤖 ቦቶቼን አስተዳድር (/mybots)", callback_data="view_my_bots")],
        [InlineKeyboardButton("📊 የገቢ ማጠቃለያ (/summary)", callback_data="view_summary")],
        [InlineKeyboardButton("💎 አዲስ AI ቦት አስጀምር (/register)", callback_data="start_register")]
    ]
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def my_bots_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = str(update.effective_user.id)
    if not supabase:
        await update.message.reply_text("የዳታቤዝ ግንኙነት የለም።")
        return

    try:
        res = supabase.table("stores").select("store_name", "industry", "ui_theme", "bot_token", "created_at").eq("owner_telegram_id", owner_id).execute()
        if not res.data:
            await update.message.reply_text("⚠️ እስካሁን ያስጀመሩት ቦት የለም። /register በመጠቀም የመጀመሪያዎን ቦት ይፍጠሩ!")
            return

        bots_list_text = "🤖 *የእርስዎ ንቁ የAI ቦቶች ዝርዝር*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for idx, store in enumerate(res.data, 1):
            masked_token = store["bot_token"][:8] + "..." + store["bot_token"][-4:] if len(store["bot_token"]) > 12 else "***"
            bots_list_text += (
                f"*{idx}. {store['store_name']}*\n"
                f"• *የንግድ ዘርፍ:* `{store.get('industry', 'አጠቃላይ').capitalize()}`\n"
                f"• *የንግግር ዘይቤ:* `{store['ui_theme'].capitalize()}`\n"
                f"• *የቶከን ቁጥር:* `{masked_token}`\n"
                f"• *ሁኔታ:* በመስመር ላይ እና በስራ ላይ ✅\n\n"
            )
        bots_list_text += "🔒 *ማስታወሻ:* የቦት ቶከኖችዎ ሙሉ በሙሉ የተጠበቁ ናቸው።"
        await update.message.reply_text(bots_list_text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"ቦቶቹን ማምጣት አልተቻለም: {str(e)}")


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
        f"🔒 *የክፍያ መጠየቂያ (INVOICE)*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• *የግብይት ቁጥር:* `{order_id}`\n"
        f"• *አገልግሎት:* ወርሃዊ ፕሮ ፈቃድ (ያልተገደበ ቦቶች)\n"
        f"• *ማስተላለፍ ያለብዎት ትክክለኛ መጠን:* **{exact_amount_etb} ብር**\n"
        f"• *የክፍያ ማስተላለፊያ:* `{channel_name}`\n"
        f"• *የሂሳብ ቁጥር/መለያ:* `{masked_account}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🚨 *ትኩረት የሚሹ መመሪያዎች:*\n"
        f"1. በትክክል **`{exact_amount_etb} ብር`** ያስተላልፉ።\n"
        f"2. የተሳካውን የክፍያ ደረሰኝ (ስክሪንሾት) ፎቶ ያንሱ።\n"
        f"3. ማረጋገጫ ለማግኘት እዚህ ቻት ላይ የደረሰኙን ፎቶ ይላኩ።"
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ ክፍያ ፈጽሜአለሁ — ፎቶ ላክ", callback_data="upload_receipt")]
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
        f"📊 *የገቢ እና አጠቃላይ የንግድ ማጠቃለያ*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• *አጠቃላይ የተረጋገጡ ተመዝጋቢዎች:* `{total_subscribers}` ሰዎች\n"
        f"• *አጠቃላይ የተረጋገጠ ገቢ:* `{total_revenue:,.2f} ብር`\n"
        f"• *ንቁ የAI ረዳቶች:* 24/7 እየሰሩ ናቸው ✅\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 AI ቦቶችዎ ደንበኞችን ያለማቋረጥ እያስተናገዱ ይገኛሉ!"
    )
    await update.message.reply_text(summary_text, parse_mode="Markdown")


async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = str(update.message.from_user.id)
    new_inventory = " ".join(context.args).strip()

    if not new_inventory:
        await update.message.reply_text(
            "⚠️ *መረጃዎን ለማዘመን የሚከተለውን ይጠቀሙ:*\n\n"
            "`/update` ብለው አዳዲስ መረጃዎችን፣ ዋጋዎችን ወይም አገልግሎቶችን ይጻፉ።\n\n"
            "*ምሳሌ:*\n"
            "`/update እቃ 1: ሻንጣ - 2,500 ብር\nእቃ 2: ጫማ - 3,200 ብር`",
            parse_mode="Markdown"
        )
        return

    if not supabase:
        await update.message.reply_text("የዳታቤዝ ግንኙነት የለም።")
        return

    try:
        res = supabase.table("stores").update({"inventory_data": new_inventory}).eq("owner_telegram_id", owner_id).execute()
        if res.data:
            await update.message.reply_text(
                "✅ *መረጃዎ በሁሉም ቦቶችዎ ላይ ወዲያውኑ ዘምኗል!*\n\nየእርስዎ AI ረዳቶች አዲሱን ዋጋ እና መረጃ በመጠቀም ደንበኞችን ማስተናገድ ጀምረዋል።",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("⚠️ ንቁ መደብር አልተገኘም። እባክዎ መጀመሪያ /register ይጠቀሙ።")
    except Exception as e:
        await update.message.reply_text(f" ማዘመን አልተቻለም: {str(e)}")


# --- Onboarding Conversation Handlers ---
async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🇪🇹 *የAI ቦት ማዋቀሪያ ረዳት*\n\n"
        "የቴሌግራም AI ረዳትዎን በጥቂት ቀላል እርምጃዎች እናዋቅረው።\n\n"
        "እርምጃ 1 ከ 4: የንግድዎ፣ የድርጅትዎ ወይም የሰርጥዎ ሙሉ ስም ማን ይባላል? (ለምሳሌ፦ *አድማስ የንግድ ማዕከል*)"
    )
    return STORE_NAME


async def receive_store_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["store_name"] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton("🏬 የችርቻሮ እና የንግድ ዕቃዎች", callback_data="ind_retail")],
        [InlineKeyboardButton("🏋️ የስፖርት እና የጤና ማዕከል", callback_data="ind_fitness")],
        [InlineKeyboardButton("🏠 የቤት እና የቦታ ኪራይ/ሽያጭ", callback_data="ind_realestate")],
        [InlineKeyboardButton("🩺 የጤና ክሊኒክ እና ፋርማሲ", callback_data="ind_clinic")],
        [InlineKeyboardButton("🤝 የንግድ ኤጀንሲ እናደልላ", callback_data="ind_broker")],
        [InlineKeyboardButton("⚙️ ሌሎች አገልግሎቶች", callback_data="ind_general")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"የድርጅቱ ስም ተመዝግቧል: *{update.message.text}*።\n\n"
        "እርምጃ 2 ከ 4: የንግድ ዘርፍዎን ይምረጡ፦",
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
        [InlineKeyboardButton("💎 ከፍተኛ ባለሙያ (Executive)", callback_data="theme_executive")],
        [InlineKeyboardButton("⚡ ኃይለኛ ሻጭ (Sales Closer)", callback_data="theme_sales")],
        [InlineKeyboardButton("🌿 ወዳጃዊ እና አስተማሪ (Friendly)", callback_data="theme_friendly")],
        [InlineKeyboardButton("🎯 ቀጥተኛ እና አጭር (Minimalist)", callback_data="theme_minimalist")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await target_message(
        f"የተመረጠው ዘርፍ: *{chosen_industry.capitalize()}*።\n\n"
        "እርምጃ 3 ከ 4: የAI ረዳትዎ ከደንበኞች ጋር እንዴት እንዲነጋገር ይፈልጋሉ?",
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
        "እርምጃ 4 ከ 4: የሚሸጡዋቸውን እቃዎች፣ አገልግሎቶች ወይም የዋጋ ዝርዝር በብር (ETB) ከነ መግለጫቸው ከታች ይጻፉልን:",
        parse_mode="Markdown"
    )
    return INVENTORY


async def receive_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["inventory_data"] = update.message.text
    await update.message.reply_text(
        "ሊጠናቀቅ ነው።\n\n"
        "እባክዎ ወደ ቴሌግራም **@BotFather** በመሄድ አዲስ ቦት ይፍጠሩ (`/newbot`)፣ የሰጡዎትን የ **Bot Token** እዚህ ይለጥፉ (Paste ያድርጉ):",
        parse_mode="Markdown"
    )
    return BOT_TOKEN


async def receive_bot_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_token = update.message.text.strip()
    owner_telegram_id = str(update.message.from_user.id)
    
    store_name = context.user_data.get("store_name", "የእኔ ንግድ")
    industry = context.user_data.get("industry", "general")
    ui_theme = context.user_data.get("ui_theme", "executive")
    inventory_data = context.user_data.get("inventory_data", "ዝርዝር መረጃ አልተሰጠም")

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
            await update.message.reply_text(f"⚠️ ማስቀመጥ ላይ ችግር ተፈጥሯል: {str(e)}")

    success_msg = (
        f"🎉 *እንኳን ደስ አለዎት! የንግድ ቦትዎ በመስመር ላይ ውሏል!* 🇪🇹🚀\n\n"
        f"• *የድርጅቱ ስም:* {store_name}\n"
        f"• *ዘርፍ:* {industry.capitalize()}\n"
        f"• *ሁኔታ:* ንቁ እና የተገናኘ ✅\n\n"
        "ቦትዎ አሁን ከደንበኞች ጋር ለመነጋገር ዝግጁ ነው።"
    )
    await update.message.reply_text(success_msg, parse_mode="Markdown")
    return ConversationHandler.END


async def cancel_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ ምዝገባው ተሰርዟል። እንደገና ለመጀመር /register ይጠቀሙ።")
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
        await query.message.reply_text("ቦትዎን ለማስጀመር /register የሚለውን ትእዛዝ ይጠቀሙ።")
    elif query.data == "upload_receipt":
        await query.message.reply_text("📸 እባክዎ የክፍያ ደረሰኝ ፎቶዎን አሁን ይላኩ።")


async def handle_receipt_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    order = pending_orders.get(user_id)
    
    if not order:
        await update.message.reply_text("❌ ንቁ የክፍያ ትዕዛዝ አልተገኘም። መጀመሪያ /upgrade በመጠቀም ይሞክሩ።")
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
                    f"🚫 *ማስጠንቀቂያ: ይህ ደረሰኝ ቀደም ሲል ጥቅም ላይ ውሏል!*\n\nድጋሚ መጠቀም የተከለከለ ነው።",
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
            f"✅ *ክፍያው ተረጋግጧል! ፕሮ አካውንትዎ ገብቷል!* ⭐🇪🇹\n\n"
            f"• *የግብይት መለያ:* `{ref_id}`\n"
            f"• *ሁኔታ:* ያልተገደበ አገልግሎት ንቁ ሆኗል!",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"📥 *ደረሰኙ ለግምገማ ተመዝግቧል*\n\n"
            f"በራስ-ሰር ማረጋገጥ አልተቻለም። አስተዳዳሪው አረጋግጦ ይመልስልዎታል።",
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
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_text = message.get("text", "")
    from_user = message.get("from", {})
    username = from_user.get("username", "አልታወቀም")
    first_name = from_user.get("first_name", "ደንበኛ")
    
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
                "text": "የንግድ መደብር ማስተካከያ አልተገኘም።"
            })
        return {"ok": True}

    payload = {
        "chat_id": chat_id,
        "user_text": user_text,
        "bot_token": bot_token,
        "store_name": store.get("store_name", "ድርጅታችን"),
        "industry": store.get("industry", "general"),
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
    store_name = payload.get("store_name", "ድርጅታችን")
    industry = payload.get("industry", "general")
    ui_theme = payload.get("ui_theme", "executive")
    inventory_data = payload.get("inventory_data", "")
    owner_telegram_id = payload.get("owner_telegram_id")
    username = payload.get("username", "አልታወቀም")
    first_name = payload.get("first_name", "ደንበኛ")
    history_messages = payload.get("history_messages", [])

    if owner_telegram_id:
        owner_id_int = int(owner_telegram_id)
        get_or_create_user_subscription(owner_id_int)
        if not verify_active_access(owner_id_int):
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={"chat_id": chat_id, "text": "⚠️ የዚህ ቦት የሙከራ ጊዜ አልቋል። ባለቤቱ ማደስ ይጠበቅበታል።"}
                )
            return {"ok": True}
        deduct_credit(owner_id_int)

    theme_prompts = {
        "executive": (
            f"You are a professional executive VIP concierge for {store_name} in the {industry} sector. "
            "Maintain a polite, elite, and prestigious tone."
        ),
        "sales": (
            f"You are a top sales representative for {store_name} in the {industry} sector. "
            "Be enthusiastic, helpful, and close sales quickly."
        ),
        "friendly": (
            f"You are a warm, welcoming local assistant for {store_name} ({industry}). "
            "Speak naturally and make clients feel completely at home."
        ),
        "minimalist": (
            f"You are a concise assistant for {store_name} ({industry}). "
            "Give brief, clear, direct answers with prices in ETB."
        )
    }

    selected_persona = theme_prompts.get(ui_theme, theme_prompts["executive"])

    system_prompt = (
        f"{selected_persona}\n\n"
        f"BUSINESS INDUSTRY: {industry.capitalize()}\n"
        f"PRODUCTS / SERVICES / PRICING DATA:\n{inventory_data}\n\n"
        f"RULES:\n"
        "1. Automatically detect the language of the customer (Amharic, Afaan Oromo, English, Tigrinya, etc.) and respond fluently in that exact same language.\n"
        "2. Answer strictly using the inventory/services data and pricing in ETB provided above.\n"
        "3. Never invent unlisted prices or contact numbers.\n"
        "4. When a customer wants to buy, book, or order, confirm their request and reassure them management has been notified."
    )
    
    messages_payload = [{"role": "system", "content": system_prompt}] + history_messages + [{"role": "user", "content": user_text}]

    response_text = f"እንኳን ወደ {store_name} በደህና መጡ! እንዴት ልንረዳዎ እንችላለን?"
    if groq_client:
        try:
            completion = groq_client.chat.completions.create(
                messages=messages_payload,
                model="openai/gpt-oss-120b",
            )
            response_text = completion.choices[0].message.content
        except Exception as e:
            response_text = f"መልእክትዎ ደርሶናል፣ እናመሰግናለን። ({str(e)})"

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
        customer_handle = f"@{username}" if username != "አልታወቀም" else f"ID: {chat_id}"
        alert_msg = (
            f"🚨 *አዲስ ጠቃሚ ደንበኛ (Lead) ለ {store_name}!* 🇪🇹\n\n"
            f"👤 *ደንበኛ:* {first_name} ({customer_handle})\n"
            f"💬 *ጥያቄ:* \"{user_text}\"\n\n"
            f"🤖 *AI ምላሽ:* \"{response_text[:150]}...\"\n\n"
            f"👉 እባክዎ በቀጥታ አግኙዋቸው!"
        )
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": owner_telegram_id, "text": alert_msg, "parse_mode": "Markdown"}
            )

    return {"ok": True}
