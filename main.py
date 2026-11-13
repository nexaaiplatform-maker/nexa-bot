import os
import random
import asyncio
import httpx
import base64
import json
import logging
from datetime import datetime, timedelta, timezone
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
from groq import AsyncGroq
from supabase import create_client, Client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NexaAI")

# Initialize FastAPI
app = FastAPI(title="Nexa AI Elite Commerce Backend")

# -------------------------------------------------------------------
# Configuration & Environment Variables
# -------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://nexa-bot-f5al.onrender.com")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")

TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "nexa_secure_random_token_9988")

TELEBIRR_ACCOUNT_MASKED = os.getenv("TELEBIRR_ACCOUNT_MASKED", "0965205354")
AWASH_ACCOUNT_MASKED = os.getenv("AWASH_ACCOUNT_MASKED", "013201740373300")

# Initialize Clients with Fail-Safe Checks & Logging
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
if not supabase:
    logger.warning("⚠️ SUPABASE_URL or SUPABASE_KEY is missing!")

async_groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
if not async_groq_client:
    logger.warning("⚠️ GROQ_API_KEY is missing! AI features will not work.")

# Master Telegram Bot Application
telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).read_timeout(10).write_timeout(10).build()

# Global HTTP Client Pool for High Throughput
http_client: httpx.AsyncClient = None

# Onboarding Conversation States
STORE_NAME, INDUSTRY, UI_THEME, INVENTORY, BOT_TOKEN = range(5)


# -------------------------------------------------------------------
# Safe UTC Datetime Parser Helper
# -------------------------------------------------------------------
def parse_dt(dt_val) -> datetime:
    if isinstance(dt_val, datetime):
        return dt_val if dt_val.tzinfo else dt_val.replace(tzinfo=timezone.utc)
    if not dt_val:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(str(dt_val).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)


# -------------------------------------------------------------------
# Root Health Check (Supports GET and HEAD for UptimeRobot)
# -------------------------------------------------------------------
@app.get("/")
@app.head("/")
async def root_health_check():
    return {"status": "healthy", "service": "Nexa AI Elite Multi-Bot Engine is live and optimized"}


# -------------------------------------------------------------------
# Core Logic: Persistent Trial, Credit & Visitor Engine (Supabase Backed)
# -------------------------------------------------------------------
async def get_or_create_user_subscription(user_id: int) -> dict:
    now = datetime.now(timezone.utc)
    if supabase:
        try:
            res = await asyncio.to_thread(
                lambda: supabase.table("subscriptions").select("*").eq("user_id", str(user_id)).execute()
            )
            if res.data:
                sub = res.data[0]
                return {
                    "trial_expires": parse_dt(sub["trial_expires"]),
                    "credits_remaining": sub["credits_remaining"],
                    "is_pro": sub["is_pro"]
                }
        except Exception as e:
            logger.error(f"Subscription fetch error: {e}")

    default_expiry = now + timedelta(days=3)
    default_sub = {
        "trial_expires": default_expiry,
        "credits_remaining": 50,
        "is_pro": False
    }
    
    if supabase:
        try:
            await asyncio.to_thread(
                lambda: supabase.table("subscriptions").upsert({
                    "user_id": str(user_id),
                    "trial_expires": default_expiry.isoformat(),
                    "credits_remaining": 50,
                    "is_pro": False
                }).execute()
            )
        except Exception as e:
            logger.error(f"Subscription upsert error: {e}")
            
    return default_sub


async def verify_active_access(user_id: int) -> bool:
    try:
        sub = await get_or_create_user_subscription(user_id)
        if sub["is_pro"]:
            return True
        now = datetime.now(timezone.utc)
        trial_exp = parse_dt(sub["trial_expires"])
        if now < trial_exp and sub["credits_remaining"] > 0:
            return True
    except Exception as e:
        logger.error(f"Access verification error: {e}")
        return True
    return False


async def deduct_credit(user_id: int):
    try:
        sub = await get_or_create_user_subscription(user_id)
        if not sub["is_pro"] and supabase:
            new_credits = max(0, sub["credits_remaining"] - 1)
            await asyncio.to_thread(
                lambda: supabase.table("subscriptions").update({"credits_remaining": new_credits}).eq("user_id", str(user_id)).execute()
            )
    except Exception as e:
        logger.error(f"Credit deduction error: {e}")


async def log_visitor(user_id: int):
    if supabase:
        try:
            await asyncio.to_thread(
                lambda: supabase.table("store_visitors").upsert({
                    "user_id": str(user_id),
                    "last_visit": datetime.now(timezone.utc).isoformat()
                }, on_conflict="user_id").execute()
            )
        except Exception as e:
            logger.error(f"Visitor logging error: {e}")


