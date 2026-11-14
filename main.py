import os
import random
import asyncio
import httpx
import base64
import json
import logging
import re
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

# 3-Tier Feature & Pricing Matrix
TIER_CONFIG = {
    1: {
        "name": "Tier 1 (Starter)",
        "price": 1000,
        "features": "Core AI Sales, Text Catalog, Photo Support, Basic Leads",
        "allows_photos": True,
        "allows_videos": False,
        "credits": 500
    },
    2: {
        "name": "Tier 2 (Business Pro)",
        "price": 2500,
        "features": "Advanced AI, Photo Catalogs, Priority Lead Tracking, Custom Themes",
        "allows_photos": True,
        "allows_videos": False,
        "credits": 2500
    },
    3: {
        "name": "Tier 3 (Enterprise VIP)",
        "price": 5000,
        "features": "Unlimited AI, Full Photo & Video Streaming, VIP Concierge, Advanced Analytics",
        "allows_photos": True,
        "allows_videos": True,
        "credits": 999999
    },
}

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

# Onboarding Conversation States: STORE_NAME, INDUSTRY, UI_THEME, PLAN_TIER, INVENTORY, BOT_TOKEN
STORE_NAME, INDUSTRY, UI_THEME, PLAN_TIER, INVENTORY, BOT_TOKEN = range(6)


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
# Dynamic Payout Load Balancer (Unified with Selected Tier Price)
# -------------------------------------------------------------------
async def select_optimal_payout_destination(amount_etb: int) -> tuple[str, str, int, str]:
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
    
    if telebirr_24h_total + amount_etb <= SAFE_TELEBIRR_CAP:
        return ("Telebirr Secure Gateway", TELEBIRR_ACCOUNT_MASKED, amount_etb, "TELEBIRR")
    else:
        return ("Awash Bank Secure Corporate Account", AWASH_ACCOUNT_MASKED, amount_etb, "AWASH")


# -------------------------------------------------------------------
# Telegram Master Bot Handlers & Commands (Clean Enterprise UI)
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
            f"🔥 የነጻ የሙከራ ጊዜ በሥራ ላይ አለ (3 ቀናት)\n"
            f"• የሚያበቃበት ጊዜ: {expires_str}\n"
            f"• የቀሩ የAI ዕዳዎች: {sub_data['credits_remaining']}"
        )
    else:
        status_text = "⚠️ የሙከራ ጊዜዎ አልቋል — ቦቶችዎ እንዳይቆሙ በብር ፕሮ አባልነት ያሻሽሉ።"

    welcome_text = (
        f"🇪🇹 እንኳን ወደ Nexa AI ስማርት መድረክ ደህና መጡ, {user.first_name}!\n\n"
        f"ይህ ዳሽቦርድ ሙሉ በሙሉ በ AI የተጎለበተ ነው። የሚፈልጉትን ማንኛውንም ትዕዛዝ በቀጥታ መጻፍ ይችላሉ።\n\n"
        f"📊 የመለያዎ ሁኔታ:\n{status_text}\n\n"
        "🎯 ፈጣን መመሪያ:\n"
        "1️⃣ /register - አዲስ የ AI ቦት ይፍጠሩ\n"
        "2️⃣ /mybots - ቦቶችዎን ያስተዳድሩ\n"
        "3️⃣ /leads - የደንበኞችዎን Leads እና ስልክ ቁጥሮች ይመልከቱ\n"
        "4️⃣ /summary - የገቢ እና የጎብኚዎች ማጠቃለያ\n"
        "5️⃣ /weekly_summary - ሳምንታዊ አጠቃላይ ሪፖርት\n"
        "6️⃣ /update - ዕቃዎችን ወይም አገልግሎቶችን ማሻሻል\n"
        "7️⃣ /pay - ለወር ወይም የመረጡትን ዕቅድ ክፍያ ይፈጽሙ"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 ፕሮ አባልነት ይክፈቱ (በብር)", callback_data="buy_pro")],
        [InlineKeyboardButton("🤖 ቦቶቼን አስተዳድር (/mybots)", callback_data="view_my_bots")],
        [InlineKeyboardButton("📋 የደንበኞች Leads (/leads)", callback_data="view_leads")],
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
            lambda: supabase.table("stores").select("store_name, bot_token, ui_theme, plan_tier").eq("owner_telegram_id", owner_id).execute()
        )
        if not res.data:
            await update.effective_message.reply_text("⚠️ እስካሁን የተፈጠረ ንቁ ቦት የለዎትም። የመጀመሪያውን የ AI ቦት ለመፍጠር /register ይጠቀሙ!")
            return

        bots_list_text = "🤖 የእርስዎ የ AI ቦቶች ዳሽቦርድ\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for idx, store in enumerate(res.data, 1):
            token_val = store.get("bot_token", "")
            masked_token = token_val[:8] + "..." + token_val[-4:] if len(token_val) > 12 else "***"
            tier_num = store.get("plan_tier", 1)
            tier_name = TIER_CONFIG.get(tier_num, TIER_CONFIG[1])["name"]
            bots_list_text += (
                f"{idx}. {store['store_name']}\n"
                f"• ዕቅድ / ፕላን: {tier_name}\n"
                f"• ቶከን ቁልፍ: {masked_token}\n"
                f"• የቦት ዘይቤ: {store.get('ui_theme', 'executive').capitalize()}\n"
                f"• ሁኔታ: በሥራ ላይ እና የተገናኘ ✅\n\n"
            )
        await update.effective_message.reply_text(bots_list_text)
    except Exception as e:
        await update.effective_message.reply_text(f"ቦቶችን ማምጣት አልተቻለም: {str(e)}")


