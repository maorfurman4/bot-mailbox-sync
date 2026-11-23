#!/usr/bin/env python3
"""
מנהל המייל — רץ 3 פעמים ביום (GitHub Actions) ומסדר את Gmail בתוויות.
כל מייל חדש בתיבה: חסימה → שולח מוכר / מיון של Gmail (בלי AI) → AI רק למה שנשאר → הגנה → מקום:
  📬 חשוב, 🧾 חשבון פתוח, 🎓 לימודים, 🔐 אבטחה — בתיבה עם תווית
  🧾 קבלה ששולמה, 💻 פיתוח, ✈️ הזמנות, 🎟️ קופונים, 📁 כללי — בארכיון, בתוך התווית
  🗑️ זבל/חסום — לפח + ביטול הרשמה
טלגרם: רק חשבונות וקבלות (בוט הקבלות) ודוח תקלות.
DRY_RUN=1: רק מדפיס החלטות. ORGANIZE_ALL=1: מסדר גם את כל המיילים הישנים בתיבה (בלי טלגרם/יומן).
"""
import base64
import hashlib
import html
import io
import json
import os
import re
import sys
from datetime import datetime, timedelta
from email.utils import parseaddr
from urllib.parse import urlparse

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

import important
import rules
import subs
from aura_report import ai, cfg_get, paused, station, working

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

# =============================================================================
# ─── CONFIG & SECRETS ────────────────────────────────────────────────────────
# =============================================================================
DRY_RUN = os.environ.get("DRY_RUN", "").strip() == "1"
ORGANIZE_ALL = os.environ.get("ORGANIZE_ALL", "").strip() == "1"
if DRY_RUN:
    os.environ["AURA_REPORT"] = "off"  # a dry run (and the tests) must not show up in the office
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()

MERGE = os.environ.get("MERGE_LABELS", "").strip() == "1"
TIDY_INBOX = os.environ.get("TIDY_INBOX", "").strip() == "1"

DONE_LABEL = "Mail_Bot_Done"          # כל מייל שהבוט טיפל בו (מוסתרת מרשימת התוויות)
# התוויות שלך — מתמזגות לתוויות החדשות ונמחקות (באישור מאור, 24/10/2026)
MERGE_LABELS = ["חיובים[", "split", "הזמנות", "קופוננים קארפור", "רודוס", "הנדסת חשמל", "עוסק פטור", "חשוב", "קופונים"]
OLD_BOT_LABELS = ["Processed_By_Bot", "Maintenance_Processed"]  # של הגרסה הקודמת — נמחקות

# קטגוריה → (תווית, נשאר בתיבה?, צבע רקע). בתיבה נשאר רק מה שצריך טיפול.
PLACES = {
    "important": ("📬 חשוב", True, "#fb4c2f"),
    "bill": ("🧾 חשבונות", True, "#ffad47"),
    "studies": ("🎓 לימודים", True, "#4a86e8"),
    "security": ("🔐 אבטחה", True, "#a479e2"),
    "dev": ("💻 פיתוח", False, "#666666"),
    "orders": ("✈️ הזמנות ונסיעות", False, "#16a766"),
    "coupon": ("🎟️ קופונים", False, "#f691b3"),
    "other": ("📁 כללי", False, "#cccccc"),
    "waiting": ("⏳ ממתין לתשובה", True, "#fad165"),  # לא קטגוריה של מיון — נוסף למייל חשוב שלא ענית לו
}
CATEGORIES = set(PLACES) - {"waiting"} | {"junk"}
EXPIRY_DAYS = {"security": 1, "dev": 1, "studies": 2}  # אחרי כמה ימים לפח (בלימודים — רק דיוור מערכת)
WAITING_AFTER_DAYS = 3

# בוט הלימודים — רק דוח תקלות; בוט הקבלות — חשבונות וקבלות
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()
TELEGRAM_TOKEN_RECEIPTS = os.environ.get("TELEGRAM_TOKEN_RECEIPTS", "").strip()
CHAT_ID_RECEIPTS = os.environ.get("CHAT_ID_RECEIPTS", "").strip()
MONDAY_API_TOKEN = os.environ.get("MONDAY_API_TOKEN", "").strip()
FINANCE_BOT_TOKEN = os.environ.get("FINANCE_BOT_TOKEN", "").strip()  # בוט הכספים — חיובים מהמייל

FAILURES = []
PREFS = important.load_prefs()  # 👍/👎/🚫 ו"אפקה חשוב" — יהלי כותבת ל-prefs.json
IMPORTANT = []  # מועמדים ל-📣 בריצה הזו

# AURA HQ (aura_report.py): station reports to the office — counts only, never a subject, a sender or an amount
BOT = "mail"
DESTINATIONS = ("receipts", "calendar", "monday", "yahli", "finance")
SENT = dict.fromkeys(DESTINATIONS + ("bills",), 0)  # what really went out in this run

class stage(working):
    """working(), but an error reports only its type: the text can hold a Telegram URL with the token, a subject or an amount."""
    def __exit__(self, exc_type, exc, tb):
        return super().__exit__(exc_type, exc and "הפרטים בלוג הריצה", tb)

def labeled(stats: dict) -> int:
    return sum(stats[k] for k in PLACES)

def accountant(fn, *args):
    """The accountant station around one money mail (bill / expense / order / subscription); result and errors pass through."""
    with stage(BOT, "accountant", "מחלץ פרטים ממייל כספי") as w:
        result = fn(*args)
        SENT["bills"] += 1
        w.done(f"{SENT['bills']} מיילים כספיים טופלו", bills=SENT["bills"])
        return result

def fail(section: str, ex) -> None:
    print(f"❌ {section}: {ex}")
    detail = re.sub(r"https?://\S+", "<url>", str(ex))[:150]  # כתובת טלגרם מכילה את הטוקן
    FAILURES.append(f"• <b>{html.escape(section)}</b>: {html.escape(detail)}")