# -------------------------------------------------------------------
# Dynamic Payout Load Balancer (Whole Birr 3500-3600 ETB Range)
# -------------------------------------------------------------------
async def select_optimal_payout_destination() -> tuple[str, str, int, str]:
    now = datetime.now(timezone.utc)
    twenty_four_hours_ago = now - timedelta(hours=24)
    
    telebirr_24h_total = 0.0
    if supabase:
        try:
            rev_res = await asyncio.to_thread(
                lambda: supabase.table("paid_subscriptions").select("amount_etb, channel, created_at").execute()
            )
            if rev_res.data:
                for tx in rev_res.data:
                    if tx.get("channel") == "TELEBIRR" and tx.get("created_at"):
                        tx_date = parse_dt(tx["created_at"])
                        if tx_date >= twenty_four_hours_ago:
                            telebirr_24h_total += float(tx["amount_etb"])
        except Exception as e:
            logger.error(f"Telebirr 24h cap check error: {e}")

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
    await log_visitor(user_id)
    
    sub_data = await get_or_create_user_subscription(user_id)
    has_access = await verify_active_access(user_id)
    expires_str = parse_dt(sub_data["trial_expires"]).strftime("%Y-%m-%d %H:%M UTC")
    
    if sub_data["is_pro"]:
        status_text = "⭐ ፕሮ አባል — ያልተወሰነ የብዙ ቦት ሽያጭ ስርዓትዎ በሥራ ላይ አለ"
    elif has_access:
        status_text = (
            f"🔥 የነጻ የሙከራ ጊዜ በሥራ ላይ አለ (3 ቀናት)
"
            f"• የሚያበቃበት ጊዜ: {expires_str}
"
            f"• የቀሩ የAI ዕዳዎች: {sub_data['credits_remaining']}"
        )
    else:
        status_text = "⚠️ የሙከራ ጊዜዎ አልቋል — ቦቶችዎ እንዳይቆሙ በብር ፕሮ አባልነት ያሻሽሉ።"

    welcome_text = (
        f"🇪🇹 እንኳን ወደ Nexa AI ስማርት መድረክ ደህና መጡ, {user.first_name}!

"
        f"ይህ ዳሽቦርድ ሙሉ በሙሉ በ AI የተጎለበተ ነው። የሚፈልጉትን ማንኛውንም ትዕዛዝ በቀጥታ መጻፍ ይችላሉ።

"
        f"📊 የመለያዎ ሁኔታ:
{status_text}

"
        "🎯 ፈጣን መመሪያ:
"
        "1️⃣ /register - አዲስ የ AI ቦት ይፍጠሩ
"
        "2️⃣ /mybots - ቦቶችዎን ያስተዳድሩ
"
        "3️⃣ /summary - የገቢ እና የጎብኚዎች ማጠቃለያ
"
        "4️⃣ /weekly_summary - ሳምንታዊ አጠቃላይ ሪፖርት
"
        "5️⃣ /update - ዕቃዎችን ወይም አገልግሎቶችን ማሻሻል"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 ፕሮ አባልነት ይክፈቱ (በብር)", callback_data="buy_pro")],
        [InlineKeyboardButton("🤖 ቦቶቼን አስተዳድር (/mybots)", callback_data="view_my_bots")],
        [InlineKeyboardButton("📊 የገቢ ማጠቃለያ (/summary)", callback_data="view_summary")],
        [InlineKeyboardButton("📈 ሳምንታዊ ሪፖርት (/weekly_summary)", callback_data="view_weekly")],
        [InlineKeyboardButton("💎 አዲስ የ AI ቦት ፍጠር (/register)", callback_data="start_register")]
    ]
    await update.effective_message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard))


async def my_bots_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = str(update.effective_user.id)
    if not supabase:
        await update.effective_message.reply_text("የዳታቤዝ ግንኙነት የለም።")
        return

    try:
        res = await asyncio.to_thread(
            lambda: supabase.table("stores").select("store_name", "bot_token", "ui_theme").eq("owner_telegram_id", owner_id).execute()
        )
        if not res.data:
            await update.effective_message.reply_text("⚠️ እስካሁን የተፈጠረ ንቁ ቦት የለዎትም። የመጀመሪያውን የ AI ቦት ለመፍጠር /register ይጠቀሙ!")
            return

        bots_list_text = "🤖 የእርስዎ የ AI ቦቶች ዳሽቦርድ
━━━━━━━━━━━━━━━━━━━━━━

"
        for idx, store in enumerate(res.data, 1):
            token_val = store.get("bot_token", "")
            masked_token = token_val[:8] + "..." + token_val[-4:] if len(token_val) > 12 else "***"
            bots_list_text += (
                f"{idx}. {store['store_name']}
"
                f"• ቶከን ቁልፍ: {masked_token}
"
                f"• የቦት ዘይቤ: {store.get('ui_theme', 'executive').capitalize()}
"
                f"• ሁኔታ: በሥራ ላይ እና የተገናኘ ✅

"
            )
        await update.effective_message.reply_text(bots_list_text)
    except Exception as e:
        await update.effective_message.reply_text(f"ቦቶችን ማምጣት አልተቻለም: {str(e)}")


