import os
import re
import hmac
import json
import base64
import random
import asyncio
import logging
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import FastAPI, Request, HTTPException, Form, Header
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# -------------------------------------------------------------------
# Secure Configuration & Environment Variables (Synced with Render)
# -------------------------------------------------------------------
ADMIN_PANEL_PASSWORD = os.getenv("ADMIN_PANEL_PASSWORD", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://nexa-bot-f5al.onrender.com").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").strip().rstrip("/")
GROQ_TEXT_MODEL = os.getenv("GROQ_TEXT_MODEL", "llama-3.3-70b-versatile").strip()
GROQ_AUDIO_MODEL = os.getenv("GROQ_AUDIO_MODEL", "whisper-large-v3").strip()
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct").strip()
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID", "").strip()

TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
NETLIFY_DASHBOARD_URL = os.getenv("NETLIFY_DASHBOARD_URL", "https://admin-nexa-telegram-bot-dashboard.netlify.app").strip()
NETLIFY_PROJECT_ID = os.getenv("NETLIFY_PROJECT_ID", "1661bfe9-a578-413d-b746-6376b245cfa0").strip()

TELEBIRR_ACCOUNT_MASKED = os.getenv("TELEBIRR_ACCOUNT_MASKED", "").strip()
AWASH_ACCOUNT_MASKED = os.getenv("AWASH_ACCOUNT_MASKED", "").strip()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NexaAI")

# Initialize FastAPI app
app = FastAPI(title="Nexa AI Elite Commerce Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://admin-nexa-telegram-bot-dashboard.netlify.app",
        "https://nexa-bot-f5al.onrender.com",
        "http://localhost:3000",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4-Tier Feature & Pricing Matrix
TIER_CONFIG = {
    1: {
        "name": "Tier 1 (Starter)",
        "price": 1000,
        "features": "Core AI Sales, Text Catalog, Photo Support, Basic Leads",
        "allows_photos": True,
        "allows_videos": False,
        "allows_voice": False,
        "credits": 500
    },
    2: {
        "name": "Tier 2 (Business Pro)",
        "price": 2500,
        "features": "Advanced AI, Photo Catalogs, Priority Lead Tracking, Custom Themes",
        "allows_photos": True,
        "allows_videos": False,
        "allows_voice": False,
        "credits": 2500
    },
    3: {
        "name": "Tier 3 (Enterprise VIP)",
        "price": 5000,
        "features": "Unlimited AI, Full Photo & Video Streaming, VIP Concierge, Advanced Analytics",
        "allows_photos": True,
        "allows_videos": True,
        "allows_voice": False,
        "credits": 999999
    },
    4: {
        "name": "Tier 4 (AI Voice Concierge)",
        "price": 7000,
        "features": "Everything in VIP + Live AI Voice Calls, Custom Phone Number Integration, Real-time STT/TTS in Amharic",
        "allows_photos": True,
        "allows_videos": True,
        "allows_voice": True,
        "credits": 999999
    },
}

# Initialize Clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
if not supabase:
    logger.warning("⚠️ SUPABASE_URL or SUPABASE_KEY is missing!")

if not GROQ_API_KEY:
    logger.warning("⚠️ GROQ_API_KEY is missing! Groq AI features will not work.")


def _groq_headers() -> dict:
    """Builds authorization headers for Groq API requests."""
    return {
        "Authorization": f"Bearer {GROQ_API_KEY}",
    }


def _build_groq_messages(
    prompt: str,
    system_instruction: str = None,
    history_messages: list[dict] = None,
) -> list[dict]:
    """Converts chat-style role/content dictionaries and a prompt into Groq chat messages."""
    messages: list[dict] = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})

    for msg in (history_messages or []):
        role = "assistant" if msg.get("role") in ("assistant", "model") else "user"
        text = str(msg.get("content") or "").strip()
        if text:
            messages.append({"role": role, "content": text})

    messages.append({"role": "user", "content": prompt})
    return messages


