#!/usr/bin/env python3
"""
מנהל המייל — רץ 3 פעמים ביום (GitHub Actions).
כל מייל חדש בתיבה: חסימה (rules.BLOCK) → סיווג AI → הגנה (rules.PROTECT) → פעולה:
  🧾 חשבון/קבלה → בוט הקבלות (+PDF, קישור תשלום בטוח, חשבון פתוח → יומן)
  🎟️ קופון → תיקיית "קופונים"   📬 חשוב → התראה   🗑️ זבל/חסום → פח + ביטול הרשמה
TeachingBox → סוכן הלימודים (עדכון היומן).
DRY_RUN=1: רק מדפיס החלטות — לא נוגע במייל, ביומן או בטלגרם.
"""
import base64
import html
import io
import json
import os
import re
import sys
from datetime import datetime, timedelta
from email.utils import parseaddr
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

import rules

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

# =============================================================================
# ─── CONFIG & SECRETS ────────────────────────────────────────────────────────
# =============================================================================
IL_TZ = ZoneInfo("Asia/Jerusalem")
DRY_RUN = os.environ.get("DRY_RUN", "").strip() == "1"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()

DONE_LABEL = "Mail_Bot_Done"          # כל מייל שהבוט טיפל בו
OLD_LABELS = ["Processed_By_Bot"]     # טופלו ע"י הגרסה הקודמת — לא שולחים שוב
COUPON_LABEL = "קופונים"
OLD_CLEANER_LABEL = "Maintenance_Processed"  # המנקה הישן — ממנו משחזרים

# בוט הלימודים — גם התראות "מייל חשוב" ודוח תקלות
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()
TELEGRAM_TOKEN_RECEIPTS = os.environ.get("TELEGRAM_TOKEN_RECEIPTS", "").strip()
CHAT_ID_RECEIPTS = os.environ.get("CHAT_ID_RECEIPTS", "").strip()

LECTURER_MAP = {
    "רמי אלקיים": "מעבדת מכניקה", "גבריאל בן סימון": "מדר (הרצאה)", "בועז ויינר": "מדר (תרגול)",
    "בועז": "מדר (תרגול)", "יוני": "חדו\"א (הרצאה)", "אלינה ליס": "חדו\"א (תרגול)",
    "אלינה": "חדו\"א (תרגול)", "אפרת אבישי": "פיזיקה חשמל (הרצאה)", "אבישי": "פיזיקה חשמל (הרצאה)",
    "אילנה": "פיזיקה חשמל (תרגול)", "ד\"ר גבי שפט": "הנדסת חשמל א' (הרצאה + תרגול)",
    "גבי שפט": "הנדסת חשמל א' (הרצאה + תרגול)", "ערן לבינגר": "מערכות ספרתיות (הרצאה + תרגול)",
}

FAILURES = []

def fail(section: str, ex) -> None:
    print(f"❌ {section}: {ex}")
    detail = re.sub(r"https?://\S+", "<url>", str(ex))[:150]  # כתובת טלגרם מכילה את הטוקן
    FAILURES.append(f"• <b>{html.escape(section)}</b>: {html.escape(detail)}")

def act(description: str, fn, *args, **kwargs):
    """כל שינוי במייל/יומן/טלגרם עובר כאן, כדי ש-DRY_RUN באמת לא ישנה כלום."""
    print(("🧪 [dry] " if DRY_RUN else "▶️ ") + description)
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

def is_blocked(address: str) -> bool:
    return _matches(address, rules.BLOCK)

def is_protected(address: str, subject: str) -> bool:
    return _matches(address, rules.PROTECT) or bool(re.search(rules.PROTECT_SUBJECT, subject or "", re.I))

def is_ad(subject: str) -> bool:
    # לפי החוק פרסומת מסומנת "פרסומת" בתחילת הנושא או בסופו; באמצע (חשבונית "מכיל דבר פרסומת") — לא
    s = (subject or "").strip(" .|-–")
    return s.startswith("פרסומת") or s.endswith("פרסומת")

CATEGORIES = {"bill", "coupon", "important", "security", "keep", "junk"}

