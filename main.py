import logging
import requests
import json
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes, ConversationHandler
)

# ─────────────────────────── إعدادات ───────────────────────────
API_TOKEN     = '8916614014:AAEZTYF3IZigS1iqL-5qMoVcvvJfEduZYXw'
CLIENT_ID     = "87pIExRhxBb3_wGsA5eSEfyATloa"
CLIENT_SECRET = "uf82p68Bgisp8Yg1Uz8Pf6_v1XYa"
BASE_URL      = "https://apim.djezzy.dz"
SESSIONS_FILE    = "sessions.json"
MODERATORS_FILE  = "moderators.json"
BANNED_FILE      = "banned.json"
MAINTENANCE_FILE = "maintenance.json"

PROXY_URL = "http://VOdU7NxiOv20_custom_zone_DZ_st__city_sid_23611181_time_90:3149931@change6.owlproxy.com:7778"
PROXIES   = {"http": PROXY_URL, "https": PROXY_URL}

HEADERS = {
    "User-Agent": "MobileApp/3.0.4",
    "accept-language": "fr",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

GIFT_DURATION_H = 7 * 24   # الهدية الأسبوعية = 7 أيام

# ─────────────────────────── الإدارة ───────────────────────────
ADMIN_IDS = {7646668945}  # معرفات الأدمن المسموح لهم

# جميع العروض: (كود الباقة، الاسم، المدة بالساعات)
OFFERS = {
    "OFF_300MO":   ("DOVINTSPEEDDAY100MoPRE",    "📶 300 MO يومية",         24),
    "OFF_2GB":     ("BTLINTSPEEDDAY2Go",          "🌐 2GB يومية",            24),
    "OFF_5GB":     ("DOVINTSPEEDDAY5GoPRE5G",     "⚡ IMTYAZE 5GB يومية",    24),
    "OFF_4GBW":    ("DOVINTSPEEDWEEK2GoPRE",      "🚀 4GB أسبوعية",          7*24),
    "OFF_10GBW":   ("DOVINTSPEEDWEEK3GoPRE",      "💎 10GB أسبوعية",         7*24),
    "OFF_30GBM":   ("DOVINTSPEEDMONTH30GoPRE",    "🔥 30GB شهرية",           30*24),
    "OFF_100GBM":  ("DOVINTSPEEDMONTH100GoPRE5G", "👑 100GB شهرية 5G",       30*24),
}

# ─────────────────────────── حالات المحادثة ───────────────────────────
SELECT_ACCOUNT, PHONE, OTP, MAIN_MENU, REFERRAL_PHONE, REAUTH_OTP, ADMIN_BROADCAST, BAN_INPUT = range(8)

# مجموعة لحماية من النقر المزدوج (uid + callback_data)
_processing: set[str] = set()

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
#  تخزين الجلسات (sessions.json)
# ══════════════════════════════════════════════════════════════
def load_sessions() -> dict:
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_sessions(data: dict):
    tmp = SESSIONS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SESSIONS_FILE)


def get_user_sessions(uid: str) -> dict:
    return load_sessions().get(uid, {"accounts": {}, "active": None})


# ── المشرفون ──
def load_moderators() -> set:
    if os.path.exists(MODERATORS_FILE):
        try:
            with open(MODERATORS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def save_moderators(mods: set):
    tmp = MODERATORS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(list(mods), f)
    os.replace(tmp, MODERATORS_FILE)


def is_moderator(uid: str) -> bool:
    return is_admin(uid) or uid in load_moderators()


def add_moderator(uid: str):
    mods = load_moderators()
    mods.add(uid)
    save_moderators(mods)


def remove_moderator(uid: str):
    mods = load_moderators()
    mods.discard(uid)
    save_moderators(mods)


# ── المحظورون ──
def load_banned() -> set:
    if os.path.exists(BANNED_FILE):
        try:
            with open(BANNED_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def save_banned(banned: set):
    tmp = BANNED_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(list(banned), f)
    os.replace(tmp, BANNED_FILE)


def is_banned(uid: str) -> bool:
    return uid in load_banned()


def ban_user(uid: str):
    banned = load_banned()
    banned.add(uid)
    save_banned(banned)


def unban_user(uid: str):
    banned = load_banned()
    banned.discard(uid)
    save_banned(banned)


def get_uid_by_phone(msisdn: str) -> str | None:
    """يجد Telegram UID من رقم الهاتف في sessions.json"""
    data = load_sessions()
    for user_id, user in data.items():
        if msisdn in user.get("accounts", {}):
            return user_id
    return None


# ── الصيانة ──
def load_maintenance() -> bool:
    if os.path.exists(MAINTENANCE_FILE):
        try:
            with open(MAINTENANCE_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("enabled", False)
        except Exception:
            pass
    return False


def set_maintenance(enabled: bool):
    tmp = MAINTENANCE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"enabled": enabled}, f)
    os.replace(tmp, MAINTENANCE_FILE)


# ── سجل العمليات ──
def save_history(uid: str, msisdn: str, op_type: str, name: str):
    data = load_sessions()
    if uid not in data or msisdn not in data[uid].get("accounts", {}):
        return
    hist = data[uid]["accounts"][msisdn].setdefault("history", [])
    hist.insert(0, {"type": op_type, "name": name, "ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M")})
    data[uid]["accounts"][msisdn]["history"] = hist[:15]
    save_sessions(data)


def get_history(uid: str, msisdn: str) -> list:
    data = load_sessions()
    try:
        return data[uid]["accounts"][msisdn].get("history", [])
    except Exception:
        return []


def format_history(uid: str, msisdn: str) -> str:
    hist = get_history(uid, msisdn)
    if not hist:
        return "📜 لا توجد عمليات مسجّلة بعد."
    lines = [
        "╔══════════════════════╗\n"
        "║   📜  سجل العمليات   ║\n"
        "╚══════════════════════╝\n"
    ]
    icons = {"gift": "🎁", "offer": "🏷️", "referral": "🔗", "invite": "📨"}
    for i, entry in enumerate(hist, 1):
        icon = icons.get(entry.get("type", ""), "•")
        lines.append(f"{i}. {icon} {entry.get('name', '—')}\n   🕐 {entry.get('ts', '')}")
    return "\n".join(lines)


def save_account(uid: str, msisdn: str, token: str, refresh_token: str = ""):
    data = load_sessions()
    if uid not in data:
        data[uid] = {"accounts": {}, "active": None}
    name = "مستخدم " + msisdn[-4:]
    if msisdn not in data[uid]["accounts"]:
        data[uid]["accounts"][msisdn] = {"token": token, "refresh_token": refresh_token, "name": name, "gift_activated": None}
    else:
        data[uid]["accounts"][msisdn]["token"] = token
        if refresh_token:
            data[uid]["accounts"][msisdn]["refresh_token"] = refresh_token
    data[uid]["active"] = msisdn
    save_sessions(data)


def set_active_account(uid: str, msisdn: str):
    data = load_sessions()
    if uid in data:
        data[uid]["active"] = msisdn
        save_sessions(data)


def save_activation(uid: str, msisdn: str, key: str):
    data = load_sessions()
    if uid in data and msisdn in data[uid]["accounts"]:
        acts = data[uid]["accounts"][msisdn].setdefault("activations", {})
        acts[key] = datetime.utcnow().isoformat()
        save_sessions(data)