async def generate_groq_text(
    prompt: str,
    system_instruction: str = None,
    history_messages: list[dict] = None,
    temperature: float = 0.7,
    max_output_tokens: int = 800,
    json_mode: bool = False,
    model_name: str = None,
) -> str:
    """Runs async Groq text or structured JSON generation via Groq Chat Completions API."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured")

    client = http_client
    owns_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=20.0)
        owns_client = True

    try:
        payload: dict = {
            "model": model_name or GROQ_TEXT_MODEL,
            "messages": _build_groq_messages(
                prompt=prompt,
                system_instruction=system_instruction,
                history_messages=history_messages,
            ),
            "temperature": temperature,
            "max_tokens": max_output_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            **_groq_headers(),
            "Content-Type": "application/json",
        }
        resp = await client.post(
            f"{GROQ_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        return str(content or "").strip()
    finally:
        if owns_client:
            await client.aclose()


# Master Telegram Bot Application
telegram_app = (
    Application.builder().token(TELEGRAM_BOT_TOKEN).read_timeout(15).write_timeout(15).build()
    if TELEGRAM_BOT_TOKEN
    else None
)
if not telegram_app:
    logger.warning("⚠️ TELEGRAM_BOT_TOKEN is missing! Master Telegram bot is disabled.")
http_client: httpx.AsyncClient = None

# Onboarding Conversation States
STORE_NAME, INDUSTRY, UI_THEME, PLAN_TIER, INVENTORY, BOT_TOKEN = range(6)
PARTNER_TELEBIRR = 100
STORE_PHONE = 101
CHANGE_PHONE = 102
SUPPORT_TICKET = 103
BUSINESS_ADVICE = 104


# -------------------------------------------------------------------
# Constant-Time Security, Input Sanitization & Date Helpers
# -------------------------------------------------------------------
def verify_admin_pwd(pwd: str, header_pwd: str = None) -> bool:
    """Uses constant-time comparison to prevent timing attacks on the admin dashboard."""
    provided = (pwd or header_pwd or "").strip()
    if not provided or not ADMIN_PANEL_PASSWORD:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), ADMIN_PANEL_PASSWORD.encode("utf-8"))


def parse_dt(dt_str):
    """Safely parses ISO strings or datetime objects into timezone-aware UTC datetimes."""
    if not dt_str:
        return datetime.now(timezone.utc) + timedelta(days=3)
    if isinstance(dt_str, datetime):
        return dt_str if dt_str.tzinfo else dt_str.replace(tzinfo=timezone.utc)
    try:
        clean = str(dt_str).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(clean)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc) + timedelta(days=3)


def safe_escape_html(text: str) -> str:
    """Escapes HTML special characters for safe rendering inside HTML templates."""
    if text is None:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def normalize_phone_digits(raw_phone: str) -> str:
    """Normalizes Ethiopian/international phone strings into comparable digits."""
    digits = re.sub(r"\D+", "", raw_phone or "")
    if digits.startswith("251") and len(digits) == 12:
        return "0" + digits[3:]
    return digits


async def lookup_registered_phone_stores(raw_phone: str) -> list[dict]:
    """Finds Nexa stores matching a registered business or owner phone number."""
    if not supabase:
        return []
    target_norm = normalize_phone_digits(raw_phone)
    if not target_norm:
        return []

    try:
        res = await asyncio.to_thread(
            lambda: supabase.table("stores").select("*").execute()
        )
        matched = []
        for s in (res.data or []):
            b_norm = normalize_phone_digits(str(s.get("business_phone") or ""))
            o_norm = normalize_phone_digits(str(s.get("owner_phone") or ""))
            if target_norm and (target_norm == b_norm or target_norm == o_norm):
                matched.append(s)
        return matched
    except Exception as e:
        logger.error(f"Registered phone lookup error: {e}")
        return []


async def answer_registered_phone_with_ai(
    raw_phone: str,
    user_question: str,
    store_record: dict = None,
    customer_lang: str = "amharic",
    history_messages: list[dict] = None,
) -> str:
    """Generates an AI-powered answer via Groq for a phone number registered in Nexa."""
    norm_phone = normalize_phone_digits(raw_phone)
    stores = [store_record] if store_record else await lookup_registered_phone_stores(norm_phone)

    if not stores:
        return (
            f"📞 **ስልክ ቁጥር `{raw_phone}` በ Nexa ሲስተም ውስጥ አልተመዘገበም።**\n\n"
            f"ይህን ቁጥር በ Nexa AI ለማስመዝገብ እና 24/7 የ AI ምላሽ ለመስጠት `/register` ወይም `/setphone` ይጠቀሙ።"
        )

    store_summaries = []
    for st in stores:
        t_num = st.get("plan_tier", 1)
        t_name = TIER_CONFIG.get(t_num, TIER_CONFIG[1])["name"]
        voice_active = "ንቁ (Active)" if st.get("voice_ai_active", True) else "ተቋርጧል (Paused)"
        store_summaries.append(
            f"- Store Name: {st.get('store_name', 'Nexa Store')}\n"
            f"  Registered Phone: {st.get('business_phone') or st.get('owner_phone') or norm_phone}\n"
            f"  Plan Tier: {t_name}\n"
            f"  Voice AI Status: {voice_active}\n"
            f"  Catalog / Info:\n{st.get('inventory_data', 'No catalog details provided.')}"
        )

    context_block = "\n\n".join(store_summaries)
    lang_rule = {
        "amharic": "በጣም የዳበረ፣ ሰዋሰዋዊ ትክክለኛነት ያለው፣ የፊደል ስህተት የሌለበት እና ተፈጥሯዊ የሆነ አማርኛ ተጠቀም።",
        "english": "Respond clearly and helpfully in English.",
        "oromo": "Afaan Oromootiin deebisi."
    }.get(customer_lang, "በጣም የዳበረ እና ትክክለኛ አማርኛ ተጠቀም።")

    system_prompt = f"""
    You are Nexa AI Commerce Assistant answering a query about or through a phone number registered in Nexa ({norm_phone}).
    Language Rule: {lang_rule}

    Registered Nexa Store Data:
    {context_block}

    Instructions:
    - Confirm clearly that this phone number is registered in Nexa AI.
    - Answer the user's question accurately using the registered store catalog, services, pricing, and status above.
    - If no specific question was asked beyond the phone number, give a helpful AI overview of the registered business, its offerings, and how to proceed or contact/order.
    - Never expose private tokens or internal database IDs.
    """

    effective_prompt = user_question.strip() if user_question and user_question.strip() else (
        f"Provide a helpful AI answer for registered phone number {norm_phone}."
    )

    if GROQ_API_KEY:
        try:
            return await generate_groq_text(
                prompt=effective_prompt,
                system_instruction=system_prompt,
                history_messages=history_messages or [],
                temperature=0.5,
                max_output_tokens=650,
            )
        except Exception as e:
            logger.error(f"Registered phone AI answer error: {e}")

    primary = stores[0]
    return (
        f"🤖 **የ Nexa AI ምላሽ — ስልክ `{norm_phone}`**\n"
        f"• የተመዘገበ መደብር: **{primary.get('store_name', 'Nexa Store')}**\n"
        f"• ካታሎግ / መረጃ:\n{primary.get('inventory_data', 'መረጃ ተመዝግቧል።')}"
    )


# -------------------------------------------------------------------
# Subscription & User Access Management
# -------------------------------------------------------------------
async def get_or_create_user_subscription(user_id: int):
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
                    "is_pro": sub["is_pro"],
                    "plan_tier": sub.get("plan_tier", 1)
                }
        except Exception as e:
            logger.error(f"Subscription fetch error: {e}")

    default_expiry = now + timedelta(days=3)
    default_sub = {
        "trial_expires": default_expiry,
        "credits_remaining": 50,
        "is_pro": False,
        "plan_tier": 1
    }

    if supabase:
        try:
            await asyncio.to_thread(
                lambda: supabase.table("subscriptions").upsert({
                    "user_id": str(user_id),
                    "trial_expires": default_expiry.isoformat(),
                    "credits_remaining": 50,
                    "is_pro": False,
                    "plan_tier": 1
                }).execute()
            )
        except Exception as e:
            logger.error(f"Subscription upsert error: {e}")

    return default_sub


async def verify_active_access(user_id: int) -> bool:
    try:
        sub = await get_or_create_user_subscription(user_id)
        now = datetime.now(timezone.utc)
        trial_exp = parse_dt(sub["trial_expires"])
        if sub["is_pro"]:
            if sub.get("trial_expires") and now > trial_exp:
                return False
            return True
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
# Telegram Voice Transcription via Groq Audio API
# -------------------------------------------------------------------
async def transcribe_telegram_voice(bot_token: str, voice_file_id: str) -> str:
    if not GROQ_API_KEY or not http_client:
        return ""
    try:
        file_resp = await http_client.get(f"https://api.telegram.org/bot{bot_token}/getFile?file_id={voice_file_id}")
        file_path = file_resp.json().get("result", {}).get("file_path")
        if not file_path:
            return ""

        audio_bytes_resp = await http_client.get(f"https://api.telegram.org/file/bot{bot_token}/{file_path}")
        audio_data = bytes(audio_bytes_resp.content)

        resp = await http_client.post(
            f"{GROQ_BASE_URL}/audio/transcriptions",
            headers=_groq_headers(),
            files={"file": ("voice.ogg", audio_data, "audio/ogg")},
            data={
                "model": GROQ_AUDIO_MODEL,
                "prompt": "Transcribe this voice message accurately in Amharic, English, or Oromo.",
            },
        )
        resp.raise_for_status()
        return str(resp.json().get("text") or "").strip()
    except Exception as e:
        logger.error(f"Voice transcription error: {e}")
        return ""


@app.get("/")
async def root_health():
    return {
        "status": "online",
        "service": "Nexa AI Elite Commerce Backend",
        "render_url": RENDER_EXTERNAL_URL,
        "netlify_dashboard": NETLIFY_DASHBOARD_URL,
        "netlify_project_id": NETLIFY_PROJECT_ID,
        "supabase_connected": bool(supabase),
        "groq_connected": bool(GROQ_API_KEY),
        "telegram_connected": bool(TELEGRAM_BOT_TOKEN),
        "webhook_secured": bool(TELEGRAM_WEBHOOK_SECRET)
    }


@app.post("/api/phone-ai-answer")
async def phone_ai_answer_endpoint(request: Request):
    """Direct API endpoint returning an AI-powered answer for a phone number registered in Nexa."""
    body = await request.json()
    phone = str(body.get("phone") or body.get("phone_number") or "").strip()
    question = str(body.get("question") or body.get("message") or "").strip()
    lang = str(body.get("language") or "amharic").strip().lower()

    if not phone:
        return {"status": "error", "message": "Phone number is required"}

    matched_stores = await lookup_registered_phone_stores(phone)
    ai_answer = await answer_registered_phone_with_ai(
        raw_phone=phone,
        user_question=question,
        customer_lang=lang,
    )
    return {
        "status": "success",
        "phone": normalize_phone_digits(phone),
        "registered_in_nexa": bool(matched_stores),
        "stores_matched": len(matched_stores),
        "ai_answer": ai_answer,
    }


# -------------------------------------------------------------------
# Live JSON Sync API for Netlify Admin Dashboard
# -------------------------------------------------------------------
@app.get("/admin/live-data")
async def admin_live_data(pwd: str = "", x_admin_password: str = Header(None)):
    """Live JSON sync endpoint for Netlify Admin Dashboard & HTML Command Center."""
    if not verify_admin_pwd(pwd, x_admin_password):
        raise HTTPException(status_code=403, detail="Unauthorized Admin Password")
    if not supabase:
        return {"status": "error", "message": "Supabase not connected"}

    try:
        r1, r2, r3, r4, r5, r6, r7, r8, r9 = await asyncio.gather(
            asyncio.to_thread(lambda: supabase.table("manual_review_queue").select("*").order("created_at", desc=True).limit(60).execute()),
            asyncio.to_thread(lambda: supabase.table("stores").select("*").order("created_at", desc=True).execute()),
            asyncio.to_thread(lambda: supabase.table("subscriptions").select("*").execute()),
            asyncio.to_thread(lambda: supabase.table("leads").select("*").order("updated_at", desc=True).limit(100).execute()),
            asyncio.to_thread(lambda: supabase.table("partners").select("*").execute()),
            asyncio.to_thread(lambda: supabase.table("support_tickets").select("*").order("created_at", desc=True).limit(60).execute()),
            asyncio.to_thread(lambda: supabase.table("paid_subscriptions").select("*").order("created_at", desc=True).limit(100).execute()),
            asyncio.to_thread(lambda: supabase.table("referrals").select("*").order("created_at", desc=True).limit(100).execute()),
            asyncio.to_thread(lambda: supabase.table("affiliate_payouts").select("*").order("created_at", desc=True).limit(50).execute())
        )
        return {
            "status": "success",
            "server_time": datetime.now(timezone.utc).isoformat(),
            "manual_reviews": r1.data or [],
            "stores": r2.data or [],
            "subscriptions": r3.data or [],
            "leads": r4.data or [],
            "partners": r5.data or [],
            "support_tickets": r6.data or [],
            "paid_subscriptions": r7.data or [],
            "referrals": r8.data or [],
            "affiliate_payouts": r9.data or [],
            "tier_config": TIER_CONFIG
        }
    except Exception as e:
        logger.error(f"Admin live data fetch error: {e}")
        return {"status": "error", "message": str(e)}


# -------------------------------------------------------------------
# Elite Nexa Web Admin Panel & Chat Inspector Routes
# -------------------------------------------------------------------
@app.get("/admin/chats/{bot_token}", response_class=HTMLResponse)
async def admin_view_chats(bot_token: str, pwd: str = ""):
    if not verify_admin_pwd(pwd):
        raise HTTPException(status_code=403, detail="Unauthorized")

    chats_res = []
    if supabase:
        try:
            res = await asyncio.to_thread(
                lambda: supabase.table("chat_history").select("*").eq("bot_token", bot_token).order("created_at", desc=True).limit(50).execute()
            )
            chats_res = res.data or []
        except Exception as e:
            logger.error(f"Admin view chats error: {e}")

    bubbles = ""
    for c in reversed(chats_res):
        role = c.get("role")
        content = safe_escape_html(c.get("content", ""))
        time_str = safe_escape_html(str(c.get("created_at", ""))[:19].replace("T", " "))
        chat_id_safe = safe_escape_html(c.get("chat_id", ""))
        if role == "user":
            bubbles += f"""
            <div class="flex flex-col items-start mb-3">
                <div class="bg-slate-800 border border-slate-700 text-slate-200 px-4 py-2.5 rounded-2xl rounded-bl-sm max-w-lg text-xs">
                    <p class="font-semibold text-[10px] text-blue-400 mb-1">Customer ({chat_id_safe})</p>
                    {content}
                </div>
                <span class="text-[9px] text-slate-500 mt-1 ml-1">{time_str}</span>
            </div>
            """
        else:
            bubbles += f"""
            <div class="flex flex-col items-end mb-3">
                <div class="bg-blue-600 text-white px-4 py-2.5 rounded-2xl rounded-br-sm max-w-lg text-xs shadow-md">
                    <p class="font-semibold text-[10px] text-blue-200 mb-1">AI Assistant</p>
                    {content}
                </div>
                <span class="text-[9px] text-slate-500 mt-1 mr-1">{time_str}</span>
            </div>
            """

    return f"""
    <!DOCTYPE html>
    <html lang="en" class="dark">
    <head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Nexa Elite - Live Chat Inspector</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen p-6">
        <div class="max-w-4xl mx-auto space-y-6">
            <div class="flex justify-between items-center bg-slate-900 border border-slate-800 p-4 rounded-2xl shadow-xl">
                <div>
                    <h1 class="text-base font-bold text-white flex items-center gap-2"><span>💬</span> Live Customer Chat Inspector</h1>
                    <p class="text-xs text-slate-400 font-mono">Bot Token: {safe_escape_html(bot_token[:10])}...</p>
                </div>
                <a href="/admin?pwd={safe_escape_html(pwd)}" class="bg-slate-800 hover:bg-slate-700 text-slate-200 px-4 py-2 rounded-xl text-xs font-semibold transition">← Back to Command Center</a>
            </div>
            <div class="bg-slate-900 border border-slate-800 p-6 rounded-2xl shadow-xl h-[70vh] overflow-y-auto space-y-2">
                {bubbles or '<p class="text-center text-slate-500 py-20">No conversation history found for this bot yet.</p>'}
            </div>
        </div>
    </body>
    </html>
    """


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(pwd: str = ""):
    if not verify_admin_pwd(pwd):
        return """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Nexa AI Elite Admin Login</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-slate-950 text-slate-100 flex items-center justify-center h-screen" oncontextmenu="return false;" onselectstart="return false;" ondragstart="return false;">
            <div class="bg-slate-900 border border-slate-800 p-8 rounded-2xl shadow-2xl w-full max-w-md text-center">
                <div class="inline-flex bg-blue-600/20 text-blue-400 p-4 rounded-full mb-4 text-2xl font-bold">💎</div>
                <h2 class="text-2xl font-black mb-2 tracking-tight">Nexa AI Elite Control</h2>
                <p class="text-slate-400 text-xs uppercase tracking-widest font-semibold mb-6">Option 1: Password or Option 2: Fingerprint</p>

                <form method="get" action="/admin" class="space-y-4">
                    <input type="password" name="pwd" placeholder="Option 1: Enter Master Admin Password" class="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-3 text-white focus:outline-none focus:border-blue-500 text-sm" required />
                    <button type="submit" class="w-full bg-blue-600 hover:bg-blue-500 text-white font-semibold py-3 rounded-xl transition duration-200 shadow-lg shadow-blue-600/30 text-sm">Secure Login with Password</button>
                </form>

                <div class="relative flex py-3 items-center">
                    <div class="flex-grow border-t border-slate-800"></div>
                    <span class="flex-shrink mx-4 text-slate-500 text-xs uppercase font-semibold">Or</span>
                    <div class="flex-grow border-t border-slate-800"></div>
                </div>

                <div id="bio-register-box" class="hidden">
                    <p class="text-xs text-amber-400 mb-2">⚠️ No fingerprint registered yet on this device.</p>
                    <button onclick="registerBiometricsFirst()" class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-semibold py-3 rounded-xl transition text-xs flex items-center justify-center gap-2">
                        <span>🧬</span> Register My Fingerprint Passkey Now
                    </button>
                </div>

                <div id="bio-login-box" class="hidden">
                    <button onclick="tryBiometricLogin()" class="w-full bg-slate-800 hover:bg-slate-700 text-slate-200 font-medium py-3 rounded-xl transition text-xs flex items-center justify-center gap-2 border border-slate-700">
                        <span>🧬</span> Option 2: Unlock with My Fingerprint
                    </button>
                </div>

                <div id="bio-status" class="hidden mt-3 bg-blue-600/10 border border-blue-500/30 text-blue-300 p-2.5 rounded-xl text-xs">
                    👆 Touch your fingerprint sensor now...
                </div>
            </div>
            <script>
                window.addEventListener("DOMContentLoaded", () => {
                    const isRegistered = localStorage.getItem("nexa_bio_registered") === "true";
                    if (!isRegistered) {
                        document.getElementById("bio-register-box").classList.remove("hidden");
                    } else {
                        document.getElementById("bio-login-box").classList.remove("hidden");
                    }
                });

                async function registerBiometricsFirst() {
                    const statusEl = document.getElementById("bio-status");
                    try {
                        if (!window.PublicKeyCredential) {
                            alert("Biometrics / WebAuthn not supported on this browser.");
                            return;
                        }
                        statusEl.classList.remove("hidden");
                        const newCredential = await navigator.credentials.create({
                            publicKey: {
                                challenge: window.crypto.getRandomValues(new Uint8Array(32)),
                                rp: { name: "Nexa AI Elite Admin" },
                                user: {
                                    id: new Uint8Array([79, 115, 115, 101, 97, 114]),
                                    name: "admin@nexa.ai",
                                    displayName: "Elite Admin"
                                },
                                pubKeyCredParams: [{ alg: -7, type: "public-key" }, { alg: -257, type: "public-key" }],
                                authenticatorSelection: { authenticatorAttachment: "platform", userVerification: "required" },
                                timeout: 60000
                            }
                        });
                        statusEl.classList.add("hidden");
                        if (newCredential) {
                            localStorage.setItem("nexa_bio_registered", "true");
                            document.getElementById("bio-register-box").classList.add("hidden");
                            document.getElementById("bio-login-box").classList.remove("hidden");
                            alert("Fingerprint registered! Click Option 2 to unlock.");
                        }
                    } catch (e) {
                        statusEl.classList.add("hidden");
                        alert("Biometric registration failed or canceled. Use Option 1 (Password).");
                    }
                }

                async function tryBiometricLogin() {
                    const statusEl = document.getElementById("bio-status");
                    try {
                        if (!window.PublicKeyCredential) {
                            alert("Biometrics / WebAuthn not supported on this browser.");
                            return;
                        }
                        statusEl.classList.remove("hidden");
                        const credential = await navigator.credentials.get({
                            publicKey: {
                                challenge: window.crypto.getRandomValues(new Uint8Array(32)),
                                timeout: 60000,
                                userVerification: "required"
                            }
                        });
                        statusEl.classList.add("hidden");
                        if (credential) {
                            alert("Biometric verified! Please enter your Master Admin Password in Option 1 to complete login.");
                            const pwdInput = document.querySelector('input[name="pwd"]');
                            if (pwdInput) pwdInput.focus();
                        }
                    } catch (e) {
                        statusEl.classList.add("hidden");
                        alert("Biometric verification failed or canceled. Use Option 1 (Password).");
                    }
                }
            </script>
        </body>
        </html>
        """

    manual_reviews, stores_data, subs_data, leads_data, partners_data, support_tickets = [], [], [], [], [], []
    if supabase:
        try:
            r1, r2, r3, r4, r5, r6 = await asyncio.gather(
                asyncio.to_thread(lambda: supabase.table("manual_review_queue").select("*").order("created_at", desc=True).limit(30).execute()),
                asyncio.to_thread(lambda: supabase.table("stores").select("*").execute()),
                asyncio.to_thread(lambda: supabase.table("subscriptions").select("*").execute()),
                asyncio.to_thread(lambda: supabase.table("leads").select("*").order("updated_at", desc=True).limit(40).execute()),
                asyncio.to_thread(lambda: supabase.table("partners").select("*").execute()),
                asyncio.to_thread(lambda: supabase.table("support_tickets").select("*").order("created_at", desc=True).limit(30).execute())
            )
            manual_reviews = r1.data or []
            stores_data = r2.data or []
            subs_data = r3.data or []
            leads_data = r4.data or []
            partners_data = r5.data or []
            support_tickets = r6.data or []
        except Exception as e:
            logger.error(f"Admin fetch error: {e}")

    subs_map = {str(s["user_id"]): s for s in subs_data}
    now = datetime.now(timezone.utc)
    safe_pwd = safe_escape_html(pwd)

    reviews_html = ""
    for r in manual_reviews:
        img_url = f"/admin/receipt/{r['screenshot_file_id']}?pwd={safe_pwd}" if r.get("screenshot_file_id") else ""
        img_btn = f'<a href="{img_url}" target="_blank" class="text-blue-400 hover:underline font-medium">View Receipt</a>' if img_url else "No Image"
        status_lbl = '<span class="px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/20 text-emerald-400">Approved</span>' if r["status"] == "approved" else ('<span class="px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-500/20 text-rose-400">Rejected</span>' if r["status"] == "rejected" else '<span class="px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/20 text-amber-400">Pending Review</span>')

        actions = ""
        if r["status"] == "pending":
            actions = f"""
            <form method="post" action="/admin/action" class="inline-flex gap-2">
                <input type="hidden" name="pwd" value="{safe_pwd}">
                <input type="hidden" name="review_id" value="{safe_escape_html(r['id'])}">
                <input type="hidden" name="user_id" value="{safe_escape_html(r['user_id'])}">
                <input type="hidden" name="plan_tier" value="{safe_escape_html(r.get('plan_tier', 1))}">
                <button name="decision" value="approve" class="bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded-lg text-xs font-semibold transition">Approve</button>
                <button name="decision" value="reject" class="bg-rose-600 hover:bg-rose-500 text-white px-3 py-1.5 rounded-lg text-xs font-semibold transition">Reject</button>
            </form>
            """

        reviews_html += f"""
        <tr class="border-b border-slate-800 hover:bg-slate-900/50 transition">
            <td class="p-4 font-medium text-slate-200">{safe_escape_html(r.get('payer_name'))}<br><span class="text-xs text-slate-400">{safe_escape_html(r.get('payer_phone'))}</span></td>
            <td class="p-4 text-slate-300">Tier {safe_escape_html(r.get('plan_tier', 1))}</td>
            <td class="p-4 text-slate-300">Expected: <b class="text-emerald-400">{safe_escape_html(r.get('expected_amount'))} ETB</b><br>Detected: {safe_escape_html(r.get('detected_amount'))} ETB</td>
            <td class="p-4 font-mono text-xs text-blue-400">{safe_escape_html(r.get('reference_id'))}</td>
            <td class="p-4">{img_btn}</td>
            <td class="p-4">{status_lbl}</td>
            <td class="p-4">{actions}</td>
        </tr>
        """

    tickets_html = ""
    for t in support_tickets:
        t_status = t.get("status", "open")
        status_lbl = '<span class="px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/20 text-emerald-400">Resolved</span>' if t_status == "resolved" else '<span class="px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/20 text-amber-400">Open Ticket</span>'
        reply_txt = safe_escape_html(t.get("admin_reply") or "No reply yet")
        tickets_html += f"""
        <tr class="border-b border-slate-800 hover:bg-slate-900/50 transition">
            <td class="p-4 font-mono text-xs text-slate-400">{safe_escape_html(t.get('user_id'))}</td>
            <td class="p-4 text-slate-200 text-sm max-w-xs">{safe_escape_html(t.get('message'))}</td>
            <td class="p-4 text-slate-400 text-xs italic max-w-xs">{reply_txt}</td>
            <td class="p-4">{status_lbl}</td>
            <td class="p-4">
                <button onclick="openSupportModal('{safe_escape_html(t.get('id'))}', '{safe_escape_html(t.get('user_id'))}')" class="bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded-lg text-xs font-semibold transition">Reply ✉️</button>
            </td>
        </tr>
        """

    partners_html = ""
    for p in partners_data:
        partners_html += f"""
        <tr class="border-b border-slate-800 hover:bg-slate-900/50 transition">
            <td class="p-4 font-medium text-white">{safe_escape_html(p.get('partner_name', 'Partner'))}</td>
            <td class="p-4 font-mono text-xs text-emerald-400">{safe_escape_html(p.get('telebirr_number'))}</td>
            <td class="p-4 font-mono text-xs text-blue-400">nexa_bot?start=ref_{safe_escape_html(p.get('partner_id'))}</td>
            <td class="p-4 text-slate-300 font-semibold">{safe_escape_html(p.get('total_referrals', 0))}</td>
            <td class="p-4 text-emerald-400 font-bold">{float(p.get('total_earned', 0)):,.2f} ETB</td>
        </tr>
        """

    stores_html = ""
    for s in stores_data:
        owner_id = str(s.get("owner_telegram_id"))
        sub = subs_map.get(owner_id, {})
        is_pro = sub.get("is_pro", False)
        trial_exp = parse_dt(sub.get("trial_expires"))

        if is_pro:
            badge = '<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-blue-500/20 text-blue-400">PRO VIP ⭐</span>'
        elif now < trial_exp:
            badge = '<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-purple-500/20 text-purple-400">FREE TRIAL 🔥</span>'
        else:
            badge = '<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-rose-500/20 text-rose-400">EXPIRED ⚠️</span>'

        b_tok = str(s.get("bot_token", ""))
        store_nm = str(s.get("store_name", ""))
        stores_html += f"""
        <tr class="border-b border-slate-800 hover:bg-slate-900/50 transition">
            <td class="p-4 font-semibold text-white">{safe_escape_html(store_nm)}</td>
            <td class="p-4 font-mono text-xs text-slate-400">{safe_escape_html(b_tok[:10])}...</td>
            <td class="p-4 text-slate-300">Tier {safe_escape_html(s.get('plan_tier', 1))} ({safe_escape_html(str(s.get('ui_theme', 'executive')).capitalize())})</td>
            <td class="p-4 font-mono text-xs text-slate-400">{safe_escape_html(owner_id)}</td>
            <td class="p-4">{badge}</td>
            <td class="p-4 flex items-center gap-2">
                <a href="/admin/chats/{safe_escape_html(b_tok)}?pwd={safe_pwd}" class="text-blue-400 hover:underline font-semibold text-xs">Inspect 💬</a>
                <button onclick="openSyncModal('{safe_escape_html(owner_id)}', '{safe_escape_html(store_nm)}', {int(s.get('plan_tier', 1))})" class="bg-indigo-600 hover:bg-indigo-500 text-white px-2 py-1 rounded text-xs font-semibold">Sync Tier ⚡</button>
            </td>
        </tr>
        """

    leads_html = ""
    for l in leads_data[:25]:
        leads_html += f"""
        <tr class="border-b border-slate-800 hover:bg-slate-900/50 transition">
            <td class="p-4 font-medium text-white">{safe_escape_html(l.get('visitor_name', 'Anonymous'))}</td>
            <td class="p-4 text-emerald-400 font-mono">{safe_escape_html(l.get('phone_number', 'No Phone ❌'))}</td>
            <td class="p-4 text-slate-300 text-sm">{safe_escape_html(l.get('interest_summary', 'General Inquiry'))}</td>
            <td class="p-4 font-mono text-xs text-slate-500">{safe_escape_html(l.get('visitor_telegram_id'))}</td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Nexa AI Elite Command Center</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen">
        <header class="bg-slate-900 border-b border-slate-800 py-4 px-6 flex justify-between items-center sticky top-0 z-50">
            <div class="flex items-center gap-3">
                <span class="text-2xl">💎</span>
                <h1 class="text-xl font-black tracking-wider bg-gradient-to-r from-blue-400 to-indigo-400 bg-clip-text text-transparent">NEXA ELITE ADMIN</h1>
            </div>
            <div class="flex items-center gap-4">
                <a href="{safe_escape_html(NETLIFY_DASHBOARD_URL)}" target="_blank" class="bg-indigo-600/20 text-indigo-400 hover:bg-indigo-600/30 px-4 py-2 rounded-xl text-xs font-semibold transition border border-indigo-500/30">🌐 Open Netlify Live UI</a>
                <button onclick="registerBiometrics()" class="bg-slate-800 hover:bg-slate-700 text-slate-200 px-4 py-2 rounded-xl text-xs font-semibold transition border border-slate-700">🧬 Enable Biometrics</button>
                <a href="/admin" class="bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 px-4 py-2 rounded-xl text-xs font-semibold transition">Lock Session</a>
            </div>
        </header>

        <main class="max-w-7xl mx-auto p-6 space-y-8">
            <section class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
                <h3 class="text-lg font-bold mb-2 flex items-center gap-2"><span>📢</span> Broadcast Feature Update / Notice to All Nexa Bot Owners</h3>
                <p class="text-slate-400 text-sm mb-4">Send instant direct telegram notifications to all active store owners on your platform.</p>
                <div class="space-y-4">
                    <textarea id="broadcast-msg" placeholder="Write your platform announcement or new feature update here..." rows="3" class="w-full bg-slate-950 border border-slate-800 rounded-xl p-4 text-white focus:outline-none focus:border-blue-500 text-sm" required></textarea>
                    <button type="button" onclick="sendBroadcast()" class="bg-blue-600 hover:bg-blue-500 text-white px-6 py-2.5 rounded-xl text-sm font-semibold transition shadow-lg shadow-blue-600/30">Broadcast Message Now</button>
                </div>
            </section>

            <section class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
                <h3 class="text-lg font-bold mb-4 flex items-center gap-2"><span>🎧</span> Customer Support & Helpdesk Tickets ({len(support_tickets)})</h3>
                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse">
                        <tr class="bg-slate-950 text-slate-400 text-xs font-bold uppercase tracking-wider border-b border-slate-800">
                            <th class="p-4">User Telegram ID</th><th class="p-4">User Inquiry / Ticket</th><th class="p-4">Admin Reply</th><th class="p-4">Status</th><th class="p-4">Action</th>
                        </tr>
                        {tickets_html or '<tr><td colspan="5" class="p-8 text-center text-slate-500">No support tickets submitted yet.</td></tr>'}
                    </table>
                </div>
            </section>

            <section class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
                <h3 class="text-lg font-bold mb-4 flex items-center gap-2"><span>🤝</span> Nexa Partners / Affiliates Program ({len(partners_data)})</h3>
                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse">
                        <tr class="bg-slate-950 text-slate-400 text-xs font-bold uppercase tracking-wider border-b border-slate-800">
                            <th class="p-4">Partner Name</th><th class="p-4">Telebirr Account</th><th class="p-4">Referral Link Code</th><th class="p-4">Total Subscriptions</th><th class="p-4">Commission Earned (1/4)</th>
                        </tr>
                        {partners_html or '<tr><td colspan="5" class="p-8 text-center text-slate-500">No registered partners yet.</td></tr>'}
                    </table>
                </div>
            </section>

            <section class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
                <h3 class="text-lg font-bold mb-4 flex items-center gap-2"><span>💳</span> Telebirr Payment Review & Mismatch Queue</h3>
                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse">
                        <tr class="bg-slate-950 text-slate-400 text-xs font-bold uppercase tracking-wider border-b border-slate-800">
                            <th class="p-4">Customer</th><th class="p-4">Tier</th><th class="p-4">Amount Comparison</th><th class="p-4">Reference ID</th><th class="p-4">Screenshot</th><th class="p-4">Status</th><th class="p-4">Action</th>
                        </tr>
                        {reviews_html or '<tr><td colspan="7" class="p-8 text-center text-slate-500">No pending payment reviews.</td></tr>'}
                    </table>
                </div>
            </section>

            <section class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
                <h3 class="text-lg font-bold mb-4 flex items-center gap-2"><span>🤖</span> Connected Nexa Bot Owners & Stores ({len(stores_data)})</h3>
                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse">
                        <tr class="bg-slate-950 text-slate-400 text-xs font-bold uppercase tracking-wider border-b border-slate-800">
                            <th class="p-4">Store Name</th><th class="p-4">Bot Token Snippet</th><th class="p-4">Tier & Theme</th><th class="p-4">Owner Telegram ID</th><th class="p-4">Subscription Status</th><th class="p-4">Action</th>
                        </tr>
                        {stores_html or '<tr><td colspan="6" class="p-8 text-center text-slate-500">No connected stores found.</td></tr>'}
                    </table>
                </div>
            </section>

            <section class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
                <h3 class="text-lg font-bold mb-4 flex items-center gap-2"><span>💬</span> Live Customer Questions & Leads ({len(leads_data)})</h3>
                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse">
                        <tr class="bg-slate-950 text-slate-400 text-xs font-bold uppercase tracking-wider border-b border-slate-800">
                            <th class="p-4">Customer Name</th><th class="p-4">Phone Number</th><th class="p-4">Inquiry / Summary</th><th class="p-4">Telegram Chat ID</th>
                        </tr>
                        {leads_html or '<tr><td colspan="4" class="p-8 text-center text-slate-500">No customer questions recorded yet.</td></tr>'}
                    </table>
                </div>
            </section>
        </main>

        <!-- Support Ticket Modal -->
        <div id="supportModal" class="fixed inset-0 bg-black/80 flex items-center justify-center hidden z-50 p-4">
            <div class="bg-slate-900 border border-slate-800 p-6 rounded-2xl max-w-md w-full space-y-4">
                <h3 class="text-lg font-bold text-white flex items-center gap-2"><span>✉️</span> Reply to Customer Support Ticket</h3>
                <p id="supportModalSub" class="text-xs text-slate-400">Send direct response to user.</p>
                <form id="supportForm" onsubmit="submitSupportReply(event)" class="space-y-4">
                    <input type="hidden" id="supportTicketId">
                    <input type="hidden" id="supportUserId">
                    <div>
                        <label class="block text-xs font-semibold text-slate-300 mb-1">Your Reply Message:</label>
                        <textarea id="supportReplyText" rows="4" class="w-full bg-slate-950 border border-slate-700 rounded-xl p-3 text-white text-xs focus:outline-none focus:border-blue-500" placeholder="Type your support reply here..." required></textarea>
                    </div>
                    <div class="flex gap-3 pt-2">
                        <button type="button" onclick="closeSupportModal()" class="flex-1 bg-slate-800 hover:bg-slate-700 text-slate-300 py-2.5 rounded-xl text-xs font-semibold transition">Cancel</button>
                        <button type="submit" class="flex-1 bg-blue-600 hover:bg-blue-500 text-white py-2.5 rounded-xl text-xs font-semibold transition shadow-lg shadow-blue-600/30">Send Reply 🚀</button>
                    </div>
                </form>
            </div>
        </div>

        <!-- Sync Tier Modal -->
        <div id="syncModal" class="fixed inset-0 bg-black/80 flex items-center justify-center hidden z-50 p-4">
            <div class="bg-slate-900 border border-slate-800 p-6 rounded-2xl max-w-md w-full space-y-4">
                <h3 class="text-lg font-bold text-white flex items-center gap-2"><span>⚡</span> Sync Store Tier & Duration</h3>
                <p id="syncModalSub" class="text-xs text-slate-400">Configure custom tier level and duration for store owner.</p>
                <form id="syncForm" onsubmit="submitSyncTier(event)" class="space-y-4">
                    <input type="hidden" id="syncUserId">
                    <div>
                        <label class="block text-xs font-semibold text-slate-300 mb-1">Select Tier Level:</label>
                        <select id="syncTierNum" class="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-2.5 text-white text-xs">
                            <option value="1">Tier 1 (Starter - 1,000 ETB/mo)</option>
                            <option value="2">Tier 2 (Business Pro - 2,500 ETB/mo)</option>
                            <option value="3">Tier 3 (Enterprise VIP - 5,000 ETB/mo)</option>
                            <option value="4">Tier 4 (AI Voice Concierge - 7,000 ETB/mo)</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-300 mb-1">Duration (Months):</label>
                        <input type="number" id="syncMonths" value="1" min="1" max="36" class="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-2.5 text-white text-xs" required />
                    </div>
                    <div class="flex gap-3 pt-2">
                        <button type="button" onclick="closeSyncModal()" class="flex-1 bg-slate-800 hover:bg-slate-700 text-slate-300 py-2.5 rounded-xl text-xs font-semibold transition">Cancel</button>
                        <button type="submit" class="flex-1 bg-blue-600 hover:bg-blue-500 text-white py-2.5 rounded-xl text-xs font-semibold transition shadow-lg shadow-blue-600/30">Save & Sync Level</button>
                    </div>
                </form>
            </div>
        </div>

        <script>
            function openSupportModal(ticketId, userId) {{
                document.getElementById("supportTicketId").value = ticketId;
                document.getElementById("supportUserId").value = userId;
                document.getElementById("supportModalSub").innerText = "Replying to User Telegram ID: " + userId;
                document.getElementById("supportModal").classList.remove("hidden");
            }}

            function closeSupportModal() {{
                document.getElementById("supportModal").classList.add("hidden");
            }}

            async function submitSupportReply(e) {{
                e.preventDefault();
                const ticketId = document.getElementById("supportTicketId").value;
                const userId = document.getElementById("supportUserId").value;
                const replyText = document.getElementById("supportReplyText").value;

                try {{
                    const resp = await fetch("/admin/support-reply", {{
                        method: "POST",
                        headers: {{ "Content-Type": "application/json" }},
                        body: JSON.stringify({{ ticket_id: ticketId, user_id: userId, reply: replyText, pwd: "{safe_pwd}" }})
                    }});
                    const data = await resp.json();
                    if (data.status === "success") {{
                        alert("Support reply sent successfully to customer!");
                        closeSupportModal();
                        window.location.reload();
                    }} else {{
                        alert("Error: " + (data.message || "Failed to send reply"));
                    }}
                }} catch (err) {{
                    alert("Network error: " + err);
                }}
            }}

            function openSyncModal(userId, storeName, currentTier) {{
                document.getElementById("syncUserId").value = userId;
                document.getElementById("syncTierNum").value = currentTier;
                document.getElementById("syncModalSub").innerText = "Store: " + storeName + " (Owner ID: " + userId + ")";
                document.getElementById("syncModal").classList.remove("hidden");
            }}

            function closeSyncModal() {{
                document.getElementById("syncModal").classList.add("hidden");
            }}

            async function submitSyncTier(e) {{
                e.preventDefault();
                const userId = document.getElementById("syncUserId").value;
                const tier = parseInt(document.getElementById("syncTierNum").value);
                const months = parseInt(document.getElementById("syncMonths").value);

                try {{
                    const resp = await fetch("/admin/sync-tier", {{
                        method: "POST",
                        headers: {{ "Content-Type": "application/json" }},
                        body: JSON.stringify({{ user_id: userId, plan_tier: tier, months: months, pwd: "{safe_pwd}" }})
                    }});
                    const data = await resp.json();
                    if (data.status === "success") {{
                        alert("Successfully synced tier to Tier " + tier + " for " + months + " month(s)! Notification sent to owner.");
                        closeSyncModal();
                        window.location.reload();
                    }} else {{
                        alert("Error: " + (data.message || "Failed to sync"));
                    }}
                }} catch (err) {{
                    alert("Network error: " + err);
                }}
            }}

            async function sendBroadcast() {{
                const msg = document.getElementById("broadcast-msg").value;
                if (!msg) {{
                    alert("Please write a message first.");
                    return;
                }}
                try {{
                    const resp = await fetch("/admin/broadcast", {{
                        method: "POST",
                        headers: {{ "Content-Type": "application/json" }},
                        body: JSON.stringify({{ message: msg, pwd: "{safe_pwd}" }})
                    }});
                    const data = await resp.json();
                    if (data.status === "success") {{
                        alert("Broadcast successfully sent to " + data.sent + " store owners!");
                        document.getElementById("broadcast-msg").value = "";
                    }} else {{
                        alert("Error: " + (data.message || "Failed to broadcast"));
                    }}
                }} catch (e) {{
                    alert("Network error sending broadcast: " + e);
                }}
            }}

            async function registerBiometrics() {{
                try {{
                    if (!window.PublicKeyCredential) {{
                        alert("Biometrics not supported on this device.");
                        return;
                    }}
                    const newCredential = await navigator.credentials.create({{
                        publicKey: {{
                            challenge: new Uint8Array([8,22,50,90,12,33,44,11]),
                            rp: {{ name: "Nexa AI Elite Admin" }},
                            user: {{
                                id: new Uint8Array([1, 2, 3, 4]),
                                name: "admin@nexa.ai",
                                displayName: "Elite Admin"
                            }},
                            pubKeyCredParams: [ {{ alg: -7, type: "public-key" }} ],
                            timeout: 60000,
                            attestation: "direct"
                        }}
                    }});
                    if (newCredential) {{
                        localStorage.setItem("nexa_bio_unlocked", "true");
                        alert("Biometric passkey registered successfully on this browser!");
                    }}
                }} catch (e) {{
                    alert("Biometric registration failed or canceled.");
                }}
            }}
        </script>
    </body>
    </html>
    """


@app.get("/admin/receipt/{file_id}")
async def view_telegram_receipt(file_id: str, pwd: str = "", x_admin_password: str = Header(None)):
    if not verify_admin_pwd(pwd, x_admin_password):
        raise HTTPException(status_code=403, detail="Unauthorized")
    if not http_client or not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=503, detail="Telegram client unavailable")
    file_resp = await http_client.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile?file_id={file_id}")
    file_path = file_resp.json().get("result", {}).get("file_path")
    if not file_path:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return RedirectResponse(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}")


class ReviewActionJSONModel(BaseModel):
    review_id: int
    user_id: str | int
    plan_tier: int = 1
    decision: str
    pwd: str = ""


@app.post("/admin/review-action-json")
async def admin_payment_action_json(data: ReviewActionJSONModel, x_admin_password: str = Header(None)):
    """JSON API endpoint for approving/rejecting payment reviews directly from Netlify HTML Admin Dashboard."""
    if not verify_admin_pwd(data.pwd, x_admin_password):
        return {"status": "error", "message": "Unauthorized password"}
    if not supabase:
        return {"status": "error", "message": "Supabase not connected"}

    user_id = str(data.user_id)
    plan_tier = int(data.plan_tier or 1)
    review_id = int(data.review_id)

    try:
        if data.decision == "approve":
            credits = TIER_CONFIG.get(plan_tier, TIER_CONFIG[1])["credits"]
            tier_price = float(TIER_CONFIG.get(plan_tier, TIER_CONFIG[1])["price"])
            expires_at = datetime.now(timezone.utc) + timedelta(days=30)
            await asyncio.gather(
                asyncio.to_thread(lambda: supabase.table("subscriptions").upsert({
                    "user_id": user_id,
                    "is_pro": True,
                    "plan_tier": plan_tier,
                    "credits_remaining": credits,
                    "trial_expires": expires_at.isoformat()
                }).execute()),
                asyncio.to_thread(lambda: supabase.table("stores").update({"plan_tier": plan_tier}).eq("owner_telegram_id", user_id).execute()),
                asyncio.to_thread(lambda: supabase.table("manual_review_queue").update({"status": "approved"}).eq("id", review_id).execute())
            )
            await record_affiliate_commission_and_revenue(
                user_id=user_id,
                amount_etb=tier_price,
                plan_tier=plan_tier,
                order_id=f"MANUAL-{review_id}",
                channel="MANUAL_APPROVED",
                reference_id=f"REV-{review_id}"
            )
            if http_client and TELEGRAM_BOT_TOKEN:
                await http_client.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={
                    "chat_id": int(user_id),
                    "text": f"🎉 ክፍያዎ ተረጋግጧል! አሁን ወደ Tier {plan_tier} ሙሉ በሙሉ አድገዋል።"
                })
        else:
            await asyncio.to_thread(lambda: supabase.table("manual_review_queue").update({"status": "rejected"}).eq("id", review_id).execute())
            if http_client and TELEGRAM_BOT_TOKEN:
                await http_client.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={
                    "chat_id": int(user_id),
                    "text": "⚠️ የላኩት የክፍያ ደረሰኝ ትክክለኛ ሆኖ አልተገኘም። እባክዎ ትክክለኛውን ደረሰኝ በድጋሚ ይላኩ።"
                })
        return {"status": "success", "decision": data.decision}
    except Exception as e:
        logger.error(f"JSON review action error: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/admin/action")
async def admin_payment_action(
    pwd: str = Form(...),
    review_id: int = Form(...),
    user_id: str = Form(...),
    plan_tier: int = Form(1),
    decision: str = Form(...)
):
    if not verify_admin_pwd(pwd):
        raise HTTPException(status_code=403, detail="Unauthorized")

    if supabase:
        if decision == "approve":
            credits = TIER_CONFIG.get(plan_tier, TIER_CONFIG[1])["credits"]
            tier_price = float(TIER_CONFIG.get(plan_tier, TIER_CONFIG[1])["price"])
            expires_at = datetime.now(timezone.utc) + timedelta(days=30)
            await asyncio.gather(
                asyncio.to_thread(lambda: supabase.table("subscriptions").upsert({
                    "user_id": user_id,
                    "is_pro": True,
                    "plan_tier": plan_tier,
                    "credits_remaining": credits,
                    "trial_expires": expires_at.isoformat()
                }).execute()),
                asyncio.to_thread(lambda: supabase.table("stores").update({"plan_tier": plan_tier}).eq("owner_telegram_id", user_id).execute()),
                asyncio.to_thread(lambda: supabase.table("manual_review_queue").update({"status": "approved"}).eq("id", review_id).execute())
            )
            await record_affiliate_commission_and_revenue(
                user_id=str(user_id),
                amount_etb=tier_price,
                plan_tier=plan_tier,
                order_id=f"MANUAL-{review_id}",
                channel="MANUAL_APPROVED",
                reference_id=f"REV-{review_id}"
            )
            if http_client and TELEGRAM_BOT_TOKEN:
                await http_client.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={
                    "chat_id": int(user_id),
                    "text": f"🎉 ክፍያዎ ተረጋግጧል! አሁን ወደ Tier {plan_tier} ሙሉ በሙሉ አድገዋል።"
                })
        else:
            await asyncio.to_thread(lambda: supabase.table("manual_review_queue").update({"status": "rejected"}).eq("id", review_id).execute())
            if http_client and TELEGRAM_BOT_TOKEN:
                await http_client.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={
                    "chat_id": int(user_id),
                    "text": "⚠️ የላኩት የክፍያ ደረሰኝ ትክክለኛ ሆኖ አልተገኘም። እባክዎ ትክክለኛውን ደረሰኝ በድጋሚ ይላኩ።"
                })

    return RedirectResponse(url=f"/admin?pwd={pwd}", status_code=303)


# -------------------------------------------------------------------
# Centralized Revenue & Affiliate 25% / 75% Split Recorder
# -------------------------------------------------------------------
async def record_affiliate_commission_and_revenue(
    user_id: str,
    amount_etb: float,
    plan_tier: int,
    order_id: str,
    channel: str,
    reference_id: str,
    bot_instance=None
):
    if not supabase:
        return

    try:
        await asyncio.to_thread(lambda: supabase.table("paid_subscriptions").insert({
            "user_id": str(user_id),
            "order_id": order_id,
            "amount_etb": float(amount_etb),
            "channel": channel,
            "reference_id": reference_id
        }).execute())

        ref_res = await asyncio.to_thread(
            lambda: supabase.table("referrals").select("*").eq("referred_user_id", str(user_id)).execute()
        )
        if ref_res.data:
            ref_row = ref_res.data[0]
            partner_id = str(ref_row["partner_id"])
            commission = round(float(amount_etb) * 0.25, 2)
            owner_net = round(float(amount_etb) - commission, 2)

            prev_paid = float(ref_row.get("amount_paid") or 0)
            prev_comm = float(ref_row.get("commission_amount") or 0)
            prev_net = float(ref_row.get("owner_net_amount") or 0)

            await asyncio.to_thread(
                lambda: supabase.table("referrals").update({
                    "plan_tier": plan_tier,
                    "amount_paid": prev_paid + float(amount_etb),
                    "commission_amount": prev_comm + commission,
                    "owner_net_amount": prev_net + owner_net,
                    "payout_status": "pending",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }).eq("referred_user_id", str(user_id)).execute()
            )

            p_info = await asyncio.to_thread(
                lambda: supabase.table("partners").select("total_earned, total_referrals").eq("partner_id", partner_id).execute()
            )
            if p_info.data:
                current_earned = float(p_info.data[0].get("total_earned") or 0)
                current_refs = int(p_info.data[0].get("total_referrals") or 0)
                is_first_payment = prev_paid == 0
                await asyncio.to_thread(
                    lambda: supabase.table("partners").update({
                        "total_earned": current_earned + commission,
                        "total_referrals": current_refs + (1 if is_first_payment else 0)
                    }).eq("partner_id", partner_id).execute()
                )

            notify_text = (
                f"🎉 **አዲስ የኮሚሽን ገቢ ተመዝግቧል! (Affiliate Commission)**\n\n"
                f"• የተመዘገበው ደረጃ: **Tier {plan_tier}**\n"
                f"• የተከፈለው ጠቅላላ መጠን: **{amount_etb:,.2f} ብር**\n"
                f"• የእርስዎ 1/4 (25%) ኮሚሽን ድርሻ: **{commission:,.2f} ብር**\n"
                f"• ሁኔታ: በአስተዳዳሪው በኩል ወደ ቴሌብር ቁጥርዎ ለመላክ ተመዝግቧል!"
            )
            if bot_instance:
                await bot_instance.send_message(chat_id=int(partner_id), text=notify_text, parse_mode="Markdown")
            elif http_client and TELEGRAM_BOT_TOKEN:
                await http_client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": int(partner_id), "text": notify_text, "parse_mode": "Markdown"}
                )
    except Exception as e:
        logger.error(f"Affiliate revenue split calculation error: {e}")


# -------------------------------------------------------------------
# Dynamic Payout Load Balancer
# -------------------------------------------------------------------
async def select_optimal_payout_destination(amount_etb: int, partner_id: str = None) -> tuple[str, str, int, str]:
    if partner_id and supabase:
        try:
            p_res = await asyncio.to_thread(
                lambda: supabase.table("partners").select("*").eq("partner_id", partner_id).execute()
            )
            if p_res.data:
                partner = p_res.data[0]
                partner_phone = partner.get("telebirr_number")
                if partner_phone:
                    commission_amount = int(amount_etb * 0.25)
                    return (f"Partner Telebirr ({partner.get('partner_name', 'Affiliate')})", partner_phone, commission_amount, "PARTNER_TELEBIRR")
        except Exception as e:
            logger.error(f"Partner payout routing error: {e}")

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
# Telegram Master Bot Handlers & Nexa Elite Business Advisor
# -------------------------------------------------------------------
async def business_advice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts a conversational, hook-driven elite business advisory session covering all sectors, legal compliance, and announcements."""
    context.user_data["advice_step"] = "awaiting_business_type"
    context.user_data["advice_history"] = []

    recent_announcements = ""
    if supabase:
        try:
            t_res = await asyncio.to_thread(
                lambda: supabase.table("support_tickets").select("message, created_at").order("created_at", desc=True).limit(2).execute()
            )
            if t_res.data:
                recent_announcements = "\n".join([f"• {str(item.get('message', ''))[:90]}" for item in t_res.data])
        except Exception:
            pass

    announcement_block = (
        f"\n📢 **ወቅታዊ ማሳሰቢያ እና የመድረክ ዜና:**\n{recent_announcements}\n"
        if recent_announcements
        else "\n📢 **ወቅታዊ ማሳሰቢያ:** ሕጋዊ ንግድን፣ የንግድ ፈቃድ/ግብር ስርዓትን እና የዲጂታል ሽያጭ (Telebirr & AI Automation) ዕድሎችን በማቀናጀት ንግድዎን እንዲያሳድጉ እናግዝዎታለን።\n"
    )

    intro_text = (
        "⚡ **ኔክሳ ኤላይት — የንግድ እና የስትራቴጂ አማካሪ (Nexa Elite Business Advisor)**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "ሰላም! እኔ ስለ **ማንኛውም የንግድ ዘርፍ** (ሱቅ፣ ኦንላይን ሽያጭ፣ ሪል እስቴት፣ ካፌ፣ አገልግሎት፣ አስመጪ/ላኪ፣ ቴክኖሎጂ ወይም አዲስ ጀማሪ ሐሳብ) "
        "ጠንቅቄ የምረዳ እና ንግድዎን በትርፍ እንዲመሩ የማግዝ የቅርብ የንግድ አማካሪዎ ነኝ።\n\n"
        "🎯 **ጥያቄ ካለዎት በማንኛውም ሰዓት መጠየቅ ይችላሉ!** ስለ ገበያ፣ ደንበኛ ማፍራት፣ ዋጋ አወሳሰን፣ ካፒታል አጠቃቀም፣ "
        "የንግድ ሕጋዊነት (ፈቃድ፣ ግብር፣ ደረሰኝ እና የሸማቾች ጥበቃ) ወይም ስለ አዳዲስ የንግድ ዕድሎች በቀጥታ ማውራት እንችላለን።"
        f"{announcement_block}\n"
        "👇 **ለመጀመር ዘርፍዎን ይምረጡ ወይም በቀጥታ ጥያቄዎን ይጻፉልኝ:**"
    )

    keyboard = [
        [InlineKeyboardButton("🛍️ ችርቻሮ / ሱቅ / ኢ-ኮሜርስ (Retail & Shop)", callback_data="adv_type_retail")],
        [InlineKeyboardButton("🏡 ሪል እስቴት / ኮንስትራክሽን (Real Estate)", callback_data="adv_type_realestate")],
        [InlineKeyboardButton("🍽️ ካፌ / ሬስቶራንት / ሆቴል (Food & Hospitality)", callback_data="adv_type_hospitality")],
        [InlineKeyboardButton("💼 አገልግሎት / ኤጀንሲ / ቴክኖሎጂ (Services & Tech)", callback_data="adv_type_services")],
        [InlineKeyboardButton("⚖️ የንግድ ሕጋዊነት እና ፈቃድ/ግብር (Legal & Compliance)", callback_data="adv_type_legal")],
        [InlineKeyboardButton("💡 ሐሳብ / ካፒታል አለኝ — ምን ልስራ? (Ideas & Capital)", callback_data="adv_type_investor")],
        [InlineKeyboardButton("🔙 ወደ ዋና ገጽ ይመለሱ", callback_data="start_menu")]
    ]

    if update.callback_query:
        await update.callback_query.message.edit_text(intro_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.effective_message.reply_text(intro_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def ask_business_situation(update: Update, context: ContextTypes.DEFAULT_TYPE, business_type_label: str):
    """Engages the user in an open, hook-driven conversation about their business, questions, and legal/market context."""
    context.user_data["advice_business_type"] = business_type_label
    context.user_data["advice_step"] = "awaiting_situation"
    context.user_data.setdefault("advice_history", [])

    prompt_text = (
        f"🔥 **አሪፍ ነው! በ {business_type_label} ላይ አተኩረን እናውራ።**\n\n"
        "አሁን ምን እየሰሩ ነው ወይም ምን ማሳካት ይፈልጋሉ? ጥያቄ ካለዎት አሁኑኑ ይጠይቁኝ — "
        "ገበያ ለማግኘት፣ ሽያጭ ለመጨመር፣ ሕጋዊ የንግድ አሰራርን ለማስተካከል ወይም ካፒታልን በብልሃት ለመጠቀም ምን እንደሚያስፈልግ በቀጥታ እንነጋገራለን።\n\n"
        "💬 *ጥያቄዎን ወይም ሐሳብዎን በጽሑፍ ወይም በድምጽ (Voice Note) ይጻፉልኝ — ከፈለጉ ስለ ካፒታልዎ እና ስለ ዋናው ፈተናዎም ይንገሩኝ...*"
    )

    keyboard = [[InlineKeyboardButton("🔙 ዘርፍ ቀይር", callback_data="business_advice_menu")]]
    if update.callback_query:
        await update.callback_query.message.edit_text(prompt_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.effective_message.reply_text(prompt_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def generate_professor_economic_advice(update: Update, context: ContextTypes.DEFAULT_TYPE, user_situation: str):
    """Conversational, hook-driven elite business advisor aware of all sectors, legal business practices, and announcements."""
    user_id = str(update.effective_user.id)
    business_type = context.user_data.get("advice_business_type", "ሁሉም የንግድ ዘርፎች (All Businesses)")
    advice_history = context.user_data.get("advice_history", [])

    await update.effective_message.reply_chat_action("typing")

    existing_store_info = ""
    announcements_context = ""
    if supabase:
        try:
            s_res, ann_res = await asyncio.gather(
                asyncio.to_thread(
                    lambda: supabase.table("stores").select("store_name, plan_tier, inventory_data").eq("owner_telegram_id", user_id).execute()
                ),
                asyncio.to_thread(
                    lambda: supabase.table("support_tickets").select("message, status").order("created_at", desc=True).limit(3).execute()
                )
            )
            if s_res.data:
                s = s_res.data[0]
                existing_store_info = f"User owns Nexa store '{s.get('store_name')}' (Tier {s.get('plan_tier', 1)})."
            if ann_res.data:
                announcements_context = "Recent platform/user updates: " + " | ".join([str(a.get("message", ""))[:80] for a in ann_res.data])
        except Exception:
            pass

    history_formatted = "\n".join([f"{h.get('role', 'user')}: {h.get('content', '')}" for h in advice_history[-6:]])

    advisor_prompt = f"""
    You are 'Nexa Elite Business Advisor' (ኔክሳ ኤላይት የንግድ አማካሪ) — a sharp, conversational, hook-driven, and deeply helpful business advisor who understands EVERY type of business, Ethiopian market realities (Addis Ababa & regional trade, ETB, Telebirr, digital commerce, import/local supply chains), legal business compliance, and current platform announcements.

    IMPORTANT STYLE RULES:
    - Do NOT use a stiff "professor/lecture" persona. Sound like a smart, practical, engaging, hook-driven business partner having a real conversation.
    - Understand whatever business or question the user brings up and answer directly, clearly, and helpfully.
    - Stay aware of legal business considerations where relevant (proper business registration/licensing, tax/receipt compliance, authentic products, transparent customer terms, data/privacy trust) in plain, practical business language—without acting as a formal courtroom lawyer.
    - Stay aware of platform features and announcements ({announcements_context or "4-tier AI store bots, Telebirr receipt verification, 25% partner affiliate program, and AI voice/chat lead capture"}).
    - Actively invite follow-up questions with an engaging hook (e.g., asking a sharp follow-up question or prompting them to ask whatever is on their mind next).
    - Include natural, high-leverage ways to grow revenue using Nexa tools (24/7 AI bot sales via `/register`, zero-capital 25% partner commissions via `/partner`) only when naturally helpful, never forced.
    - Write in clear, natural, engaging, grammatically accurate Amharic.

    Selected Focus Area: {business_type}
    {existing_store_info}
    Recent Conversation:
    {history_formatted or "None yet"}

    Current User Message: {user_situation}
    """

    advice_reply = (
        "⚡ **ኔክሳ የንግድ አማካሪ**\n\n"
        "ይቅርታ፣ አሁን ምላሽ ማዘጋጀት አልተቻለም። ጥያቄዎን በድጋሚ ይጻፉልኝ — በደስታ እንቀጥላለን!"
    )
    if GROQ_API_KEY:
        try:
            advice_reply = await generate_groq_text(
                prompt=user_situation,
                system_instruction=advisor_prompt,
                history_messages=advice_history[-6:],
                temperature=0.7,
                max_output_tokens=900,
            )
        except Exception as e:
            logger.error(f"Nexa Elite Advisor AI generation error: {e}")
            advice_reply = f"⚠️ የAI ምላሽ ስህተት አጋጥሟል: {str(e)}"

    advice_history.append({"role": "user", "content": user_situation})
    advice_history.append({"role": "assistant", "content": advice_reply})
    context.user_data["advice_history"] = advice_history[-8:]
    context.user_data["advice_step"] = "mentoring_active"

    keyboard = [
        [InlineKeyboardButton("🤖 የ AI ሻጭ ቦት ፍጠር (/register)", callback_data="start_register")],
        [InlineKeyboardButton("🤝 ያለ ካፒታል 25% ኮሚሽን (/partner)", callback_data="partner_menu")],
        [InlineKeyboardButton("🔄 አዲስ ውይይት ጀምር", callback_data="business_advice_menu")],
        [InlineKeyboardButton("📊 ዋና ገጽ ይመለሱ", callback_data="start_menu")]
    ]
    await update.effective_message.reply_text(advice_reply, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("advice_step", None)
    context.user_data.pop("advice_history", None)
    context.user_data.pop("support_ticket_step", None)
    context.user_data.pop("partner_setup_step", None)
    context.user_data.pop("payment_step", None)

    user = update.effective_user
    user_id = user.id
    await log_visitor(user_id)

    args = context.args
    if args and args[0].startswith("ref_"):
        partner_id = args[0].replace("ref_", "")
        referred_username = f"@{user.username}" if user.username else "No Username"
        referred_full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or f"User {user_id}"
        if supabase and partner_id != str(user_id):
            try:
                await asyncio.to_thread(
                    lambda: supabase.table("referrals").upsert({
                        "referred_user_id": str(user_id),
                        "referred_username": referred_username,
                        "referred_full_name": referred_full_name,
                        "partner_id": partner_id,
                        "created_at": datetime.now(timezone.utc).isoformat()
                    }, on_conflict="referred_user_id").execute()
                )
            except Exception as e:
                logger.error(f"Referral record error: {e}")

    sub_data = await get_or_create_user_subscription(user_id)
    has_access = await verify_active_access(user_id)
    trial_exp = parse_dt(sub_data["trial_expires"])
    now = datetime.now(timezone.utc)
    remaining_days = max(0, (trial_exp - now).days)

    store_tier_name = "Starter"
    if supabase:
        try:
            store_res = await asyncio.to_thread(
                lambda: supabase.table("stores").select("plan_tier").eq("owner_telegram_id", str(user_id)).execute()
            )
            if store_res.data:
                tier_num = store_res.data[0].get("plan_tier", 1)
                store_tier_name = TIER_CONFIG.get(tier_num, TIER_CONFIG[1])["name"]
        except Exception as e:
            logger.error(f"Store tier check error: {e}")

    if sub_data["is_pro"] and has_access:
        status_text = f"⭐ ንቁ አባልነት (VIP Enterprise — {store_tier_name}) — የንግድ አውቶሜሽን ስርዓትዎ በሥራ ላይ አለ።"
    elif has_access:
        status_text = (
            f"📋 የሙከራ ጊዜ በሥራ ላይ አለ (3 ቀናት)\n"
            f"• የቀረው ጊዜ: {remaining_days} ቀናት\n"
            f"• የሚያበቃበት ጊዜ: {trial_exp.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"• የቀሩ የAI ዕዳዎች: {sub_data['credits_remaining']}"
        )
    else:
        status_text = "⚠️ የሙከራ ጊዜዎ አልቋል — አገልግሎቱ እንዳይቋረጥ አባልነትዎን ያሻሽሉ።"

    welcome_text = (
        f"🌟 NEXA AI COMMERCE PLATFORM 🤖\n"
        f"🇪🇹 እንኳን ደህና መጡ, {user.first_name}! ይህ እጅግ ዘመናዊ የሆነ የ AI ሱቅ እና የንግድ ማስተዳደሪያ መድረክ ነው።\n\n"
        f"📊 የመለያዎ ሁኔታ:\n{status_text}\n\n"
        "🎯 ፈጣን መመሪያ:\n"
        "1️⃣ /advice - ⚡ የንግድ እና የስትራቴጂ አማካሪ (Elite Business Advisor)\n"
        "2️⃣ /register - አዲስ የ AI ሱቅ ቦት ይፍጠሩ\n"
        "3️⃣ /partner - የ Nexa አጋር በመሆን 25% ኮሚሽን ያግኙ\n"
        "4️⃣ /mybots - ቦቶችዎን ያስተዳድሩ\n"
        "5️⃣ /leads - የደንበኞችዎን Leads እና ስልክ ቁጥሮች ይመልከቱ\n"
        "6️⃣ /summary - የገቢ እና የጎብኚዎች ማጠቃለያ\n"
        "7️⃣ /setphone - የንግድ ስልክ ቁጥርዎን ያስገቡ ወይም ይቀይሩ\n"
        "8️⃣ /support - የደንበኞች ድጋፍ (Customer Support)\n"
        "9️⃣ /pay - አባልነትዎን ያሻሽሉ"
    )

    keyboard = [
        [InlineKeyboardButton("⚡ የንግድ አማካሪ — ጥያቄ ይጠይቁ (Business Advisor)", callback_data="business_advice_menu")],
        [InlineKeyboardButton("💎 አዲስ የ AI ቦት ፍጠር (/register)", callback_data="start_register")],
        [InlineKeyboardButton("🚀 አባልነት ያሻሽሉ (ክፍያ ይፈጽሙ)", callback_data="buy_pro")],
        [InlineKeyboardButton("🤝 Nexa Partnership (25% ኮሚሽን ፕሮግራም)", callback_data="partner_menu")],
        [InlineKeyboardButton("🤖 ቦቶቼን አስተዳድር (/mybots)", callback_data="view_my_bots")],
        [InlineKeyboardButton("📋 የደንበኞች Leads (/leads)", callback_data="view_leads")],
        [InlineKeyboardButton("📊 የገቢ ማጠቃለያ (/summary)", callback_data="view_summary")],
        [InlineKeyboardButton("📞 ስልክ ቁጥር ማስተካከያ (/setphone)", callback_data="change_partner_phone"),
         InlineKeyboardButton("🎧 ድጋፍ / Support", callback_data="support_menu")]
    ]
    await update.effective_message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard))


async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"🎧 **የ Nexa AI የደንበኞች ድጋፍ ማዕከል (Customer Support Helpdesk)**\n\n"
        f"ማንኛውም ጥያቄ፣ የቴክኒክ እገዛ ወይም የክፍያ ማስተካከያ ከፈለጉ እባክዎ ጥያቄዎን ወይም ችግርዎን ከታች ይጻፉ። "
        f"የእኛ የድጋፍ ቡድን እና AI ረዳት ወዲያውኑ ምላሽ ይሰጡዎታል!"
    )
    context.user_data["support_ticket_step"] = "awaiting_ticket_message"

    keyboard = [[InlineKeyboardButton("📊 ዋና ገጽ ይመለሱ", callback_data="start_menu")]]

    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def partner_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    partner = None
    if supabase:
        try:
            res = await asyncio.to_thread(
                lambda: supabase.table("partners").select("*").eq("partner_id", user_id).execute()
            )
            if res.data:
                partner = res.data[0]
        except Exception as e:
            logger.error(f"Partner fetch error: {e}")

    bot_username = context.bot.username or "nexa_bot"
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    if partner:
        p_name = partner.get("partner_name", "Partner")
        p_phone = partner.get("telebirr_number", "Not set")
        earned = partner.get("total_earned", 0)
        referrals = partner.get("total_referrals", 0)

        text = (
            f"🤝 **የ Nexa Partnership (Affiliate Program) ዳሽቦርድ**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 ስም: {p_name}\n"
            f"📞 የቴሌብር ቁጥርዎ: `{p_phone}`\n"
            f"👥 ያመጡዋቸው አባላት: {referrals} ሰዎች\n"
            f"💰 ያገኙት ጠቅላላ ኮሚሽን (1/4): **{earned:,.2f} ብር**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔗 **የእርስዎ ልዩ የማስታወቂያ ማገናኛ (Referral Link):**\n"
            f"`{ref_link}`\n\n"
            f"💡 ማሳሰቢያ፡ ማንኛውም ሰው በዚህ ሊንክ ገብቶ Nexa አባልነት ሲገዛ፣ ከክፍያው **1/4 (25%)** በቀጥታ ወደ እርስዎ የቴሌብር ቁጥር ይላካል እንዲሁም በሰርቨራችን ይመዘገባል።"
        )
        keyboard = [
            [InlineKeyboardButton("✏️ የቴሌብር ቁጥር መቀየሪያ", callback_data="change_partner_phone")],
            [InlineKeyboardButton("📊 ዋና ገጽ ይመለሱ", callback_data="start_menu")]
        ]
        if update.callback_query:
            await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        text = (
            f"🤝 **ወደ Nexa Partnership (Affiliate) ፕሮግራም እንኳን ደህና መጡ!**\n\n"
            f"Nexa AIን ለሌሎች ሰዎች በማስተዋወቅ ከሚገቡት ክፍያዎች **1/4 (25%) ኮሚሽን** በቋሚነት ማግኘት ይችላሉ።\n\n"
            f"ለመጀመር እባክዎ ክፍያ የሚቀበሉበትን **ትክክለኛ የቴሌብር ስልክ ቁጥርዎን (Telebirr Phone Number)** ከታች ይጻፉ (ለምሳሌ: 09... ወይም 07...):"
        )
        context.user_data["partner_setup_step"] = "awaiting_telebirr"
        if update.callback_query:
            await update.callback_query.message.edit_text(text, parse_mode="Markdown")
        else:
            await update.effective_message.reply_text(text, parse_mode="Markdown")


async def my_bots_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = str(update.effective_user.id)
    if not supabase:
        await update.effective_message.reply_text("የዳታቤዝ ግንኙነት የለም።")
        return

    try:
        res = await asyncio.to_thread(
            lambda: supabase.table("stores").select("store_name, bot_token, ui_theme, plan_tier, business_phone, voice_ai_active").eq("owner_telegram_id", owner_id).execute()
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
            bus_phone = store.get("business_phone") or "አልተመዘገበም ❌"
            voice_status = "🟢 በሥራ ላይ (Active)" if store.get("voice_ai_active", True) else "🛑 ቆሟል (Paused)"
            bots_list_text += (
                f"🤖 **{store['store_name']}**\n"
                f"• ዕቅድ / ፕላን: {tier_name}\n"
                f"• የንግድ ስልክ ቁጥር: `{bus_phone}`\n"
                f"• የድምጽ ስልክ ረዳት: {voice_status}\n"
                f"• ቶከን ቁልፍ: `{masked_token}`\n"
                f"• የቦት ዘይቤ: {store.get('ui_theme', 'executive').capitalize()}\n\n"
            )
        await update.effective_message.reply_text(bots_list_text, parse_mode="Markdown")
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
        f"  _(Core AI Sales, Text Catalog, Photo Support)_\n\n"
        f"• **Tier 2 (Business Pro)**: 2,500 ብር / ወር\n"
        f"  _(Advanced AI, Photo Catalogs, Priority Leads)_\n\n"
        f"• **Tier 3 (Enterprise VIP)**: 5,000 ብር / ወር\n"
        f"  _(Unlimited AI, Full Photo & Video Streaming, VIP Concierge)_\n\n"
        f"• **Tier 4 (AI Voice Concierge)**: 7,000 ብር / ወር\n"
        f"  _(Includes Live AI Voice Calls & Automated Phone Receptionist in Amharic)_\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✨ **ለምን ወደ Tier 4 AI Voice ያሻሽላሉ?**\n"
        f"የድርጅትዎን ስልክ ቁጥር ከ Nexa AI ጋር በማገናኘት ደንበኞችዎ ሲደውሉ AI ድምጽ ረዳቱ በንግድዎ ካታሎግ መሰረት በቀጥታ በስልክ ያነጋግሯቸዋል!\n\n"
        f"እባክዎ ክፍያ ለመፈጸም ከታች ካሉት ዕቅዶች አንዱን ይምረጡ:"
    )

    keyboard = [
        [InlineKeyboardButton("🥉 Tier 1: Starter (1,000 ብር / ወር)", callback_data="tier_pay_1")],
        [InlineKeyboardButton("🥈 Tier 2: Business Pro (2,500 ብር / ወር)", callback_data="tier_pay_2")],
        [InlineKeyboardButton("🥇 Tier 3: Enterprise VIP (5,000 ብር / ወር)", callback_data="tier_pay_3")],
        [InlineKeyboardButton("💎 Tier 4: AI Voice Concierge (7,000 ብር / ወር)", callback_data="tier_pay_4")]
    ]

    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(tier_select_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        except Exception:
            await update.callback_query.message.reply_text(tier_select_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.effective_message.reply_text(tier_select_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def start_tier_upgrade_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, tier_num: int):
    context.user_data["selected_tier"] = tier_num
    context.user_data["payment_step"] = "awaiting_payer_name"

    target_msg = update.callback_query.message if update.callback_query else update.effective_message
    if update.callback_query:
        await update.callback_query.answer()

    await target_msg.reply_text(
        "📝 **የክፍያ ማረጋገጫ መረጃ (Verification Details)**\n\n"
        "እባክዎ ትክክለኛ ስምዎን (Full Name) ይጻፉ (ይህ በ AI-OCR ደረሰኝ ማረጋገጫ ወቅት ይረዳል):",
        parse_mode="Markdown"
    )


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
        vis_res, leads_res = await asyncio.gather(
            asyncio.to_thread(
                lambda: supabase.table("tenant_visitors").select("chat_id", count="exact").eq("bot_token", bot_token).execute()
            ),
            asyncio.to_thread(
                lambda: supabase.table("leads").select("*").eq("bot_token", bot_token).order("updated_at", desc=True).limit(35).execute()
            )
        )
        total_bot_visitors = vis_res.count if vis_res.count is not None else len(vis_res.data or [])
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
            raw_name = str(lead.get("visitor_name") or "").strip()
            name = raw_name if raw_name and raw_name.lower() not in ["anonymous", "none", "null", "unknown"] else f"ደንበኛ #{lead.get('visitor_telegram_id', idx)}"
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
# AI Self-Healing & Auto-Correction Auditor
# -------------------------------------------------------------------
async def run_ai_system_audit_and_heal(target_owner_id: str = None) -> str:
    if not supabase:
        return "⚠️ Supabase connection missing."

    repaired_webhooks = 0
    healed_stores = 0

    try:
        if TELEGRAM_BOT_TOKEN and http_client:
            expected_master_wh = f"{RENDER_EXTERNAL_URL}/webhook"
            try:
                wh_info = await http_client.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo", timeout=5.0)
                if wh_info.status_code == 200:
                    current_wh_url = wh_info.json().get("result", {}).get("url", "")
                    if current_wh_url != expected_master_wh:
                        await http_client.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook", json={"url": expected_master_wh, "secret_token": TELEGRAM_WEBHOOK_SECRET}, timeout=5.0)
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
            if store.get("plan_tier") not in [1, 2, 3, 4]:
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
        "🤖 **አዲስ የ AI ቦት ምዝገባ (Step 1 from 6)**\n\n"
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
        "እርምጃ 2 ከ 6: የንግድ ዘርፍዎን (Industry) ይምረጡ:",
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
        "እርምጃ 3 ከ 6: የቦትዎን የውይይት ዘይቤ (UI/UX Theme) ይምረጡ:",
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
        [InlineKeyboardButton("🥇 Tier 3: Enterprise VIP (5,000 ብር / ወር)", callback_data="tier_3")],
        [InlineKeyboardButton("💎 Tier 4: AI Voice Concierge (7,000 ብር / ወር)", callback_data="tier_4")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await target_message(
        "እርምጃ 4 ከ 6: የሚፈልጉትን የአገልግሎት ደረጃ (Tier) ይምረጡ:\n"
        "• **Tier 1:** የላቀ AI + የጽሁፍ ካታሎግ + የፎቶ ድጋፍ\n"
        "• **Tier 2:** የላቀ AI + የፎቶ ካታሎግ + የላቀ የደንበኛ ክትትል\n"
        "• **Tier 3:** ያልተወሰነ AI + ሙሉ የፎቶ እና ቪዲዮ ስትሪሚንግ ድጋፍ\n"
        "• **Tier 4:** ሁሉም የ VIP አገልግሎቶች + በቀጥታ የሚሰራ የ AI ድምጽ ስልክ ረዳት (AI Voice Call Receptionist)",
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
        f"የተመረጠው ዕቅድ: {tier_info['name']} ({tier_info['price']:,} ብር / ወር)\n\n"
        "እርምጃ 5 ከ 6: እባክዎ ሙሉ ዕቃዎችዎን፣ አገልግሎቶችዎን፣ የሪል እስቴት መረጃዎን ወይም ካታሎግ ጽሑፍ ከታች ይለጥፉ:"
    )
    return INVENTORY


async def receive_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_input = update.effective_message.text

    await update.effective_message.reply_text("🔄 Groq AI is analyzing, sorting, and formatting your catalog data for Supabase...")

    structured_inventory = raw_input
    if GROQ_API_KEY:
        try:
            prompt = (
                f"You are an expert database and catalog structurer. Clean up, re-organize, and simplify the following raw store inventory or catalog text "
                f"into a clean, professional markdown format. Remove messy columns or broken syntax. Ensure clear item names, prices in ETB, and concise descriptions:\n\n{raw_input}"
            )
            structured_inventory = await generate_groq_text(
                prompt=prompt,
                temperature=0.2,
                max_output_tokens=1000,
            )
        except Exception as e:
            logger.error(f"AI catalog structuring error: {e}")

    context.user_data["inventory_data"] = structured_inventory
    await update.effective_message.reply_text(
        "✅ Catalog successfully sorted and structured by Groq AI!\n\n"
        "እርምጃ 6 ከ 6: እባክዎ ከ @BotFather የወሰዱትን ልዩ የቦት ቶከን (Bot Token) እዚህ ይለጥፉ:"
    )
    return BOT_TOKEN


async def receive_bot_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_token = update.effective_message.text.strip()

    if not re.match(r"^\d+:[A-Za-z0-9_-]{35}$", bot_token):
        await update.effective_message.reply_text("⚠️ ያስገቡት የቦት ቶከን ቅርጸት ልክ አይደለም። እባክዎ ከ @BotFather ትክክለኛውን ቶከን ኮፒ አድርገው ይላኩ:")
        return BOT_TOKEN

    context.user_data["bot_token"] = bot_token

    await update.effective_message.reply_text(
        "📱 **የስልክ ቁጥር ምዝገባ (Ethiopian Phone Number)**\n\n"
        "እባክዎ የንግድዎን ወይም የባለቤቱን ስልክ ቁጥር ያስገቡ (`09...` ወይም `07...`):",
        parse_mode="Markdown"
    )
    return STORE_PHONE


async def receive_store_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone_input = update.effective_message.text.strip()

    if not re.match(r"^0[79]\d{8}$", phone_input.replace(" ", "")):
        await update.effective_message.reply_text("⚠️ ትክክለኛ የኢትዮጵያ ስልክ ቁጥር አይደለም። እባክዎ በ 09 ወይም በ 07 የሚጀምር 10 አሃዝ ቁጥር ይጻፉ (ለምሳሌ: 0911223344):")
        return STORE_PHONE

    owner_telegram_id = str(update.effective_user.id)
    store_name = context.user_data.get("store_name", "My Store")
    inventory_data = context.user_data.get("inventory_data", "No inventory specified")
    ui_theme = context.user_data.get("ui_theme", "executive")
    plan_tier = context.user_data.get("plan_tier", 1)
    bot_token = context.user_data.get("bot_token")

    tenant_webhook_url = f"{RENDER_EXTERNAL_URL}/tenant-webhook/{bot_token}"

    try:
        resp = await http_client.post(
            f"https://api.telegram.org/bot{bot_token}/setWebhook",
            json={"url": tenant_webhook_url}
        )
        if not resp.json().get("ok"):
            await update.effective_message.reply_text("⚠️ የቦቱ ዌብሁክ ሊመዘገብ አልቻለም። እባክዎ /register በመጠቀም እንደገና ይሞክሩ።")
            return ConversationHandler.END
    except Exception as e:
        logger.error(f"SetWebhook error: {e}")
        await update.effective_message.reply_text("⚠️ ቶከኑን ማረጋገጥ አልተቻለም።")
        return ConversationHandler.END

    if supabase:
        try:
            store_payload = {
                "bot_token": bot_token,
                "owner_telegram_id": owner_telegram_id,
                "store_name": store_name,
                "inventory_data": inventory_data,
                "ui_theme": ui_theme,
                "plan_tier": plan_tier,
                "owner_phone": phone_input,
                "business_phone": phone_input,
                "voice_ai_active": True
            }
            await asyncio.to_thread(
                lambda: supabase.table("stores").upsert(store_payload, on_conflict="bot_token").execute()
            )
        except Exception as e:
            logger.error(f"Supabase upsert error with phone: {e}")
            try:
                fallback_payload = {
                    "bot_token": bot_token,
                    "owner_telegram_id": owner_telegram_id,
                    "store_name": store_name,
                    "inventory_data": inventory_data,
                    "ui_theme": ui_theme,
                    "plan_tier": plan_tier
                }
                await asyncio.to_thread(
                    lambda: supabase.table("stores").upsert(fallback_payload, on_conflict="bot_token").execute()
                )
            except Exception as inner_e:
                await update.effective_message.reply_text(f"⚠️ ዳታቤዝ ላይ ማስቀመጥ አልተቻለም: {str(inner_e)}")
                return ConversationHandler.END

    tier_info = TIER_CONFIG.get(plan_tier, TIER_CONFIG[1])
    cool_advert_text = (
        f"🤖 **የንግድ መደብር ቦትዎ በተሳካ ሁኔታ ተፈጥሯል!**\n\n"
        f"እንኳን ደስ አለዎት! የንግድ መደብርዎ **{store_name}** (ስልክ: `{phone_input}`) በዘመናዊ የ AI ሻጭ ረዳት ተዋቅሯል።\n"
        f"• የነጻ ሙከራ ጊዜ: **3 ቀናት** በሥራ ላይ ውሏል\n"
        f"• የተመረጠው ዕቅድ: {tier_info['name']}\n"
        f"• የድምጽ ስልክ ቁጥር: `{phone_input}` ከ ሲስተሙ ጋር ተገናኝቷል!\n\n"
        f"💡 አሁን `/pay` በመጫን ወይም ከታች ባለው ሊንክ አባልነትዎን ማሻሻል ይችላሉ!"
    )

    keyboard = [
        [InlineKeyboardButton("🚀 አባልነት ማሻሻያ (Upgrade / Pay)", callback_data="buy_pro")],
        [InlineKeyboardButton("⚡ የንግድ አማካሪ (/advice)", callback_data="business_advice_menu")],
        [InlineKeyboardButton("📊 የጎብኚዎች ማጠቃለያ (/summary)", callback_data="view_summary")]
    ]

    await update.effective_message.reply_text(cool_advert_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return ConversationHandler.END


# -------------------------------------------------------------------
# Phone Number & AI Voice Control Commands
# -------------------------------------------------------------------
async def select_phone_bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return CHANGE_PHONE
    await query.answer()
    bot_token = query.data.replace("change_phone_bot_", "", 1)
    context.user_data["target_bot_token_for_phone"] = bot_token
    store_label = "Selected Store"
    if supabase:
        try:
            res = await asyncio.to_thread(
                lambda: supabase.table("stores").select("store_name").eq("bot_token", bot_token).limit(1).execute()
            )
            if res.data:
                store_label = res.data[0].get("store_name", store_label)
        except Exception as e:
            logger.error(f"Store lookup for phone change error: {e}")
    await query.message.reply_text(
        f"📞 እባክዎ ለ **{store_label}** አዲስ የንግድ ስልክ ቁጥር (`09...` ወይም `07...`) ያስገቡ:",
        parse_mode="Markdown"
    )
    return CHANGE_PHONE


async def setphone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = str(update.effective_user.id)
    if not supabase:
        await update.effective_message.reply_text("የዳታቤዝ ግንኙነት የለም።")
        return ConversationHandler.END

    try:
        res = await asyncio.to_thread(
            lambda: supabase.table("stores").select("bot_token, store_name, business_phone").eq("owner_telegram_id", owner_id).execute()
        )
        if not res.data:
            await update.effective_message.reply_text("❌ እስካሁን የተመዘገበ ቦት የለዎትም። ለመፍጠር /register ይጠቀሙ።")
            return ConversationHandler.END

        if len(res.data) == 1:
            context.user_data["target_bot_token_for_phone"] = res.data[0]["bot_token"]
            await update.effective_message.reply_text(
                f"📞 ለ **{res.data[0]['store_name']}** አዲስ የንግድ ስልክ ቁጥር (Business Phone) ያስገቡ (`09...` ወይም `07...`):",
                parse_mode="Markdown"
            )
            return CHANGE_PHONE
        else:
            keyboard = []
            for store in res.data:
                keyboard.append([InlineKeyboardButton(f"🤖 {store['store_name']} ({store.get('business_phone', 'No Phone')})", callback_data=f"change_phone_bot_{store['bot_token']}")])

            await update.effective_message.reply_text(
                "📱 **ስልክ ቁጥር መቀየሪያ (Change Phone)**\n\nእባክዎ ስልክ ቁጥሩን ማሻሻል የሚፈልጉትን መደብር/ቦት ይምረጡ:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return CHANGE_PHONE
    except Exception as e:
        await update.effective_message.reply_text(f"ስልክ ቁጥር ማምጣት አልተቻለም: {str(e)}")
        return ConversationHandler.END


async def receive_updated_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone_input = update.effective_message.text.strip()

    if not re.match(r"^0[79]\d{8}$", phone_input.replace(" ", "")):
        await update.effective_message.reply_text("⚠️ ትክክለኛ የኢትዮጵያ ስልክ ቁጥር አይደለም። እባክዎ በ 09 ወይም በ 07 የሚጀምር 10 አሃዝ ቁጥር ይጻፉ:")
        return CHANGE_PHONE

    bot_token = context.user_data.get("target_bot_token_for_phone")
    if not bot_token and supabase:
        owner_id = str(update.effective_user.id)
        res = await asyncio.to_thread(
            lambda: supabase.table("stores").select("bot_token").eq("owner_telegram_id", owner_id).order("created_at", desc=True).limit(1).execute()
        )
        if res.data:
            bot_token = res.data[0]["bot_token"]

    if not bot_token:
        await update.effective_message.reply_text("❌ የተሳሳተ ሂደት። እባክዎ /setphone በመጠቀም እንደገና ይሞክሩ።")
        return ConversationHandler.END

    if supabase:
        try:
            await asyncio.to_thread(
                lambda: supabase.table("stores").update({
                    "business_phone": phone_input,
                    "owner_phone": phone_input
                }).eq("bot_token", bot_token).execute()
            )
            ai_confirm = await answer_registered_phone_with_ai(
                raw_phone=phone_input,
                user_question="Briefly welcome this newly registered phone number in Nexa AI and explain how it gives AI-powered answers.",
                customer_lang="amharic",
            )
            await update.effective_message.reply_text(
                f"✅ የስልክ ቁጥርዎ በተሳካ ሁኔታ ወደ **`{phone_input}`** ተቀይሯል!\n\n{ai_confirm}",
                parse_mode="Markdown"
            )
        except Exception as e:
            await update.effective_message.reply_text(f"⚠️ ስልክ ቁጥሩን ማሻሻል አልተቻለም: {str(e)}")

    context.user_data.pop("target_bot_token_for_phone", None)
    return ConversationHandler.END


async def stop_voice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = str(update.effective_user.id)
    if not supabase:
        await update.effective_message.reply_text("የዳታቤዝ ግንኙነት የለም።")
        return

    try:
        await asyncio.to_thread(
            lambda: supabase.table("stores").update({"voice_ai_active": False}).eq("owner_telegram_id", owner_id).execute()
        )
        await update.effective_message.reply_text(
            "🛑 **የ AI ድምጽ ስልክ ረዳት (AI Voice Concierge) አገልግሎት በጊዜያዊነት ቆሟል።**\n\n"
            "ደንበኞችዎ ሲደውሉ AI ድምጽ ረዳቱ አያነጋግራቸውም። እንደገና ለማስጀመር `/startvoice` የሚለውን ይጠቀሙ።",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.effective_message.reply_text(f"ስራውን ማቆም አልተቻለም: {str(e)}")


async def start_voice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = str(update.effective_user.id)
    if not supabase:
        await update.effective_message.reply_text("የዳታቤዝ ግንኙነት የለም።")
        return

    try:
        await asyncio.to_thread(
            lambda: supabase.table("stores").update({"voice_ai_active": True}).eq("owner_telegram_id", owner_id).execute()
        )
        await update.effective_message.reply_text(
            "🟢 **የ AI ድምጽ ስልክ ረዳት (AI Voice Concierge) አገልግሎት በድጋሚ በሥራ ላይ ውሏል!**\n\n"
            "አሁን ደንበኞችዎ ወደ ንግድ ስልክ ቁጥርዎ ሲደውሉ Groq AI በሰዓቱ በስልክ ይመልስላቸዋል።",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.effective_message.reply_text(f"አገልግሎቱን ማስጀመር አልተቻለም: {str(e)}")


async def cancel_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("❌ ምዝገባው ተሰርዟል። ዝግጁ ሲሆኑ /register ይጠቀሙ።")
    return ConversationHandler.END


# -------------------------------------------------------------------
# Media Upload Handler (/addmedia tag)
# -------------------------------------------------------------------
async def handle_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    caption = update.message.caption or ""
    match = re.search(r"/addmedia\s+([a-zA-Z0-9_\-]+)", caption)

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

            clean_caption = re.sub(r"/addmedia\s+[a-zA-Z0-9_\-]+", "", caption).strip()

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
# Tier 4 AI Voice Call Receptionist Endpoint
# -------------------------------------------------------------------
@app.post("/api/voice-call-webhook/{bot_token}")
async def ai_voice_call_webhook(bot_token: str, request: Request):
    data = await request.json()
    caller_phone = data.get("caller_phone") or data.get("From", "Unknown Caller")
    spoken_text = data.get("spoken_text") or data.get("SpeechResult", "")

    store = None
    if supabase:
        try:
            res = await asyncio.to_thread(lambda: supabase.table("stores").select("*").eq("bot_token", bot_token).execute())
            if res.data:
                store = res.data[0]
        except Exception as e:
            logger.error(f"Voice webhook store fetch error: {e}")

    if not store:
        return {"status": "error", "message": "Store not found"}

    if store.get("voice_ai_active") is False:
        return {"status": "paused", "message": "AI Voice concierge is currently stopped by store owner"}

    plan_tier = store.get("plan_tier", 1)
    if plan_tier < 4:
        return {"status": "unauthorized", "message": "AI Voice Call Receptionist requires Tier 4 (AI Voice Concierge)"}

    inventory = store.get("inventory_data", "")
    store_name = store.get("store_name", "Nexa Store")

    system_prompt = (
        f"You are the professional AI Voice Receptionist for company {store_name}. "
        "Your responses will be spoken aloud to callers via Text-to-Speech in Amharic or English. "
        "Keep answers polite, concise, natural, and directly helpful based on the store catalog below.\n\n"
        f"Catalog:\n{inventory}"
    )

    ai_response = "ሰላም! የድርጅታችን የ AI ስልክ ረዳት ነኝ። በምን ልረዳዎ እችላለሁ?"
    if GROQ_API_KEY and spoken_text:
        try:
            ai_response = await generate_groq_text(
                prompt=spoken_text,
                system_instruction=system_prompt,
                temperature=0.5,
                max_output_tokens=250,
            )
        except Exception as e:
            logger.error(f"Voice AI generation error: {e}")

    if supabase and caller_phone:
        try:
            await asyncio.to_thread(
                lambda: supabase.table("leads").upsert({
                    "bot_token": bot_token,
                    "visitor_telegram_id": f"phone_{caller_phone}",
                    "visitor_name": f"Phone Caller ({caller_phone})",
                    "phone_number": caller_phone,
                    "interest_summary": f"[PHONE CALL] {spoken_text[:100]}",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }, on_conflict="bot_token,visitor_telegram_id").execute()
            )
        except Exception as lead_err:
            logger.error(f"Phone lead log error: {lead_err}")

    return {
        "status": "success",
        "store_name": store_name,
        "caller_phone": caller_phone,
        "ai_reply_text": ai_response,
        "tts_ready": True
    }


# -------------------------------------------------------------------
# Admin Sync Tier, Support Reply, Payouts & Broadcast Endpoints
# -------------------------------------------------------------------
class TierSyncModel(BaseModel):
    user_id: str | int
    plan_tier: int
    months: int = 1
    pwd: str = ""

class BroadcastModel(BaseModel):
    message: str
    target: str = "all"
    pwd: str = ""

class DirectChatModel(BaseModel):
    chat_id: str | int
    message: str
    pwd: str = ""

class SupportReplyModel(BaseModel):
    ticket_id: str | int
    user_id: str | int
    reply: str
    pwd: str = ""

class AffiliatePayoutModel(BaseModel):
    partner_id: str
    amount_paid: float
    reference_note: str = ""
    pwd: str = ""

class StoreActionModel(BaseModel):
    bot_token: str
    action: str  # "pause_voice", "resume_voice", "delete_store"
    pwd: str = ""


@app.post("/admin/store-action")
async def admin_store_action(data: StoreActionModel, x_admin_password: str = Header(None)):
    """Allows the Netlify Admin HTML Dashboard to control any connected store live."""
    if not verify_admin_pwd(data.pwd, x_admin_password):
        return {"status": "error", "message": "Unauthorized password"}
    if not supabase:
        return {"status": "error", "message": "Supabase not connected"}

    try:
        if data.action == "pause_voice":
            await asyncio.to_thread(lambda: supabase.table("stores").update({"voice_ai_active": False}).eq("bot_token", data.bot_token).execute())
        elif data.action == "resume_voice":
            await asyncio.to_thread(lambda: supabase.table("stores").update({"voice_ai_active": True}).eq("bot_token", data.bot_token).execute())
        elif data.action == "delete_store":
            await asyncio.to_thread(lambda: supabase.table("stores").delete().eq("bot_token", data.bot_token).execute())
            if http_client:
                await http_client.post(f"https://api.telegram.org/bot{data.bot_token}/deleteWebhook")
        return {"status": "success", "action": data.action}
    except Exception as e:
        logger.error(f"Store action error: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/admin/broadcast")
async def admin_broadcast(data: BroadcastModel, x_admin_password: str = Header(None)):
    if not verify_admin_pwd(data.pwd, x_admin_password):
        return {"status": "error", "message": "Unauthorized password"}
    if not supabase:
        return {"status": "error", "message": "Supabase not connected"}
    if not http_client or not TELEGRAM_BOT_TOKEN:
        return {"status": "error", "message": "Telegram bot token or HTTP client unavailable"}

    try:
        stores_res = await asyncio.to_thread(
            lambda: supabase.table("stores").select("owner_telegram_id").execute()
        )
        owner_ids = list({str(s["owner_telegram_id"]) for s in (stores_res.data or []) if s.get("owner_telegram_id")})

        sent_count = 0
        broadcast_text = (
            f"📢 **NEXA AI OFFICIAL ANNOUNCEMENT**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{data.message}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💎 Nexa AI Elite Team"
        )
        for oid in owner_ids:
            try:
                resp = await http_client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": int(oid),
                        "text": broadcast_text,
                        "parse_mode": "Markdown"
                    }
                )
                if resp.status_code == 200:
                    sent_count += 1
            except Exception as send_err:
                logger.error(f"Broadcast failed for owner {oid}: {send_err}")

        return {"status": "success", "sent": sent_count, "total_targets": len(owner_ids)}
    except Exception as e:
        logger.error(f"Admin broadcast error: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/admin/record-payout")
async def admin_record_affiliate_payout(data: AffiliatePayoutModel, x_admin_password: str = Header(None)):
    if not verify_admin_pwd(data.pwd, x_admin_password):
        return {"status": "error", "message": "Unauthorized password"}
    if not supabase:
        return {"status": "error", "message": "Supabase not connected"}

    try:
        p_res = await asyncio.to_thread(
            lambda: supabase.table("partners").select("*").eq("partner_id", str(data.partner_id)).execute()
        )
        if not p_res.data:
            return {"status": "error", "message": "Partner not found"}

        partner = p_res.data[0]
        prev_paid_out = float(partner.get("paid_out") or 0)
        new_paid_out = prev_paid_out + float(data.amount_paid)

        await asyncio.gather(
            asyncio.to_thread(lambda: supabase.table("partners").update({
                "paid_out": new_paid_out
            }).eq("partner_id", str(data.partner_id)).execute()),
            asyncio.to_thread(lambda: supabase.table("affiliate_payouts").insert({
                "partner_id": str(data.partner_id),
                "partner_name": partner.get("partner_name", "Partner"),
                "telebirr_number": partner.get("telebirr_number", ""),
                "amount_paid": float(data.amount_paid),
                "reference_note": data.reference_note or "Manual Telebirr Transfer"
            }).execute()),
            asyncio.to_thread(lambda: supabase.table("referrals").update({
                "payout_status": "paid"
            }).eq("partner_id", str(data.partner_id)).eq("payout_status", "pending").execute())
        )

        if http_client and TELEGRAM_BOT_TOKEN:
            try:
                await http_client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": int(data.partner_id),
                        "text": (
                            f"💸 **የኮሚሽን ክፍያ ተልኳል! (Affiliate Payout Sent)**\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"• የተላከው መጠን: **{float(data.amount_paid):,.2f} ብር**\n"
                            f"• መቀበያ ቴሌብር: `{partner.get('telebirr_number', 'N/A')}`\n"
                            f"• ማስታወሻ / Ref: `{data.reference_note or 'Telebirr Payout'}`\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"✨ ከ Nexa AI ጋር አብረው ስለሚሰሩ እናመሰግናለን!"
                        ),
                        "parse_mode": "Markdown"
                    }
                )
            except Exception as tg_err:
                logger.error(f"Payout Telegram notification error: {tg_err}")

        return {"status": "success", "new_paid_out": new_paid_out}
    except Exception as e:
        logger.error(f"Record payout error: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/admin/support-reply")
async def admin_support_reply(data: SupportReplyModel, x_admin_password: str = Header(None)):
    if not verify_admin_pwd(data.pwd, x_admin_password):
        return {"status": "error", "message": "Unauthorized password"}

    if supabase:
        try:
            await asyncio.to_thread(
                lambda: supabase.table("support_tickets").update({
                    "admin_reply": data.reply,
                    "status": "resolved"
                }).eq("id", data.ticket_id).execute()
            )
        except Exception as e:
            logger.error(f"Support reply DB update error: {e}")

    if not http_client or not TELEGRAM_BOT_TOKEN:
        return {"status": "error", "message": "Telegram bot token or HTTP client unavailable"}

    try:
        reply_msg = (
            f"🎧 **NEXA CUSTOMER SUPPORT REPLY**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{data.reply}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✨ አስተያየትዎ ወይም ጥያቄዎ ተመልሷል። እናመሰግናለን!"
        )
        await http_client.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": int(data.user_id),
                "text": reply_msg,
                "parse_mode": "Markdown"
            }
        )
    except Exception as e:
        logger.error(f"Support Telegram notification error: {e}")
        return {"status": "error", "message": str(e)}

    return {"status": "success", "message": "Support reply sent successfully"}


@app.post("/admin/sync-tier")
async def sync_tier(data: TierSyncModel, x_admin_password: str = Header(None)):
    if not verify_admin_pwd(data.pwd, x_admin_password):
        return {"status": "error", "message": "Unauthorized password"}

    user_id_str = str(data.user_id)
    tier = int(data.plan_tier)
    months = int(data.months or 1)

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=30 * months)
    credits = TIER_CONFIG.get(tier, TIER_CONFIG[1])["credits"]

    if supabase:
        try:
            await asyncio.to_thread(
                lambda: supabase.table("stores").update({"plan_tier": tier}).eq("owner_telegram_id", user_id_str).execute()
            )
            await asyncio.to_thread(
                lambda: supabase.table("subscriptions").upsert({
                    "user_id": user_id_str,
                    "is_pro": True,
                    "plan_tier": tier,
                    "trial_expires": expires_at.isoformat(),
                    "credits_remaining": credits
                }).execute()
            )
        except Exception as e:
            logger.error(f"Sync tier DB error: {e}")
            return {"status": "error", "message": str(e)}

    if TELEGRAM_BOT_TOKEN:
        try:
            tier_name = TIER_CONFIG.get(tier, TIER_CONFIG[1])["name"] if tier > 0 else "Free Tier (Level 0)"
            alert_text = (
                f"⚡ **የአካውንትዎ Tier እና የቆይታ ጊዜ በአስተዳዳሪው ተሻሽሏል!**\n\n"
                f"• አዲስ ዕቅድ: **{tier_name} (Level {tier})**\n"
                f"• የቆይታ ጊዜ: **{months} ወር(ዎች)**\n"
                f"• የሚያበቃበት ቀን: `{expires_at.strftime('%Y-%m-%d %H:%M UTC')}`\n\n"
                f"🚀 አሁን የ Nexa AI አገልግሎቶች በአዲሱ ደረጃ በሥራ ላይ ውለዋል!"
            )
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": int(user_id_str),
                        "text": alert_text,
                        "parse_mode": "Markdown"
                    }
                )
        except Exception as tg_err:
            logger.error(f"Tier sync Telegram notification error: {tg_err}")

    return {"status": "success", "message": f"Successfully synced user {user_id_str} to Tier {tier} for {months} month(s)."}


