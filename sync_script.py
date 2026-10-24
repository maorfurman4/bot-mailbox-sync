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

import rules

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

# =============================================================================
# ─── CONFIG & SECRETS ────────────────────────────────────────────────────────
# =============================================================================
DRY_RUN = os.environ.get("DRY_RUN", "").strip() == "1"
ORGANIZE_ALL = os.environ.get("ORGANIZE_ALL", "").strip() == "1"
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
                        print(f"❌ PDF extraction error for {name}: {e}")
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

def ask_ai(prompt: str) -> dict:
    resp = requests.post("https://api.openai.com/v1/chat/completions", timeout=90,
                         headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                         json={"model": "gpt-4o-mini", "temperature": 0, "response_format": {"type": "json_object"},
                               "messages": [{"role": "user", "content": prompt}]})
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])

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
        metadataHeaders=["From", "Subject", "List-Unsubscribe", "List-Unsubscribe-Post"]).execute()
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
            print(f"⚠️ unsubscribe failed for {mail['sender']}: {ex}")
    act(f"trash: {mail['sender']} | {mail['subject'][:60]}", gmail.users().messages().trash(userId="me", id=mail["id"]).execute)
    stats["junk"] += 1

def classify(mails: list) -> dict:
    """שולח מוכר / מיון של Gmail בלי AI; את השאר — קריאת AI אחת לכל 25 מיילים."""
    result = {m["id"]: known_category(m["sender"], m["subject"], m["labels"]) for m in mails}
    unknown = [m for m in mails if result[m["id"]] is None]
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
    print(f"🧮 {len(mails)} emails: {len(mails) - len(unknown)} by rules, {len(unknown)} by AI "
          f"in {-(-len(unknown) // 25)} call(s)")
    return result

def apply_labels(gmail, calendar, mails, stats, unsubscribed, *, move: bool, notify: bool, merging: bool = False):
    """מיון → תווית. move: להזיז לתיבה/ממנה; notify: חשבון לטלגרם ויומן; merging: מיזוג התוויות הישנות."""
    done_id = label_id(gmail, DONE_LABEL)
    categories = classify(mails)
    for mail in mails:
        action = decide(mail["sender"], mail["subject"], categories[mail["id"]])
        if merging:
            action = merge_action(action, mail["subject"])
        print(f"📨 {action:9} ← {categories[mail['id']]!s:9} | {mail['sender']} | {mail['subject'][:60]}")
        try:
            if action in ("junk", "block"):
                junk(gmail, mail, unsubscribed, stats)
                continue
            paid = True
            if action == "bill" and notify:
                paid = handle_bill(gmail, calendar, mail)
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

    # 1) שולחים חסומים — כל מה שבתיבה, גם ישן
    for msg in fetch(gmail, "in:inbox from:(" + " OR ".join(rules.BLOCK) + ")", 500):
        mail = metadata(gmail, msg["id"])
        # החיפוש של Gmail רחב יותר מהכלל, והתראות אבטחה עוברות חסימה — לכן decide
        if decide(mail["sender"], mail["subject"], "junk") == "block":
            junk(gmail, mail, unsubscribed, stats)

    # 2) מיילים חדשים בכל ה-Gmail — גם מה שפילטרים ישנים העבירו ישר לתוויות ועקף את התיבה.
    #    ORGANIZE_ALL: כל התיבה + 60 יום אחורה, בלי להזיז מיקום ובלי טלגרם/יומן
    base = f"-in:trash -in:spam -in:sent -label:{DONE_LABEL}"
    query = f"(in:inbox OR newer_than:60d) {base}" if ORGANIZE_ALL else f"newer_than:3d {base}"
    mails = [m for m in (metadata(gmail, msg["id"]) for msg in fetch(gmail, query, 1000 if ORGANIZE_ALL else 100))
             if "DRAFT" not in m["labels"]]
    apply_labels(gmail, calendar, mails, stats, unsubscribed, move=not ORGANIZE_ALL, notify=not ORGANIZE_ALL)

    # TIDY_INBOX (חד-פעמי): כל מה שבתיבה — גם מה שכבר סומן — מקבל תווית ועובר למקום שלו. בלי טלגרם/יומן
    if TIDY_INBOX:
        inbox = [m for m in (metadata(gmail, msg["id"]) for msg in fetch(gmail, "in:inbox", 1000))
                 if "DRAFT" not in m["labels"]]
        print(f"🧹 tidy inbox: {len(inbox)} emails")
        apply_labels(gmail, calendar, inbox, stats, unsubscribed, move=True, notify=False)

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
    return stats

# =============================================================================
# ─── חשבונות וקבלות → בוט הקבלות ─────────────────────────────────────────────
# =============================================================================
BILL_PROMPT = """חלץ מהחשבון/קבלה (כולל טקסט מ-PDF). JSON בלבד, ואם חסר — "לא צוין":
{{"merchant": "שם הספק", "amount": "רק המספר", "currency": "₪/$/€", "billing_period": "תקופה או תאריך",
"due_date": "DD/MM/YYYY או לא צוין", "payment_link": "קישור תשלום כפי שמופיע בטקסט, או לא נמצא",
"is_paid": true/false}}
טקסט:
{body}"""

def handle_bill(gmail, calendar, mail: dict) -> bool:
    """שולח לבוט הקבלות; מחזיר האם שולם (קבלה ששולמה יוצאת מהתיבה)."""
    full = gmail.users().messages().get(userId="me", id=mail["id"], format="full").execute()
    body = extract_body(gmail, mail["id"], full["payload"], mail["snippet"])
    bill = ask_ai(BILL_PROMPT.format(body=body[:3000]))  # הנתונים בחשבונית נמצאים בהתחלה
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
    return is_paid

# =============================================================================
# ─── MAIN ────────────────────────────────────────────────────────────────────
# =============================================================================
def main():
    gmail, calendar = get_google_services()
    modes = [m for m, on in (("DRY RUN — no changes", DRY_RUN), ("ORGANIZE ALL", ORGANIZE_ALL), ("MERGE LABELS", MERGE),
                             ("TIDY INBOX", TIDY_INBOX)) if on]
    print(f"--- Mail manager {' | '.join(modes)} ---")
    stats = organize(gmail, calendar)
    print("🏁 " + " ".join(f"{k}={v}" for k, v in stats.items()))
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