def get_remaining(uid: str, msisdn: str, key: str, duration_h: int) -> str | None:
    """الوقت المتبقي لأي باقة، أو None إذا انتهت أو لم تُفعَّل من البوت"""
    data = load_sessions()
    try:
        acts = data[uid]["accounts"][msisdn].get("activations", {})
        ts   = acts.get(key)
        if not ts:
            return None
        activated_at = datetime.fromisoformat(ts)
        expires_at   = activated_at + timedelta(hours=duration_h)
        remaining    = expires_at - datetime.utcnow()
        if remaining.total_seconds() <= 0:
            return None
        mins  = int(remaining.total_seconds() // 60)
        h, m  = divmod(mins, 60)
        d, h  = divmod(h, 24)
        parts = []
        if d: parts.append(f"{d} يوم")
        if h: parts.append(f"{h} ساعة")
        if m: parts.append(f"{m} دقيقة")
        return " و ".join(parts) or "أقل من دقيقة"
    except Exception:
        return None


def get_gift_remaining(uid: str, msisdn: str) -> str | None:
    return get_remaining(uid, msisdn, "GIFT", GIFT_DURATION_H)


def fetch_gift_history(msisdn: str, token: str) -> str | None:
    """
    يجلب تاريخ آخر تفعيل للهدية من سيرفر جيزي مباشرةً.
    يُرجع نص الوقت المتبقي، أو None إذا انتهى الأسبوع أو لا يوجد سجل.
    """
    try:
        res, code = djezzy_api("GET", f"subscribers/subscription-history/{msisdn}", token)
        if code != 200 or not res:
            return None
        items = res.get("data", [])
        if not isinstance(items, list):
            return None
        last_dt = None
        for item in items:
            if item.get("packageCode") == "GIFTWALKWIN2GO":
                raw_dt = item.get("subscriptionDateTime", "")
                # تنسيق: "2025-06-01T12:34:56" أو مع timezone
                raw_dt = raw_dt[:19]  # أخذ أول 19 حرف فقط
                try:
                    last_dt = datetime.strptime(raw_dt, "%Y-%m-%dT%H:%M:%S")
                except Exception:
                    continue
                break  # أول نتيجة هي الأحدث
        if not last_dt:
            return None
        expires_at = last_dt + timedelta(hours=GIFT_DURATION_H)
        remaining  = expires_at - datetime.utcnow()
        if remaining.total_seconds() <= 0:
            return None
        mins = int(remaining.total_seconds() // 60)
        h, m = divmod(mins, 60)
        d, h = divmod(h, 24)
        parts = []
        if d: parts.append(f"{d} يوم")
        if h: parts.append(f"{h} ساعة")
        if m: parts.append(f"{m} دقيقة")
        return " و ".join(parts) or "أقل من دقيقة"
    except Exception as e:
        logger.error(f"fetch_gift_history error: {e}")
        return None


# ══════════════════════════════════════════════════════════════
#  طلبات API جيزي
# ══════════════════════════════════════════════════════════════
def send_otp(msisdn: str) -> tuple[int, str]:
    url    = f"{BASE_URL}/mobile-api/oauth2/registration"
    params = {"msisdn": msisdn, "client_id": CLIENT_ID, "scope": "smsotp"}
    body   = {"consent-agreement": [{"marketing-notifications": False}], "is-consent": True}
    try:
        res = requests.post(url, params=params, json=body, headers=HEADERS, proxies=PROXIES, timeout=15)
        logger.info(f"send_otp [{res.status_code}]: {res.text[:200]}")
        return res.status_code, res.text
    except Exception as e:
        logger.error(f"send_otp error: {e}")
        return 500, str(e)


def verify_otp(msisdn: str, otp: str) -> tuple[dict | None, int]:
    url     = f"{BASE_URL}/mobile-api/oauth2/token"
    headers = {**HEADERS, "Content-Type": "application/x-www-form-urlencoded"}
    data    = (f"otp={otp}&mobileNumber={msisdn}&scope=djezzyAppV2"
               f"&client_id={CLIENT_ID}&client_secret={CLIENT_SECRET}&grant_type=mobile")
    try:
        res = requests.post(url, data=data, headers=headers, proxies=PROXIES, timeout=15)
        return res.json(), res.status_code
    except Exception as e:
        logger.error(f"verify_otp error: {e}")
        return None, 500


def refresh_access_token(msisdn: str, refresh_token: str) -> tuple[str | None, str | None]:
    """
    يجدّد التوكن باستخدام refresh_token دون الحاجة لـ OTP.
    يُرجع (access_token_جديد, refresh_token_جديد) أو (None, None) عند الفشل.
    """
    url     = f"{BASE_URL}/mobile-api/oauth2/token"
    headers = {**HEADERS, "Content-Type": "application/x-www-form-urlencoded"}
    data    = (f"grant_type=refresh_token&refresh_token={refresh_token}"
               f"&client_id={CLIENT_ID}&client_secret={CLIENT_SECRET}")
    try:
        res = requests.post(url, data=data, headers=headers, proxies=PROXIES, timeout=15)
        logger.info(f"refresh_token [{msisdn}] [{res.status_code}]: {res.text[:200]}")
        if res.status_code == 200:
            j = res.json()
            return j.get("access_token"), j.get("refresh_token", refresh_token)
        return None, None
    except Exception as e:
        logger.error(f"refresh_access_token error [{msisdn}]: {e}")
        return None, None


def djezzy_api(method: str, endpoint: str, token: str, body: dict = None) -> tuple[dict | None, int]:
    url     = f"{BASE_URL}/mobile-api/api/v1/{endpoint}"
    headers = {**HEADERS, "Authorization": f"Bearer {token}"}
    try:
        if method == "GET":
            res = requests.get(url, headers=headers, proxies=PROXIES, timeout=15)
        else:
            res = requests.post(url, headers=headers, json=body, proxies=PROXIES, timeout=15)
        logger.info(f"API {method} {endpoint} [{res.status_code}]: {res.text[:200]}")
        return res.json(), res.status_code
    except Exception as e:
        logger.error(f"djezzy_api error: {e}")
        return None, 500


# ══════════════════════════════════════════════════════════════
#  مساعدات الواجهة
# ══════════════════════════════════════════════════════════════
def fmt_phone(msisdn: str) -> str:
    return "0" + msisdn[3:] if msisdn.startswith("213") else msisdn


def clean_phone(raw: str) -> str | None:
    """
    يُنظّف رقم الهاتف ويتحقق منه.
    يقبل: 0770123456 / 770123456 / +213770123456 / 213770123456
    يُرجع الرقم بصيغة 213xxxxxxxxx أو None إذا كان خاطئاً.
    """
    p = raw.strip().replace(" ", "").replace("-", "").replace(".", "")
    if p.startswith("+213"):
        p = "213" + p[4:]
    elif p.startswith("00213"):
        p = "213" + p[5:]
    elif p.startswith("213") and len(p) == 12:
        pass
    elif p.startswith("0") and len(p) == 10:
        p = "213" + p[1:]
    elif len(p) == 9 and p.startswith("7"):
        p = "213" + p
    else:
        return None
    # التحقق: يجب أن يكون 12 رقماً ويبدأ بـ 213
    if not (len(p) == 12 and p.isdigit() and p.startswith("213")):
        return None
    return p


def delete_account(uid: str, msisdn: str) -> bool:
    """يحذف حساباً من sessions.json ويُرجع True عند النجاح"""
    data = load_sessions()
    if uid not in data:
        return False
    accs = data[uid].get("accounts", {})
    if msisdn not in accs:
        return False
    del accs[msisdn]
    # إذا حُذف الحساب النشط، اختر غيره أو None
    if data[uid].get("active") == msisdn:
        data[uid]["active"] = next(iter(accs), None)
    save_sessions(data)
    return True


def extract_msg(res: dict | None, default: str = "") -> str:
    if not res:
        return default
    try:
        msg = res.get("message", default)
        if isinstance(msg, dict):
            return msg.get("ar") or msg.get("en") or default
        return str(msg) if msg else default
    except Exception:
        return default



def main_keyboard(uid: str, msisdn: str) -> InlineKeyboardMarkup:
    rem = get_gift_remaining(uid, msisdn)
    gift_lbl = f"🎁 الهدية الأسبوعية  ⏳ {rem}" if rem else "🎁  الهدية الأسبوعية المجانية"
    rows = [
        [InlineKeyboardButton("💰  الرصيد المالي",       callback_data="BALANCE")],
        [InlineKeyboardButton("📊  رصيد الإنترنت",      callback_data="DATA")],
        [InlineKeyboardButton(gift_lbl,                  callback_data="GIFT")],
        [InlineKeyboardButton("🏷️  العروض الحصرية",     callback_data="OFFERS")],
        [InlineKeyboardButton("🔗  نظام الإحالة",       callback_data="REFERRAL")],
        [InlineKeyboardButton("👤  تبديل الحساب",       callback_data="SWITCH")],
        [InlineKeyboardButton("❓  مساعدة",             callback_data="HELP")],
    ]
    rows.append([InlineKeyboardButton("📜  سجل العمليات",       callback_data="HISTORY")])
    if is_moderator(uid):
        rows.append([InlineKeyboardButton("🛡️  لوحة المشرف",  callback_data="MOD_PANEL")])
    else:
        rows.append([InlineKeyboardButton("📋  طلب الانضمام كمشرف", callback_data="MOD_REQUEST")])
    return InlineKeyboardMarkup(rows)


def mod_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 حظر مستخدم",         callback_data="MOD_BAN")],
        [InlineKeyboardButton("✅ رفع الحظر عن مستخدم", callback_data="MOD_UNBAN_LIST")],
        [InlineKeyboardButton("🔙 رجوع للقائمة",        callback_data="MENU")],
    ])