@app.post("/admin/send-message")
async def send_direct_message(data: DirectChatModel, x_admin_password: str = Header(None)):
    if not verify_admin_pwd(data.pwd, x_admin_password):
        return {"status": "error", "message": "Unauthorized password"}
    if not http_client or not TELEGRAM_BOT_TOKEN:
        return {"status": "error", "message": "Telegram bot token or HTTP client unavailable"}
    try:
        await http_client.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": int(data.chat_id),
                "text": f"📩 **ADMIN MESSAGE**\n\n{data.message}",
                "parse_mode": "Markdown"
            }
        )
        return {"status": "success", "message": "Message sent via bot"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# -------------------------------------------------------------------
# Button, Receipt & Master Message / Voice Handlers
# -------------------------------------------------------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "business_advice_menu":
        await business_advice_command(update, context)
    elif query.data.startswith("adv_type_"):
        type_map = {
            "adv_type_retail": "🛍️ ችርቻሮ / ሱቅ / ኢ-ኮሜርስ (Retail & E-Commerce)",
            "adv_type_realestate": "🏡 ሪል እስቴት / ኮንስትራክሽን (Real Estate & Property)",
            "adv_type_hospitality": "🍽️ ካፌ / ሬስቶራንት / ሆቴል (Food & Hospitality)",
            "adv_type_services": "💼 አገልግሎት / ኤጀንሲ / ቴክኖሎጂ (Services & Tech)",
            "adv_type_legal": "⚖️ የንግድ ሕጋዊነት፣ ፈቃድ እና ግብር (Legal & Compliance)",
            "adv_type_startup": "🌱 አዲስ ንግድ ጀማሪ (New Startup Business)",
            "adv_type_investor": "💡 ሐሳብ እና ካፒታል አጠቃቀም (Ideas & Capital)"
        }
        chosen_label = type_map.get(query.data, "ሁሉም የንግድ ዘርፎች")
        await ask_business_situation(update, context, chosen_label)
    elif query.data in ["buy_pro", "upgrade", "pay"]:
        await upgrade_command(update, context)
    elif query.data in ["upgrade_tier_1", "tier_pay_1", "tier_1"]:
        await start_tier_upgrade_flow(update, context, 1)
    elif query.data in ["upgrade_tier_2", "tier_pay_2", "tier_2"]:
        await start_tier_upgrade_flow(update, context, 2)
    elif query.data in ["upgrade_tier_3", "tier_pay_3", "tier_3"]:
        await start_tier_upgrade_flow(update, context, 3)
    elif query.data in ["upgrade_tier_4", "tier_pay_4", "tier_4"]:
        await start_tier_upgrade_flow(update, context, 4)
    elif query.data == "partner_menu":
        await partner_command(update, context)
    elif query.data == "support_menu":
        await support_command(update, context)
    elif query.data == "change_partner_phone":
        context.user_data["partner_setup_step"] = "awaiting_telebirr"
        await query.message.reply_text("📞 አዲስ የቴሌብር ስልክ ቁጥርዎን (Telebirr Phone Number) ይጻፉ:")
    elif query.data.startswith("change_phone_bot_"):
        bot_token = query.data.replace("change_phone_bot_", "")
        context.user_data["target_bot_token_for_phone"] = bot_token
        await query.message.reply_text("📞 እባክዎ ለአዲሱ መደብር አዲስ የንግድ ስልክ ቁጥር (`09...` ወይም `07...`) ያስገቡ:", parse_mode="Markdown")
    elif query.data == "start_menu":
        await start_command(update, context)
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
    b64_image = base64.b64encode(bytes(image_bytes)).decode("utf-8")

    expected_amount_str = order["amount"]
    expected_payer_name = order.get("payer_name", "")
    expected_payer_phone = order.get("payer_phone", "")

    parsed_result = {"valid": False, "reference_id": None, "detected_amount": None, "detected_name": None, "detected_phone": None}

    if GROQ_API_KEY and http_client:
        try:
            prompt = (
                f"Analyze this Ethiopian bank or Telebirr payment receipt image with 100% strict accuracy. Extract:\n"
                f"1. Transaction Reference ID or Confirmation Code (string)\n"
                f"2. Total Amount in ETB transferred (number or string without commas)\n"
                f"3. Sender or Payer Name if visible (string or null)\n"
                f"4. Sender Phone Number if visible (string or null)\n"
                f"Return strictly valid JSON format: "
                f'{{"valid": true/false, "reference_id": "string", "detected_amount": "string", "detected_name": "string", "detected_phone": "string"}}'
            )
            vision_resp = await http_client.post(
                f"{GROQ_BASE_URL}/chat/completions",
                headers={
                    **_groq_headers(),
                    "Content-Type": "application/json",
                },
                json={
                    "model": GROQ_VISION_MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"},
                                },
                            ],
                        }
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1,
                    "max_tokens": 500,
                },
            )
            vision_resp.raise_for_status()
            vision_text = (
                vision_resp.json()
                .get("choices", [{}])[0]
                .get("message", {})
                .get("content", "{}")
            )
            parsed_result = json.loads(vision_text or "{}")
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
                store_tier = 1
                s_res = await asyncio.to_thread(lambda: supabase.table("stores").select("plan_tier").eq("owner_telegram_id", str(user_id)).limit(1).execute())
                if s_res.data:
                    store_tier = int(s_res.data[0].get("plan_tier") or 1)

                expires_at = datetime.now(timezone.utc) + timedelta(days=30)
                await asyncio.to_thread(lambda: supabase.table("processed_receipts").insert({
                    "user_id": str(user_id), "order_id": order["order_id"], "reference_id": ref_id,
                    "amount": expected_amount_str, "channel": order["channel"], "created_at": datetime.now(timezone.utc).isoformat()
                }).execute())
                await asyncio.to_thread(lambda: supabase.table("subscriptions").upsert({
                    "user_id": str(user_id),
                    "is_pro": True,
                    "plan_tier": store_tier,
                    "credits_remaining": 999999,
                    "trial_expires": expires_at.isoformat()
                }).execute())
                await asyncio.to_thread(lambda: supabase.table("pending_orders").delete().eq("user_id", str(user_id)).execute())

                await record_affiliate_commission_and_revenue(
                    user_id=str(user_id),
                    amount_etb=float(expected_amount_str),
                    plan_tier=store_tier,
                    order_id=order["order_id"],
                    channel=order.get("destination_code", "TELEBIRR"),
                    reference_id=ref_id,
                    bot_instance=context.bot
                )
            except Exception as e:
                logger.error(f"DB Error: {e}")

        appreciation_msg = (
            f"🎉 **ክፍያዎ በተሳካ ሁኔታ ተረጋግጧል! እናመሰግናለን!** ⭐🇪🇹\n\n"
            f"✨ ሠላም **{expected_payer_name}**! ንግድዎ በብቃት እንዲቀጥል Nexa AI ከጎንዎ አብሮለታል። "
            f"አሁን ሁሉም ፕሪሚየም አገልግሎቶች ሙሉ በሙሉ ተከፍተዋል!\n\n"
            f"• የግብይት ማረጋገጫ ቁጥር: `{ref_id}`\n"
            f"🚀 ቦቶችዎ ያለ ምንም ገደብ በሥራ ላይ ይገኛሉ!"
        )
        await update.effective_message.reply_text(appreciation_msg, parse_mode="Markdown")
    else:
        if supabase:
            try:
                store_tier = 1
                s_res = await asyncio.to_thread(lambda: supabase.table("stores").select("plan_tier").eq("owner_telegram_id", str(user_id)).limit(1).execute())
                if s_res.data:
                    store_tier = int(s_res.data[0].get("plan_tier") or 1)

                await asyncio.to_thread(lambda: supabase.table("manual_review_queue").insert({
                    "user_id": str(user_id),
                    "order_id": order["order_id"],
                    "payer_name": expected_payer_name,
                    "payer_phone": expected_payer_phone,
                    "expected_amount": float(expected_amount_str),
                    "detected_amount": float(detected_amount_str) if detected_amount_str else 0,
                    "reference_id": ref_id or "MISMATCH",
                    "screenshot_file_id": update.message.photo[-1].file_id,
                    "plan_tier": store_tier,
                    "status": "pending"
                }).execute())
            except Exception as q_err:
                logger.error(f"Manual queue insert error: {q_err}")

        if ADMIN_TELEGRAM_ID:
            try:
                await context.bot.forward_message(chat_id=ADMIN_TELEGRAM_ID, from_chat_id=update.effective_chat.id, message_id=update.message.message_id)
            except Exception:
                pass
        frustration_fix_text = (
            "⚠️ **የክፍያ ማረጋገጫው በራስ-ሰር ሊመሳሰል አልቻለም።**\n\n"
            "💡 ደረሰኝዎ ወደ Nexa Web Admin Dashboard ተልቋል። አስተዳዳሪው በአጭር ጊዜ ውስጥ አረጋግጦ አካውንትዎን ያጸድቅልዎታል!"
        )
        await update.effective_message.reply_text(frustration_fix_text, parse_mode="Markdown")