def decide(address: str, subject: str, ai_category: str) -> str:
    """אבטחה > חסימה > פרסומת > הגנה > AI; שולח חשוב תמיד מקבל התראה."""
    if re.search(rules.SECURITY_SUBJECT, subject or "", re.I) or address.split("@")[0] in ("security", "account", "accounts"):
        return "security"
    if is_blocked(address):
        return "block"
    category = ai_category if ai_category in CATEGORIES else "keep"
    if is_ad(subject):
        category = "junk"
    elif category == "junk" and is_protected(address, subject):
        category = "keep"
    if category in ("keep", "security") and _matches(address, rules.IMPORTANT):
        category = "important"
    if category == "important" and _matches(address, rules.NO_ALERT):
        category = "keep"
    return category

def should_rescue(address: str, subject: str) -> bool:
    return is_protected(address, subject) and decide(address, subject, "keep") not in ("block", "junk")

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

def local_iso(date_iso: str, hhmm: str) -> str:
    return datetime.strptime(f"{date_iso} {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=IL_TZ).isoformat()

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

def label_id(gmail, name: str) -> str:
    for label in gmail.users().labels().list(userId="me").execute().get("labels", []):
        if label["name"] == name:
            return label["id"]
    if DRY_RUN:
        return f"<{name}>"
    return gmail.users().labels().create(userId="me", body={"name": name}).execute()["id"]

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
                        print(f"❌ PDF extraction error for {name}: {e}")
            elif "parts" in part:
                body_text += extract_body(gmail, msg_id, part)
    elif payload.get("body", {}).get("data"):
        body_text += strip_html(text_of(payload["body"]["data"]))
    clean = body_text.strip()
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

def ask_ai(prompt: str, model: str = "gpt-4o-mini") -> dict:
    resp = requests.post("https://api.openai.com/v1/chat/completions", timeout=60,
                         headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                         json={"model": model, "temperature": 0, "response_format": {"type": "json_object"},
                               "messages": [{"role": "user", "content": prompt}]})
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])

# =============================================================================
# ─── מיון ────────────────────────────────────────────────────────────────────
# =============================================================================
TRIAGE_PROMPT = """אתה ממיין את המייל של מאור — סטודנט להנדסת חשמל באפקה, מאבטח במשמרות, מפתח אפליקציות ובוטים.
סווג את המייל לאחת:
- "bill": חשבון לתשלום, דרישת תשלום, חשבונית או קבלה על רכישה/תשלום.
- "coupon": שובר, קופון, גיפט קארד או קוד הטבה שאפשר לממש.
- "important": משהו שמאור צריך לראות או לטפל בו — אדם פרטי שכותב לו, לימודים, ממשלה, בריאות,
  בנק, משפטי, עבודה, פנייה שמחכה לתשובה.
- "security": התראת אבטחה, כניסה ממכשיר חדש, שינוי סיסמה, קוד אימות.
- "keep": שימושי אבל לא דחוף — אישורי הזמנה, טיסות, התראות מערכת (GitHub/Vercel), עדכוני שירות.
- "junk": פרסומת, מבצע, ניוזלטר, רשת חברתית, משהו שלא קשור אליו.
summary: משפט אחד בעברית — מה המייל אומר ומה (אם בכלל) צריך לעשות.

שולח: {sender}
נושא: {subject}
תקציר: {snippet}

החזר JSON בלבד: {{"category": "...", "summary": "..."}}"""

def fetch(gmail, query: str, limit: int) -> list:
    msgs, token = [], None
    while len(msgs) < limit:
        res = gmail.users().messages().list(userId="me", q=query, maxResults=min(100, limit), pageToken=token).execute()
        msgs += res.get("messages", [])
        token = res.get("nextPageToken")
        if not token:
            break
    return msgs[:limit]

def metadata(gmail, msg_id: str) -> dict:
    full = gmail.users().messages().get(
        userId="me", id=msg_id, format="metadata",
        metadataHeaders=["From", "Subject", "List-Unsubscribe", "List-Unsubscribe-Post"]).execute()
    headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
    return {"id": msg_id, "headers": headers, "from": headers.get("From", ""), "sender": sender_of(headers.get("From", "")),
            "subject": headers.get("Subject", "(ללא נושא)"), "snippet": html.unescape(full.get("snippet", ""))}