def offers_keyboard(uid: str, msisdn: str) -> InlineKeyboardMarkup:
    rows = []
    for key, (_, name, dur) in OFFERS.items():
        rem = get_remaining(uid, msisdn, key, dur)
        lbl = f"{name}  ⏳ {rem}" if rem else name
        rows.append([InlineKeyboardButton(lbl, callback_data=f"ACT_{key}")])
    rows.append([InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="MENU")])
    return InlineKeyboardMarkup(rows)


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="MENU")]])


def referral_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📨 دعوة صديق",          callback_data="REF_INVITE")],
        [InlineKeyboardButton("🎁 تفعيل مكافأة الإحالة", callback_data="REF_REWARD")],
        [InlineKeyboardButton("🔙 رجوع للقائمة",        callback_data="MENU")],
    ])


def accounts_keyboard(uid: str, show_back: bool = False) -> InlineKeyboardMarkup:
    sess  = get_user_sessions(uid)
    accs  = sess.get("accounts", {})
    active = sess.get("active")
    rows  = []
    for msisdn, info in accs.items():
        mark = "✅ " if msisdn == active else ""
        rows.append([
            InlineKeyboardButton(
                f"{mark}{fmt_phone(msisdn)} — {info.get('name','')}",
                callback_data=f"ACC_{msisdn}"
            ),
            InlineKeyboardButton("🗑", callback_data=f"DEL_{msisdn}"),
        ])
    rows.append([InlineKeyboardButton("➕ إضافة حساب جديد", callback_data="ADD_ACCOUNT")])
    if show_back:
        rows.append([InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="BACK_TO_MENU")])
    return InlineKeyboardMarkup(rows)


def format_data_balance(res: dict) -> str:
    try:
        items = res.get("data", res)
        if isinstance(items, dict):
            items = [items]
        if not items:
            return "📊 لا توجد باقة إنترنت نشطة حالياً."
        lines = [
            "╔══════════════════════╗\n"
            "║  📊  رصيد الإنترنت   ║\n"
            "╚══════════════════════╝"
        ]
        for it in (items if isinstance(items, list) else [items]):
            name_raw = it.get("name") or it.get("offerName") or it.get("packageCode") or "—"
            if isinstance(name_raw, dict):
                name = name_raw.get("ar") or name_raw.get("en") or "—"
            else:
                name = str(name_raw)
            remaining = it.get("remainingData") or it.get("remaining") or it.get("volume") or "—"
            total     = it.get("totalData")     or it.get("total")    or it.get("quota")  or ""
            exp       = it.get("expiryDate")    or it.get("validityDate") or it.get("endDate") or "—"
            try:
                rem_mb = float(remaining)
                if rem_mb >= 1024:
                    rem_str = f"{rem_mb/1024:.2f} GB"
                else:
                    rem_str = f"{rem_mb:.0f} MB"
            except Exception:
                rem_str = str(remaining)
            try:
                tot_mb = float(total)
                if tot_mb >= 1024:
                    tot_str = f" / {tot_mb/1024:.2f} GB"
                else:
                    tot_str = f" / {tot_mb:.0f} MB" if tot_mb else ""
            except Exception:
                tot_str = f" / {total}" if total else ""
            lines.append(
                f"\n📦 الباقة   : {name}\n"
                f"📶 المتبقي  : {rem_str}{tot_str}\n"
                f"📅 الانتهاء : {exp}"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"format_data_balance error: {e}")
        return f"📊 رصيد الإنترنت:\n{json.dumps(res, indent=2, ensure_ascii=False)}"


def format_balance(res: dict) -> str:
    try:
        # الـ API يُرجع البيانات داخل "data"
        d     = res.get("data", res)
        main  = d.get("mainBalance", "—")
        due   = d.get("due", 0)
        info  = d.get("customerInformations", {})
        phone = fmt_phone(info.get("msisdn", ""))
        conn  = info.get("connectionType", "—")
        pay   = info.get("paymentType", "—")
        st    = info.get("status", "—")
        sub   = info.get("subscriptionType", {})
        sn    = sub.get("name", {}) if isinstance(sub, dict) else {}
        sub_n = (sn.get("ar") or sn.get("en") or "—") if isinstance(sn, dict) else str(sn)
        # تنسيق الرصيد
        try:
            main_fmt = f"{float(main):.2f}"
        except Exception:
            main_fmt = str(main)
        try:
            due_fmt = f"{float(due):.2f}"
        except Exception:
            due_fmt = str(due)
        # ترجمة الحالة
        status_map = {"active": "✅ نشط", "inactive": "❌ غير نشط", "suspended": "⏸ موقوف"}
        st_ar = status_map.get(str(st).lower(), st)
        # ترجمة نوع الخط
        pay_map = {"prepaid": "مسبق الدفع", "postpaid": "بعدي الدفع"}
        pay_ar = pay_map.get(str(pay).lower(), pay)
        return (
            "╔══════════════════════╗\n"
            "║   💰  معلومات الحساب  ║\n"
            "╚══════════════════════╝\n"
            f"📱 الرقم     : {phone}\n"
            f"💵 الرصيد    : {main_fmt} دج\n"
            f"📋 المستحق   : {due_fmt} دج\n"
            f"📶 الاتصال   : {conn}\n"
            f"💳 نوع الخط  : {pay_ar}\n"
            f"📦 الاشتراك  : {sub_n}\n"
            f"✅ الحالة    : {st_ar}"
        )
    except Exception as e:
        logger.error(f"format_balance error: {e}")
        return f"💰 الرصيد:\n{json.dumps(res, indent=2, ensure_ascii=False)}"


# ══════════════════════════════════════════════════════════════
#  نص الترحيب الثابت
# ══════════════════════════════════════════════════════════════
WELCOME = (
    "╔════════════════════════════╗\n"
    "║   🇩🇿  تطبيق خدمات جيزي    ║\n"
    "╚════════════════════════════╝\n\n"
    "👨‍💻 تطوير: يوسف قيبوج\n\n"
    "✨ مميزات التطبيق:\n"
    "🎁 هدية أسبوعية: تفعيل هديتك المجانية بضغطة زر\n"
    "📊 عرض الرصيد: متابعة رصيدك المالي لحظة بلحظة\n"
    "🔗 نظام الإحالة: ادعُ أصدقاءك واربح إنترنت إضافي\n"
    "📱 تعدد الحسابات: تسجيل أكثر من رقم والتبديل بينهم\n\n"
    "📲 نزّل تطبيقنا للاستخدام الكامل:\n"
    "👉 https://t.me/youcef_kiboudj_dam/25\n\n"
    "📢 قناتنا على تيليجرام:\n"
    "👉 https://t.me/youcef_kiboudj_dam"
)


# ══════════════════════════════════════════════════════════════
#  معالجات المحادثة
# ══════════════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid   = str(update.effective_user.id)

    if is_banned(uid):
        await update.message.reply_text("🚫 أنت محظور من استخدام هذا البوت.")
        return ConversationHandler.END

    if load_maintenance() and not is_moderator(uid):
        await update.message.reply_text(
            "🔧 البوت في وضع الصيانة حالياً.\n"
            "سيعود للعمل قريباً، شكراً على صبرك! ⏳"
        )
        return ConversationHandler.END

    sess  = get_user_sessions(uid)
    accs  = sess.get("accounts", {})

    if accs:
        active = sess.get("active") or next(iter(accs))
        context.user_data["msisdn"] = active
        context.user_data["token"]  = accs[active]["token"]
        await update.message.reply_text(
            WELCOME + "\n\n──────────────────────────\n"
            "مرحباً بعودتك! اختر الحساب أو أضف جديداً:",
            reply_markup=accounts_keyboard(uid),
            disable_web_page_preview=True
        )
        return SELECT_ACCOUNT

    await update.message.reply_text(
        WELCOME + "\n\n──────────────────────────\n"
        "للبدء، أدخل رقم هاتف جيزي:\nمثال: 0770123456",
        disable_web_page_preview=True
    )
    return PHONE