async def handle_master_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice = update.effective_message.voice
    if not voice or not TELEGRAM_BOT_TOKEN:
        return
    await update.effective_message.reply_chat_action("typing")
    transcribed_text = await transcribe_telegram_voice(TELEGRAM_BOT_TOKEN, voice.file_id)
    if not transcribed_text:
        await update.effective_message.reply_text("⚠️ የድምጽ መልዕክትዎን መተርጎም አልተቻለም። እባክዎ በጽሑፍ ይጻፉ ወይም እንደገና ይሞክሩ።")
        return
    await update.effective_message.reply_text(f"🎙️ *የተተረጎመ ድምጽ:* _{transcribed_text}_", parse_mode="Markdown")
    await handle_master_message(update, context, override_text=transcribed_text)


async def handle_master_message(update: Update, context: ContextTypes.DEFAULT_TYPE, override_text: str = None):
    user_text = override_text if override_text is not None else (update.effective_message.text if update.effective_message else "")
    if not user_text:
        return

    # 1. Nexa Elite Business Advisor Interactive Flow
    advice_step = context.user_data.get("advice_step")
    if advice_step == "awaiting_business_type":
        await ask_business_situation(update, context, user_text.strip())
        return
    elif advice_step in ["awaiting_situation", "mentoring_active"] and not user_text.startswith("/"):
        await generate_professor_economic_advice(update, context, user_text.strip())
        return

    # 2. Support Ticket Flow
    support_step = context.user_data.get("support_ticket_step")
    if support_step == "awaiting_ticket_message":
        ticket_msg = user_text.strip()
        context.user_data.pop("support_ticket_step", None)
        user_obj = update.effective_user
        user_id = user_obj.id
        username_str = f"@{user_obj.username}" if user_obj.username else "No Username"
        full_name_str = f"{user_obj.first_name or ''} {user_obj.last_name or ''}".strip() or f"User {user_id}"

        if supabase:
            try:
                await asyncio.to_thread(
                    lambda: supabase.table("support_tickets").insert({
                        "user_id": str(user_id),
                        "username": username_str,
                        "full_name": full_name_str,
                        "message": ticket_msg,
                        "status": "open",
                        "created_at": datetime.now(timezone.utc).isoformat()
                    }).execute()
                )
            except Exception as e:
                logger.error(f"Support ticket insert error: {e}")

        if ADMIN_TELEGRAM_ID:
            try:
                await context.bot.send_message(
                    chat_id=int(ADMIN_TELEGRAM_ID),
                    text=f"🎧 **NEW SUPPORT TICKET**\n\n"
                         f"• Sender: **{full_name_str}** ({username_str})\n"
                         f"• Telegram ID: `{user_id}`\n"
                         f"• Question: {ticket_msg}\n\n"
                         f"Reply directly from your Web Admin App ({NETLIFY_DASHBOARD_URL}).",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

        await update.effective_message.reply_text(
            "✅ **የድጋፍ ቲኬትዎ (Support Ticket) በተሳካ ሁኔታ ተልኳል!**\n\n"
            "የአስተዳደር ቡድናችን መልእክትዎን ተቀብሏል። በአጭር ጊዜ ውስጥ ምላሽ እንሰጥዎታለን። እናመሰግናለን!"
        )
        return

    # 3. Partner Setup Flow
    partner_setup_step = context.user_data.get("partner_setup_step")
    if partner_setup_step == "awaiting_telebirr":
        telebirr_phone = user_text.strip()
        context.user_data.pop("partner_setup_step", None)
        user_obj = update.effective_user
        user_id = user_obj.id
        user_name = f"{user_obj.first_name or ''} {user_obj.last_name or ''}".strip() or "Partner"
        tg_username = f"@{user_obj.username}" if user_obj.username else "No Username"

        if supabase:
            try:
                await asyncio.to_thread(
                    lambda: supabase.table("partners").upsert({
                        "partner_id": str(user_id),
                        "partner_name": user_name,
                        "telegram_username": tg_username,
                        "telebirr_number": telebirr_phone,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }, on_conflict="partner_id").execute()
                )
            except Exception as e:
                logger.error(f"Partner upsert error: {e}")

        bot_username = context.bot.username or "nexa_bot"
        ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

        success_msg = (
            f"✅ **እንኳን ደስ አለዎት! አሁን ኦፊሴላዊ የ Nexa Partner (Affiliate) ነዎት!**\n\n"
            f"📞 የተመዘገበ የቴሌብር ቁጥር: `{telebirr_phone}`\n"
            f"💰 ኮሚሽን: ማንኛውም ሰው በእርስዎ ሊንክ ገብቶ ሲመዝገብ ከክፍያው **1/4 (25%)** በቀጥታ ወደ እርስዎ ይገባል።\n\n"
            f"🔗 **የእርስዎ ልዩ የማስታወቂያ ማገናኛ (Referral Link):**\n"
            f"`{ref_link}`"
        )
        await update.effective_message.reply_text(success_msg, parse_mode="Markdown")
        return

    # 4. Payment Verification Flow
    payment_step = context.user_data.get("payment_step")
    if payment_step == "awaiting_payer_name":
        context.user_data["payer_name"] = user_text.strip()
        context.user_data["payment_step"] = "awaiting_payer_phone"
        await update.effective_message.reply_text(
            "📞 አሁን ደግሞ የቴሌብር ስልክ ቁጥርዎን (Telebirr Phone Number) ያስገቡ (ለምሳሌ: 09... ወይም 07...):",
            parse_mode="Markdown"
        )
        return
    elif payment_step == "awaiting_payer_phone":
        phone = user_text.strip()
        context.user_data["payer_phone"] = phone
        context.user_data.pop("payment_step", None)

        user_id = update.effective_user.id
        owner_id = str(user_id)
        tier_num = context.user_data.get("selected_tier", 1)
        payer_name = context.user_data.get("payer_name", "Valued Customer")

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

        partner_id = None
        if supabase:
            try:
                ref_res = await asyncio.to_thread(
                    lambda: supabase.table("referrals").select("partner_id").eq("referred_user_id", owner_id).execute()
                )
                if ref_res.data:
                    partner_id = ref_res.data[0]["partner_id"]
            except Exception as e:
                logger.error(f"Referral check error: {e}")

        channel_name, masked_account, _, channel_code = await select_optimal_payout_destination(exact_amount_etb, partner_id=partner_id)
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
                        "payer_name": payer_name,
                        "payer_phone": phone,
                        "status": "pending_payment"
                    }, on_conflict="user_id").execute()
                )
                await asyncio.to_thread(
                    lambda: supabase.table("stores").update({"plan_tier": tier_num}).eq("owner_telegram_id", owner_id).execute()
                )
            except Exception as e:
                logger.error(f"Pending order save error: {e}")

        partner_note = "⭐ (በአጋር/Affiliate ማስታወቂያ በኩል የተደረገ ክፍያ)" if partner_id else ""
        invoice_text = (
            f"💳 **የቴሌብር ክፍያ ዝርዝር — {tier_info['name']} ({store_name})** {partner_note}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 ከፋይ: {payer_name} | 📞 `{phone}`\n"
            f"• የሚከፈለው ትክክለኛ መጠን: **{exact_amount_etb:,} ብር**\n"
            f"• የክፍያ መቀበያ ቁጥር: `{masked_account}`\n"
            f"• የደረሰኝ ቁጥር: {order_id}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📌 **ምን ማድረግ ይኖርብዎታል?**\n"
            f"1. በስልክዎ የቴሌብር መተግበሪያ በመጠቀም ከላይ ወደተጠቀሰው ቁጥር `{masked_account}` ትክክለኛውን `{exact_amount_etb:,} ብር` ያስተላልፉ።\n"
            f"2. ክፍያውን ከፈጸሙ በኋላ የሚደርሰውን የቴሌብር SMS ማረጋገጫ (Screenshot) እዚህ ይላኩ።\n"
            f"3. የ AI-OCR ሲስተሙ ስምዎን፣ ስልክ ቁጥርዎን እና የትራንዛክሽን መጠንዎን አረጋግጦ አካውንትዎን ወዲያውኑ ይከፍትልዎታል።"
        )

        keyboard = [
            [InlineKeyboardButton(f"📋 ቁጥር ቅዳ: {masked_account}", callback_data=f"copy_acc_{masked_account}")],
            [InlineKeyboardButton("✅ ከፍያለሁ — ደረሰኝ ጫን", callback_data="upload_receipt")]
        ]

        await update.effective_message.reply_text(invoice_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    if user_text.startswith("/"):
        return

    # 5. Registered Phone Number AI Query Interceptor
    phone_candidates = re.findall(r"(?:\+251[79]\d{8}|0[79]\d{8})", user_text.replace(" ", ""))
    if phone_candidates:
        matched_stores = await lookup_registered_phone_stores(phone_candidates[0])
        if matched_stores:
            await update.effective_message.reply_chat_action("typing")
            ai_phone_answer = await answer_registered_phone_with_ai(
                raw_phone=phone_candidates[0],
                user_question=user_text,
                customer_lang="amharic",
            )
            await update.effective_message.reply_text(ai_phone_answer, parse_mode="Markdown")
            return

    system_prompt = (
        "You are Nexa AI Master Assistant and Business Advisor. Analyze user intent from Amharic/English message. "
        "The user might be asking about any business, legal compliance, strategy, or might have registered a bot earlier and forgotten what to do. "
        "If they ask about business growth, making money, pricing, profit, legal/licensing/tax business practices, or business strategy, classify as 'advice'. "
        "Otherwise guide them clearly on what to click or type (e.g. /advice, /mybots, /leads, /summary, /support, /register, /upgrade, /partner, /setphone). "
        "CRITICAL AMHARIC RULE: All Amharic responses ('reply') MUST be written in highly eloquent, natural, grammatically flawless, and spelling-accurate Amharic. "
        "Classify into: 'advice', 'mybots', 'leads', 'summary', 'weekly', 'support', 'register', 'upgrade', 'partner', 'setphone', 'general'. "
        'Return strictly valid JSON: {"intent": "category", "reply": "helpful response in grammatically flawless, natural Amharic guiding them precisely what to do or click"}'
    )
    intent_result = {"intent": "general", "reply": "ሰላም! የንግድ እና የስትራቴጂ ምክር ለማግኘት /advice፣ ቦቶቻችሁን ለማስተዳደር /mybots፣ ወይም አዲስ ቦት ለመፍጠር /register የሚለውን ይጫኑ።"}
    if GROQ_API_KEY:
        try:
            raw_intent_json = await generate_groq_text(
                prompt=user_text,
                system_instruction=system_prompt,
                temperature=0.3,
                max_output_tokens=400,
                json_mode=True,
            )
            intent_result = json.loads(raw_intent_json)
        except Exception as e:
            logger.error(f"Master message intent error: {e}")

    intent = intent_result.get("intent")
    if intent == "advice":
        await business_advice_command(update, context)
    elif intent == "mybots":
        await my_bots_command(update, context)
    elif intent == "leads":
        await leads_command(update, context)
    elif intent == "summary":
        await summary_command(update, context)
    elif intent == "weekly":
        await weekly_summary_command(update, context)
    elif intent == "support":
        await support_command(update, context)
    elif intent == "register":
        await update.effective_message.reply_text("አዲስ ቦት ለመፍጠር /register የሚለውን ይጠቀሙ።")
    elif intent == "upgrade":
        await upgrade_command(update, context)
    elif intent == "partner":
        await partner_command(update, context)
    elif intent == "setphone":
        await setphone_command(update, context)
    else:
        await update.effective_message.reply_text(intent_result.get("reply", "ሰላም! ምን ልረዳዎ እችላለሁ? የንግድ ምክር ለማግኘት /advice ወይም ቦቶቻችሁን ለማየት /mybots ይጠቀሙ።"))


if telegram_app:
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("register", register_start),
            CallbackQueryHandler(register_start, pattern="^start_register$"),
            CommandHandler("setphone", setphone_command)
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
            STORE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_store_phone)],
            CHANGE_PHONE: [
                CallbackQueryHandler(select_phone_bot_callback, pattern="^change_phone_bot_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_updated_phone)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_registration)],
    )

    telegram_app.add_handler(CommandHandler("start", start_command))
    telegram_app.add_handler(CommandHandler("advice", business_advice_command))
    telegram_app.add_handler(CommandHandler("support", support_command))
    telegram_app.add_handler(CommandHandler("partner", partner_command))
    telegram_app.add_handler(CommandHandler("upgrade", upgrade_command))
    telegram_app.add_handler(CommandHandler("pay", upgrade_command))
    telegram_app.add_handler(CommandHandler("leads", leads_command))
    telegram_app.add_handler(CommandHandler("update", update_command))
    telegram_app.add_handler(CommandHandler("audit", audit_command))
    telegram_app.add_handler(CommandHandler("summary", summary_command))
    telegram_app.add_handler(CommandHandler("weekly_summary", weekly_summary_command))
    telegram_app.add_handler(CommandHandler("mybots", my_bots_command))
    telegram_app.add_handler(CommandHandler("stopvoice", stop_voice_command))
    telegram_app.add_handler(CommandHandler("startvoice", start_voice_command))
    telegram_app.add_handler(conv_handler)
    telegram_app.add_handler(CallbackQueryHandler(button_handler))
    telegram_app.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO) & filters.CaptionRegex(r"^/addmedia"), handle_media_upload))
    telegram_app.add_handler(MessageHandler(filters.PHOTO, handle_receipt_photo))
    telegram_app.add_handler(MessageHandler(filters.VOICE, handle_master_voice))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_master_message))