def junk(gmail, mail: dict, unsubscribed: set, stats: dict):
    url = one_click_url(mail["headers"])
    if url and mail["sender"] not in unsubscribed:
        unsubscribed.add(mail["sender"])
        try:
            act(f"unsubscribe {mail['sender']}", requests.post, url, data={"List-Unsubscribe": "One-Click"}, timeout=15)
            stats["unsubscribed"] += 1
        except Exception as ex:
            print(f"⚠️ unsubscribe failed for {mail['sender']}: {ex}")
    act(f"trash: {mail['sender']} | {mail['subject'][:60]}", gmail.users().messages().trash(userId="me", id=mail["id"]).execute)
    stats["trashed"] += 1

def triage(gmail, calendar):
    stats = {k: 0 for k in ("blocked", "trashed", "unsubscribed", "bill", "coupon", "important", "kept")}
    unsubscribed = set()
    done_id, coupon_id = label_id(gmail, DONE_LABEL), label_id(gmail, COUPON_LABEL)

    # 1) שולחים חסומים — כל מה שבתיבה, גם ישן
    blocked_query = "in:inbox from:(" + " OR ".join(rules.BLOCK) + ")"
    for msg in fetch(gmail, blocked_query, 500):
        mail = metadata(gmail, msg["id"])
        # החיפוש של Gmail רחב יותר מהכלל, והתראות אבטחה עוברות חסימה — לכן decide
        if decide(mail["sender"], mail["subject"], "junk") == "block":
            junk(gmail, mail, unsubscribed, stats)
            stats["blocked"] += 1

    # 2) מיילים חדשים — סיווג AI והחלטה
    skip = " ".join(f"-label:{name}" for name in [DONE_LABEL, *OLD_LABELS])
    for msg in fetch(gmail, f"in:inbox newer_than:3d {skip}", 100):
        mail = metadata(gmail, msg["id"])
        if decide(mail["sender"], mail["subject"], "junk") == "block":
            continue  # כבר טופל בשלב 1
        try:
            ai = ask_ai(TRIAGE_PROMPT.format(sender=mail["from"], subject=mail["subject"], snippet=mail["snippet"][:500]))
        except Exception as ex:
            fail(f"סיווג: {mail['subject'][:40]}", ex)
            continue
        action = decide(mail["sender"], mail["subject"], ai.get("category", ""))
        print(f"📨 {action:9} ← {ai.get('category')!s:9} | {mail['sender']} | {mail['subject'][:60]}")
        try:
            if action == "junk":
                junk(gmail, mail, unsubscribed, stats)
            elif action == "bill":
                handle_bill(gmail, calendar, mail)
            elif action == "coupon":
                act(f"→ {COUPON_LABEL}: {mail['subject'][:60]}", gmail.users().messages().modify(
                    userId="me", id=mail["id"], body={"addLabelIds": [coupon_id], "removeLabelIds": ["INBOX"]}).execute)
            elif action == "important":
                act(f"alert: {mail['subject'][:60]}", telegram, TELEGRAM_TOKEN, CHAT_ID,
                    f"📬 <b>מייל חשוב</b>\n👤 {html.escape(mail['from'])}\n📝 {html.escape(mail['subject'])}\n"
                    f"💡 {html.escape(ai.get('summary', ''))}",
                    [{"text": "📧 פתח את המייל", "url": gmail_link(mail["id"])}])
            stats[action if action in stats else "kept"] += 1
        except Exception as ex:
            fail(f"{action}: {mail['subject'][:40]}", ex)
            continue
        if action != "junk":
            act("label done", gmail.users().messages().modify(
                userId="me", id=mail["id"], body={"addLabelIds": [done_id]}).execute)
    return stats

# =============================================================================
# ─── חשבונות וקבלות ──────────────────────────────────────────────────────────
# =============================================================================
BILL_PROMPT = """אתה מנתח חשבונות וקבלות. קרא בעיון את הטקסט (כולל טקסט מחולץ מ-PDF).
החזר JSON בלבד (אם חסר — "לא צוין"):
{{
  "merchant": "שם החברה/ספק",
  "amount": "סכום (רק המספר)",
  "currency": "₪/$/€",
  "billing_period": "תקופת החשבון או תאריך",
  "due_date": "תאריך אחרון לתשלום DD/MM/YYYY, או 'לא צוין'",
  "payment_link": "קישור URL לתשלום כפי שהוא מופיע בטקסט, או 'לא נמצא'",
  "is_paid": true/false (true אם זו קבלה על תשלום שכבר בוצע)
}}
טקסט המייל:
{body}"""