async def select_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = str(update.effective_user.id)

    if query.data == "ADD_ACCOUNT":
        context.user_data.pop("awaiting_broadcast", None)
        await query.edit_message_text("📱 أدخل رقم هاتف جيزي الجديد:\nمثال: 0770123456")
        return PHONE

    if query.data.startswith("ACC_"):
        msisdn = query.data[4:]
        sess   = get_user_sessions(uid)
        if msisdn in sess.get("accounts", {}):
            set_active_account(uid, msisdn)
            context.user_data["msisdn"] = msisdn
            context.user_data["token"]  = sess["accounts"][msisdn]["token"]
            await query.edit_message_text(
                f"✅ تم اختيار: {fmt_phone(msisdn)}\n\nاختر ما تريد:",
                reply_markup=main_keyboard(uid, msisdn)
            )
            return MAIN_MENU

    # ── حذف حساب — خطوة 1: طلب التأكيد ──
    if query.data.startswith("DEL_"):
        msisdn_del = query.data[4:]
        phone_fmt  = fmt_phone(msisdn_del)
        await query.edit_message_text(
            f"🗑 هل تريد حذف الحساب {phone_fmt}؟\n\n"
            "⚠️ لا يمكن التراجع عن هذا الإجراء.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ نعم، احذف",  callback_data=f"DELCONF_{msisdn_del}"),
                 InlineKeyboardButton("❌ إلغاء",      callback_data="BACK_ACCOUNTS")],
            ])
        )
        return SELECT_ACCOUNT

    # ── حذف حساب — خطوة 2: تنفيذ الحذف ──
    if query.data.startswith("DELCONF_"):
        msisdn_del = query.data[8:]
        delete_account(uid, msisdn_del)

        # إذا كان الحساب المحذوف هو النشط، نحدّث context
        if context.user_data.get("msisdn") == msisdn_del:
            sess = get_user_sessions(uid)
            accs = sess.get("accounts", {})
            if accs:
                new_msisdn = sess.get("active") or next(iter(accs))
                context.user_data["msisdn"] = new_msisdn
                context.user_data["token"]  = accs[new_msisdn]["token"]
            else:
                context.user_data["msisdn"] = ""
                context.user_data["token"]  = ""

        sess = get_user_sessions(uid)
        accs = sess.get("accounts", {})

        if not accs:
            await query.edit_message_text(
                "✅ تم حذف الحساب بنجاح.\n\n"
                "لا توجد حسابات أخرى.\n"
                "اضغط /start لإضافة حساب جديد."
            )
            return ConversationHandler.END

        await query.edit_message_text(
            f"✅ تم حذف الحساب {fmt_phone(msisdn_del)} بنجاح.\n\n"
            "👤 اختر حساباً آخر:",
            reply_markup=accounts_keyboard(uid)
        )
        return SELECT_ACCOUNT

    # ── رجوع لقائمة الحسابات ──
    if query.data == "BACK_ACCOUNTS":
        await query.edit_message_text(
            "👤 اختر الحساب أو أضف جديداً:",
            reply_markup=accounts_keyboard(uid, show_back=True)
        )
        return SELECT_ACCOUNT

    # ── رجوع للقائمة الرئيسية من شاشة الحسابات ──
    if query.data == "BACK_TO_MENU":
        msisdn = context.user_data.get("msisdn", "")
        if msisdn:
            await query.edit_message_text(
                f"📱 {fmt_phone(msisdn)}\n\nاختر ما تريد:",
                reply_markup=main_keyboard(uid, msisdn)
            )
            return MAIN_MENU
        # لا يوجد حساب نشط — أرجعه لاختيار الحساب
        await query.edit_message_text(
            "👤 اختر الحساب:",
            reply_markup=accounts_keyboard(uid)
        )
        return SELECT_ACCOUNT

    await query.edit_message_text("❌ حدث خطأ. /start")
    return ConversationHandler.END


async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text
    context.user_data.pop("awaiting_broadcast", None)
    try:
        await update.message.delete()
    except Exception:
        pass

    msisdn = clean_phone(raw_text)
    if not msisdn:
        m = await update.effective_chat.send_message(
            "⚠️ رقم الهاتف غير صحيح.\n\n"
            "الصيغ المقبولة:\n"
            "• 0770123456\n"
            "• 213770123456\n"
            "• +213770123456\n\n"
            "أدخل الرقم مجدداً:"
        )
        context.user_data["last_bot_msg"] = m.message_id
        return PHONE

    context.user_data["msisdn"] = msisdn

    # حذف رسالة البوت السابقة إن وجدت
    if context.user_data.get("last_bot_msg"):
        try:
            await update.effective_chat.delete_message(context.user_data["last_bot_msg"])
        except Exception:
            pass

    m = await update.effective_chat.send_message(
        f"⏳ جاري إرسال رمز التحقق إلى {fmt_phone(msisdn)}..."
    )
    context.user_data["last_bot_msg"] = m.message_id
    code, _ = send_otp(msisdn)

    if code in (200, 201):
        try:
            await update.effective_chat.delete_message(context.user_data["last_bot_msg"])
        except Exception:
            pass
        m = await update.effective_chat.send_message(
            "✅ تم إرسال الرمز بنجاح!\n"
            "أدخل الرمز المكوّن من 6 أرقام:"
        )
        context.user_data["last_bot_msg"] = m.message_id
        return OTP
    elif code == 429:
        m = await update.effective_chat.send_message(
            "⚠️ كثرة المحاولات، انتظر دقيقة ثم حاول مجدداً.\n\n/start"
        )
        context.user_data["last_bot_msg"] = m.message_id
        return ConversationHandler.END
    elif code == 400:
        m = await update.effective_chat.send_message(
            "❌ هذا الرقم غير مسجل في شبكة جيزي.\n"
            "تأكد أن الرقم تابع لجيزي وأدخله مجدداً:"
        )
        context.user_data["last_bot_msg"] = m.message_id
        return PHONE
    else:
        m = await update.effective_chat.send_message("❌ فشل الإرسال. حاول لاحقاً.\n\n/start")
        context.user_data["last_bot_msg"] = m.message_id
        return ConversationHandler.END


async def handle_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    otp      = update.message.text.strip()
    msisdn   = context.user_data.get("msisdn", "")
    uid      = str(update.effective_user.id)

    try:
        await update.message.delete()
    except Exception:
        pass

    if not otp.isdigit() or len(otp) != 6:
        m = await update.effective_chat.send_message("⚠️ أدخل رمزاً مكوناً من 6 أرقام فقط.")
        context.user_data["last_bot_msg"] = m.message_id
        return OTP

    # حذف رسالة "أدخل الرمز" السابقة
    if context.user_data.get("last_bot_msg"):
        try:
            await update.effective_chat.delete_message(context.user_data["last_bot_msg"])
        except Exception:
            pass

    m = await update.effective_chat.send_message("⏳ جاري التحقق من الرمز...")
    context.user_data["last_bot_msg"] = m.message_id
    result, code = verify_otp(msisdn, otp)

    if code == 200 and result and "access_token" in result:
        token   = result["access_token"]
        rtoken  = result.get("refresh_token", "")
        context.user_data["token"] = token
        save_account(uid, msisdn, token, rtoken)
        try:
            await update.effective_chat.delete_message(context.user_data["last_bot_msg"])
        except Exception:
            pass
        await update.effective_chat.send_message(
            f"🎉 تم تسجيل الدخول بنجاح!\n📱 {fmt_phone(msisdn)}\n\nاختر ما تريد:",
            reply_markup=main_keyboard(uid, msisdn)
        )
        return MAIN_MENU
    elif code == 400:
        await update.effective_chat.send_message("❌ الرمز غير صحيح أو منتهي الصلاحية.\n\n/start")
        return ConversationHandler.END
    else:
        await update.effective_chat.send_message("❌ خطأ في التحقق. حاول لاحقاً.\n\n/start")
        return ConversationHandler.END


async def trigger_reauth(query, msisdn: str) -> int:
    """عند 401 — أرسل OTP تلقائياً وانتقل لحالة REAUTH_OTP"""
    code, _ = send_otp(msisdn)
    if code in (200, 201):
        await query.edit_message_text(
            "🔑 انتهت صلاحية الجلسة.\n"
            "✅ تم إرسال رمز التحقق تلقائياً إلى رقمك.\n\n"
            "أدخل الرمز المكون من 6 أرقام:"
        )
        return REAUTH_OTP
    else:
        await query.edit_message_text(
            "🔑 انتهت صلاحية الجلسة.\n"
            "⚠️ تعذّر إرسال رمز التحقق. اضغط /start لتسجيل الدخول مجدداً."
        )
        return ConversationHandler.END