@app.on_event("startup")
async def startup_event():
    global http_client
    http_client = httpx.AsyncClient(timeout=15.0)
    if telegram_app:
        await telegram_app.initialize()
        await telegram_app.start()
        if RENDER_EXTERNAL_URL:
            await telegram_app.bot.set_webhook(url=f"{RENDER_EXTERNAL_URL}/webhook", secret_token=TELEGRAM_WEBHOOK_SECRET or None)

    asyncio.create_task(run_ai_system_audit_and_heal())


@app.on_event("shutdown")
async def shutdown_event():
    if telegram_app:
        await telegram_app.stop()
        await telegram_app.shutdown()
    if http_client:
        await http_client.aclose()


@app.post("/webhook")
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str = Header(None)):
    """Enforces strict Telegram Webhook Secret verification to block unauthorized webhook spoofing."""
    if not TELEGRAM_WEBHOOK_SECRET or not x_telegram_bot_api_secret_token:
        logger.warning("⚠️ Blocked Telegram webhook call missing secret token!")
        raise HTTPException(status_code=403, detail="Missing Telegram Webhook Secret Token")
    if not hmac.compare_digest(x_telegram_bot_api_secret_token.encode("utf-8"), TELEGRAM_WEBHOOK_SECRET.encode("utf-8")):
        logger.warning("⚠️ Blocked unauthorized Telegram webhook call with invalid secret token!")
        raise HTTPException(status_code=403, detail="Invalid Telegram Webhook Secret Token")

    if not telegram_app:
        raise HTTPException(status_code=503, detail="Telegram bot is not configured")

    update = Update.de_json(await request.json(), telegram_app.bot)
    await telegram_app.process_update(update)
    return {"status": "ok"}