def public(line: str) -> str:
    """The repo and its run logs are public (2026-11-23): on GitHub the personal part of a log line (after ':', or the
    address after 'unsubscribe') becomes '…'. Run locally, the full line stays."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return line
    head, sep, _ = line.partition(":")
    return f"{head}: …" if sep else re.sub(r"^unsubscribe \S+", "unsubscribe …", line)

def act(description: str, fn, *args, **kwargs):
    """כל שינוי במייל/יומן/טלגרם עובר כאן, כדי ש-DRY_RUN באמת לא ישנה כלום."""
    print(("🧪 [dry] " if DRY_RUN else "▶️ ") + public(description))
    if not DRY_RUN:
        return fn(*args, **kwargs)

# =============================================================================
# ─── חוקים (טהורים — נבדקים ב-test_mail.py) ─────────────────────────────────
# =============================================================================
def sender_of(from_header: str) -> str:
    return parseaddr(from_header or "")[1].strip().lower()

def _matches(address: str, entries: list) -> bool:
    domain = address.rsplit("@", 1)[-1]
    return any(address == e or domain == e or domain.endswith("." + e) for e in entries)

def is_blocked(address: str, from_header: str = "") -> bool:
    return _matches(address, rules.BLOCK) or important.pref_of(PREFS, address, from_header) == "block"

def is_protected(address: str, subject: str) -> bool:
    return _matches(address, rules.PROTECT) or bool(re.search(rules.PROTECT_SUBJECT, subject or "", re.I))

def is_ad(subject: str) -> bool:
    # לפי החוק פרסומת מסומנת "פרסומת" בתחילת הנושא או בסופו; באמצע (חשבונית "מכיל דבר פרסומת") — לא
    s = (subject or "").strip(" .|-–")
    return s.startswith("פרסומת") or s.endswith("פרסומת")

def known_category(address: str, subject: str, gmail_labels: list):
    """קטגוריה בלי AI: שולח מוכר (כתובת מדויקת לפני דומיין), או פרסומת/רשת חברתית לפי Gmail. None = לשאול AI."""
    exact = [c for c, entries in rules.KNOWN.items() if address in entries]
    known = exact[0] if exact else next(
        (c for c, entries in rules.KNOWN.items() if _matches(address, [e for e in entries if "@" not in e])), None)
    if known and not (known == "bill" and not re.search(rules.RECEIPT_SUBJECT, subject or "", re.I)):
        return known
    if {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL"} & set(gmail_labels) and not is_protected(address, subject):
        return "junk"
    return None

def decide(address: str, subject: str, category: str) -> str:
    """אבטחה > חסימה > פרסומת > הגנה > קטגוריה; שולח ממשלתי/בריאות תמיד "חשוב"."""
    if re.search(rules.SECURITY_SUBJECT, subject or "", re.I) or address.split("@")[0] in ("security", "account", "accounts"):
        return "security"
    if is_blocked(address):
        return "block"
    category = category if category in CATEGORIES else "other"
    if is_ad(subject):
        category = "junk"
    elif category == "junk" and is_protected(address, subject):
        category = "other"
    if category == "other" and _matches(address, rules.KNOWN["important"]):
        category = "important"
    return category

def is_afeka_system(address: str) -> bool:
    local, _, domain = address.partition("@")
    return domain == "afeka.ac.il" and (local in rules.AFEKA_SYSTEM or "reply" in local)

def is_expired(category: str, subject: str, address: str) -> bool:
    """אבטחה ופיתוח — כולם; לימודים — רק דיוור מערכת של אפקה (שיחה שענית בה נבדקת בנפרד)."""
    return category in ("security", "dev") or (category == "studies" and is_afeka_system(address))

def is_person(address: str, subject: str) -> bool:
    local, _, domain = address.partition("@")
    if re.search(rules.NOT_PERSON, local, re.I) or re.search(rules.AUTO_REPLY_SUBJECT, subject or "", re.I):
        return False
    return domain in rules.PERSONAL_DOMAINS or bool(re.search(r"[._]", local))

def i_replied(thread_labels: list) -> bool:
    return any("SENT" in labels for labels in thread_labels)

def placement(category: str, paid: bool = False, address: str = "") -> tuple:
    name, in_inbox, _ = PLACES[category]
    if (category == "bill" and paid) or (category == "studies" and is_afeka_system(address)):
        in_inbox = False
    return name, in_inbox

def parse_batch(answer: dict, count: int) -> dict:
    out = {}
    for r in answer.get("results", []) if isinstance(answer, dict) else []:
        if isinstance(r, dict) and r.get("i") in range(count) and r.get("category") in CATEGORIES:
            out[r["i"]] = r["category"]
    return out

def merge_action(action: str, subject: str) -> str:
    """במיזוג התוויות שלך: זבל לפי ה-AI לא נמחק — רק פרסומת מסומנת או שולח חסום."""
    return "other" if action == "junk" and not is_ad(subject) else action

def inbox_change(in_inbox: bool, labels: list, move: bool) -> tuple:
    """(להוסיף, להסיר) — תיבה. move=False (מיזוג/סידור ישן): לא מזיזים כלום."""
    if not move:
        return None, None
    has = "INBOX" in labels
    return ("INBOX" if in_inbox and not has else None), ("INBOX" if has and not in_inbox else None)

def _site(host: str) -> str:
    """הדומיין הרשום: pay.meiavivim.co.il → meiavivim.co.il, a.b.example.com → example.com."""
    parts = host.lower().split(".")
    return ".".join(parts[-3:] if len(parts) > 2 and parts[-2] in ("co", "org", "gov", "ac", "net") else parts[-2:])

def safe_pay_link(link, address: str, body: str) -> bool:
    link = str(link or "")
    if not link.startswith("https://") or link not in (body or ""):
        return False  # רק קישור שבאמת מופיע במייל, ולא משהו שה-AI המציא
    host = urlparse(link).hostname or ""
    return _site(host) == _site(address.rsplit("@", 1)[-1]) or any(
        host == p or host.endswith("." + p) for p in rules.PAYMENT_PROCESSORS)

def parse_due(text):
    try:
        return datetime.strptime(str(text or "").strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None

def one_click_url(headers: dict):
    """ביטול הרשמה רק בתקן One-Click (RFC 8058) — בלי לפתוח דפים ובלי לשלוח מיילים בשמך."""
    if "one-click" not in (headers.get("List-Unsubscribe-Post") or "").lower():
        return None
    urls = re.findall(r"<(https://[^>]+)>", headers.get("List-Unsubscribe") or "")
    return urls[0] if urls else None

# =============================================================================
# ─── Google, Gmail, Telegram, AI ─────────────────────────────────────────────
# =============================================================================
def get_google_services():
    creds = Credentials.from_authorized_user_info(json.loads(os.environ["GOOGLE_CREDENTIALS"]), [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/calendar",
    ])
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds), build("calendar", "v3", credentials=creds)

_LABELS = {}

def label_id(gmail, name: str, color: str | None = None) -> str:
    if not _LABELS:
        _LABELS.update({l["name"]: l["id"] for l in gmail.users().labels().list(userId="me").execute().get("labels", [])})
    if name not in _LABELS:
        if DRY_RUN:
            return f"<{name}>"
        body = {"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
        try:
            _LABELS[name] = gmail.users().labels().create(userId="me", body={
                **body, "color": {"backgroundColor": color, "textColor": "#ffffff"}} if color else body).execute()["id"]
        except Exception:  # צבע שלא בפלטה של Gmail — בלי צבע
            _LABELS[name] = gmail.users().labels().create(userId="me", body=body).execute()["id"]
    return _LABELS[name]

def safe_b64decode(data: str) -> bytes:
    data = data or ""
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))

def extract_body(gmail, msg_id, payload, snippet="") -> str:
    body_text = ""
    def text_of(data: str) -> str:
        try:
            return safe_b64decode(data).decode("utf-8", errors="ignore")
        except Exception:
            return ""
    def strip_html(raw: str) -> str:
        raw = re.sub(r'<a\s+(?:[^>]*?\s+)?href=["\'](http[^"\']+)["\'][^>]*>(.*?)</a>', r'\2 (Link: \1)', raw, flags=re.I)
        return re.sub(r"<[^>]+>", " ", raw)

    if "parts" in payload:
        for part in payload["parts"]:
            mime_type = part.get("mimeType", "")
            if mime_type == "text/plain":
                body_text += text_of(part.get("body", {}).get("data", ""))
            elif mime_type == "text/html":
                body_text += strip_html(text_of(part.get("body", {}).get("data", "")))
            elif PyPDF2 and (mime_type == "application/pdf" or part.get("filename", "").lower().endswith(".pdf")):
                for name, data in pdf_attachments(gmail, msg_id, {"parts": [part]}):
                    try:
                        reader = PyPDF2.PdfReader(io.BytesIO(data))
                        body_text += f"\n--- PDF ({name}) ---\n" + "".join(p.extract_text() or "" for p in reader.pages)
                    except Exception as e:
                        print(public(f"❌ PDF extraction error: {name} {e}"))
            elif "parts" in part:
                body_text += extract_body(gmail, msg_id, part)
    elif payload.get("body", {}).get("data"):
        body_text += strip_html(text_of(payload["body"]["data"]))
    clean = re.sub(r"\s+", " ", body_text).strip()
    return clean if len(clean) > 10 else snippet

def pdf_attachments(gmail, msg_id, payload) -> list:
    out = []
    for part in payload.get("parts", []):
        name = part.get("filename", "")
        if part.get("mimeType") == "application/pdf" or name.lower().endswith(".pdf"):
            att_id = part.get("body", {}).get("attachmentId")
            if att_id:
                att = gmail.users().messages().attachments().get(userId="me", messageId=msg_id, id=att_id).execute()
                out.append((name or "document.pdf", safe_b64decode(att["data"])))
        elif "parts" in part:
            out += pdf_attachments(gmail, msg_id, part)
    return out

def gmail_link(msg_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#all/{msg_id}"

def telegram(token, chat_id, text, buttons=None):
    if not token or not chat_id:
        raise RuntimeError("missing Telegram token/chat id")
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": [[b] for b in buttons]}
    resp = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=15)
    if not resp.json().get("ok"):
        raise RuntimeError(f"Telegram: {resp.json().get('description')}")

def telegram_file(token, chat_id, name: str, data: bytes):
    resp = requests.post(f"https://api.telegram.org/bot{token}/sendDocument", data={"chat_id": chat_id},
                         files={"document": (name, data, "application/pdf")}, timeout=30)
    if not resp.json().get("ok"):
        raise RuntimeError(f"Telegram file: {resp.json().get('description')}")

# gpt-4o-mini shuts down on 2027-01-14. gpt-6.1-terra sorted more precisely in a side-by-side test (2026-11-19); gpt-6-luna was cheaper
# but called a homework reminder junk and a Facebook security notice an order.
AI_MODEL = os.environ.get("AI_MODEL", "").strip() or "gpt-6.1-terra"

def ask_ai(prompt: str) -> dict:
    resp = requests.post("https://api.openai.com/v1/chat/completions", timeout=120,
                         headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                         json={"model": AI_MODEL, "reasoning_effort": "low", "response_format": {"type": "json_object"},
                               "messages": [{"role": "user", "content": prompt}]})
    resp.raise_for_status()
    data = resp.json()
    ai(AI_MODEL, data)  # AURA HQ: tokens for the open smart/accountant/important block
    return json.loads(data["choices"][0]["message"]["content"])

# =============================================================================
# ─── מיון ────────────────────────────────────────────────────────────────────
# =============================================================================
TRIAGE_PROMPT = """אתה ממיין את המייל של מאור — סטודנט להנדסת חשמל, מאבטח במשמרות, מפתח אפליקציות ובוטים.
לכל מייל ברשימה בחר קטגוריה אחת:
important = אדם פרטי שכותב לו, ממשלה, בריאות, בנק, משפטי, עבודה, משהו שמחכה לתשובה או לטיפול
bill = חשבון לתשלום, דרישת תשלום, חשבונית או קבלה
coupon = שובר, קופון, גיפט קארד, קוד הטבה למימוש
studies = לימודים ואוניברסיטה
security = התראת אבטחה, כניסה ממכשיר חדש, שינוי סיסמה, קוד אימות
dev = GitHub, Vercel, שרתים, פיתוח תוכנה
orders = אישור הזמנה, טיסה, נסיעה, כרטיס, שירות שהוזמן
other = שימושי אבל לא דחוף
junk = פרסומת, מבצע, ניוזלטר, רשת חברתית, לא קשור אליו