async def handle_reauth_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال OTP بعد انتهاء التوكن وتجديده تلقائياً"""
    otp    = update.message.text.strip()
    msisdn = context.user_data.get("msisdn", "")
    uid    = str(update.effective_user.id)

    try:
        await update.message.delete()
    except Exception:
        pass

    if not otp.isdigit() or len(otp) != 6:
        await update.effective_chat.send_message("⚠️ أدخل رمزاً مكوناً من 6 أرقام فقط.")
        return REAUTH_OTP

    await update.effective_chat.send_message("⏳ جاري تجديد الجلسة...")
    result, code = verify_otp(msisdn, otp)

    if code == 200 and result and "access_token" in result:
        token   = result["access_token"]
        rtoken  = result.get("refresh_token", "")
        context.user_data["token"] = token
        save_account(uid, msisdn, token, rtoken)
        await update.effective_chat.send_message(
            f"✅ تم تجديد الجلسة بنجاح!\n📱 {fmt_phone(msisdn)}\n\nاختر ما تريد:",
            reply_markup=main_keyboard(uid, msisdn)
        )
        return MAIN_MENU
    elif code == 400:
        await update.effective_chat.send_message("❌ الرمز غير صحيح أو منتهي الصلاحية.\n\n/start")
        return ConversationHandler.END
    else:
        await update.effective_chat.send_message("❌ خطأ في التحقق. حاول لاحقاً.\n\n/start")
        return ConversationHandler.END


async def handle_referral_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال رقم الصديق للدعوة"""
    uid      = str(update.effective_user.id)
    token    = context.user_data.get("token", "")
    msisdn   = context.user_data.get("msisdn", "")
    raw_text = update.message.text

    try:
        await update.message.delete()
    except Exception:
        pass

    friend = clean_phone(raw_text)
    if not friend:
        await update.effective_chat.send_message(
            "⚠️ رقم الهاتف غير صحيح.\n\n"
            "الصيغ المقبولة:\n"
            "• 0770123456\n"
            "• +213770123456\n\n"
            "أدخل رقم صديقك مجدداً:"
        )
        return REFERRAL_PHONE

    if friend == msisdn:
        await update.effective_chat.send_message(
            "❌ لا يمكنك دعوة نفسك!\nأدخل رقم شخص آخر:"
        )
        return REFERRAL_PHONE

    await update.effective_chat.send_message(f"⏳ جاري إرسال الدعوة إلى {fmt_phone(friend)}...")
    res, code = djezzy_api("POST", f"services/mgm/send-invitation/{msisdn}", token, {"msisdnReciever": friend})

    if code in (200, 201):
        msg = extract_msg(res, "تم إرسال الدعوة بنجاح")
        await update.effective_chat.send_message(
            f"⚡ تم إرسال الدعوة إلى {fmt_phone(friend)}!\n💬 {msg}",
            reply_markup=back_keyboard()
        )
    else:
        msg = extract_msg(res, "فشل إرسال الدعوة")
        await update.effective_chat.send_message(f"⚠️ {msg}", reply_markup=back_keyboard())

    return MAIN_MENU


async def menu_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    uid    = str(update.effective_user.id)

    # ── حماية من النقر المزدوج ──
    lock_key = f"{uid}:{query.data}"
    if lock_key in _processing:
        await query.answer("⏳ جاري المعالجة...")
        return MAIN_MENU
    _processing.add(lock_key)
    try:
        return await _menu_actions_inner(update, context, query, uid)
    finally:
        _processing.discard(lock_key)