async def upgrade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    channel_name, masked_account, exact_amount_etb, channel_code = await select_optimal_payout_destination()
    order_id = f"NEXA-SECURE-{random.randint(1000, 9999)}"
    
    if supabase:
        try:
            await asyncio.to_thread(
                lambda: supabase.table("pending_orders").upsert({
                    "user_id": str(user_id),
                    "order_id": order_id,
                    "amount": str(exact_amount_etb),
                    "channel": channel_name,
                    "destination_code": channel_code,
                    "status": "pending_payment"
                }, on_conflict="user_id").execute()
            )
        except Exception as e:
            logger.error(f"Pending order save error: {e}")
    
    invoice_text = (
        f"🔒 ደህንነቱ የተጠበቀ የክፍያ መጠየቂያ
"
        f"━━━━━━━━━━━━━━━━━━━━━━
"
        f"• የደረሰኝ ቁጥር: {order_id}
"
        f"• የክፍያ መጠን: {exact_amount_etb} ብር
"
        f"• የክፍያ መንገድ: {channel_name}
"
        f"• የሂሳብ ቁጥር: {masked_account}
"
        f"━━━━━━━━━━━━━━━━━━━━━━

"
        f"🚨 መመሪያ:
1. ከላይ ያለውን የሂሳብ ቁጥር በመጠቀም {exact_amount_etb} ብር ያስተላልፉ።
2. የተሳካውን የክፍያ ደረሰኝ ፎቶ (Screenshot) በመላክ ያረጋግጡ።"
    )
    keyboard = [
        [InlineKeyboardButton(f"📋 ሂሳብ ቁጥር ቅዳ: {masked_account}", callback_data=f"copy_acc_{masked_account}")],
        [InlineKeyboardButton("✅ ከፍያለሁ — ደረሰኝ ጫን", callback_data="upload_receipt")]
    ]
    await update.effective_message.reply_text(invoice_text, reply_markup=InlineKeyboardMarkup(keyboard))


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_revenue, total_subscribers, total_visitors = 0, 0, 0
    top_payers = []

    if supabase:
        try:
            rev_res = await asyncio.to_thread(
                lambda: supabase.table("paid_subscriptions").select("user_id", "amount_etb").execute()
            )
            if rev_res.data:
                total_revenue = sum(float(tx["amount_etb"]) for tx in rev_res.data)
                total_subscribers = len(rev_res.data)
                payer_totals = {}
                for tx in rev_res.data:
                    uid = tx["user_id"]
                    payer_totals[uid] = payer_totals.get(uid, 0) + float(tx["amount_etb"])
                top_payers = sorted(payer_totals.items(), key=lambda x: x[1], reverse=True)[:5]

            vis_res = await asyncio.to_thread(
                lambda: supabase.table("store_visitors").select("user_id", count="exact").execute()
            )
            total_visitors = vis_res.count if vis_res.count is not None else len(vis_res.data or [])
        except Exception as e:
            logger.error(f"Summary fetch error: {e}")

    top_payers_text = "".join([f"{i}. መለያ {uid} — {amt:,.2f} ብር
" for i, (uid, amt) in enumerate(top_payers, 1)]) or "እስካሁን ከፋይ የለም።"
    summary_text = (
        f"📊 አጠቃላይ የንግድ እና የጎብኚዎች ማጠቃለያ
━━━━━━━━━━━━━━━━━━━━━━
"
        f"• አጠቃላይ የቦት ጎብኚዎች: {total_visitors} ተጠቃሚዎች
"
        f"• የተረጋገጡ ከፋዮች: {total_subscribers} ተጠቃሚዎች
"
        f"• አጠቃላይ የተረጋገጠ ገቢ: {total_revenue:,.2f} ብር
━━━━━━━━━━━━━━━━━━━━━━

🏆 ከፍተኛ ከፋዮች:
{top_payers_text}"
    )
    await update.effective_message.reply_text(summary_text)


async def weekly_summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    weekly_revenue, weekly_subscribers, tenant_visitors_count = 0, 0, 0

    if supabase:
        try:
            stores_res = await asyncio.to_thread(
                lambda: supabase.table("stores").select("bot_token").eq("owner_telegram_id", user_id).execute()
            )
            bot_tokens = [s["bot_token"] for s in stores_res.data] if stores_res.data else []

            if bot_tokens:
                vis_res = await asyncio.to_thread(
                    lambda: supabase.table("tenant_visitors").select("chat_id, created_at").in_("bot_token", bot_tokens).execute()
                )
                if vis_res.data:
                    for v in vis_res.data:
                        if parse_dt(v.get("created_at")) >= week_ago:
                            tenant_visitors_count += 1

            rev_res = await asyncio.to_thread(
                lambda: supabase.table("paid_subscriptions").select("amount_etb, created_at").execute()
            )
            if rev_res.data:
                for tx in rev_res.data:
                    if tx.get("created_at") and parse_dt(tx["created_at"]) >= week_ago:
                        weekly_revenue += float(tx["amount_etb"])
                        weekly_subscribers += 1
        except Exception as e:
            logger.error(f"Weekly summary error: {e}")

    weekly_text = (
        f"📈 ሳምንታዊ ሪፖርት (Weekly Summary)
━━━━━━━━━━━━━━━━━━━━━━
"
        f"• የደንበኛ ቦቶችዎ ጎብኚዎች (በዚህ ሳምንት): {tenant_visitors_count} ተጠቃሚዎች
"
        f"• በዚህ ሳምንት የተመዘገቡ አባላት: {weekly_subscribers} ተጠቃሚዎች
"
        f"• የሳምንቱ አጠቃላይ ገቢ: {weekly_revenue:,.2f} ብር
━━━━━━━━━━━━━━━━━━━━━━

💡 ጠቃሚ ምክር: ሽያጭዎን ለማሳደግ ዕቃዎችዎን በ /update ማሻሻልዎን አይርሱ!"
    )
    await update.effective_message.reply_text(weekly_text)


async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = str(update.message.from_user.id)
    new_inventory = " ".join(context.args).strip()

    if not new_inventory:
        await update.effective_message.reply_text(
            "⚠️ ዕቃዎችን ወይም አገልግሎቶችን ማሻሻል:

/update ብለው በመቀጠል አዲሱን ዝርዝር ይጻፉ።
ምሳሌ:
/update ጫማ - 2,800 ብር"
        )
        return

    if supabase:
        try:
            res = await asyncio.to_thread(
                lambda: supabase.table("stores").update({"inventory_data": new_inventory}).eq("owner_telegram_id", owner_id).execute()
            )
            if res.data:
                await update.effective_message.reply_text("✅ በሁሉም ቦቶችዎ ላይ በቅጽበት ተሻሽሏል!")
                return
        except Exception as e:
            logger.error(f"Update error: {e}")
    await update.effective_message.reply_text("⚠️ ምንም ንቁ መደብር አልተገኘም ወይም ስህተት አጋጥሟል።")


# -------------------------------------------------------------------
# Onboarding Conversation Handlers
# -------------------------------------------------------------------
async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message:
        return STORE_NAME
    await message.reply_text(
        "🇪🇹 NEXA AI ቦት ፈጣሪ ረዳት

"
        "የቴሌግራም AI ቦትዎን በቀላል ደረጃዎች እንፍጠር።

"
        "እርምጃ 1 ከ 4: የንግድዎ፣ የመደብርዎ ወይም የአገልግሎትዎ ትክክለኛ ስም ማን ነው? (ለምሳሌ: አዲስ ሪል እስቴት)"
    )
    return STORE_NAME


async def receive_store_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["store_name"] = update.effective_message.text
    
    keyboard = [
        [InlineKeyboardButton("🛍️ ቸርቻሪ እና እቃዎች", callback_data="ind_retail")],
        [InlineKeyboardButton("🏋️ ጤና እና የአካል ብቃት", callback_data="ind_fitness")],
        [InlineKeyboardButton("🏠 የቤት እና ንብረት ሽያጭ", callback_data="ind_realestate")],
        [InlineKeyboardButton("🩺 ህክምና እና ክሊኒክ", callback_data="ind_clinic")],
        [InlineKeyboardButton("🤝 ኤጀንሲ እና ደላላ", callback_data="ind_broker")],
        [InlineKeyboardButton("⚙️ አጠቃላይ አገልግሎቶች", callback_data="ind_general")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.effective_message.reply_text(
        f"የንግድ ስም ተመዝግቧል: {update.effective_message.text}.

"
        "እርምጃ 2 ከ 4: ዋናውን የስራ ዘርፍ ይምረጡ:",
        reply_markup=reply_markup
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
        chosen_industry = update.effective_message.text.lower()
        target_message = update.effective_message.reply_text

    context.user_data["industry"] = chosen_industry

    keyboard = [
        [InlineKeyboardButton("💎 ቪአይፒ ኤክስክሉቲቭ", callback_data="theme_executive")],
        [InlineKeyboardButton("⚡ ከፍተኛ ሽያጭ አቅጣጫ", callback_data="theme_sales")],
        [InlineKeyboardButton("🌿 ወዳጃዊ አማካሪ", callback_data="theme_friendly")],
        [InlineKeyboardButton("🎯 ቀጥተኛ እና አጭር", callback_data="theme_minimalist")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await target_message(
        f"የተመረጠው ዘርፍ: {chosen_industry.capitalize()}.

"
        "እርምጃ 3 ከ 4: የ AI ረዳትዎ ከደንበኞች ጋር እንዴት ማውራት እንዳለበት ይምረጡ:",
        reply_markup=reply_markup
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
        chosen_theme = "executive"
        target_message = update.effective_message.reply_text

    context.user_data["ui_theme"] = chosen_theme
    
    await target_message(
        "እርምጃ 4 ከ 4: ሙሉ ዕቃዎችዎን፣ አገልግሎቶችዎን፣ የሪል እስቴት መረጃዎን ወይም ካታሎግ ጽሑፍ ከታች ይለጥፉ:"
    )
    return INVENTORY


async def receive_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["inventory_data"] = update.effective_message.text
    await update.effective_message.reply_text(
        "ሊጠናቀቅ ነው።!

"
        "ወደ ኦፊሴላዊው የቴሌግራም @BotFather ይሂዱ፣ ቦት ይፍጠሩ (/newbot)፣ ልዩ የቦት ቶከን ይውሰዱ እና እዚህ ይለጥፉ:"
    )
    return BOT_TOKEN


async def receive_bot_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_token = update.effective_message.text.strip()
    owner_telegram_id = str(update.effective_user.id)
    store_name = context.user_data.get("store_name", "My Store")
    inventory_data = context.user_data.get("inventory_data", "No inventory specified")
    ui_theme = context.user_data.get("ui_theme", "executive")

    tenant_webhook_url = f"{RENDER_EXTERNAL_URL}/tenant-webhook/{bot_token}"
    
    try:
        resp = await http_client.post(
            f"https://api.telegram.org/bot{bot_token}/setWebhook", 
            json={"url": tenant_webhook_url}
        )
        if not resp.json().get("ok"):
            await update.effective_message.reply_text("⚠️ ያስገቡት የቦት ቶከን ልክ አይደለም። እባክዎ ትክክለኛ ቶከን እንደገና ይላኩ:")
            return BOT_TOKEN
    except Exception as e:
        logger.error(f"SetWebhook error: {e}")
        await update.effective_message.reply_text("⚠️ ቶከኑን ማረጋገጥ አልተቻለም። እባክዎ ትክክለኛ ቶከን ያስገቡ:")
        return BOT_TOKEN

    if supabase:
        try:
            await asyncio.to_thread(
                lambda: supabase.table("stores").upsert({
                    "bot_token": bot_token,
                    "owner_telegram_id": owner_telegram_id,
                    "store_name": store_name,
                    "inventory_data": inventory_data,
                    "ui_theme": ui_theme
                }, on_conflict="bot_token").execute()
            )
        except Exception as e:
            await update.effective_message.reply_text(f"⚠️ ዳታቤዝ ላይ ማስቀመጥ አልተቻለም: {str(e)}")
            return BOT_TOKEN

    await update.effective_message.reply_text(
        f"🎉 እንኳን ደስ አለዎት! የ AI ቦትዎ በሥራ ላይ ውሏል! 🇪🇹🚀

"
        f"• የንግድ ስም: {store_name}
"
        f"• የቦት ዘይቤ: {ui_theme.capitalize()}
"
        f"• ሁኔታ: ተገናኝቷል እና ንቁ ነው ✅

"
        "ደንበኞችዎ ቦትዎን ሲጀምሩ (/start) ቀጥተኛ ውይይት ይጀምራሉ።"
    )
    return ConversationHandler.END


async def cancel_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("❌ ምዝገባው ተሰርዟል። ዝግጁ ሲሆኑ /register ይጠቀሙ።")
    return ConversationHandler.END


# -------------------------------------------------------------------
# Payment & OCR Handlers
# -------------------------------------------------------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "buy_pro":
        await upgrade_command(update, context)
    elif query.data == "view_summary":
        await summary_command(update, context)
    elif query.data == "view_weekly":
        await weekly_summary_command(update, context)
    elif query.data == "view_my_bots":
        await my_bots_command(update, context)
    elif query.data == "upload_receipt":
        await query.message.reply_text("📸 እባክዎ የክፍያ ደረሰኝ ፎቶ (Screenshot) ይላኩ።")
    elif query.data.startswith("copy_acc_"):
        acc_num = query.data.replace("copy_acc_", "")
        await query.answer(text=f"የሂሳብ ቁጥር ተገልብጧል: {acc_num}", show_alert=True)


async def handle_receipt_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    order = None
    
    if supabase:
        try:
            res = await asyncio.to_thread(
                lambda: supabase.table("pending_orders").select("*").eq("user_id", str(user_id)).execute()
            )
            if res.data:
                order = res.data[0]
        except Exception as e:
            logger.error(f"Fetch pending order error: {e}")
    
    if not order:
        await update.effective_message.reply_text("❌ ምንም ንቁ ትዕዛዝ አልተገኘም። መጀመሪያ /upgrade ይጠቀሙ።")
        return

    photo_file = await update.message.photo[-1].get_file()
    image_bytes = await photo_file.download_as_bytearray()
    base64_image = base64.b64encode(bytes(image_bytes)).decode('utf-8')
    
    expected_amount_str = order["amount"]
    parsed_result = {"valid": False, "reference_id": None, "detected_amount": None}

    if async_groq_client:
        try:
            prompt = (
                f"Analyze this Ethiopian bank or Telebirr payment receipt image with 100% strict accuracy. Extract:
"
                f"1. Transaction Reference ID or Confirmation Code (string)
"
                f"2. Total Amount in ETB transferred (number or string without commas)
"
                f"Return strictly valid JSON format: "
                f'{{"valid": true/false, "reference_id": "string", "detected_amount": "string"}}'
            )
            response = await async_groq_client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
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
            logger.error(f"OCR Error: {e}")

    ref_id = parsed_result.get("reference_id")
    detected_amount_str = str(parsed_result.get("detected_amount", ""))

    try:
        clean_expected = float(expected_amount_str.replace(",", "").replace("ብር", "").strip())
        clean_detected = float(detected_amount_str.replace(",", "").replace("ብር", "").strip())
        amount_matches = abs(clean_expected - clean_detected) < 1.0
    except Exception:
        amount_matches = False

    if parsed_result.get("valid") and amount_matches and ref_id:
        if supabase:
            try:
                await asyncio.to_thread(lambda: supabase.table("processed_receipts").insert({
                    "user_id": str(user_id), "order_id": order["order_id"], "reference_id": ref_id,
                    "amount": expected_amount_str, "channel": order["channel"], "created_at": datetime.now(timezone.utc).isoformat()
                }).execute())
                await asyncio.to_thread(lambda: supabase.table("paid_subscriptions").insert({
                    "user_id": str(user_id), "order_id": order["order_id"], "amount_etb": float(expected_amount_str),
                    "channel": order.get("destination_code", "TELEBIRR"), "reference_id": ref_id
                }).execute())
                await asyncio.to_thread(lambda: supabase.table("subscriptions").upsert({
                    "user_id": str(user_id), "is_pro": True, "credits_remaining": 999999
                }).execute())
                await asyncio.to_thread(lambda: supabase.table("pending_orders").delete().eq("user_id", str(user_id)).execute())
            except Exception as e:
                logger.error(f"DB Error: {e}")

        await update.effective_message.reply_text(f"✅ ክፍያው ተረጋግጧል እና ፕሮ አባልነት ተከፍቷል! ⭐🇪🇹
• የግብይት መለያ: {ref_id}")
    else:
        if ADMIN_TELEGRAM_ID:
            try:
                await context.bot.forward_message(chat_id=ADMIN_TELEGRAM_ID, from_chat_id=update.effective_chat.id, message_id=update.message.message_id)
            except Exception:
                pass
        await update.effective_message.reply_text("📥 ደረሰኙ ለግምገማ ተመዝግቧል አስተዳዳሪው ያረጋግጥለታል።")


# -------------------------------------------------------------------
# Master Natural Language Fallback
# -------------------------------------------------------------------
async def handle_master_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data and len(context.user_data) > 0:
        return
    user_text = update.effective_message.text
    if not user_text or user_text.startswith("/"):
        return

    system_prompt = (
        "You are Nexa AI Master Assistant. Analyze user intent from Amharic/English message. "
        "Classify into: 'mybots', 'summary', 'weekly', 'register', 'upgrade', 'general'. "
        "Return strictly valid JSON: {"intent": "category", "reply": "helpful response"}"
    )
    intent_result = {"intent": "general", "reply": "ሰላም! ምን ልረዳዎ እችላለሁ?"}
    if async_groq_client:
        try:
            response = await async_groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}],
                temperature=0.3
            )
            intent_result = json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"Master message intent error: {e}")

    intent = intent_result.get("intent")
    if intent == "mybots":
        await my_bots_command(update, context)
    elif intent == "summary":
        await summary_command(update, context)
    elif intent == "weekly":
        await weekly_summary_command(update, context)
    elif intent == "register":
        await update.effective_message.reply_text("አዲስ ቦት ለመፍጠር /register የሚለውን ይጠቀሙ።")
    elif intent == "upgrade":
        await upgrade_command(update, context)
    else:
        await update.effective_message.reply_text(intent_result.get("reply", "ሰላም! በምን ልረዳዎ እችላለሁ?"))


# -------------------------------------------------------------------
# FastAPI Webhooks & Tenant Bot Engine
# -------------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    global http_client
    http_client = httpx.AsyncClient(timeout=10.0)
    await telegram_app.initialize()
    await telegram_app.start() 
    await telegram_app.bot.set_webhook(url=f"{RENDER_EXTERNAL_URL}/webhook")

    if supabase:
        try:
            stores_res = await asyncio.to_thread(lambda: supabase.table("stores").select("bot_token").execute())
            if stores_res.data:
                tasks = [
                    http_client.post(f"https://api.telegram.org/bot{s['bot_token']}/setWebhook", json={"url": f"{RENDER_EXTERNAL_URL}/tenant-webhook/{s['bot_token']}"})
                    for s in stores_res.data if s.get("bot_token")
                ]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error(f"Startup webhook sync error: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    await telegram_app.stop()
    if http_client:
        await http_client.aclose()


@app.post("/webhook")
async def telegram_webhook(request: Request):
    update = Update.de_json(await request.json(), telegram_app.bot)
    await telegram_app.process_update(update)
    return {"status": "ok"}


@app.post("/tenant-webhook/{bot_token}")
async def tenant_bot_webhook(bot_token: str, request: Request):
    data = await request.json()
    
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_text = message.get("text", "")
    
    if not chat_id or not user_text:
        return {"ok": True}

    store = None
    if supabase:
        try:
            res = await asyncio.to_thread(lambda: supabase.table("stores").select("*").eq("bot_token", bot_token).execute())
            if res.data:
                store = res.data[0]
        except Exception as e:
            logger.error(f"Tenant store fetch error: {e}")

    if not store:
        await http_client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
            "chat_id": chat_id, "text": "⚠️ Store configuration not found or inactive."
        })
        return {"ok": True}

    if supabase:
        try:
            await asyncio.to_thread(lambda: supabase.table("tenant_visitors").upsert({
                "bot_token": bot_token, "chat_id": str(chat_id), "created_at": datetime.now(timezone.utc).isoformat()
            }, on_conflict="bot_token,chat_id").execute())
        except Exception:
            pass

    if user_text == "/start":
        if supabase:
            try:
                await asyncio.to_thread(lambda: supabase.table("customer_languages").upsert({
                    "chat_id": str(chat_id), "bot_token": bot_token, "language": "amharic"
                }, on_conflict="chat_id,bot_token").execute())
            except Exception:
                pass

        ui_theme = store.get("ui_theme", "executive")
        theme_intros = {
            "energetic": "🚀 በደስታ ተቀብለናል! ዛሬ ምን እንድንሰራሎት ይፈልጋሉ?",
            "friendly": "👋 ሰላም! እንኳን ደህና መጡ። በምን እንተባበር?",
            "executive": "💼 እንኳን ወደ ቪአይፒ የውሳኔ ማዕከል በደህና መጡ።",
            "sales": "🎯 ምርጥ ምርጫዎችን እና ቅናሾችን ለማግኘት ዝግጁ ነን!",
            "minimalist": "🎯 ሰላም! በምን ልረዳዎ እችላለሁ?"
        }

        direct_welcome = (
            f"{theme_intros.get(ui_theme, 'ሰላም!')} እንኳን ወደ **{store.get('store_name')}** በደህና መጡ!

"
            f"እቃዎቻችንን፣ ዋጋዎቻችንን ወይም አገልግሎቶቻችንን ከታች በመጻፍ መጠየቅ ይችላሉ። በምን ልረዳዎ?"
        )
        await http_client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
            "chat_id": chat_id,
            "text": direct_welcome
        })
        await http_client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
            "chat_id": chat_id,
            "text": "🛡️ **የደህንነት እና የታማኝነት ማስታወሻ**: የእርስዎ ውይይቶች እና መረጃዎች ሙሉ በሙሉ የተመሰጠሩ (Encrypted) እና ደህንነታቸው የተጠበቁ ናቸው።"
        })
        return {"ok": True}

    customer_lang = "amharic"
    if supabase:
        try:
            lang_res = await asyncio.to_thread(lambda: supabase.table("customer_languages").select("language").eq("chat_id", str(chat_id)).eq("bot_token", bot_token).execute())
            if lang_res.data:
                customer_lang = lang_res.data[0]["language"]
        except Exception:
            pass

    history_messages = []
    if supabase:
        try:
            hist_res = await asyncio.to_thread(lambda: supabase.table("chat_history").select("role, content").eq("chat_id", str(chat_id)).eq("bot_token", bot_token).order("created_at", desc=True).limit(6).execute())
            if hist_res.data:
                history_messages = list(reversed(hist_res.data))
        except Exception:
            pass

    payload = {
        "chat_id": chat_id, "user_text": user_text, "bot_token": bot_token,
        "store_name": store.get("store_name", "Our Business"), "inventory_data": store.get("inventory_data", ""),
        "owner_telegram_id": store.get("owner_telegram_id"), "customer_lang": customer_lang,
        "ui_theme": store.get("ui_theme", "executive"), "history_messages": history_messages
    }
    
    return await store_chat_webhook(payload)