def handle_bill(gmail, calendar, mail: dict):
    full = gmail.users().messages().get(userId="me", id=mail["id"], format="full").execute()
    body = extract_body(gmail, mail["id"], full["payload"], mail["snippet"])
    bill = ask_ai(BILL_PROMPT.format(body=body[:8000]))
    is_paid = bool(bill.get("is_paid"))
    merchant, amount, currency = bill.get("merchant", "לא צוין"), bill.get("amount", "?"), bill.get("currency", "₪")
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
    for name, data in pdf_attachments(gmail, mail["id"], full["payload"]):
        act(f"pdf → telegram: {name}", telegram_file, TELEGRAM_TOKEN_RECEIPTS, CHAT_ID_RECEIPTS, name, data)

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

# =============================================================================
# ─── שחזור — מה שהמנקה הישן העביר לפח בטעות ─────────────────────────────────
# =============================================================================
def rescue(gmail) -> int:
    restored, old_id = 0, label_id(gmail, OLD_CLEANER_LABEL)
    for msg in fetch(gmail, f"in:trash label:{OLD_CLEANER_LABEL}", 500):
        mail = metadata(gmail, msg["id"])
        if should_rescue(mail["sender"], mail["subject"]):
            act(f"restore: {mail['subject'][:60]}", gmail.users().messages().untrash(userId="me", id=mail["id"]).execute)
            # המעבר לפח מוריד את INBOX — מחזירים לתיבה, כלא נקרא, כדי שבאמת תראה אותו
            act("back to inbox", gmail.users().messages().modify(
                userId="me", id=mail["id"], body={"removeLabelIds": [old_id], "addLabelIds": ["INBOX", "UNREAD"]}).execute)
            restored += 1
    return restored

# =============================================================================
# ─── AGENT: ACADEMIC (TeachingBox → יומן) ────────────────────────────────────
# =============================================================================
def fetch_teachingbox_emails(gmail) -> list[dict]:
    query = f'(label:TeachingBox OR "TeachingBox") -label:{OLD_LABELS[0]} -label:{DONE_LABEL}'
    emails = []
    for msg in fetch(gmail, query, 20):
        full = gmail.users().messages().get(userId="me", id=msg["id"], format="full").execute()
        headers = {h["name"]: h["value"] for h in full["payload"]["headers"]}
        emails.append({"id": msg["id"], "subject": headers.get("Subject", ""),
                       "body": extract_body(gmail, msg["id"], full["payload"], full.get("snippet", ""))})
    return emails

def analyze_email_with_openai(email: dict) -> dict:
    lecturer_list = "\n".join(f"- {k} → {v}" for k, v in LECTURER_MAP.items())
    return ask_ai(f"""אתה עוזר אקדמי. קרא את *תוכן המייל בלבד* (התעלם מהתאריך והשעה שבהם נשלח).
עליך לחלץ מידע מדויק:
1. action: "cancellation", "update", "delay", או "ignore".
2. is_permanent: האם קבוע? true או false.
3. lecturer: שם המרצה מהרשימה.
4. course: שם הקורס מהרשימה.
5. event_date: תאריך השיעור (YYYY-MM-DD). אם אין, null.
6. start_time/end_time: שעות (HH:MM). אם אין, null.
7. room: מספר חדר. אם אין, "לא צוין".
8. change_details: הסבר קצר.
רשימת מרצים:
{lecturer_list}
גוף המייל:
{email['body']}
החזר JSON בלבד במבנה המתאים.""")

def find_calendar_event(calendar, course: str, event_dt: str) -> dict | None:
    if not event_dt:
        return None
    dt = datetime.fromisoformat(event_dt)
    events = calendar.events().list(calendarId="primary", timeMin=(dt - timedelta(hours=2)).isoformat(),
                                    timeMax=(dt + timedelta(hours=2)).isoformat(), q=course,
                                    singleEvents=True).execute().get("items", [])
    return events[0] if events else None

def update_event(calendar, event: dict, change_details: str, room: str, is_permanent: bool):
    event["description"] = event.get("description", "") + f"\n\n📝 עדכון בוט: {change_details}"
    if room and room != "לא צוין":
        event["location"] = room
    if is_permanent and "recurringEventId" in event:
        master = calendar.events().get(calendarId="primary", eventId=event["recurringEventId"]).execute()
        if room and room != "לא צוין":
            master["location"] = room
        master["description"] = event["description"]
        act("update recurring class", calendar.events().update(
            calendarId="primary", eventId=master["id"], body=master).execute)
    else:
        act("update class", calendar.events().update(calendarId="primary", eventId=event["id"], body=event).execute)