async def _menu_actions_inner(update, context, query, uid):
    await query.answer()
    token  = context.user_data.get("token", "")
    msisdn = context.user_data.get("msisdn", "")

    # ── فحص وضع الصيانة ──
    if load_maintenance() and not is_moderator(uid) and query.data not in ("MENU",):
        await query.edit_message_text(
            "🔧 البوت في وضع الصيانة حالياً.\n"
            "سيعود للعمل قريباً، شكراً على صبرك! ⏳"
        )
        return ConversationHandler.END

    # ── سجل العمليات ──
    if query.data == "HISTORY":
        await query.edit_message_text(
            format_history(uid, msisdn),
            reply_markup=back_keyboard()
        )
        return MAIN_MENU

    # ── رجوع للقائمة ──
    if query.data == "MENU":
        await query.edit_message_text(
            f"📱 {fmt_phone(msisdn)}\n\nاختر ما تريد:",
            reply_markup=main_keyboard(uid, msisdn)
        )
        return MAIN_MENU

    # ── تبديل الحساب ──
    if query.data == "SWITCH":
        await query.edit_message_text("👤 اختر الحساب:", reply_markup=accounts_keyboard(uid, show_back=True))
        return SELECT_ACCOUNT

    # ── تحديث التوكن من sessions.json (تفادياً للتوكن القديم بعد التجديد التلقائي) ──
    if msisdn:
        fresh = get_user_sessions(uid).get("accounts", {}).get(msisdn, {}).get("token", "")
        if fresh and fresh != token:
            token = fresh
            context.user_data["token"] = fresh

    if not token or not msisdn:
        await query.edit_message_text("❌ انتهت الجلسة. /start")
        return ConversationHandler.END

    # ── مساعدة ──
    if query.data == "HELP":
        await query.edit_message_text(
            "╔══════════════════════════╗\n"
            "║       ❓ المساعدة         ║\n"
            "╚══════════════════════════╝\n\n"
            "📌 الأوامر المتاحة:\n"
            "/start — بدء البوت / القائمة الرئيسية\n"
            "/admin — لوحة الإدارة (للمشرفين)\n\n"
            "📋 الأزرار:\n"
            "💰 الرصيد المالي — يعرض رصيدك ومعلومات حسابك\n"
            "📊 رصيد الإنترنت — يعرض باقة الإنترنت المتبقية\n"
            "🎁 الهدية الأسبوعية — تفعيل 2GB مجاناً كل 7 أيام\n"
            "🏷️ العروض — باقات إنترنت متنوعة يومية وأسبوعية وشهرية\n"
            "🔗 الإحالة — ادعُ صديقاً لجيزي واربح إنترنت\n"
            "👤 تبديل الحساب — إدارة حسابات متعددة\n"
            "🗑 حذف حساب — احذف حساباً من القائمة\n\n"
            "👨‍💻 تطوير: يوسف قيبوج\n"
            "📢 https://t.me/youcef_kiboudj_dam",
            reply_markup=back_keyboard()
        )
        return MAIN_MENU

    # ── الرصيد المالي ──
    if query.data == "BALANCE":
        await query.edit_message_text("⏳ جاري جلب معلومات الحساب...")
        res, code = djezzy_api("GET", f"subscribers/main-balance/{msisdn}", token)
        if code == 401:
            return await trigger_reauth(query, msisdn)
        if code == 200 and res:
            await query.edit_message_text(format_balance(res), reply_markup=back_keyboard())
        else:
            await query.edit_message_text("❌ تعذّر جلب الرصيد. حاول لاحقاً.", reply_markup=back_keyboard())
        return MAIN_MENU

    # ── رصيد الإنترنت ──
    if query.data == "DATA":
        await query.edit_message_text("⏳ جاري جلب رصيد الإنترنت...")
        res, code = djezzy_api("GET", f"subscribers/connected-products-balances/{msisdn}", token)
        if code == 401:
            return await trigger_reauth(query, msisdn)
        if code == 200 and res:
            await query.edit_message_text(format_data_balance(res), reply_markup=back_keyboard())
        else:
            await query.edit_message_text("❌ تعذّر جلب رصيد الإنترنت. حاول لاحقاً.", reply_markup=back_keyboard())
        return MAIN_MENU

    # ── الهدية الأسبوعية ──
    if query.data == "GIFT":
        await query.edit_message_text("⏳ جاري التحقق من سجل الهدية...")

        # ── خطوة 1: جلب الوقت الحقيقي من سيرفر جيزي ──
        rem = fetch_gift_history(msisdn, token)
        if rem:
            await query.edit_message_text(
                "🗓 عذراً، لم تكمل الأسبوع بعد.\n"
                f"⏳ الوقت المتبقي: {rem}\n\n"
                "يمكنك المطالبة بالهدية مرة واحدة كل 7 أيام.",
                reply_markup=back_keyboard()
            )
            return MAIN_MENU

        # ── خطوة 2: الأسبوع اكتمل — حاول التفعيل ──
        await query.edit_message_text("✅ الأسبوع اكتمل! جاري تفعيل الهدية...")
        res, code = djezzy_api("POST", f"subscribers/activate-product/{msisdn}", token, {"packageCode": "GIFTWALKWIN2GO"})

        if code == 401:
            return await trigger_reauth(query, msisdn)
        elif code in (200, 201):
            msg = extract_msg(res, "تمت العملية بنجاح")
            save_activation(uid, msisdn, "GIFT")
            save_history(uid, msisdn, "gift", "🎁 الهدية الأسبوعية (2GB - 7 أيام)")
            await query.edit_message_text(
                f"🎉 تم تفعيل الهدية الأسبوعية!\n"
                f"📦 2GB لمدة 7 أيام\n\n💬 {msg}",
                reply_markup=back_keyboard()
            )
        elif code == 402:
            await query.edit_message_text("❌ رصيدك غير كافٍ.", reply_markup=back_keyboard())
        else:
            msg = extract_msg(res) or "تعذّر التفعيل"
            await query.edit_message_text(
                f"⚠️ {msg}",
                reply_markup=back_keyboard()
            )
        return MAIN_MENU

    # ── نظام الإحالة ──
    if query.data == "REFERRAL":
        await query.edit_message_text(
            "🔗 نظام الإحالة\n"
            "──────────────────────────\n"
            "📨 ادعُ صديقاً ليشترك في جيزي واربح إنترنت مجاني!\n"
            "🎁 فعّل مكافأتك بعد قبول الصديق للدعوة.",
            reply_markup=referral_keyboard()
        )
        return MAIN_MENU

    if query.data == "REF_INVITE":
        await query.edit_message_text(
            "📨 أدخل رقم هاتف صديقك لدعوته:\n"
            "مثال: 0770123456"
        )
        return REFERRAL_PHONE

    if query.data == "REF_REWARD":
        await query.edit_message_text("⏳ جاري فحص وتفعيل مكافأة الإحالة...")
        res, code = djezzy_api("POST", f"services/mgm/activate-reward/{msisdn}", token)
        if code == 401:
            return await trigger_reauth(query, msisdn)
        if code in (200, 201):
            msg = extract_msg(res, "تم تفعيل المكافأة بنجاح")
            save_history(uid, msisdn, "referral", "🔗 مكافأة الإحالة")
            await query.edit_message_text(f"🎉 {msg}", reply_markup=back_keyboard())
        else:
            msg = extract_msg(res) or "تعذّرت العملية، حاول لاحقاً"
            await query.edit_message_text(f"⚠️ {msg}", reply_markup=back_keyboard())
        return MAIN_MENU

    # ── قائمة العروض ──
    if query.data == "OFFERS":
        await query.edit_message_text(
            "🏷️ العروض الحصرية\n"
            "──────────────────────────\n"
            "اختر العرض المناسب لتفعيله:\n"
            "⏳ يعني الوقت المتبقي قبل انتهاء الباقة",
            reply_markup=offers_keyboard(uid, msisdn)
        )
        return MAIN_MENU


    # ── تفعيل عرض محدد — خطوة 1: تأكيد ──
    if query.data.startswith("ACT_"):
        offer_key = query.data[4:]
        if offer_key not in OFFERS:
            await query.edit_message_text("❌ عرض غير معروف.", reply_markup=back_keyboard())
            return MAIN_MENU

        pkg_code, offer_name, dur_h = OFFERS[offer_key]

        # فحص إذا كان العرض نشطاً
        rem = get_remaining(uid, msisdn, offer_key, dur_h)
        if rem:
            await query.edit_message_text(
                f"{offer_name}\n"
                f"✅ هذا العرض نشط حالياً.\n⏳ الوقت المتبقي: {rem}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع للعروض", callback_data="OFFERS")]
                ])
            )
            return MAIN_MENU

        # عرض تأكيد قبل التفعيل
        await query.edit_message_text(
            f"🏷️ {offer_name}\n"
            "──────────────────────────\n"
            "⚠️ هل تريد تفعيل هذا العرض؟\n"
            "سيتم خصم قيمته من رصيدك.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأكيد التفعيل", callback_data=f"CONF_{offer_key}"),
                 InlineKeyboardButton("❌ إلغاء",          callback_data="OFFERS")],
            ])
        )
        return MAIN_MENU

    # ── تفعيل عرض محدد — خطوة 2: تنفيذ بعد التأكيد ──
    if query.data.startswith("CONF_"):
        offer_key = query.data[5:]
        if offer_key not in OFFERS:
            await query.edit_message_text("❌ عرض غير معروف.", reply_markup=back_keyboard())
            return MAIN_MENU

        pkg_code, offer_name, dur_h = OFFERS[offer_key]
        await query.edit_message_text(f"⏳ جاري تفعيل {offer_name}...")
        res, code = djezzy_api("POST", f"subscribers/activate-product/{msisdn}", token, {"packageCode": pkg_code})

        if code == 401:
            return await trigger_reauth(query, msisdn)
        elif code in (200, 201):
            msg = extract_msg(res, "تمت العملية بنجاح")
            save_activation(uid, msisdn, offer_key)
            save_history(uid, msisdn, "offer", f"🏷️ {offer_name}")
            await query.edit_message_text(
                f"🎉 تم تفعيل {offer_name} بنجاح!\n\n💬 {msg}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع للعروض",      callback_data="OFFERS")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="MENU")],
                ])
            )
        elif code == 402:
            await query.edit_message_text(
                f"❌ رصيدك غير كافٍ لتفعيل {offer_name}.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع للعروض", callback_data="OFFERS")]
                ])
            )
        else:
            msg = extract_msg(res) or "الحالة غير معروفة"
            await query.edit_message_text(
                f"⚠️ {msg}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع للعروض", callback_data="OFFERS")]
                ])
            )
            return MAIN_MENU

    # ── لوحة المشرف ──
    if query.data == "MOD_PANEL":
        if not is_moderator(uid):
            await query.edit_message_text("❌ ليس لديك صلاحية المشرف.", reply_markup=back_keyboard())
            return MAIN_MENU
        await query.edit_message_text(
            "🛡️ لوحة المشرف\n"
            "──────────────────────────\n"
            "اختر الإجراء:",
            reply_markup=mod_keyboard()
        )
        return MAIN_MENU

    # ── طلب الانضمام كمشرف ──
    if query.data == "MOD_REQUEST":
        if is_moderator(uid):
            await query.edit_message_text("✅ أنت مشرف بالفعل.", reply_markup=back_keyboard())
            return MAIN_MENU
        name   = update.effective_user.full_name or uid
        req_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ قبول", callback_data=f"ADM_APPMOD_{uid}"),
             InlineKeyboardButton("❌ رفض",  callback_data=f"ADM_REJMOD_{uid}")],
        ])
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        "📋 طلب انضمام كمشرف جديد\n"
                        "──────────────────────────\n"
                        f"👤 الاسم : {name}\n"
                        f"🆔 المعرف: `{uid}`\n"
                        f"📱 الرقم : {fmt_phone(msisdn)}"
                    ),
                    reply_markup=req_kb,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.warning(f"mod_request notify admin {admin_id}: {e}")
        await query.edit_message_text(
            "✅ تم إرسال طلبك للإدارة.\n"
            "سيتم الرد عليك قريباً.",
            reply_markup=back_keyboard()
        )
        return MAIN_MENU

    # ── حظر مستخدم ──
    if query.data == "MOD_BAN":
        if not is_moderator(uid):
            await query.edit_message_text("❌ ليس لديك صلاحية.", reply_markup=back_keyboard())
            return MAIN_MENU
        await query.edit_message_text(
            "🚫 حظر مستخدم\n"
            "──────────────────────────\n"
            "أرسل معرف المستخدم (User ID رقمي)\n"
            "أو رقم هاتفه المسجل في البوت.\n\n"
            "للإلغاء اكتب: إلغاء"
        )
        return BAN_INPUT

    # ── رفع الحظر — عرض القائمة ──
    if query.data == "MOD_UNBAN_LIST":
        if not is_moderator(uid):
            await query.edit_message_text("❌ ليس لديك صلاحية.", reply_markup=back_keyboard())
            return MAIN_MENU
        banned = load_banned()
        if not banned:
            await query.edit_message_text("✅ لا يوجد مستخدمون محظورون حالياً.", reply_markup=mod_keyboard())
            return MAIN_MENU
        rows = []
        for b_uid in list(banned)[:20]:
            rows.append([InlineKeyboardButton(f"🔓 {b_uid}", callback_data=f"MOD_UNBAN_{b_uid}")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="MOD_PANEL")])
        await query.edit_message_text(
            f"🚫 المستخدمون المحظورون ({len(banned)}):\n"
            "اضغط على المستخدم لرفع الحظر عنه:",
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return MAIN_MENU

    # ── رفع الحظر عن مستخدم محدد ──
    if query.data.startswith("MOD_UNBAN_"):
        if not is_moderator(uid):
            await query.edit_message_text("❌ ليس لديك صلاحية.", reply_markup=back_keyboard())
            return MAIN_MENU
        target = query.data[len("MOD_UNBAN_"):]
        unban_user(target)
        try:
            await context.bot.send_message(chat_id=int(target), text="✅ تم رفع الحظر عنك. يمكنك استخدام البوت مجدداً.")
        except Exception:
            pass
        await query.edit_message_text(f"✅ تم رفع الحظر عن المستخدم {target}.", reply_markup=mod_keyboard())
        return MAIN_MENU

    return MAIN_MENU


# ══════════════════════════════════════════════════════════════
#  نظام الإدارة
# ══════════════════════════════════════════════════════════════
def is_admin(uid: str) -> bool:
    return int(uid) in ADMIN_IDS


def get_all_user_ids() -> list[str]:
    data = load_sessions()
    return list(data.keys())


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 إرسال إشعار لكل المستخدمين", callback_data="ADM_BROADCAST")],
        [InlineKeyboardButton("📊 إحصائيات البوت",              callback_data="ADM_STATS")],
        [InlineKeyboardButton("👥 قائمة المستخدمين",            callback_data="ADM_USERS")],
        [InlineKeyboardButton("🛡️ إدارة المشرفين",             callback_data="ADM_MODS")],
        [InlineKeyboardButton("🚫 المستخدمون المحظورون",        callback_data="ADM_BANNED")],
        [InlineKeyboardButton("🔧 تبديل وضع الصيانة",          callback_data="ADM_MAINTENANCE")],
        [InlineKeyboardButton("🔙 إغلاق لوحة الإدارة",         callback_data="ADM_CLOSE")],
    ])


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /admin — يفتح لوحة الإدارة للأدمن فقط"""
    uid = str(update.effective_user.id)
    if not is_admin(uid):
        await update.message.reply_text("❌ ليس لديك صلاحية الوصول.")
        return

    total = len(get_all_user_ids())
    await update.message.reply_text(
        "╔══════════════════════╗\n"
        "║   ⚙️  لوحة الإدارة    ║\n"
        "╚══════════════════════╝\n\n"
        f"👥 إجمالي المستخدمين: {total}\n\n"
        "اختر الإجراء:",
        reply_markup=admin_keyboard()
    )




# ══════════════════════════════════════════════════════════════
#  handlers مستقلة للوحة الإدارة (تعمل خارج ConversationHandler)
# ══════════════════════════════════════════════════════════════
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج مستقل لأزرار لوحة الإدارة — يعمل بغض النظر عن حالة المحادثة"""
    query = update.callback_query
    await query.answer()
    uid = str(update.effective_user.id)

    if not is_admin(uid):
        return

    if query.data == "ADM_STATS":
        data      = load_sessions()
        total     = len(data)
        total_acc = sum(len(u.get("accounts", {})) for u in data.values())
        await query.edit_message_text(
            "📊 إحصائيات البوت\n"
            "──────────────────────────\n"
            f"👥 المستخدمون : {total}\n"
            f"📱 الحسابات   : {total_acc}\n",
            reply_markup=admin_keyboard()
        )

    elif query.data == "ADM_USERS":
        data  = load_sessions()
        lines = []
        for i, (uid_u, info) in enumerate(data.items(), 1):
            accs = list(info.get("accounts", {}).keys())
            nums = ", ".join(fmt_phone(m) for m in accs) if accs else "—"
            lines.append(f"{i}. `{uid_u}` ← {nums}")
        text = "👥 المستخدمون:\n──────────────────────────\n" + "\n".join(lines[:30])
        if len(data) > 30:
            text += f"\n... و {len(data)-30} آخرين"
        await query.edit_message_text(text, reply_markup=admin_keyboard(), parse_mode="Markdown")

    elif query.data == "ADM_CLOSE":
        await query.edit_message_text("✅ تم إغلاق لوحة الإدارة.")

    # ── إدارة المشرفين ──
    elif query.data == "ADM_MODS":
        mods = load_moderators()
        rows = []
        for m_uid in list(mods)[:20]:
            rows.append([InlineKeyboardButton(f"🗑 إزالة {m_uid}", callback_data=f"ADM_RMMOD_{m_uid}")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="ADM_STATS")])
        count = len(mods)
        text = f"🛡️ المشرفون ({count}):\n──────────────────────────\n"
        if mods:
            text += "\n".join(f"• `{m}`" for m in list(mods)[:20])
        else:
            text += "لا يوجد مشرفون حالياً."
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

    elif query.data.startswith("ADM_RMMOD_"):
        target = query.data[len("ADM_RMMOD_"):]
        remove_moderator(target)
        try:
            await context.bot.send_message(chat_id=int(target), text="⚠️ تم إزالتك من قائمة المشرفين.")
        except Exception:
            pass
        await query.edit_message_text(f"✅ تم إزالة المشرف {target}.", reply_markup=admin_keyboard())

    # ── قائمة المحظورين ──
    elif query.data == "ADM_BANNED":
        banned = load_banned()
        rows = []
        for b_uid in list(banned)[:20]:
            rows.append([InlineKeyboardButton(f"🔓 رفع حظر {b_uid}", callback_data=f"ADM_UNBAN_{b_uid}")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="ADM_STATS")])
        count = len(banned)
        text = f"🚫 المحظورون ({count}):\n──────────────────────────\n"
        if banned:
            text += "\n".join(f"• `{b}`" for b in list(banned)[:20])
        else:
            text += "لا يوجد مستخدمون محظورون."
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

    elif query.data.startswith("ADM_UNBAN_"):
        target = query.data[len("ADM_UNBAN_"):]
        unban_user(target)
        try:
            await context.bot.send_message(chat_id=int(target), text="✅ تم رفع الحظر عنك. يمكنك استخدام البوت مجدداً.")
        except Exception:
            pass
        await query.edit_message_text(f"✅ تم رفع الحظر عن {target}.", reply_markup=admin_keyboard())

    # ── قبول/رفض طلب مشرف ──
    elif query.data.startswith("ADM_APPMOD_"):
        target = query.data[len("ADM_APPMOD_"):]
        add_moderator(target)
        try:
            await context.bot.send_message(
                chat_id=int(target),
                text="🎉 تمت الموافقة على طلبك! أنت الآن مشرف في البوت.\nاضغط /start لتجديد القائمة."
            )
        except Exception:
            pass
        await query.edit_message_text(f"✅ تم قبول {target} كمشرف.", reply_markup=admin_keyboard())

    elif query.data.startswith("ADM_REJMOD_"):
        target = query.data[len("ADM_REJMOD_"):]
        try:
            await context.bot.send_message(
                chat_id=int(target),
                text="❌ تم رفض طلبك للانضمام كمشرف."
            )
        except Exception:
            pass
        await query.edit_message_text(f"❌ تم رفض طلب {target}.", reply_markup=admin_keyboard())

    elif query.data == "ADM_MAINTENANCE":
        current = load_maintenance()
        set_maintenance(not current)
        if not current:
            status_text = "🔧 تم تفعيل وضع الصيانة.\nالمستخدمون العاديون لن يستطيعوا الوصول للبوت."
        else:
            status_text = "✅ تم إلغاء وضع الصيانة. البوت يعمل الآن للجميع."
        await query.edit_message_text(status_text, reply_markup=admin_keyboard())

    elif query.data == "ADM_BROADCAST":
        context.user_data["awaiting_broadcast"] = True
        await query.edit_message_text(
            "📢 إرسال إشعار لكل المستخدمين\n"
            "──────────────────────────\n"
            "اكتب نص الإشعار الذي تريد إرساله:\n\n"
            "⚠️ سيُرسل هذا النص لجميع مستخدمي البوت فوراً.\n\n"
            "للإلغاء اكتب: إلغاء"
        )