{emails}

החזר JSON בלבד: {{"results": [{{"i": 0, "category": "..."}}]}}"""

def fetch(gmail, query: str, limit: int, label_ids: list | None = None) -> list:
    msgs, token = [], None
    while len(msgs) < limit:
        res = gmail.users().messages().list(userId="me", q=query, maxResults=min(100, limit), pageToken=token,
                                            labelIds=label_ids or None).execute()
        msgs += res.get("messages", [])
        token = res.get("nextPageToken")
        if not token:
            break
    return msgs[:limit]

def metadata(gmail, msg_id: str) -> dict:
    full = gmail.users().messages().get(
        userId="me", id=msg_id, format="metadata",
        metadataHeaders=["From", "Subject", "List-Unsubscribe", "List-Unsubscribe-Post", "To", "Cc", "Precedence",
                         "List-Id"]).execute()
    headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
    return {"id": msg_id, "headers": headers, "from": headers.get("From", ""), "sender": sender_of(headers.get("From", "")),
            "subject": headers.get("Subject", "(ללא נושא)"), "snippet": html.unescape(full.get("snippet", "")),
            "labels": full.get("labelIds", []), "thread": full.get("threadId")}

def replied(gmail, mail: dict) -> bool:
    thread = gmail.users().threads().get(userId="me", id=mail["thread"], format="minimal").execute()
    return i_replied([m.get("labelIds", []) for m in thread.get("messages", [])])

def junk(gmail, mail: dict, unsubscribed: set, stats: dict):
    url = one_click_url(mail["headers"])
    if url and mail["sender"] not in unsubscribed:
        unsubscribed.add(mail["sender"])
        try:
            act(f"unsubscribe {mail['sender']}", requests.post, url, data={"List-Unsubscribe": "One-Click"}, timeout=15)
            stats["unsubscribed"] += 1
        except Exception as ex:
            print(public(f"⚠️ unsubscribe failed: {mail['sender']} {ex}"))
    act(f"trash: {mail['sender']} | {mail['subject'][:60]}", gmail.users().messages().trash(userId="me", id=mail["id"]).execute)
    stats["junk"] += 1

def classify(mails: list) -> dict:
    """שולח מוכר / מיון של Gmail בלי AI; את השאר — קריאת AI אחת לכל 25 מיילים."""
    with stage(BOT, "rules", f"ממיין {len(mails)} מיילים לפי כללים") as w:
        result = {m["id"]: known_category(m["sender"], m["subject"], m["labels"]) for m in mails}
        unknown = [m for m in mails if result[m["id"]] is None]
        w.done(f"{len(mails) - len(unknown)} מתוך {len(mails)} סווגו לפי כללים", classified=len(mails) - len(unknown))
    if unknown:
        with stage(BOT, "smart", f"ממיין {len(unknown)} מיילים עם AI") as w:
            classify_ai(unknown, result)
            w.done(f"{len(unknown)} מיילים סווגו ב-AI", mails=len(unknown), calls=-(-len(unknown) // 25))
    print(f"🧮 {len(mails)} emails: {len(mails) - len(unknown)} by rules, {len(unknown)} by AI "
          f"in {-(-len(unknown) // 25)} call(s)")
    return result

def classify_ai(unknown: list, result: dict) -> None:
    for start in range(0, len(unknown), 25):
        chunk = unknown[start:start + 25]
        listing = "\n".join(f'{i}. שולח: {m["from"]} | נושא: {m["subject"]} | תקציר: {m["snippet"][:200]}'
                            for i, m in enumerate(chunk))
        try:
            answers = parse_batch(ask_ai(TRIAGE_PROMPT.format(emails=listing)), len(chunk))
        except Exception as ex:
            fail("סיווג AI", ex)
            answers = {}
        for i, m in enumerate(chunk):
            result[m["id"]] = answers.get(i, "other")  # בלי תשובה → כללי (לא נמחק)

def apply_labels(gmail, calendar, mails, stats, unsubscribed, *, move: bool, notify: bool, merging: bool = False):
    """מיון → תווית. move: להזיז לתיבה/ממנה; notify: חשבון לטלגרם ויומן; merging: מיזוג התוויות הישנות."""
    done_id = label_id(gmail, DONE_LABEL)
    categories = classify(mails)
    before = labeled(stats)
    with stage(BOT, "filer", f"מתייק {len(mails)} מיילים") as w:
        for mail in mails:
            action = decide(mail["sender"], mail["subject"], categories[mail["id"]])
            if merging:
                action = merge_action(action, mail["subject"])
            print(public(f"📨 {action:9} ← {categories[mail['id']]!s:9}: {mail['sender']} | {mail['subject'][:60]}"))
            try:
                if action in ("junk", "block"):
                    junk(gmail, mail, unsubscribed, stats)
                    continue
                paid = True
                if notify and (vendor := business_vendor(mail["sender"], mail["subject"])):
                    accountant(handle_expense, gmail, mail, vendor)  # בנוסף למיון הרגיל (Vercel/Render הם "פיתוח")
                if notify and action not in ("junk", "block") and (
                        action == "important" or important.pref_of(PREFS, mail["sender"], mail["from"]) == "important"
                        or important.MOVE_SUBJECT.search(mail["subject"] or "")):  # 🔁 מועד שזז — גם מייל לכל הקורס
                    IMPORTANT.append(mail)  # 📣 — נבדק בסוף הריצה (אישי? AI? מכסה)
                if notify and action not in ("junk", "block", "bill") and (kind := subs.kind_of(mail["subject"])):
                    accountant(handle_subscription, gmail, mail, kind)  # 💳 מנוי חדש / ⏳ ניסיון / 📈 מחיר → בוט הכספים
                if action == "bill" and notify:
                    paid = accountant(handle_bill, gmail, calendar, mail)
                elif notify and is_order(mail["sender"], mail["subject"]):
                    accountant(handle_order, gmail, mail)  # בנוסף למיון הרגיל (נשאר ב-✈️ הזמנות)
                name, in_inbox = placement(action, paid=paid, address=mail["sender"])
                add, remove = inbox_change(in_inbox, mail["labels"], move)
                body = {"addLabelIds": [label_id(gmail, name, PLACES[action][2]), done_id] + ([add] if add else [])}
                if remove:
                    body["removeLabelIds"] = [remove]
                act(f"{name}{' → inbox' if add else ' (archive)' if remove else ''}: {mail['subject'][:50]}",
                    gmail.users().messages().modify(userId="me", id=mail["id"], body=body).execute)
                stats[action] += 1
            except Exception as ex:
                fail(f"{action}: {mail['subject'][:40]}", ex)
        w.done(f"{labeled(stats) - before} מיילים תויקו", labeled=labeled(stats) - before)

def merge_old_labels(gmail, calendar, stats, unsubscribed):
    """מעביר כל מה שבתוויות שלך לתוויות החדשות, ואז מוחק את התוויות הישנות (המיילים עצמם נשארים)."""
    label_id(gmail, DONE_LABEL)  # טוען את רשימת התוויות
    for name in MERGE_LABELS + OLD_BOT_LABELS:
        lid = _LABELS.get(name)
        if not lid:
            continue
        if name in MERGE_LABELS:
            mails = [m for m in (metadata(gmail, msg["id"]) for msg in fetch(gmail, "-in:trash", 1000, [lid]))
                     if label_id(gmail, DONE_LABEL) not in m["labels"]]
            print(f"🔀 {name}: {len(mails)} emails to move")
            apply_labels(gmail, calendar, mails, stats, unsubscribed, move=False, notify=False, merging=True)
        act(f"delete label {name}", gmail.users().labels().delete(userId="me", id=lid).execute)
    act(f"hide label {DONE_LABEL}", gmail.users().labels().patch(
        userId="me", id=label_id(gmail, DONE_LABEL), body={"labelListVisibility": "labelHide"}).execute)

def organize(gmail, calendar):
    stats = {k: 0 for k in ("junk", "unsubscribed", "expired", *PLACES)}  # כולל "waiting"
    unsubscribed = set()
    if MERGE:
        merge_old_labels(gmail, calendar, stats, unsubscribed)

    # 1) שולחים חסומים — כל מה שבתיבה, גם ישן (כולל 🚫 מיהלי ב-prefs.json)
    blocked = rules.BLOCK + [e for e in PREFS["block"] if not e.startswith("word:")]
    before = stats["junk"]
    with stage(BOT, "doorman", "בודק שולחים חסומים") as w:
        for msg in fetch(gmail, "in:inbox from:(" + " OR ".join(blocked) + ")", 500):
            mail = metadata(gmail, msg["id"])
            # החיפוש של Gmail רחב יותר מהכלל, והתראות אבטחה עוברות חסימה — לכן decide
            if decide(mail["sender"], mail["subject"], "junk") == "block":
                junk(gmail, mail, unsubscribed, stats)
        w.done(f"{stats['junk'] - before} מיילים משולחים חסומים נזרקו", blocked=stats["junk"] - before)

    # 2) מיילים חדשים בכל ה-Gmail — גם מה שפילטרים ישנים העבירו ישר לתוויות ועקף את התיבה.
    #    ORGANIZE_ALL: כל התיבה + 60 יום אחורה, בלי להזיז מיקום ובלי טלגרם/יומן
    base = f"-in:trash -in:spam -in:sent -label:{DONE_LABEL}"
    query = f"(in:inbox OR newer_than:60d) {base}" if ORGANIZE_ALL else f"newer_than:3d {base}"
    mails = [m for m in (metadata(gmail, msg["id"]) for msg in fetch(gmail, query, 1000 if ORGANIZE_ALL else 100))
             if "DRAFT" not in m["labels"]]
    apply_labels(gmail, calendar, mails, stats, unsubscribed, move=not ORGANIZE_ALL, notify=not ORGANIZE_ALL)
    if not ORGANIZE_ALL:
        try:
            with stage(BOT, "important", f"בודק {len(IMPORTANT)} מועמדים למייל חשוב") as w:
                stats["important_sent"] = send_important(gmail, IMPORTANT)
                w.done(f"{stats['important_sent']} מיילים חשובים סומנו", flagged=stats["important_sent"])
        except Exception as ex:
            fail("מיילים חשובים → יהלי", ex)

    # TIDY_INBOX (חד-פעמי): כל מה שבתיבה — גם מה שכבר סומן — מקבל תווית ועובר למקום שלו. בלי טלגרם/יומן
    if TIDY_INBOX:
        inbox = [m for m in (metadata(gmail, msg["id"]) for msg in fetch(gmail, "in:inbox", 1000))
                 if "DRAFT" not in m["labels"]]
        print(f"🧹 tidy inbox: {len(inbox)} emails")
        apply_labels(gmail, calendar, inbox, stats, unsubscribed, move=True, notify=False)

    with stage(BOT, "filer", "זורק מיילים שפג תוקפם ומסמן ממתינים לתשובה") as w:
        # 3) פג תוקף → לפח: אבטחה ופיתוח אחרי יום, דיוור מערכת של אפקה אחרי יומיים — אבל לא שיחה שענית בה.
        #    לפי מזהה התווית — חיפוש לפי שם עם אימוג'י לא אמין
        for category, days in EXPIRY_DAYS.items():
            lid = label_id(gmail, PLACES[category][0])
            if lid.startswith("<"):
                continue  # DRY_RUN לפני שהתווית נוצרה
            for msg in fetch(gmail, f"older_than:{days}d -in:trash", 500, [lid]):
                mail = metadata(gmail, msg["id"])
                if is_expired(category, mail["subject"], mail["sender"]) and not (
                        category == "studies" and replied(gmail, mail)):
                    act(f"expired → trash: {mail['subject'][:50]}",
                        gmail.users().messages().trash(userId="me", id=mail["id"]).execute)
                    stats["expired"] += 1

        # 4) ⏳ ממתין לתשובה — מייל חשוב מאדם, בתיבה יותר מ-3 ימים, ועוד לא ענית בשיחה
        important_id, waiting_id = label_id(gmail, PLACES["important"][0]), label_id(gmail, *PLACES["waiting"][::2])
        if not important_id.startswith("<"):
            for msg in fetch(gmail, f"in:inbox older_than:{WAITING_AFTER_DAYS}d", 200, [important_id]):
                mail = metadata(gmail, msg["id"])
                waiting = is_person(mail["sender"], mail["subject"]) and not replied(gmail, mail)
                if waiting != (waiting_id in mail["labels"]):  # להוסיף, או להוריד אחרי שענית
                    act(f"{'⏳ waiting' if waiting else '✔️ replied'}: {mail['subject'][:50]}",
                        gmail.users().messages().modify(userId="me", id=mail["id"], body={
                            "addLabelIds" if waiting else "removeLabelIds": [waiting_id]}).execute)
                    stats["waiting"] += waiting
        w.done(f"{labeled(stats)} מיילים תויקו, {stats['expired']} שפג תוקפם נזרקו", labeled=labeled(stats), trashed=stats["expired"])
    return stats

# =============================================================================
# ─── חשבונות וקבלות → בוט הקבלות ─────────────────────────────────────────────
# =============================================================================
BILL_PROMPT = """חלץ מהחשבון/קבלה (כולל טקסט מ-PDF). JSON בלבד, ואם חסר — "לא צוין":
- amount: הסכום הכולל לתשלום כולל מע"מ (סה"כ / סה"כ כולל מע"מ), בדיוק כמו שכתוב בטקסט. לא בטוח — "לא צוין". אסור לנחש.
- is_paid: true גם אם כתוב שהחיוב ייגבה אוטומטית (כרטיס אשראי, הוראת קבע, "לא לתשלום") — אין מה לשלם ידנית.
- טקסט שחולץ מ-PDF בעברית מופיע לפעמים הפוך (מילים ומספרים בסדר הפוך).
{{"merchant": "שם הספק", "amount": "רק המספר", "currency": "₪/$/€", "billing_period": "תקופה או תאריך",
"due_date": "DD/MM/YYYY או לא צוין", "payment_link": "קישור תשלום כפי שמופיע בטקסט, או לא נמצא",
"is_paid": true/false}}
טקסט:
{body}"""

def bill_text(body: str) -> str:
    """הטקסט ל-AI: ה-PDF (החשבונית עצמה) קודם — אחרת הוא נחתך אחרי 3000 התווים ונשאר רק "החשבונית מצורפת",
    וה-AI ממציא סכום (מנהרות הכרמל, 11/2026: "96 ₪" במקום 24.16)."""
    i = body.find("--- PDF")
    return (body[i:] + " " + body[:i] if i > 0 else body)[:3000]

def amount_in_text(amount, text: str) -> bool:
    """הסכום שה-AI החזיר באמת כתוב בחשבונית (גם הפוך — עברית מ-PDF מתהפכת)."""
    a = str(amount or "").replace(",", "").strip()
    if not re.fullmatch(r"\d+(\.\d+)?", a):
        return False
    nums = [n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]
    return any(n in (a, a[::-1]) or float(n) == float(a) for n in nums if re.fullmatch(r"\d+(\.\d+)?", n))

# הסכום הכולל — לפי כללים, לפני ה-AI (8.11: 10bis — ה-AI לקח "11" מהכתובת "קומה 11" במקום 2.0).
# PyPDF2 הופך עברית בחלק מה-PDF-ים: 'םולשתל כ"הס 2.0' — לכן מחפשים כל תווית גם הפוכה; המספרים נשארים בסדר.
TOTAL_LABELS = [  # לפי עדיפות: "לתשלום" > "בש"ח / כולל מע"מ / amount paid" > "סה"כ" לבד (אחרון: אצל 10bis זה לפני מע"מ)
    ('סה"כ לתשלום', "לתשלום", "total due", "amount due"),
    ('סה"כ בש"ח', 'כולל מע"מ', 'סה"כ ils', "amount paid", "total paid", "grand total", "charged"),
    ('סה"כ', "total"),
]
NUM_RE = re.compile(r"(?<![\d.,])\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?(?![\d%])|(?<![\d.,])\d+(?:\.\d{1,2})?(?![\d%])")
DATE_RE = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](20\d\d)(?!\d)")

def _label_at(label: str, line: str) -> int:
    """איפה התווית נגמרת בשורה (גם הפוכה); -1 — לא שם."""
    if label == "total":  # מילה שלמה — לא subtotal
        m = re.search(r"(?<![a-z])total(?![a-z])", line)
        return m.end() if m else -1
    for form in (label, label[::-1]):
        if form in line:
            return line.index(form) + len(form)
    return -1

def total_amount(text: str):
    """(סכום, מטבע): המספר הראשון אחרי תווית הסכום הכולל (אין — האחרון לפניה, ואז השורה הבאה); None — לא נמצא."""
    lines = (text or "").replace("״", '"').replace("׳", "'").lower().splitlines()
    nums = lambda t: [n for n in NUM_RE.findall(t) if float(n.replace(",", "")) > 0]  # noqa: E731
    for labels in TOTAL_LABELS:
        for i, line in enumerate(lines):
            at = max(_label_at(label, line) for label in labels)
            if at < 0:
                continue
            after, before = nums(line[at:]), nums(line[:at])
            nxt = nums(lines[i + 1]) if i + 1 < len(lines) else []
            pick = after[0] if after else before[-1] if before else nxt[0] if nxt else None
            if pick:
                where = line if after or before else f"{line} {lines[i + 1]}"  # "Grand Total:\n$45.00"
                return money(pick), "$" if "$" in where or "usd" in where else "₪"
    return None

def issue_date(text: str):
    """התאריך הראשון בחשבונית (06.11.2026 / 07/11/2026) — לא "05/30" של תוקף הכרטיס."""
    for d, m, y in DATE_RE.findall(text or ""):
        try:
            return datetime(int(y), int(m), int(d)).date()
        except ValueError:
            continue
    return None

def handle_bill(gmail, calendar, mail: dict) -> bool:
    """שולח לבוט הקבלות; מחזיר האם שולם (קבלה ששולמה יוצאת מהתיבה)."""
    full = gmail.users().messages().get(userId="me", id=mail["id"], format="full").execute()
    body = extract_body(gmail, mail["id"], full["payload"], mail["snippet"])
    if _matches(mail["sender"], ["splitwise.com"]):  # חשבונות הדירה — כללים, לא ה-AI הכללי (שם יצא "לא צוין — 135")
        return handle_splitwise(mail, body, mail_date(full))
    source = bill_text(body)
    bill = ask_ai(BILL_PROMPT.format(body=source))
    is_paid = bool(bill.get("is_paid"))
    merchant, amount, currency = bill.get("merchant", "לא צוין"), bill.get("amount", "?"), bill.get("currency", "₪")
    found = total_amount(f"{mail['snippet']}\n{source}")
    if found:  # הכלל קודם ל-AI
        amount, currency = (f"{found[0]:.2f}" if found[0] != int(found[0]) else str(int(found[0]))), found[1]
    elif not amount_in_text(amount, source):
        amount = "לא צוין"  # סכום שלא כתוב בחשבונית — לא מעבירים הלאה (גם לא ליומן)
    issued = issue_date(source)
    if str(bill.get("billing_period", "לא צוין")).strip() in ("", "לא צוין") and issued:
        bill["billing_period"] = f"{issued:%d/%m/%Y}"
    due = parse_due(bill.get("due_date"))

    text = (f"{'✅' if is_paid else '💳'} <b>{'קבלה' if is_paid else 'חשבון לתשלום'}</b>\n\n"
            f"🏪 <b>ספק:</b> {html.escape(str(merchant))}\n💰 <b>סכום:</b> {html.escape(f'{amount} {currency}')}\n"
            f"📅 <b>תקופה/תאריך:</b> {html.escape(str(bill.get('billing_period', 'לא צוין')))}")
    if not is_paid and due:
        text += f"\n⏰ <b>לתשלום עד:</b> {datetime.fromisoformat(due):%d/%m/%Y}"
    buttons = []
    if not is_paid and safe_pay_link(bill.get("payment_link"), mail["sender"], body):
        buttons.append({"text": "💳 לתשלום (באתר של הספק)", "url": bill["payment_link"]})
    buttons.append({"text": "📧 פתח את המייל", "url": gmail_link(mail["id"])})
    act(f"receipt → telegram: {merchant} {amount}", telegram, TELEGRAM_TOKEN_RECEIPTS, CHAT_ID_RECEIPTS, text, buttons)
    SENT["receipts"] += 1
    for name, data in pdf_attachments(gmail, mail["id"], full["payload"]):
        act(f"pdf → telegram: {name}", telegram_file, TELEGRAM_TOKEN_RECEIPTS, CHAT_ID_RECEIPTS, name, data)
    # קבלה ששולמה → בוט הכספים (הצעה ✅/✖️). הוצאת עסק — כבר נשלחה ב-handle_expense
    if is_paid and found and not business_vendor(mail["sender"], mail["subject"]):
        ils = round(found[0] * rules.USD_TO_ILS, 2) if found[1] == "$" else found[0]
        to_finance(vendor_label(mail["sender"], str(merchant)), ils, issued or mail_date(full), False, mail["id"])

    if not is_paid and due:  # חשבון פתוח → יומן ביום האחרון לתשלום (דבי מציג אותו בתדריך)
        exists = calendar.events().list(calendarId="primary", privateExtendedProperty=f"mailbot={mail['id']}").execute()
        if not exists.get("items"):
            end = (datetime.fromisoformat(due) + timedelta(days=1)).strftime("%Y-%m-%d")
            act(f"calendar bill {due}", calendar.events().insert(calendarId="primary", body={
                "summary": f"💳 לשלם {merchant} — {amount} {currency}",
                "description": gmail_link(mail["id"]),
                "start": {"date": due}, "end": {"date": end},
                "extendedProperties": {"private": {"mailbot": mail["id"]}},
            }).execute)
            SENT["calendar"] += 1
    return is_paid

# =============================================================================
# ─── 💸 כסף → monday: חשבונות הדירה (Splitwise) והוצאות עסק ────────────────────
# =============================================================================
def mail_date(full: dict):
    return datetime.fromtimestamp(int(full.get("internalDate", 0)) / 1000).date()

def money(text) -> float:
    return float(str(text).replace(",", ""))

def fmt(amount: float) -> str:
    return f"{amount:g}" if amount != int(amount) else str(int(amount))

def parse_splitwise(subject: str, text: str):
    """→ (מה, למי, כמה אני חייב) / None = אין מה לשלם (אני מקבל, תשלום אליי, סיכום חודשי, עדכון)."""
    added = re.match(r"^['\"“‘](.+?)\s*['\"”’]\s*\(₪[\d,.]+\)\s+added by (\S+)", subject or "")
    if not added or re.search(r"you are owed|you get back", text or "", re.I):
        return None
    owe = re.search(r"you owe\s*₪\s*([\d,]+(?:\.\d+)?)", text or "", re.I)
    item, who = added[1].strip(), added[2]
    return item, rules.SPLITWISE_PAYEES.get(who, who), money(owe[1]) if owe else None

SPLIT_PROMPT = """מייל מ-Splitwise. כמה מאור חייב (רק החלק שלו, לא הסכום הכולל)? אם הוא לא חייב כלום — null.
JSON בלבד: {{"you_owe": מספר או null}}
{text}"""

def handle_splitwise(mail: dict, body: str, day) -> bool:
    """הוצאה בדירה שמאור חייב בה → פריט "לשלם למקסים — חשמל 301 ₪" ב-💳 תשלומים. מחזיר "שולם?" (לתיבה או לארכיון)."""
    parsed = parse_splitwise(mail["subject"], f"{mail['snippet']} {body}")
    if not parsed:
        return " updated by " not in mail["subject"]  # עדכון להוצאה — נשאר בתיבה שיראה; השאר לארכיון
    item, payee, owe = parsed
    if owe is None:  # הכללים לא מצאו "You owe" — AI כגיבוי
        owe = (ask_ai(SPLIT_PROMPT.format(text=f"{mail['subject']}\n{body[:1500]}")) or {}).get("you_owe")
        if not owe:
            return True
        owe = money(owe)
    name = f"לשלם ל{payee} — {item} {fmt(owe)} ₪"
    created = monday_add("אישיות", "תשלומים", name, mail["id"], {
        "סטטוס": {"label": "לא התחיל"}, "דדליין": {"date": (day + timedelta(days=7)).isoformat()},
        "הערות": {"text": f"{gmail_link(mail['id'])}\nSplitwise: סה\"כ לפי המייל, החלק שלך {fmt(owe)} ₪"}})
    SENT["monday"] += created
    if created:  # 16.11: החלק של מאור → בוט הכספים כהצעה (✅/✖️) — בלי ➗; כבר רשם אותו סכום — בוט הכספים מדלג
        finance_post("splitwise share → finance bot", {"vendor": f"{payee} · {item} (החלק שלי)", "amount": owe,
                                                      "date": day.isoformat(), "business": False, "link": gmail_link(mail["id"])})
    act(f"splitwise → telegram: {name}", telegram, TELEGRAM_TOKEN_RECEIPTS, CHAT_ID_RECEIPTS,
        f"💳 <b>{html.escape(name)}</b>\n📅 עד {day + timedelta(days=7):%d/%m}" + ("" if created else " (כבר ב-monday)"),
        [{"text": "📧 פתח את המייל", "url": gmail_link(mail["id"])}])
    SENT["receipts"] += 1
    return False

def business_vendor(address: str, subject: str):
    """(ספק, מה, פרויקט) לקבלה של הוצאת עסק; None אם זה לא ספק עסקי או לא קבלה."""
    domain = next((d for d in rules.BUSINESS_VENDORS if _matches(address, [d])), None)
    if not domain or not re.search(rules.EXPENSE_SUBJECT, subject or "", re.I) \
            or re.search(rules.NOT_EXPENSE_SUBJECT, subject or "", re.I):
        return None
    return rules.BUSINESS_VENDORS[domain]

def parse_amount(text: str):
    """(סכום, מטבע) לפי כללים: "charged $10.00" (OpenAI), "Amount paid $85.88" (Stripe), אחרת הראשון שנמצא."""
    for pattern in (r"charged\s*(\$|₪)\s*([\d,]+(?:\.\d+)?)", r"amount paid\s*(\$|₪)\s*([\d,]+(?:\.\d+)?)",
                    r"total\s*(\$|₪)\s*([\d,]+(?:\.\d+)?)", r"(\$|₪)\s*([\d,]+\.\d{2})"):
        if m := re.search(pattern, text or "", re.I):
            return money(m[2]), m[1]
    return None

def handle_expense(gmail, mail: dict, vendor: tuple) -> None:
    """קבלה של הוצאת עסק → פריט "OpenAI — טעינת קרדיט API" ב-💰 הכנסות והוצאות (סוג הוצאה, סכום ב-₪, בוצע)."""
    name_vendor, what, project = vendor
    full = gmail.users().messages().get(userId="me", id=mail["id"], format="full").execute()
    body = extract_body(gmail, mail["id"], full["payload"], mail["snippet"])
    found = total_amount(f"{mail['snippet']}\n{body}") or parse_amount(f"{mail['snippet']} {body}")
    if not found:  # הכללים לא מצאו — AI כגיבוי
        source = bill_text(body)
        bill = ask_ai(BILL_PROMPT.format(body=source))
        try:
            if not amount_in_text(bill.get("amount"), source):
                raise ValueError("amount not in the receipt")  # לא רושמים הוצאה עם סכום מומצא
            found = money(bill.get("amount")), "$" if "$" in str(bill.get("currency")) else "₪"
        except (TypeError, ValueError):
            fail(f"הוצאה בלי סכום: {mail['subject'][:40]}", "לא נמצא סכום")
            return
    amount, currency = found
    ils = round(amount * rules.USD_TO_ILS, 2) if currency == "$" else amount
    # 8.11: הוצאות עסק עוברות לבוט הכספים ("הוצאות עסקיות" באפליקציה) — לא עוד פריט "הוצאה" בלוח העסקים
    to_finance(f"{name_vendor} — {what}", ils, mail_date(full), True, mail["id"])

# 🛒 הזמנה בחנות אונליין עם סכום → בוט הכספים (הצעה ✅/✖️, "קניות אונליין")
def is_order(address: str, subject: str) -> bool:
    return bool(re.search(rules.ORDER_SUBJECT, subject or "", re.I)) \
        and not re.search(rules.NOT_ORDER_SUBJECT, subject or "", re.I) \
        and not _matches(address, rules.KNOWN["orders"]) and not business_vendor(address, subject)

def order_number(text: str):
    m = re.search(rules.ORDER_NUMBER, text or "", re.I)
    return m[1] if m else None

def shop_name(from_header: str, address: str) -> str:
    """"Amazon.com <auto-confirm@amazon.com>" → "Amazon"; בלי שם — הדומיין."""
    name = re.sub(r"\s*<.*", "", from_header or "").strip().strip('"') or address.split("@")[-1]
    return re.sub(r"\.(com|co\.il|net)$", "", name, flags=re.I)

SEEN_ORDERS = set()

def order_seen(gmail, order: str, mail_id: str, internal: int) -> bool:
    """אישור הזמנה קודם עם אותו מספר (ריצה קודמת) — כבר הוצע. מיילי משלוח עם המספר לא נחשבים (לפי הנושא)."""
    for msg in fetch(gmail, f'"{order}" label:{DONE_LABEL}', 10):
        if msg["id"] == mail_id:
            continue
        other = gmail.users().messages().get(userId="me", id=msg["id"], format="metadata", metadataHeaders=["From", "Subject"]).execute()
        h = {x["name"]: x["value"] for x in other.get("payload", {}).get("headers", [])}
        if is_order(sender_of(h.get("From", "")), h.get("Subject", "")) and int(other.get("internalDate", 0)) < internal:
            return True
    return False

def handle_order(gmail, mail: dict) -> bool:
    """מחזיר אם הוצע. בלי סכום כולל במייל — לא הזמנה שאפשר לרשום."""
    full = gmail.users().messages().get(userId="me", id=mail["id"], format="full").execute()
    body = extract_body(gmail, mail["id"], full["payload"], mail["snippet"])
    found = total_amount(f"{mail['snippet']}\n{body}")
    if not found:
        return False
    order = order_number(body)
    if order and (order in SEEN_ORDERS or order_seen(gmail, order, mail["id"], int(full.get("internalDate", 0)))):
        print("💤 order already offered")  # בלי מספר/ספק בלוג — ה-repo ציבורי
        return False
    SEEN_ORDERS.add(order)
    ils = round(found[0] * rules.USD_TO_ILS, 2) if found[1] == "$" else found[0]
    to_finance(f"{shop_name(mail['from'], mail['sender'])} · הזמנה אונליין", ils, mail_date(full), False, mail["id"])
    return True

def send_important(gmail, mails: list) -> int:
    """📣 → יהלי (שם הכפתורים). קפדני: אישי + AI אומר שצריך לעשות משהו; 👍 שולח — תמיד; 👎 / 🚫 — לעולם לא.
    עד 3 ביום (לפי התווית); השאר — הודעה אחת מקובצת. בלוג — רק מספרים."""
    if not mails:
        return 0
    if not important.ingest_secret():
        fail("מיילים חשובים → יהלי", "חסר הסוד MAIL_INGEST_SECRET")
        return 0
    me = gmail.users().getProfile(userId="me").execute().get("emailAddress", "")
    today = datetime.now().date()
    picked = []
    for mail in mails:
        pref = important.pref_of(PREFS, mail["sender"], mail["from"])
        personal = important.is_personal(mail, me)
        if pref in ("not_important", "block") or (
                pref != "important" and not personal and not important.MOVE_SUBJECT.search(mail["subject"] or "")):
            continue
        full = gmail.users().messages().get(userId="me", id=mail["id"], format="full").execute()
        body = extract_body(gmail, mail["id"], full["payload"], mail["snippet"])
        verdict = important.judge(ask_ai, mail, body, today) if OPENAI_API_KEY else None
        if verdict is None and pref == "important":  # 👍 על השולח — שולחים גם כשה-AI לא בטוח
            verdict = {"summary": mail["subject"][:160], "todo": None, "deadline": None, "event": None}
        if verdict and not personal and pref != "important" and not verdict.get("move_only"):
            verdict = {**verdict, "move_only": True} if verdict.get("moved") else None  # לכל הקורס — רק המועד שזז
        if verdict:
            picked.append({**verdict, "id": mail["id"], "from_name": important.from_name(mail["from"], mail["sender"]),
                           "sender": mail["sender"], "subject": mail["subject"][:200], "link": gmail_link(mail["id"])})
    if not picked:
        print(f"📣 important: 0 of {len(mails)} candidates")
        return 0
    sent_label = label_id(gmail, important.SENT_LABEL_HE)
    sent_today = 0 if sent_label.startswith("<") else len(fetch(gmail, f"after:{today:%Y/%m/%d}", 50, [sent_label]))
    moves = [p for p in picked if p.get("move_only")]  # 🔁 — לא נספרים במכסה (יהלי שולחת רק אם יש אירוע ביומן)
    single, rest = important.split_daily([p for p in picked if not p.get("move_only")], sent_today)
    strip = lambda items: [{k: v for k, v in i.items() if k != "id"} for i in items]  # noqa: E731
    resp = act(f"important → yahli: {len(single)} + {len(rest)} combined", requests.post, important.YAHLI_URL, timeout=30,
               headers={"X-Ingest-Secret": important.ingest_secret()},
               json={"items": strip(single + moves), "combined": strip(rest)})
    if resp is not None and not resp.ok:
        fail("מיילים חשובים → יהלי", f"HTTP {resp.status_code}")
        return 0
    if resp is not None:  # really posted (not a dry run)
        SENT["yahli"] = len(single) + len(moves) + len(rest)
        station(BOT, "couriers", "done", f"{SENT['yahli']} מיילים חשובים נמסרו ליהלי", {"yahli": SENT["yahli"]}, handoff_to="yahli")
    for item in single + rest:
        act("label → sent to yahli", gmail.users().messages().modify(
            userId="me", id=item["id"], body={"addLabelIds": [sent_label]}).execute)
    print(f"📣 important: {len(single)} sent, {len(rest)} combined, {len(moves)} date moves, of {len(mails)} candidates")
    return len(single) + len(rest)

def handle_subscription(gmail, mail: dict, kind: str) -> bool:
    """AI מחלץ שירות/מחיר/תאריך (סכום שלא במייל נזרק) → בוט הכספים: מנוי חדש = הצעה לקבועה; ניסיון / מחיר = אזהרה."""
    if not (OPENAI_API_KEY and FINANCE_BOT_TOKEN):
        return False
    full = gmail.users().messages().get(userId="me", id=mail["id"], format="full").execute()
    body = extract_body(gmail, mail["id"], full["payload"], mail["snippet"])
    try:
        found = subs.extract(ask_ai, kind, mail["subject"], f"{mail['snippet']}\n{body}", rules.USD_TO_ILS)
    except Exception as ex:
        fail("מנוי", ex)
        return False
    if not found:
        print(f"💤 subscription ({kind}): nothing clear")
        return False
    finance_post(f"{kind} → finance bot", {**found, "link": gmail_link(mail["id"])})
    return True

FINANCE_URL = "https://bot-finance-mu.vercel.app/api/webhook?ingest"
VENDOR_PREFIX = {"wolt.com": "וולט", "10bis.co.il": "תן ביס"}  # "וולט · פאפי פסטה" — כדי שבוט הכספים יזהה קטגוריה

def vendor_label(sender: str, merchant: str) -> str:
    prefix = next((p for d, p in VENDOR_PREFIX.items() if _matches(sender, [d])), None)
    return f"{prefix} · {merchant}" if prefix and prefix not in merchant else merchant

def to_finance(vendor: str, ils: float, day, business: bool, mail_id: str) -> None:
    """חיוב → בוט הכספים. הסוד נגזר מהטוקן שלו (FINANCE_BOT_TOKEN). בלוג — בלי ספק/סכום (ה-repo ציבורי)."""
    if not FINANCE_BOT_TOKEN:
        return
    finance_post("charge → finance bot", {"vendor": vendor, "amount": ils, "date": day.isoformat(), "business": business,
                                          "link": gmail_link(mail_id)})

def finance_post(what: str, payload: dict) -> None:
    """POST ?ingest לבוט הכספים; הסוד נגזר מהטוקן שלו. בלוג — רק מה (בלי ספק/סכום)."""
    if not FINANCE_BOT_TOKEN:
        return
    secret = hashlib.sha256(b"ingest:" + FINANCE_BOT_TOKEN.encode()).hexdigest()[:32]
    resp = act(what, requests.post, FINANCE_URL, timeout=30, headers={"X-Ingest-Secret": secret}, json=payload)
    if resp is not None and not resp.ok:
        fail("finance bot", f"HTTP {resp.status_code}")
    elif resp is not None:  # really posted (not a dry run)
        SENT["finance"] += 1
        if SENT["finance"] == 1:  # one handoff per run; the full count goes out at the end of the run
            station(BOT, "couriers", "done", "חיוב נמסר לבוט הכספים", {"finance": 1}, handoff_to="finance")

def monday_gql(query: str, **variables) -> dict:
    resp = requests.post("https://api.monday.com/v2", json={"query": query, "variables": variables}, timeout=30,
                         headers={"Authorization": MONDAY_API_TOKEN, "API-Version": "2025-04"})
    if not resp.ok:
        raise RuntimeError(f"monday {resp.status_code}: {resp.text[:150]}")
    body = resp.json()
    if body.get("errors"):
        raise RuntimeError(f"monday: {str(body['errors'])[:150]}")
    return body["data"]

def monday_add(board_part: str, group_part: str, name: str, mail_id: str, values: dict) -> bool:
    """פריט חדש — לוח, קבוצה ועמודות לפי שם; מייל שכבר יובא (המזהה בהערות) לא נוצר פעמיים. מחזיר האם נוצר."""
    boards = monday_gql("{ boards(state: active, limit: 100) { id name type groups { id title } columns { id title } } }")["boards"]
    board = next(b for b in boards if b["type"] == "board" and board_part in b["name"])
    group = next(g["id"] for g in board["groups"] if group_part in g["title"])
    col = {c["title"]: c["id"] for c in board["columns"]}
    q = {"rules": [{"column_id": col["הערות"], "compare_value": [mail_id], "operator": "contains_text"}]}
    if monday_gql("query ($ids: [ID!], $q: ItemsQuery) { boards(ids: $ids) { items_page(limit: 1, query_params: $q)"
                  " { items { id } } } }", ids=[board["id"]], q=q)["boards"][0]["items_page"]["items"]:
        print(public(f"💤 monday already there: {name}"))
        return False
    act(f"monday → {board['name']} / {group_part}: {name}", monday_gql,
        "mutation ($board: ID!, $group: String!, $name: String!, $values: JSON!) {"
        " create_item(board_id: $board, group_id: $group, item_name: $name, column_values: $values) { id } }",
        board=board["id"], group=group, name=name, values=json.dumps({col[t]: v for t, v in values.items()}))
    return True

# =============================================================================
# ─── MAIN ────────────────────────────────────────────────────────────────────
# =============================================================================
def apply_aura_settings():
    """Maor's overrides from AURA, read once at run start: AURA > env AI_MODEL > the constants; none set -> no change."""
    global AI_MODEL, WAITING_AFTER_DAYS
    AI_MODEL = cfg_get(BOT, "AI_MODEL", [AI_MODEL])[0]
    important.DAILY_LIMIT = cfg_get(BOT, "DAILY_LIMIT", important.DAILY_LIMIT)
    WAITING_AFTER_DAYS = cfg_get(BOT, "WAITING_AFTER_DAYS", WAITING_AFTER_DAYS)