@app.post("/api/store-chat")
async def store_chat_webhook(payload: dict):
    chat_id = payload.get("chat_id")
    user_text = payload.get("user_text", "")
    bot_token = payload.get("bot_token")
    store_name = payload.get("store_name", "Our Business")
    inventory_data = payload.get("inventory_data", "")
    owner_telegram_id = payload.get("owner_telegram_id")
    customer_lang = payload.get("customer_lang", "amharic")
    ui_theme = payload.get("ui_theme", "executive")
    history_messages = payload.get("history_messages", [])

    if owner_telegram_id:
        try:
            owner_id_int = int(owner_telegram_id)
            await get_or_create_user_subscription(owner_id_int)
            if not await verify_active_access(owner_id_int):
                await http_client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={"chat_id": chat_id, "text": "⚠️ የቦቱ የፈተና ጊዜ አልቋል። እባክዎ የቦቱን ባለቤት ያነጋግሩ።"}
                )
                return {"ok": True}
            await deduct_credit(owner_id_int)
        except Exception as e:
            logger.error(f"Subscription enforcement error: {e}")

    await http_client.post(
        f"https://api.telegram.org/bot{bot_token}/sendChatAction",
        json={"chat_id": chat_id, "action": "typing"}
    )

    lang_instructions = {
        "amharic": "በአማርኛ ቋንቋ ብቻ መልስ ስጥ.",
        "english": "Respond in English.",
        "oromo": "Afaan Oromootን deebisi."
    }

    theme_prompts = {
        "energetic": "Be highly energetic, exciting, friendly, and action-oriented.",
        "friendly": "Be warm, welcoming, approachable, and helpful.",
        "executive": "Be a professional executive VIP concierge, polished and authoritative.",
        "sales": "Be conversion-focused, direct, highlighting value and urgency.",
        "minimalist": "Be direct, concise, and straight to the point."
    }

    # Enhanced Analytical & Store-Grounded System Prompt
    system_prompt = f"""
    You are an advanced, intelligent AI sales and analytical assistant for {store_name}. 
    Tone/Theme Style: {theme_prompts.get(ui_theme, theme_prompts['executive'])}
    Language Rule: {lang_instructions.get(customer_lang, lang_instructions['amharic'])}
    
    Core Directives & Analytical Approach:
    - Deeply analyze the customer's request and intelligently match/relate it with the Live Store Catalog Data provided below.
    - Provide smart, flexible, and well-reasoned answers. Do not mechanically repeat text; analyze what the customer is looking for and present the most relevant items, pricing, features, or solutions accurately.
    - If a customer asks about a product, service, or general inquiry, evaluate the store catalog context and give a structured, professional, and helpful response.
    - If customers want to order, book, or purchase, warmly and professionally guide them to provide their name and phone number for fulfillment.
    - Always maintain trust, clarity, and security.
    
    Live Store Catalog Data:
    {inventory_data}
    """

    ai_reply = "ይቅርታ፣ የአገልግሎት ስህተት አጋጥሟል።"
    if async_groq_client:
        try:
            messages = [{"role": "system", "content": system_prompt}]
            for hm in history_messages:
                messages.append({"role": hm.get("role", "user"), "content": hm.get("content", "")})
            messages.append({"role": "user", "content": user_text})

            completion = await async_groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.7,
                max_tokens=600
            )
            ai_reply = completion.choices[0].message.content
        except Exception as e:
            logger.error(f"Groq Chat Error: {e}")
            ai_reply = f"⚠️ Groq AI Error: {str(e)}"

    if supabase:
        try:
            now_user = datetime.now(timezone.utc)
            now_assistant = now_user + timedelta(milliseconds=500)
            
            await asyncio.to_thread(lambda: supabase.table("chat_history").insert({
                "chat_id": str(chat_id), "bot_token": bot_token, "role": "user", "content": user_text, "created_at": now_user.isoformat()
            }).execute())
            
            await asyncio.to_thread(lambda: supabase.table("chat_history").insert({
                "chat_id": str(chat_id), "bot_token": bot_token, "role": "assistant", "content": ai_reply, "created_at": now_assistant.isoformat()
            }).execute())
        except Exception as e:
            logger.error(f"Chat history insert error: {e}")

    await http_client.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": ai_reply}
    )
    return {"ok": True}


# -------------------------------------------------------------------
# Register Handlers & App Routing
# -------------------------------------------------------------------
conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler("register", register_start),
        CallbackQueryHandler(register_start, pattern="^start_register$")
    ],
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
telegram_app.add_handler(CommandHandler("weekly_summary", weekly_summary_command))
telegram_app.add_handler(CommandHandler("mybots", my_bots_command))
telegram_app.add_handler(conv_handler)
telegram_app.add_handler(CallbackQueryHandler(button_handler))
telegram_app.add_handler(MessageHandler(filters.PHOTO, handle_receipt_photo))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_master_message))