async def admin_broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج مستقل — يستقبل نص الإشعار من الأدمن بعد الضغط على ADM_BROADCAST"""
    uid = str(update.effective_user.id)
    if not is_admin(uid) or not context.user_data.get("awaiting_broadcast"):
        return

    context.user_data.pop("awaiting_broadcast", None)

    try:
        await update.message.delete()
    except Exception:
        pass

    text = update.message.text.strip()
    if text in ("إلغاء", "/cancel"):
        await update.effective_chat.send_message(
            "❌ تم إلغاء الإرسال.",
            reply_markup=admin_keyboard()
        )
        return

    user_ids = get_all_user_ids()
    msg_text = (
        "📢 إشعار من الإدارة\n"
        "══════════════════════\n\n"
        f"{text}\n\n"
        "──────────────────────────\n"
        "🤖 FX INTERNET BOT"
    )

    status_msg = await update.effective_chat.send_message(
        f"⏳ جاري الإرسال لـ {len(user_ids)} مستخدم..."
    )

    success, failed = 0, 0
    for target_uid in user_ids:
        try:
            await context.bot.send_message(chat_id=int(target_uid), text=msg_text)
            success += 1
        except Exception as e:
            logger.warning(f"broadcast failed for {target_uid}: {e}")
            failed += 1

    await status_msg.edit_text(
        f"✅ تم الإرسال!\n\n"
        f"📨 وصل لـ: {success} مستخدم\n"
        f"❌ فشل لـ: {failed} مستخدم",
        reply_markup=admin_keyboard()
    )


# ══════════════════════════════════════════════════════════════
#  حظر المستخدمين — استقبال الإدخال من المشرف
# ══════════════════════════════════════════════════════════════
async def handle_ban_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يستقبل User ID أو رقم هاتف ثم يحظر المستخدم"""
    uid  = str(update.effective_user.id)
    text = update.message.text.strip()

    try:
        await update.message.delete()
    except Exception:
        pass

    if text.lower() in ("إلغاء", "/cancel"):
        await update.effective_chat.send_message("❌ تم إلغاء الحظر.", reply_markup=mod_keyboard())
        return MAIN_MENU

    target_uid = None

    # محاولة تفسير النص كرقم هاتف أولاً
    msisdn = clean_phone(text)
    if msisdn:
        target_uid = get_uid_by_phone(msisdn)
        if not target_uid:
            await update.effective_chat.send_message(
                f"⚠️ لم يُعثر على مستخدم مسجّل بالرقم {fmt_phone(msisdn)}.\n"
                "أدخل معرّف المستخدم (User ID) مجدداً أو اكتب: إلغاء"
            )
            return BAN_INPUT
    elif text.isdigit():
        target_uid = text
    else:
        await update.effective_chat.send_message(
            "⚠️ أدخل رقم هاتف صحيح أو معرّف مستخدم رقمي.\n"
            "للإلغاء اكتب: إلغاء"
        )
        return BAN_INPUT

    if not target_uid:
        await update.effective_chat.send_message(
            "⚠️ لم يُعثر على مستخدم.\nأدخل مجدداً أو اكتب: إلغاء"
        )
        return BAN_INPUT

    if is_admin(target_uid):
        await update.effective_chat.send_message(
            "❌ لا يمكن حظر المشرف الرئيسي.", reply_markup=mod_keyboard()
        )
        return MAIN_MENU

    if target_uid == uid:
        await update.effective_chat.send_message(
            "❌ لا يمكنك حظر نفسك.", reply_markup=mod_keyboard()
        )
        return MAIN_MENU

    ban_user(target_uid)
    label = fmt_phone(msisdn) if msisdn else f"`{target_uid}`"
    await update.effective_chat.send_message(
        f"✅ تم حظر المستخدم {label} بنجاح.",
        reply_markup=mod_keyboard(),
        parse_mode="Markdown"
    )
    try:
        await context.bot.send_message(
            chat_id=int(target_uid),
            text="🚫 تم حظرك من استخدام هذا البوت من قِبَل الإدارة."
        )
    except Exception:
        pass

    return MAIN_MENU