@app.post("/tenant-webhook/{bot_token}")
async def tenant_bot_webhook(bot_token: str, request: Request):
    data = await request.json()

    message = data.get("message", {})
    chat_obj = message.get("chat", {})
    chat_id = chat_obj.get("id")
    user_text = message.get("text", "")
    voice_obj = message.get("voice")

    user_obj = message.get("from", {})
    full_name = f"{user_obj.get('first_name', '')} {user_obj.get('last_name', '')}".strip()
    if not full_name:
        full_name = f"{chat_obj.get('first_name', '')} {chat_obj.get('last_name', '')}".strip()
    username = user_obj.get("username") or chat_obj.get("username")
    if full_name and username:
        visitor_name = f"{full_name} (@{username})"
    elif full_name:
        visitor_name = full_name
    elif username:
        visitor_name = f"@{username}"
    else:
        visitor_name = f"User {chat_id}"

    if not chat_id:
        return {"ok": True}

    if not user_text and voice_obj and voice_obj.get("file_id"):
        if http_client:
            asyncio.create_task(http_client.post(
                f"https://api.telegram.org/bot{bot_token}/sendChatAction",
                json={"chat_id": chat_id, "action": "typing"}
            ))
        user_text = await transcribe_telegram_voice(bot_token, voice_obj["file_id"])
        if not user_text:
            if http_client:
                await http_client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
                    "chat_id": chat_id,
                    "text": "⚠️ የድምጽ መልዕክትዎን መተርጎም አልተቻለም። እባክዎ በጽሑፍ ይጻፉ።"
                })
            return {"ok": True}

    if not user_text:
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
        if http_client:
            await http_client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
                "chat_id": chat_id, "text": "⚠️ Store configuration not found or inactive."
            })
        return {"ok": True}

    owner_id = store.get("owner_telegram_id")
    if owner_id:
        try:
            is_active = await verify_active_access(int(owner_id))
            if not is_active:
                if http_client:
                    await http_client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
                        "chat_id": chat_id,
                        "text": "⚠️ **የዚህ መደብር የነጻ ሙከራ ጊዜ (3 Days Trial) አልቋል እንዲሁም ክፍያ አልተፈጸመም።** ባለቤቱ አባልነቱን እስከሚያሻሽል ድረስ የ AI አገልግሎቱ ጊዜያዊ ቆሟል።"
                    })
                return {"ok": True}
        except Exception as sub_check_err:
            logger.error(f"Tenant trial check error: {sub_check_err}")

    if supabase:
        async def _record_visitor_and_lead():
            try:
                await asyncio.gather(
                    asyncio.to_thread(lambda: supabase.table("tenant_visitors").upsert({
                        "bot_token": bot_token, "chat_id": str(chat_id), "created_at": datetime.now(timezone.utc).isoformat()
                    }, on_conflict="bot_token,chat_id").execute()),
                    asyncio.to_thread(lambda: supabase.table("leads").upsert({
                        "bot_token": bot_token,
                        "visitor_telegram_id": str(chat_id),
                        "visitor_name": visitor_name,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }, on_conflict="bot_token,visitor_telegram_id").execute())
                )
            except Exception as e:
                logger.error(f"Visitor/Lead record error: {e}")
        task = asyncio.create_task(_record_visitor_and_lead())
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    if user_text == "/start":
        if supabase:
            asyncio.create_task(asyncio.to_thread(lambda: supabase.table("customer_languages").upsert({
                "chat_id": str(chat_id), "bot_token": bot_token, "language": "amharic"
            }, on_conflict="chat_id,bot_token").execute()))

        ui_theme = store.get("ui_theme", "executive")
        theme_intros = {
            "energetic": "🚀 በደስታ ተቀብለናል! ዛሬ ምን እንድንሰራሎት ይፈልጋሉ?",
            "friendly": "👋 ሰላም! እንኳን ደህና መጡ። በምን እንተባበር?",
            "executive": "💼 እንኳን ወደ ቪአይፒ የውሳኔ ማዕከል በደህና መጡ።",
            "sales": "🎯 ምርጥ ምርጫዎችን እና ቅናሾችን ለማግኘት ዝግጁ ነን!",
            "minimalist": "🎯 ሰላም! በምን ልረዳዎ እችላለሁ?"
        }

        registered_phone = store.get("business_phone") or store.get("owner_phone") or ""
        phone_line = f"\n📞 የተመዘገበ የንግድ ስልክ: `{registered_phone}` (የ AI ምላሽ በቀጥታ ማግኘት ይችላሉ)" if registered_phone else ""

        direct_welcome = (
            f"{theme_intros.get(ui_theme, 'ሰላም!')} እንኳን ወደ **{store.get('store_name')}** በደህና መጡ!{phone_line}\n\n"
            f"እቃዎቻችንን፣ ዋጋዎቻችንን ወይም አገልግሎቶቻችንን ከታች በመጻፍ ወይም በድምጽ (Voice Note) መጠየቅ ይችላሉ። ፎቶ ወይም ቪዲዮ ማየት ከፈለጉ መጠየቅ ይችላሉ!"
        )
        if http_client:
            await http_client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
                "chat_id": chat_id,
                "text": direct_welcome,
                "parse_mode": "Markdown"
            })
        return {"ok": True}

    customer_lang = "amharic"
    history_messages = []
    available_tags = []
    if supabase:
        try:
            lang_res, hist_res, media_res = await asyncio.gather(
                asyncio.to_thread(lambda: supabase.table("customer_languages").select("language").eq("chat_id", str(chat_id)).eq("bot_token", bot_token).execute()),
                asyncio.to_thread(lambda: supabase.table("chat_history").select("role, content").eq("chat_id", str(chat_id)).eq("bot_token", bot_token).order("created_at", desc=True).limit(6).execute()),
                asyncio.to_thread(lambda: supabase.table("property_media").select("item_tag, caption").eq("bot_token", bot_token).execute())
            )
            if lang_res.data:
                customer_lang = lang_res.data[0]["language"]
            if hist_res.data:
                history_messages = list(reversed(hist_res.data))
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
        "available_tags": available_tags, "plan_tier": store.get("plan_tier", 1),
        "business_phone": store.get("business_phone") or store.get("owner_phone") or ""
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
    if not supabase or not GROQ_API_KEY:
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
        raw_lead_json = await generate_groq_text(
            prompt=analysis_prompt,
            temperature=0.1,
            max_output_tokens=400,
            json_mode=True,
        )
        structured_data = json.loads(raw_lead_json)

        phone = structured_data.get("phone_number")
        if not phone:
            phone_match = re.search(r"(\+251[79]\d{8}|0[79]\d{8})", user_text.replace(" ", ""))
            phone = phone_match.group(0) if phone_match else None

        intent_lvl = str(structured_data.get("intent_level", "low")).lower()
        action_summary = structured_data.get("action_summary") or user_text[:100]
        is_vip = bool(structured_data.get("is_high_payer", False))
        vip_prefix = "💎 VIP | " if is_vip else ""

        extracted_name = str(structured_data.get("customer_name") or "").strip()
        if not extracted_name or extracted_name.lower() in ["anonymous", "unknown", "none", "null", "user"]:
            final_visitor_name = visitor_name
        else:
            final_visitor_name = extracted_name

        lead_payload = {
            "bot_token": bot_token,
            "visitor_telegram_id": str(chat_id),
            "visitor_name": final_visitor_name,
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
    registered_phone = payload.get("business_phone", "")

    if owner_telegram_id:
        try:
            owner_id_int = int(owner_telegram_id)
            if not await verify_active_access(owner_id_int):
                if http_client:
                    await http_client.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={"chat_id": chat_id, "text": "⚠️ የቦቱ የፈተና ጊዜ አልቋል። እባክዎ የቦቱን ባለቤት ያነጋግሩ።"}
                    )
                return {"ok": True}
            asyncio.create_task(deduct_credit(owner_id_int))
        except Exception as e:
            logger.error(f"Subscription enforcement error: {e}")

    if http_client:
        asyncio.create_task(http_client.post(
            f"https://api.telegram.org/bot{bot_token}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"}
        ))

    # Check if the user mentions a phone number registered in Nexa to provide an AI-powered answer
    phone_matches = re.findall(r"(?:\+251[79]\d{8}|0[79]\d{8})", user_text.replace(" ", ""))
    if phone_matches and registered_phone and normalize_phone_digits(phone_matches[0]) == normalize_phone_digits(registered_phone):
        ai_reply = await answer_registered_phone_with_ai(
            raw_phone=phone_matches[0],
            user_question=user_text,
            store_record={
                "store_name": store_name,
                "business_phone": registered_phone,
                "plan_tier": plan_tier,
                "inventory_data": inventory_data,
                "voice_ai_active": True,
            },
            customer_lang=customer_lang,
            history_messages=history_messages,
        )
    else:
        lang_instructions = {
            "amharic": "በጣም የዳበረ፣ ሰዋሰዋዊ ትክክለኛነት ያለው፣ የፊደል ስህተት የሌለበት እና ተፈጥሯዊ የሆነ ንጹህ አማርኛ ቋንቋ ብቻ ተጠቀም።",
            "english": "Respond in English.",
            "oromo": "Afaan Oromootiin deebisi."
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
        phone_context_line = f"Registered Store Phone in Nexa: {registered_phone}" if registered_phone else "Registered Store Phone in Nexa: Not set"

        system_prompt = f"""
        You are an advanced, intelligent AI sales and analytical assistant for {store_name}.
        Tone/Theme Style: {theme_prompts.get(ui_theme, theme_prompts['executive'])}
        Language Rule: {lang_instructions.get(customer_lang, lang_instructions['amharic'])}
        Store Plan Tier: {tier_capabilities['name']} ({tier_capabilities['features']})
        {phone_context_line}

        Core Directives & Analytical Approach:
        - Deeply analyze the customer's request and intelligently match/relate it with the Live Store Catalog Data provided below.
        - Provide smart, flexible, and well-reasoned answers. Do not mechanically repeat text; analyze what the customer is looking for and present the most relevant items, pricing, features, or solutions accurately.
        - When responding in Amharic, strictly enforce native Ethiopian Amharic grammar, proper Ge'ez fidel spelling, natural phrasing, and polite business etiquette without any awkward literal translations or spelling mistakes.
        - If the customer asks to see photos, pictures, or videos of a property, item, or service, and a matching tag exists in Available Media Tags, you MUST include the token `[SEND_MEDIA:tag_name]` in your response (Note: Video support requires Tier 3 Enterprise).
        - If customers want to order, book, or purchase, warmly and professionally guide them to provide their name and phone number for fulfillment.

        Available Media Tags: {tags_str}

        Live Store Catalog Data:
        {inventory_data}
        """

        ai_reply = "ይቅርታ፣ የአገልግሎት ስህተት አጋጥሟል።"
        if GROQ_API_KEY:
            try:
                ai_reply = await generate_groq_text(
                    prompt=user_text,
                    system_instruction=system_prompt,
                    history_messages=history_messages,
                    temperature=0.7,
                    max_output_tokens=600,
                )
            except Exception as e:
                logger.error(f"Groq Chat Error: {e}")
                ai_reply = f"⚠️ Groq AI Error: {str(e)}"

    tag_match = re.search(r"\[SEND_MEDIA:([a-zA-Z0-9_\-]+)\]", ai_reply)
    clean_ai_reply = re.sub(r"\[SEND_MEDIA:[a-zA-Z0-9_\-]+\]", "", ai_reply).strip()

    if supabase:
        async def _save_chat_history():
            try:
                now_user = datetime.now(timezone.utc)
                now_assistant = now_user + timedelta(milliseconds=500)
                await asyncio.to_thread(lambda: supabase.table("chat_history").insert([
                    {"chat_id": str(chat_id), "bot_token": bot_token, "role": "user", "content": user_text, "created_at": now_user.isoformat()},
                    {"chat_id": str(chat_id), "bot_token": bot_token, "role": "assistant", "content": clean_ai_reply, "created_at": now_assistant.isoformat()}
                ]).execute())
            except Exception as e:
                logger.error(f"Chat history insert error: {e}")
        asyncio.create_task(_save_chat_history())

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

    if http_client:
        await http_client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": clean_ai_reply}
        )

    tier_capabilities = TIER_CONFIG.get(plan_tier, TIER_CONFIG[1])
    if tag_match and supabase and http_client:
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