async def upgrade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    owner_id = str(user_id)
    
    store_name = "Nexa Store"
    if supabase:
        try:
            store_res = await asyncio.to_thread(
                lambda: supabase.table("stores").select("store_name").eq("owner_telegram_id", owner_id).order("created_at", desc=True).limit(1).execute()
            )
            if store_res.data:
                store_name = store_res.data[0].get("store_name", "Nexa Store")
        except Exception as e:
            logger.error(f"Store fetch error: {e}")

    tier_select_text = (
        f"⭐ **የፕሮ አባልነት ዕቅድ ይምረጡ ({store_name})**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• **Tier 1 (Starter)**: 1,000 ብር / ወር\n"
        f"• **Tier 2 (Business Pro)**: 2,500 ብር / ወር\n"
        f"• **Tier 3 (Enterprise VIP)**: 5,000 ብር / ወር\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"እባክዎ ክፍያ ለመፈጸም ከታች ካሉት ዕቅዶች አንዱን ይምረጡ:"
    )
    
    keyboard = [
        [InlineKeyboardButton("🥉 Tier 1: Starter (1,000 ብር)", callback_data="tier_pay_1")],
        [InlineKeyboardButton("🥈 Tier 2: Business Pro (2,500 ብር)", callback_data="tier_pay_2")],
        [InlineKeyboardButton("🥇 Tier 3: Enterprise VIP (5,000 ብር)", callback_data="tier_pay_3")]
    ]
    
    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(tier_select_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        except Exception:
            await update.callback_query.message.reply_text(tier_select_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.effective_message.reply_text(tier_select_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def process_tier_upgrade_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, tier_num: int):
    user_id = update.effective_user.id
    owner_id = str(user_id)
    
    store_name = "Nexa Store"
    if supabase:
        try:
            store_res = await asyncio.to_thread(
                lambda: supabase.table("stores").select("store_name").eq("owner_telegram_id", owner_id).order("created_at", desc=True).limit(1).execute()
            )
            if store_res.data:
                store_name = store_res.data[0].get("store_name", "Nexa Store")
        except Exception as e:
            logger.error(f"Store fetch error: {e}")

    tier_info = TIER_CONFIG.get(tier_num, TIER_CONFIG[1])
    base_price = tier_info["price"]
    
    exact_amount_etb = random.randint(base_price, base_price + 100)
    channel_name, masked_account, _, channel_code = await select_optimal_payout_destination(exact_amount_etb)
    order_id = f"NEXA-SECURE-{random.randint(1000, 9999)}"
    
    if supabase:
        try:
            await asyncio.to_thread(
                lambda: supabase.table("pending_orders").upsert({
                    "user_id": owner_id,
                    "order_id": order_id,
                    "amount": str(exact_amount_etb),
                    "channel": channel_name,
                    "destination_code": channel_code,
                    "status": "pending_payment"
                }, on_conflict="user_id").execute()
            )
            await asyncio.to_thread(
                lambda: supabase.table("stores").update({"plan_tier": tier_num}).eq("owner_telegram_id", owner_id).execute()
            )
        except Exception as e:
            logger.error(f"Pending order save error: {e}")

    invoice_text = (
        f"💳 **የቴሌብር ክፍያ ዝርዝር — {tier_info['name']} ({store_name})**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• የሚከፈለው ትክክለኛ መጠን: **{exact_amount_etb:,} ብር**\n"
        f"• የክፍያ መቀበያ ቁጥር (Telebirr): `{masked_account}`\n"
        f"• የደረሰኝ ቁጥር: {order_id}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 **ምን ማድረግ ይኖርብዎታል?**\n"
        f"1. በስልክዎ የቴሌብር መተግበሪያ በመጠቀም ከላይ ወደተጠቀሰው ቁጥር `{masked_account}` ትክክለኛውን `{exact_amount_etb:,} ብር` ያስተላልፉ።\n"
        f"2. ክፍያውን ከፈጸሙ በኋላ የሚደርሰውን የቴሌብር SMS ማረጋገጫ (Screenshot) ወይም የግብይት ቁጥር (Transaction ID) እዚህ ይላኩ።\n"
        f"3. የ AI-OCR ሲስተሙ ክፍያዎን ወዲያውኑ አረጋግጦ አካውንትዎን ይከፍትልዎታል።"
    )
    
    keyboard = [
        [InlineKeyboardButton(f"📋 ቁጥር ቅዳ: {masked_account}", callback_data=f"copy_acc_{masked_account}")],
        [InlineKeyboardButton("✅ ከፍያለሁ — ደረሰኝ ጫን", callback_data="upload_receipt")]
    ]
    
    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(invoice_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        except Exception:
            await update.callback_query.message.reply_text(invoice_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.effective_message.reply_text(invoice_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def leads_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = str(update.effective_user.id)
    if not supabase:
        await update.effective_message.reply_text("የዳታቤዝ ግንኙነት የለም።")
        return

    try:
        stores_res = await asyncio.to_thread(
            lambda: supabase.table("stores").select("bot_token, store_name").eq("owner_telegram_id", owner_id).execute()
        )
        if not stores_res.data:
            await update.effective_message.reply_text("❌ እስካሁን የተመዘገበ ቦት የለዎትም። ለመፍጠር /register ይጠቀሙ።")
            return

        if len(stores_res.data) == 1:
            await show_store_leads_and_analytics(update.effective_message, stores_res.data[0]["bot_token"], stores_res.data[0]["store_name"])
        else:
            keyboard = []
            for store in stores_res.data:
                keyboard.append([InlineKeyboardButton(f"🤖 {store['store_name']}", callback_data=f"select_lead_bot_{store['bot_token']}")])
            
            target_msg = update.callback_query.message if update.callback_query else update.effective_message
            text_prompt = "📋 **የሊድስ እና ስታቲስቲክስ መቆጣጠሪያ**\n\nእባክዎ መረጃውን ማየት የሚፈልጉትን ቦት/መደብር ይምረጡ:"
            
            if update.callback_query:
                await target_msg.edit_text(text_prompt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            else:
                await target_msg.reply_text(text_prompt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        await update.effective_message.reply_text(f"Leads ማምጣት አልተቻለም: {str(e)}")


async def show_store_leads_and_analytics(message_target, bot_token: str, store_name: str):
    try:
        vis_res = await asyncio.to_thread(
            lambda: supabase.table("tenant_visitors").select("chat_id", count="exact").eq("bot_token", bot_token).execute()
        )
        total_bot_visitors = vis_res.count if vis_res.count is not None else len(vis_res.data or [])

        leads_res = await asyncio.to_thread(
            lambda: supabase.table("leads").select("*").eq("bot_token", bot_token).order("updated_at", desc=True).limit(35).execute()
        )
        leads_data = leads_res.data or []

        high_intent_count = 0
        vip_payer_count = 0

        for lead in leads_data:
            intent_val = str(lead.get("intent_level", "low")).lower()
            is_vip = bool(lead.get("is_high_payer", False))
            if is_vip:
                vip_payer_count += 1
            if intent_val in ["high", "vip"] or is_vip:
                high_intent_count += 1

        analytics_header = (
            f"📊 **የእርስዎ ቦት ጎብኚዎች እና ስታቲስቲክስ — {store_name}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• ጠቅላላ የቦት ጎብኚዎች (Total Visitors): {total_bot_visitors} ተጠቃሚዎች\n"
            f"• ንቁ የውይይት ተሳታፊዎች: {len(leads_data)} ተጠቃሚዎች\n"
            f"• 💎 ከፍተኛ ከፋዮች (VIP High-Payers): {vip_payer_count} ተጠቃሚዎች\n"
            f"• 🔥 ለመግዛት የተዘጋጁ (High-Intent Leads): {high_intent_count} ተጠቃሚዎች\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📋 **በ AI የተተነተነ የደንበኞች እና ስልክ ቁጥሮች ዝርዝር:**\n"
        )

        lines = [analytics_header]
        for idx, lead in enumerate(leads_data[:25], start=1):
            name = lead.get("visitor_name") or "ስም ያልታወቀ"
            phone = lead.get("phone_number") or "አልሰጠም ❌"
            chat_id_val = lead.get("visitor_telegram_id") or "N/A"
            summary = lead.get("interest_summary") or "አጠቃላይ ፍለጋ"
            is_vip = bool(lead.get("is_high_payer", False))

            intent_badge = "💎 ከፍተኛ ከፋይ (VIP High-Payer)" if is_vip else "💬 ንቁ ደንበኛ (Lead)"

            lines.append(
                f"**{idx}. የደንበኛ ስም:** {name}\n"
                f"   📞 **ስልክ ቁጥር:** `{phone}`\n"
                f"   🆔 **ቴሌግራም ID (Chat ID):** `{chat_id_val}`\n"
                f"   📌 **የውይይት ማጠቃለያ:** _{summary}_\n"
                f"   🏷️ **ሁኔታ:** {intent_badge}\n"
                f"   ──────────────────────────\n"
            )

        if not leads_data:
            lines.append("📭 እስካሁን ቦትዎን የጎበኘ ወይም ስልክ ቁጥር የሰጠ ደንበኛ የለም።")

        full_text = "\n".join(lines)
        if hasattr(message_target, "edit_text"):
            try:
                await message_target.edit_text(full_text, parse_mode="Markdown")
            except Exception as edit_err:
                if "Message is not modified" in str(edit_err):
                    return
                raise edit_err
        else:
            await message_target.reply_text(full_text, parse_mode="Markdown")
    except Exception as e:
        if "Message is not modified" in str(e):
            return
        logger.error(f"Analytics display error: {e}")
        err_msg = f"ስታቲስቲክስ ማምጣት አልተቻለም: {str(e)}"
        if hasattr(message_target, "edit_text"):
            try:
                await message_target.edit_text(err_msg)
            except Exception:
                pass
        else:
            await message_target.reply_text(err_msg)


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    total_revenue, total_subscribers, total_visitors = 0, 0, 0
    bot_names_summary = []

    if supabase:
        try:
            stores_res = await asyncio.to_thread(
                lambda: supabase.table("stores").select("bot_token, store_name").eq("owner_telegram_id", user_id).execute()
            )
            bot_tokens = [s["bot_token"] for s in stores_res.data] if stores_res.data else []

            if bot_tokens:
                vis_res = await asyncio.to_thread(
                    lambda: supabase.table("tenant_visitors").select("chat_id", count="exact").in_("bot_token", bot_tokens).execute()
                )
                total_visitors = vis_res.count if vis_res.count is not None else len(vis_res.data or [])

                for store in stores_res.data:
                    b_token = store["bot_token"]
                    s_name = store["store_name"]
                    v_res = await asyncio.to_thread(
                        lambda bt=b_token: supabase.table("tenant_visitors").select("chat_id", count="exact").eq("bot_token", bt).execute()
                    )
                    b_count = v_res.count if v_res.count is not None else len(v_res.data or [])
                    bot_names_summary.append(f"• የቦት ስም ({s_name}): {b_count} ጎብኚዎች")

            rev_res = await asyncio.to_thread(
                lambda: supabase.table("paid_subscriptions").select("user_id", "amount_etb").eq("user_id", user_id).execute()
            )
            if rev_res.data:
                total_revenue = sum(float(tx["amount_etb"]) for tx in rev_res.data)
                total_subscribers = len(rev_res.data)
        except Exception as e:
            logger.error(f"Summary fetch error: {e}")

    bots_breakdown = "\n".join(bot_names_summary) or "እስካሁን የተፈጠረ ቦት የለም።"
    summary_text = (
        f"📊 **የእርስዎ ቦቶች እና የጎብኚዎች ማጠቃለያ**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• የሁሉም ቦቶችዎ ጠቅላላ ጎብኚዎች (Total Visitors): {total_visitors} ተጠቃሚዎች\n"
        f"• የከፈሉባቸው የደንበኝነት ክፍያዎች: {total_subscribers}\n"
        f"• ያወጡት ጠቅላላ ወጪ / ክፍያ: {total_revenue:,.2f} ብር\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🤖 **በእርስዎ ቦቶች የተመዘገቡ ጎብኚዎች ዝርዝር:**\n"
        f"{bots_breakdown}"
    )
    await update.effective_message.reply_text(summary_text, parse_mode="Markdown")


async def weekly_summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    weekly_revenue, tenant_visitors_count, leads_this_week = 0, 0, 0

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

                leads_res = await asyncio.to_thread(
                    lambda: supabase.table("leads").select("updated_at").in_("bot_token", bot_tokens).execute()
                )
                if leads_res.data:
                    for l in leads_res.data:
                        if parse_dt(l.get("updated_at")) >= week_ago:
                            leads_this_week += 1

            rev_res = await asyncio.to_thread(
                lambda: supabase.table("paid_subscriptions").select("amount_etb, created_at").eq("user_id", user_id).execute()
            )
            if rev_res.data:
                for tx in rev_res.data:
                    if tx.get("created_at") and parse_dt(tx["created_at"]) >= week_ago:
                        weekly_revenue += float(tx["amount_etb"])
        except Exception as e:
            logger.error(f"Weekly summary error: {e}")

    weekly_text = (
        f"📈 **የእርስዎ ቦቶች ሳምንታዊ ሪፖርት (Weekly Summary)**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• ባለፉት 7 ቀናት ቦቶችዎን የጎበኙ ሰዎች: {tenant_visitors_count} ተጠቃሚዎች\n"
        f"• ባለፉት 7 ቀናት የተመዘገቡ አዳዲስ ሊድስ/ስልክ ቁጥሮች: {leads_this_week}\n"
        f"• የሳምንቱ የክፍያ እንቅስቃሴ: {weekly_revenue:,.2f} ብር\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 ደንበኞችዎን በዝርዝር ለማየት `/leads` የሚለውን ትዕዛዝ ይጠቀሙ!"
    )
    await update.effective_message.reply_text(weekly_text, parse_mode="Markdown")


async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = str(update.effective_user.id)
    if not supabase:
        await update.effective_message.reply_text("የዳታቤዝ ግንኙነት የለም።")
        return

    text_content = update.effective_message.text.replace("/update", "").strip()
    if not text_content:
        await update.effective_message.reply_text(
            "⚠️ እባክዎ ማሻሻል የሚፈልጉትን አዲስ የዕቃ ዝርዝር ወይም ካታሎግ ከ `/update` ትዕዛዝ ጋር አብረው ይጻፉ።\n\n"
            "ምሳሌ: `/update 1. የቤት እቃዎች - 5000 ብር`"
        )
        return

    try:
        res = await asyncio.to_thread(
            lambda: supabase.table("stores").update({"inventory_data": text_content}).eq("owner_telegram_id", owner_id).execute()
        )
        if res.data:
            await update.effective_message.reply_text("✅ የዕቃ ዝርዝርዎ እና ካታሎግዎ በተሳካ ሁኔታ ተሻሽሏል!")
            return
    except Exception as e:
        logger.error(f"Update error: {e}")
    await update.effective_message.reply_text("⚠️ ምንም ንቁ መደብር አልተገኘም ወይም ስህተት አጋጥሟል።")


# -------------------------------------------------------------------
# AI Self-Healing & Auto-Correction Auditor (Nexa & Connected Bots)
# -------------------------------------------------------------------
async def run_ai_system_audit_and_heal(target_owner_id: str = None) -> str:
    if not supabase:
        return "⚠️ Supabase connection missing."

    repaired_webhooks = 0
    healed_stores = 0
    analyzed_leads = 0

    try:
        if TELEGRAM_BOT_TOKEN and http_client:
            expected_master_wh = f"{RENDER_EXTERNAL_URL}/webhook"
            try:
                wh_info = await http_client.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo", timeout=5.0)
                if wh_info.status_code == 200:
                    current_wh_url = wh_info.json().get("result", {}).get("url", "")
                    if current_wh_url != expected_master_wh:
                        await http_client.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook", json={"url": expected_master_wh}, timeout=5.0)
                        repaired_webhooks += 1
            except Exception as master_wh_err:
                logger.error(f"Master webhook audit error: {master_wh_err}")

        query = supabase.table("stores").select("*")
        if target_owner_id:
            query = query.eq("owner_telegram_id", target_owner_id)
        stores_res = await asyncio.to_thread(lambda: query.execute())
        stores = stores_res.data or []

        for store in stores:
            bot_token = store.get("bot_token")
            if not bot_token:
                continue

            expected_tenant_wh = f"{RENDER_EXTERNAL_URL}/tenant-webhook/{bot_token}"
            if http_client:
                try:
                    t_info = await http_client.get(f"https://api.telegram.org/bot{bot_token}/getWebhookInfo", timeout=3.0)
                    if t_info.status_code == 200:
                        current_t_wh = t_info.json().get("result", {}).get("url", "")
                        if current_t_wh != expected_tenant_wh:
                            await http_client.post(f"https://api.telegram.org/bot{bot_token}/setWebhook", json={"url": expected_tenant_wh}, timeout=3.0)
                            repaired_webhooks += 1
                except Exception:
                    pass

            updates_needed = {}
            valid_themes = ["executive", "sales", "friendly", "minimalist", "energetic"]
            if store.get("ui_theme") not in valid_themes:
                updates_needed["ui_theme"] = "executive"
            if store.get("plan_tier") not in [1, 2, 3]:
                updates_needed["plan_tier"] = 1

            if updates_needed:
                await asyncio.to_thread(
                    lambda u=updates_needed, bt=bot_token: supabase.table("stores").update(u).eq("bot_token", bt).execute()
                )
                healed_stores += 1

        return (
            f"🛡️ **የAI ሲስተም ፍተሻ እና ራስ-ሰር እርማት ተጠናቋል!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• የተስተካከሉ ዌብሁኮች: {repaired_webhooks}\n"
            f"• የተስተካከሉ ቦቶች: {healed_stores}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Nexa እና ሁሉም የተገናኙ ቦቶች በትክክል እየሰሩ መሆናቸው ተረጋግጧል።"
        )
    except Exception as e:
        logger.error(f"System audit error: {e}")
        return f"⚠️ Audit failed: {str(e)}"


async def audit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = str(update.effective_user.id)
    await update.effective_message.reply_text("🛡️ AI system audit and self-healing started...")
    result_text = await run_ai_system_audit_and_heal(target_owner_id=owner_id)
    await update.effective_message.reply_text(result_text, parse_mode="Markdown")


# -------------------------------------------------------------------
# Conversation Handler Steps for Bot Creation
# -------------------------------------------------------------------
async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_msg = update.callback_query.message if update.callback_query else update.effective_message
    if update.callback_query:
        await update.callback_query.answer()

    await target_msg.reply_text(
        "🤖 **አዲስ የ AI ቦት ምዝገባ (Step 1 from 5)**\n\n"
        "እባክዎ ለንግድዎ ወይም ለመደብርዎ የሚሆን ስም (Store/Business Name) ይጻፉ:",
        parse_mode="Markdown"
    )
    return STORE_NAME


async def receive_store_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store_name = update.effective_message.text.strip()
    context.user_data["store_name"] = store_name

    keyboard = [
        [InlineKeyboardButton("🛍️ ችርቻሮ እና ግብይት (Retail & E-Commerce)", callback_data="ind_retail")],
        [InlineKeyboardButton("🏡 ሪል እስቴት እና ቤቶች (Real Estate)", callback_data="ind_realestate")],
        [InlineKeyboardButton("🍽️ ሆቴል እና ካፌ (Hospitality & Food)", callback_data="ind_hospitality")],
        [InlineKeyboardButton("⚙️ አገልግሎት እና ቴክኖሎጂ (Services & Tech)", callback_data="ind_services")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.effective_message.reply_text(
        f"እርምጃ 2 ከ 5: የንግድ ዘርፍዎን (Industry) ይምረጡ:",
        reply_markup=reply_markup
    )
    return INDUSTRY


async def receive_industry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    industry = "retail"
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        industry = query.data.replace("ind_", "")
        target_message = query.edit_message_text
    else:
        industry = "retail"
        target_message = update.effective_message.reply_text

    context.user_data["industry"] = industry

    keyboard = [
        [InlineKeyboardButton("💼 Executive VIP", callback_data="theme_executive")],
        [InlineKeyboardButton("🎯 Sales Conversion", callback_data="theme_sales")],
        [InlineKeyboardButton("👋 Friendly & Warm", callback_data="theme_friendly")],
        [InlineKeyboardButton("⚡ Energetic", callback_data="theme_energetic")],
        [InlineKeyboardButton("🎯 Minimalist", callback_data="theme_minimalist")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await target_message(
        "እርምጃ 3 ከ 5: የቦትዎን የውይይት ዘይቤ (UI/UX Theme) ይምረጡ:",
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
    
    keyboard = [
        [InlineKeyboardButton("🥉 Tier 1: Starter (1,000 ብር / ወር)", callback_data="tier_1")],
        [InlineKeyboardButton("🥈 Tier 2: Business Pro (2,500 ብር / ወር)", callback_data="tier_2")],
        [InlineKeyboardButton("🥇 Tier 3: Enterprise VIP (5,000 ብር / ወር)", callback_data="tier_3")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await target_message(
        "እርምጃ 4 ከ 5: የሚፈልጉትን የባሪዮች ደረጃ (Tier) ይምረጡ:\n"
        "• **Tier 1:** የላቀ AI + የጽሁፍ ካታሎግ + የፎቶ ድጋፍ\n"
        "• **Tier 2:** የላቀ AI + የፎቶ ካታሎግ + የላቀ የደንበኛ ክትትል\n"
        "• **Tier 3:** ያልተወሰነ AI + ሙሉ የፎቶ እና ቪዲዮ ስትሪሚንግ ድጋፍ",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return PLAN_TIER


async def receive_plan_tier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tier_num = 1
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        tier_num = int(query.data.replace("tier_", ""))
        target_message = query.edit_message_text
    else:
        tier_num = 1
        target_message = update.effective_message.reply_text

    context.user_data["plan_tier"] = tier_num
    tier_info = TIER_CONFIG.get(tier_num, TIER_CONFIG[1])

    await target_message(
        f"የተመረጠው ዕቅድ: {tier_info['name']} ({tier_info['price']:,} ብር)\n\n"
        "እርምጃ 5 ከ 5: ሙሉ ዕቃዎችዎን፣ አገልግሎቶችዎን፣ የሪል እስቴት መረጃዎን ወይም ካታሎግ ጽሑፍ ከታች ይለጥፉ:"
    )
    return INVENTORY


async def receive_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_input = update.effective_message.text
    
    await update.effective_message.reply_text("🔄 AI is analyzing, sorting, and formatting your catalog data for Supabase...")
    
    structured_inventory = raw_input
    if async_groq_client:
        try:
            prompt = (
                f"Analyze and re-organize the following raw store catalog or inventory text into a clean, highly structured, "
                f"professional format with clear headings, item names, prices in ETB, and descriptions:\n\n{raw_input}"
            )
            completion = await async_groq_client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            structured_inventory = completion.choices[0].message.content
        except Exception as e:
            logger.error(f"AI catalog structuring error: {e}")

    context.user_data["inventory_data"] = structured_inventory
    await update.effective_message.reply_text(
        "✅ Catalog successfully sorted and structured by AI!\n\n"
        "ወደ ኦፊሴላዊው የቴሌግራም @BotFather ይሂዱ፣ ቦት ይፍጠሩ (/newbot)፣ ልዩ የቦት ቶከን ይውሰዱ እና እዚህ ይለጥፉ:"
    )
    return BOT_TOKEN


async def receive_bot_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_token = update.effective_message.text.strip()
    owner_telegram_id = str(update.effective_user.id)
    store_name = context.user_data.get("store_name", "My Store")
    inventory_data = context.user_data.get("inventory_data", "No inventory specified")
    ui_theme = context.user_data.get("ui_theme", "executive")
    plan_tier = context.user_data.get("plan_tier", 1)

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
            store_payload = {
                "bot_token": bot_token,
                "owner_telegram_id": owner_telegram_id,
                "store_name": store_name,
                "inventory_data": inventory_data,
                "ui_theme": ui_theme,
                "plan_tier": plan_tier
            }
            await asyncio.to_thread(
                lambda: supabase.table("stores").upsert(store_payload, on_conflict="bot_token").execute()
            )
        except Exception as e:
            logger.error(f"Supabase strict upsert error, attempting graceful fallback: {e}")
            try:
                fallback_payload = {
                    "bot_token": bot_token,
                    "owner_telegram_id": owner_telegram_id,
                    "store_name": store_name,
                    "inventory_data": inventory_data,
                    "ui_theme": ui_theme
                }
                await asyncio.to_thread(
                    lambda: supabase.table("stores").upsert(fallback_payload, on_conflict="bot_token").execute()
                )
            except Exception as inner_e:
                await update.effective_message.reply_text(f"⚠️ ዳታቤዝ ላይ ማስቀመጥ አልተቻለም: {str(inner_e)}")
                return BOT_TOKEN

    tier_info = TIER_CONFIG.get(plan_tier, TIER_CONFIG[1])
    await update.effective_message.reply_text(
        f"🎉 እንኳን ደስ አለዎት! የ AI ቦትዎ በሥራ ላይ ውሏል! 🇪🇹🚀\n\n"
        f"• የንግድ ስም: {store_name}\n"
        f"• የተመረጠው ዕቅድ: {tier_info['name']}\n"
        f"• ችሎታዎች: {tier_info['features']}\n"
        f"• ሁኔታ: ተገናኝቷል እና ንቁ ነው ✅\n\n"
        "ደንበኞችዎ ቦትዎን ሲጀምሩ (/start) ቀጥተኛ ውይይት ይጀምራሉ።"
    )
    return ConversationHandler.END


async def cancel_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("❌ ምዝገባው ተሰርዟል። ዝግጁ ሲሆኑ /register ይጠቀሙ።")
    return ConversationHandler.END


# -------------------------------------------------------------------
# Media Upload Handler (/addmedia tag)
# -------------------------------------------------------------------
async def handle_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    caption = update.message.caption or ""
    match = re.search(r"/addmedia\s+([a-zA-Z0-9_\\-]+)", caption)
    
    if not match:
        return

    item_tag = match.group(1).lower()
    
    if supabase:
        try:
            stores_res = await asyncio.to_thread(
                lambda: supabase.table("stores").select("bot_token").eq("owner_telegram_id", user_id).execute()
            )
            if not stores_res.data:
                await update.effective_message.reply_text("❌ ምንም ንቁ መደብር አልተገኘም።")
                return

            bot_token = stores_res.data[0]["bot_token"]
            
            file_id = ""
            media_type = "photo"
            if update.message.photo:
                file_id = update.message.photo[-1].file_id
                media_type = "photo"
            elif update.message.video:
                file_id = update.message.video.file_id
                media_type = "video"

            clean_caption = re.sub(r"/addmedia\s+[a-zA-Z0-9_\\-]+", "", caption).strip()

            await asyncio.to_thread(
                lambda: supabase.table("property_media").insert({
                    "bot_token": bot_token,
                    "item_tag": item_tag,
                    "file_id": file_id,
                    "media_type": media_type,
                    "caption": clean_caption
                }).execute()
            )
            await update.effective_message.reply_text(f"✅ ሚዲያ በተሳካ ሁኔታ ተመዝግቧል! (Tag: `{item_tag}`)", parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Media upload error: {e}")
            await update.effective_message.reply_text("⚠️ ሚዲያ ማስቀመጥ አልተቻለም።")


# -------------------------------------------------------------------
# Button, Receipt & Master Message Handlers
# -------------------------------------------------------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data in ["buy_pro", "upgrade", "pay"]:
        await upgrade_command(update, context)
    elif query.data in ["upgrade_tier_1", "tier_pay_1", "tier_1"]:
        await process_tier_upgrade_selection(update, context, 1)
    elif query.data in ["upgrade_tier_2", "tier_pay_2", "tier_2"]:
        await process_tier_upgrade_selection(update, context, 2)
    elif query.data in ["upgrade_tier_3", "tier_pay_3", "tier_3"]:
        await process_tier_upgrade_selection(update, context, 3)
    elif query.data == "view_summary":
        await summary_command(update, context)
    elif query.data == "view_weekly":
        await weekly_summary_command(update, context)
    elif query.data == "view_my_bots":
        await my_bots_command(update, context)
    elif query.data == "view_leads":
        await leads_command(update, context)
    elif query.data == "start_register":
        await register_start(update, context)
    elif query.data == "upload_receipt":
        await query.message.reply_text("📸 እባክዎ የክፍያ ደረሰኝ ፎቶ (Screenshot) ይላኩ።")
    elif query.data.startswith("copy_acc_"):
        acc_num = query.data.replace("copy_acc_", "")
        await query.answer(text=f"የሂሳብ ቁጥር ተገልብጧል: {acc_num}", show_alert=True)
    elif query.data.startswith("select_lead_bot_"):
        bot_token = query.data.replace("select_lead_bot_", "")
        store_name = "Selected Store"
        if supabase:
            try:
                res = await asyncio.to_thread(
                    lambda: supabase.table("stores").select("store_name").eq("bot_token", bot_token).execute()
                )
                if res.data:
                    store_name = res.data[0].get("store_name", "Selected Store")
            except Exception:
                pass
        await show_store_leads_and_analytics(query.message, bot_token, store_name)


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
        await update.effective_message.reply_text("❌ ምንም ንቁ ትዕዛዝ አልተገኘም። መጀመሪያ /upgrade ወይም /pay ይጠቀሙ።")
        return

    photo_file = await update.message.photo[-1].get_file()
    image_bytes = await photo_file.download_as_bytearray()
    base64_image = base64.b64encode(bytes(image_bytes)).decode('utf-8')
    
    expected_amount_str = order["amount"]
    parsed_result = {"valid": False, "reference_id": None, "detected_amount": None}

    if async_groq_client:
        try:
            prompt = (
                f"Analyze this Ethiopian bank or Telebirr payment receipt image with 100% strict accuracy. Extract:\n"
                f"1. Transaction Reference ID or Confirmation Code (string)\n"
                f"2. Total Amount in ETB transferred (number or string without commas)\n"
                f"Return strictly valid JSON format: "
                f'{{"valid": true/false, "reference_id": "string", "detected_amount": "string"}}'
            )
            response = await async_groq_client.chat.completions.create(
                model="qwen/qwen3.8-27b",
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

    if ref_id and supabase:
        try:
            dup_check = await asyncio.to_thread(
                lambda: supabase.table("processed_receipts").select("*").eq("reference_id", ref_id).execute()
            )
            if dup_check.data:
                await update.effective_message.reply_text(
                    "⚠️ **ይህ የክፍያ ደረሰኝ (Screenshot / Reference ID) ከዚህ በፊት ጥቅም ላይ ውሏል!**\n\n"
                    "እባክዎ አዲስ እና ትክክለኛ የክፍያ ደረሰኝ Screenshot በድጋሚ ይላኩ።"
                )
                return
        except Exception as dup_err:
            logger.error(f"Duplicate receipt check error: {dup_err}")

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

        await update.effective_message.reply_text(f"✅ ክፍያው በ AI-OCR ተረጋግጧል እና ፕሮ አባልነትዎ በቅጽበት ገብቷል! ⭐🇪🇹\n• የግብይት መለያ: `{ref_id}`", parse_mode="Markdown")
    else:
        if ADMIN_TELEGRAM_ID:
            try:
                await context.bot.forward_message(chat_id=ADMIN_TELEGRAM_ID, from_chat_id=update.effective_chat.id, message_id=update.message.message_id)
            except Exception:
                pass
        await update.effective_message.reply_text(
            "⚠️ በ AI-OCR የክፍያውን መጠን ወይም የግብይት መለያ ማረጋገጥ አልተቻለም።\n\n"
            "እባክዎ ትክክለኛውን የቴሌብር SMS ፎቶ (Screenshot) በግልጽ እንደገና ይላኩ ወይም የግብይት ቁጥሩን በጽሁፍ ይጻፉ።"
        )


async def handle_master_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data and len(context.user_data) > 0:
        return
    user_text = update.effective_message.text
    if not user_text or user_text.startswith("/"):
        return

    system_prompt = (
        "You are Nexa AI Master Assistant. Analyze user intent from Amharic/English message. "
        "Classify into: 'mybots', 'leads', 'summary', 'weekly', 'register', 'upgrade', 'general'. "
        'Return strictly valid JSON: {"intent": "category", "reply": "helpful response"}'
    )
    intent_result = {"intent": "general", "reply": "ሰላም! ምን ልረዳዎ እችላለሁ?"}
    if async_groq_client:
        try:
            response = await async_groq_client.chat.completions.create(
                model="openai/gpt-oss-120b",
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
    elif intent == "leads":
        await leads_command(update, context)
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


@app.on_event("startup")
async def startup_event():
    global http_client
    http_client = httpx.AsyncClient(timeout=10.0)
    await telegram_app.initialize()
    await telegram_app.start() 
    await telegram_app.bot.set_webhook(url=f"{RENDER_EXTERNAL_URL}/webhook")

    asyncio.create_task(run_ai_system_audit_and_heal())


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
    user_obj = message.get("from", {})
    visitor_name = f"{user_obj.get('first_name', '')} {user_obj.get('last_name', '')}".strip() or "Anonymous"
    
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
        except Exception as e:
            logger.error(f"Visitor record error: {e}")

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
            f"{theme_intros.get(ui_theme, 'ሰላም!')} እንኳን ወደ **{store.get('store_name')}** በደህና መጡ!\n\n"
            f"እቃዎቻችንን፣ ዋጋዎቻችንን ወይም አገልግሎቶቻችንን ከታች በመጻፍ መጠየቅ ይችላሉ። ፎቶ ወይም ቪዲዮ ማየት ከፈለጉ መጠየቅ ይችላሉ!"
        )
        await http_client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
            "chat_id": chat_id,
            "text": direct_welcome
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

    available_tags = []
    if supabase:
        try:
            media_res = await asyncio.to_thread(lambda: supabase.table("property_media").select("item_tag, caption").eq("bot_token", bot_token).execute())
            if media_res.data:
                available_tags = list({f"{m['item_tag']} ({m.get('caption', '')})" for m in media_res.data})
        except Exception:
            pass

    payload = {
        "chat_id": chat_id, "user_text": user_text, "bot_token": bot_token,
        "visitor_name": visitor_name,
        "store_name": store.get("store_name", "Our Business"), "inventory_data": store.get("inventory_data", ""),
        "owner_telegram_id": store.get("owner_telegram_id"), "customer_lang": customer_lang,
        "ui_theme": store.get("ui_theme", "executive"), "history_messages": history_messages,
        "available_tags": available_tags, "plan_tier": store.get("plan_tier", 1)
    }
    
    return await store_chat_webhook(payload)


# -------------------------------------------------------------------
# One-by-One AI Conversation Structuring & Supabase Sync
# -------------------------------------------------------------------
async def analyze_and_upsert_lead(
    bot_token: str,
    chat_id: str,
    visitor_name: str,
    user_text: str,
    history_messages: list,
    inventory_data: str
):
    if not supabase or not async_groq_client:
        return

    convo_text = "\n".join([f"{m['role']}: {m['content']}" for m in history_messages[-5:]])
    convo_text += f"\nuser: {user_text}"

    analysis_prompt = f"""
    Analyze this customer conversation one-by-one for a business store and extract structured lead intelligence.
    Store Catalog Reference: {inventory_data[:1200]}
    
    Conversation:
    {convo_text}
    
    Return strictly valid JSON with these exact keys:
    {{
        "customer_name": "extracted real name or '{visitor_name}'",
        "phone_number": "extracted Ethiopian phone (+251... or 09.../07...) or null",
        "requested_items": "concise summary of specific products/services they want",
        "estimated_budget": 0,
        "intent_level": "high" or "medium" or "low",
        "is_high_payer": true or false (true if asking about bulk orders, high-ticket/premium items, or showing readiness to pay substantial amounts),
        "action_summary": "1-sentence Amharic summary of the customer's exact need and next step"
    }}
    """

    try:
        res = await async_groq_client.chat.completions.create(
            model="openai/gpt-oss-120b",
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": analysis_prompt}],
            temperature=0.1
        )
        structured_data = json.loads(res.choices[0].message.content)

        phone = structured_data.get("phone_number")
        if not phone:
            phone_match = re.search(r"(\+251[79]\d{8}|0[79]\d{8})", user_text.replace(" ", ""))
            phone = phone_match.group(0) if phone_match else None

        intent_lvl = str(structured_data.get("intent_level", "low")).lower()
        action_summary = structured_data.get("action_summary") or user_text[:100]
        is_vip = bool(structured_data.get("is_high_payer", False))
        vip_prefix = "💎 VIP | " if is_vip else ""

        lead_payload = {
            "bot_token": bot_token,
            "visitor_telegram_id": str(chat_id),
            "visitor_name": structured_data.get("customer_name") or visitor_name,
            "interest_summary": f"[{intent_lvl.upper()}] {vip_prefix}{action_summary}",
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        if phone:
            lead_payload["phone_number"] = phone

        await asyncio.to_thread(
            lambda: supabase.table("leads").upsert(
                lead_payload, on_conflict="bot_token,visitor_telegram_id"
            ).execute()
        )
    except Exception as e:
        logger.error(f"AI Lead Structuring Error: {e}")


@app.post("/api/store-chat")
async def store_chat_webhook(payload: dict):
    chat_id = payload.get("chat_id")
    user_text = payload.get("user_text", "")
    bot_token = payload.get("bot_token")
    visitor_name = payload.get("visitor_name", "Anonymous")
    store_name = payload.get("store_name", "Our Business")
    inventory_data = payload.get("inventory_data", "")
    owner_telegram_id = payload.get("owner_telegram_id")
    customer_lang = payload.get("customer_lang", "amharic")
    ui_theme = payload.get("ui_theme", "executive")
    history_messages = payload.get("history_messages", [])
    available_tags = payload.get("available_tags", [])
    plan_tier = payload.get("plan_tier", 1)

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

    tier_capabilities = TIER_CONFIG.get(plan_tier, TIER_CONFIG[1])
    tags_str = ", ".join(available_tags) if available_tags else "None"

    system_prompt = f"""
    You are an advanced, intelligent AI sales and analytical assistant for {store_name}. 
    Tone/Theme Style: {theme_prompts.get(ui_theme, theme_prompts['executive'])}
    Language Rule: {lang_instructions.get(customer_lang, lang_instructions['amharic'])}
    Store Plan Tier: {tier_capabilities['name']} ({tier_capabilities['features']})
    
    Core Directives & Analytical Approach:
    - Deeply analyze the customer's request and intelligently match/relate it with the Live Store Catalog Data provided below.
    - Provide smart, flexible, and well-reasoned answers. Do not mechanically repeat text; analyze what the customer is looking for and present the most relevant items, pricing, features, or solutions accurately.
    - If the customer asks to see photos, pictures, or videos of a property, item, or service, and a matching tag exists in Available Media Tags, you MUST include the token `[SEND_MEDIA:tag_name]` in your response (Note: Video support requires Tier 3 Enterprise).
    - If customers want to order, book, or purchase, warmly and professionally guide them to provide their name and phone number for fulfillment.
    
    Available Media Tags: {tags_str}
    
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
                model="openai/gpt-oss-120b",
                messages=messages,
                temperature=0.7,
                max_tokens=600
            )
            ai_reply = completion.choices[0].message.content
        except Exception as e:
            logger.error(f"Groq Chat Error: {e}")
            ai_reply = f"⚠️ Groq AI Error: {str(e)}"

    tag_match = re.search(r"\\\[SEND_MEDIA:([a-zA-Z0-9_\\-]+)\\\]", ai_reply)
    clean_ai_reply = re.sub(r"\\\[SEND_MEDIA:[a-zA-Z0-9_\\-]+\\\]", "", ai_reply).strip()

    if supabase:
        try:
            now_user = datetime.now(timezone.utc)
            now_assistant = now_user + timedelta(milliseconds=500)
            
            await asyncio.to_thread(lambda: supabase.table("chat_history").insert({
                "chat_id": str(chat_id), "bot_token": bot_token, "role": "user", "content": user_text, "created_at": now_user.isoformat()
            }).execute())
            
            await asyncio.to_thread(lambda: supabase.table("chat_history").insert({
                "chat_id": str(chat_id), "bot_token": bot_token, "role": "assistant", "content": clean_ai_reply, "created_at": now_assistant.isoformat()
            }).execute())
        except Exception as e:
            logger.error(f"Chat history insert error: {e}")

    asyncio.create_task(
        analyze_and_upsert_lead(
            bot_token=bot_token,
            chat_id=str(chat_id),
            visitor_name=visitor_name,
            user_text=user_text,
            history_messages=history_messages,
            inventory_data=inventory_data
        )
    )

    await http_client.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": clean_ai_reply}
    )

    if tag_match and supabase:
        requested_tag = tag_match.group(1).lower()
        try:
            media_rows = await asyncio.to_thread(
                lambda: supabase.table("property_media").select("*").eq("bot_token", bot_token).eq("item_tag", requested_tag).execute()
            )
            if media_rows.data:
                for item in media_rows.data:
                    file_id = item["file_id"]
                    media_type = item["media_type"]
                    caption = item.get("caption") or ""
                    if media_type == "photo":
                        await http_client.post(
                            f"https://api.telegram.org/bot{bot_token}/sendPhoto",
                            json={"chat_id": chat_id, "photo": file_id, "caption": caption}
                        )
                    elif media_type == "video":
                        if tier_capabilities["allows_videos"]:
                            await http_client.post(
                                f"https://api.telegram.org/bot{bot_token}/sendVideo",
                                json={"chat_id": chat_id, "video": file_id, "caption": caption}
                            )
                        else:
                            await http_client.post(
                                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                                json={"chat_id": chat_id, "text": "🔒 ቪዲዮዎችን ማየት የሚቻለው ለ Tier 3 (Enterprise) አባላት ብቻ ነው። እባክዎ መደብር ባለቤቱን ያነጋግሩ።"}
                            )
        except Exception as e:
            logger.error(f"Media dispatch error: {e}")

    return {"ok": True}


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
        PLAN_TIER: [
            CallbackQueryHandler(receive_plan_tier, pattern="^tier_"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_plan_tier)
        ],
        INVENTORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_inventory)],
        BOT_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bot_token)],
    },
    fallbacks=[CommandHandler("cancel", cancel_registration)],
)

telegram_app.add_handler(CommandHandler("start", start_command))
telegram_app.add_handler(CommandHandler("upgrade", upgrade_command))
telegram_app.add_handler(CommandHandler("pay", upgrade_command))
telegram_app.add_handler(CommandHandler("leads", leads_command))
telegram_app.add_handler(CommandHandler("update", update_command))
telegram_app.add_handler(CommandHandler("audit", audit_command))
telegram_app.add_handler(CommandHandler("summary", summary_command))
telegram_app.add_handler(CommandHandler("weekly_summary", weekly_summary_command))
telegram_app.add_handler(CommandHandler("mybots", my_bots_command))
telegram_app.add_handler(conv_handler)
telegram_app.add_handler(CallbackQueryHandler(button_handler))
telegram_app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO & filters.CaptionRegex(r"^/addmedia"), handle_media_upload))
telegram_app.add_handler(MessageHandler(filters.PHOTO, handle_receipt_photo))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_master_message))