# ══════════════════════════════════════════════════════════════
#  تجديد التوكنات تلقائياً كل ساعة
# ══════════════════════════════════════════════════════════════
async def auto_refresh_all_tokens(context) -> None:
    """تعمل كل ساعة — تجدّد access_token لكل الحسابات باستخدام refresh_token"""
    data    = load_sessions()
    changed = False

    for uid, user in data.items():
        accounts = user.get("accounts", {})
        for msisdn, acc in accounts.items():
            rtoken = acc.get("refresh_token", "")
            if not rtoken:
                logger.info(f"[auto-refresh] {msisdn} — لا يوجد refresh_token، تخطّي")
                continue

            new_access, new_refresh = refresh_access_token(msisdn, rtoken)
            if new_access:
                acc["token"]         = new_access
                acc["refresh_token"] = new_refresh or rtoken
                changed = True
                logger.info(f"[auto-refresh] ✅ {msisdn} — تم تجديد التوكن")
            else:
                logger.warning(f"[auto-refresh] ❌ {msisdn} — فشل التجديد")

    if changed:
        save_sessions(data)
        logger.info("[auto-refresh] 💾 تم حفظ التوكنات المجدّدة")


# ══════════════════════════════════════════════════════════════
#  أوامر المشرفين
# ══════════════════════════════════════════════════════════════
async def cmd_addmod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if not is_moderator(uid):
        await update.message.reply_text("❌ ليس لديك صلاحية لهذا الأمر.")
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "⚠️ الاستخدام: /addmod <user_id>\n"
            "مثال: /addmod 123456789"
        )
        return
    target = args[0]
    if str(target) in {str(a) for a in ADMIN_IDS}:
        await update.message.reply_text("ℹ️ هذا المستخدم أدمن بالفعل.")
        return
    mods = load_moderators()
    if target in mods:
        await update.message.reply_text("ℹ️ هذا المستخدم مشرف بالفعل.")
        return
    add_moderator(target)
    await update.message.reply_text(f"✅ تم إضافة {target} كمشرف.")
    try:
        await context.bot.send_message(
            chat_id=int(target),
            text="🎉 تمت إضافتك كمشرف في البوت!\nاضغط /start لتحديث القائمة."
        )
    except Exception:
        pass


async def cmd_removemod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if not is_moderator(uid):
        await update.message.reply_text("❌ ليس لديك صلاحية لهذا الأمر.")
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "⚠️ الاستخدام: /removemod <user_id>\n"
            "مثال: /removemod 123456789"
        )
        return
    target = args[0]
    if str(target) in {str(a) for a in ADMIN_IDS}:
        await update.message.reply_text("❌ لا يمكن إزالة الأدمن الرئيسي.")
        return
    mods = load_moderators()
    if target not in mods:
        await update.message.reply_text("ℹ️ هذا المستخدم ليس مشرفاً.")
        return
    remove_moderator(target)
    await update.message.reply_text(f"✅ تم إزالة {target} من قائمة المشرفين.")
    try:
        await context.bot.send_message(
            chat_id=int(target),
            text="⚠️ تم إزالتك من قائمة المشرفين."
        )
    except Exception:
        pass


async def cmd_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if not is_moderator(uid):
        await update.message.reply_text("❌ ليس لديك صلاحية لهذا الأمر.")
        return
    current = load_maintenance()
    set_maintenance(not current)
    if not current:
        await update.message.reply_text(
            "🔧 تم تفعيل وضع الصيانة.\n"
            "المستخدمون العاديون لن يستطيعوا الوصول للبوت."
        )
    else:
        await update.message.reply_text(
            "✅ تم إلغاء وضع الصيانة.\n"
            "البوت يعمل الآن للجميع."
        )


# ══════════════════════════════════════════════════════════════
#  تشغيل البوت
# ══════════════════════════════════════════════════════════════
def main():
    app  = Application.builder().token(API_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_ACCOUNT:  [CallbackQueryHandler(select_account)],
            PHONE:           [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone)],
            OTP:             [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_otp)],
            MAIN_MENU:       [CallbackQueryHandler(menu_actions)],
            REFERRAL_PHONE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_referral_phone)],
            REAUTH_OTP:      [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reauth_otp)],
            BAN_INPUT:       [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ban_input)],
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
        allow_reentry=True,
    )

    # ── handlers الأدمن المستقلة (group=0 تأخذ الأولوية على conv) ──
    app.add_handler(CommandHandler("admin",       admin_panel))
    app.add_handler(CommandHandler("addmod",      cmd_addmod))
    app.add_handler(CommandHandler("removemod",   cmd_removemod))
    app.add_handler(CommandHandler("maintenance", cmd_maintenance))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^ADM_"))

    # ── handler نص broadcast للأدمن في group مختلف ──
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.User(list(ADMIN_IDS)),
            admin_broadcast_text
        ),
        group=1
    )

    app.add_handler(conv)

    # تجديد التوكنات تلقائياً كل ساعة (أول تشغيل بعد 60 ثانية)
    app.job_queue.run_repeating(auto_refresh_all_tokens, interval=3600, first=60)

    logger.info("✅ FX INTERNET BOT — شغّال")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