def add_event(calendar, course: str, event_dt: str, change_details: str, room: str):
    if not event_dt:
        return
    dt = datetime.fromisoformat(event_dt)
    event = {"summary": f"📚 {course}", "description": f"📝 {change_details}",
             "start": {"dateTime": dt.isoformat(), "timeZone": "Asia/Jerusalem"},
             "end": {"dateTime": (dt + timedelta(hours=2)).isoformat(), "timeZone": "Asia/Jerusalem"}}
    if room and room != "לא צוין":
        event["location"] = room
    act(f"add class {course}", calendar.events().insert(calendarId="primary", body=event).execute)

def process_academic(gmail, calendar) -> int:
    done_id, count = label_id(gmail, DONE_LABEL), 0
    for email in fetch_teachingbox_emails(gmail):
        try:
            a = analyze_email_with_openai(email)
            action = a.get("action", "ignore")
            course, lecturer, room = a.get("course", "קורס לא ידוע"), a.get("lecturer", ""), a.get("room", "לא צוין")
            event_date, start_time, details = a.get("event_date"), a.get("start_time"), a.get("change_details", "")
            # שעון ישראל אמיתי — לא +03:00 קבוע (בחורף זה היה מזיז שעה)
            event_dt = local_iso(event_date, start_time) if event_date and start_time else None
            when = datetime.fromisoformat(event_dt).strftime("%d/%m/%Y") if event_dt else (event_date or "לא צוין")
            if action == "cancellation":
                event = find_calendar_event(calendar, course, event_dt)
                if event:
                    act(f"delete class {course}", calendar.events().delete(calendarId="primary", eventId=event["id"]).execute)
                act("academic → telegram", telegram, TELEGRAM_TOKEN, CHAT_ID,
                    f"⚠️ <b>בוטל שיעור:</b> {course}\n👨‍🏫 <b>מרצה:</b> {lecturer}\n📅 <b>תאריך:</b> {when}\n🗑️ הוסר מהיומן.")
            elif action == "update":
                event = find_calendar_event(calendar, course, event_dt)
                if event:
                    update_event(calendar, event, details, room, a.get("is_permanent", False))
                else:
                    add_event(calendar, course, event_dt, details, room)
                perm = "🔄 <b>שינוי קבוע במערכת!</b>" if a.get("is_permanent") else "📅 <b>שינוי חד פעמי</b>"
                act("academic → telegram", telegram, TELEGRAM_TOKEN, CHAT_ID,
                    f"✅ <b>עדכון במערכת:</b> {course}\n{perm}\n👨‍🏫 <b>מרצה:</b> {lecturer}\n📅 <b>תאריך:</b> {when}\n"
                    f"⏰ <b>שעות:</b> {start_time or '?'} - {a.get('end_time') or '?'}\n🚪 <b>חדר:</b> {room}\n📝 <b>פרטים:</b> {details}")
            elif action == "delay":
                act("academic → telegram", telegram, TELEGRAM_TOKEN, CHAT_ID,
                    f"⏳ <b>הודעת עיכוב:</b> {course}\n👨‍🏫 <b>המרצה:</b> {lecturer} מתעכב.\n📅 <b>תאריך:</b> {when}\n"
                    f"🚪 <b>חדר:</b> {room}\n📝 <b>פרטים:</b> {details}")
            act("label done", gmail.users().messages().modify(
                userId="me", id=email["id"], body={"addLabelIds": [done_id]}).execute)
            count += 1
        except Exception as ex:
            fail(f"לימודים: {email['subject'][:40]}", ex)
    return count

# =============================================================================
# ─── MAIN ────────────────────────────────────────────────────────────────────
# =============================================================================
def main():
    gmail, calendar = get_google_services()
    print(f"--- Mail manager {'(DRY RUN — no changes)' if DRY_RUN else ''} ---")
    restored = rescue(gmail)
    stats = triage(gmail, calendar)
    academic = process_academic(gmail, calendar)
    print(f"🏁 restored={restored} academic={academic} " + " ".join(f"{k}={v}" for k, v in stats.items()))
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