def cron_superseded():
    """AURA's central scheduler starts this bot (AURA_SCHEDULES on): GitHub's own cron run would be a second run of the
    same slot, so it skips. A dispatch always runs; with AURA unreachable there are no settings and the cron is the backup."""
    return os.environ.get("GITHUB_EVENT_NAME") == "schedule" and cfg_get(BOT, "AURA_SCHEDULES", False) is True

def main():
    if paused(BOT):
        return  # paused in AURA: no Gmail, no station report
    if cron_superseded():
        print("[AURA] AURA starts this bot now: the GitHub cron run skips")
        return
    apply_aura_settings()
    gmail, calendar = get_google_services()
    modes = [m for m, on in (("DRY RUN — no changes", DRY_RUN), ("ORGANIZE ALL", ORGANIZE_ALL), ("MERGE LABELS", MERGE),
                             ("TIDY INBOX", TIDY_INBOX)) if on]
    print(f"--- Mail manager {' | '.join(modes)} ---")
    stats = organize(gmail, calendar)
    print("🏁 " + " ".join(f"{k}={v}" for k, v in stats.items()))
    if sent := {d: SENT[d] for d in DESTINATIONS if SENT[d]}:
        station(BOT, "couriers", "done", f"{sum(sent.values())} משלוחים ל-{len(sent)} יעדים", sent)
    if FAILURES:
        act("failures → telegram", telegram, TELEGRAM_TOKEN, CHAT_ID,
            "⚠️ <b>מנהל המייל — מה לא עבד:</b>\n" + "\n".join(FAILURES))

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        if not DRY_RUN:
            try:
                telegram(TELEGRAM_TOKEN, CHAT_ID, f"⚠️ <b>מנהל המייל נכשל:</b> {html.escape(str(e)[:300])}")
            except Exception:
                pass
        sys.exit(1)  # שההרצה ב-GitHub תסומן ככישלון ולא תיעלם בשקט
