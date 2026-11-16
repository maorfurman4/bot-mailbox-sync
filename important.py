"""📣 מייל חשוב → יהלי (16.11). קפדני מאוד — עדיף לפספס מאשר להציף:
רק מייל אישי למאור (לא רשימת תפוצה / noreply / הרבה נמענים / "לכולם") → AI: מבקש ממנו לעשות משהו או משנה לו משהו?
עד 3 ביום; מה שמעבר — הודעה אחת מקובצת. ההעדפות (👍/👎/🚫 ו"אפקה חשוב") — prefs.json ב-repo, יהלי כותבת אליו."""

import json
import os
import re
from datetime import date
from email.utils import getaddresses

PREFS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prefs.json")
DAILY_LIMIT = 3
YAHLI_URL = "https://yossi-bot.vercel.app/api/webhook?ingest=mail"
SENT_LABEL_HE = "📣 נשלח ליהלי"  # כמה כבר נשלחו היום (לפי התווית; בלי מצב נוסף)

# "אפקה חשוב" — מילה בעברית → חלק מהדומיין
ALIASES = {"אפקה": "afeka", "מכבי": "maccabi", "כללית": "clalit", "מאוחדת": "meuhedet", "לאומית": "leumit",
           "ביטוח לאומי": "btl.gov", "מס הכנסה": "taxes.gov", "רשות המסים": "taxes.gov", "עירייה": "tel-aviv.gov",
           "בנק הפועלים": "bankhapoalim", "לאומי": "leumi", "דיסקונט": "discount", "מקס": "max.co.il", "ישראכרט": "isracard"}

def load_prefs(path: str = PREFS_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        got = {}
    return {k: [str(x).lower() for x in got.get(k, [])] for k in ("important", "not_important", "block")}

def matches(entry: str, address: str, from_header: str) -> bool:
    """כתובת מדויקת / דומיין / "word:אפקה" (בשם השולח, או בדומיין דרך ALIASES)."""
    domain = address.rsplit("@", 1)[-1]
    if entry.startswith("word:"):
        word = entry[5:]
        return word in (from_header or "").lower() or (word in ALIASES and ALIASES[word] in domain)
    return address == entry or domain == entry or domain.endswith("." + entry)

def pref_of(prefs: dict, address: str, from_header: str) -> str | None:
    """"block" > "not_important" > "important" > None."""
    for kind in ("block", "not_important", "important"):
        if any(matches(e, address, from_header) for e in prefs.get(kind, [])):
            return kind
    return None

BULK_LOCAL = re.compile(r"no-?reply|do-?not-?reply|donotreply|notif|news|mailer|bounce|marketing|^info$|^support$|"
                        r"system|alert|updates?$|digest|hello$|team$|community", re.I)

def recipients(headers: dict) -> list:
    return [a.lower() for _, a in getaddresses([headers.get("To", ""), headers.get("Cc", "")]) if a]

def is_personal(mail: dict, me: str) -> bool:
    """אישי למאור: בלי List-Unsubscribe/List-Id/Precedence, לא noreply, מאור ב-To/Cc, עד 4 נמענים."""
    h = mail.get("headers", {})
    if h.get("List-Unsubscribe") or h.get("List-Id") or re.search(r"bulk|list|junk", h.get("Precedence", ""), re.I):
        return False
    if BULK_LOCAL.search(mail["sender"].split("@")[0]):
        return False
    to = recipients(h)
    return bool(me) and me.lower() in to and len(to) <= 4

PROMPT = """מייל אישי למאור (סטודנט להנדסת חשמל באפקה, מאבטח, מפתח). היום {today}.
שולח: {sender}
נושא: {subject}
תוכן: {body}

האם המייל מבקש ממנו לעשות משהו, או משנה לו משהו (מבחן/שיעור שזז, טופס למלא, תור, מסמך לשלוח, חיוב חריג, תשובה שמחכים לה)?
הודעה כללית לכולם, ניוזלטר, אישור אוטומטי, "לידיעה" בלי שום פעולה — false. אם לא בטוח — false.
בנוסף: אם המייל מזיז מועד של משהו קיים (מבחן / שיעור / תור / פגישה שזזו) — moved; אחרת moved = null.
JSON בלבד: {{"important": true/false, "summary": "<עד 15 מילים>", "todo": "<פועל + מה, עד 8 מילים, או null>",
"deadline": "YYYY-MM-DD או null", "event": {{"title": "...", "date": "YYYY-MM-DD", "time": "HH:MM או null"}} או null,
"moved": {{"what": "<שם קצר כמו שכנראה ביומן, למשל 'מבחן הסתברות'>", "old_date": "YYYY-MM-DD או null",
"new_date": "YYYY-MM-DD", "new_time": "HH:MM או null"}} או null}}"""

# 🔁 C2: מייל שמזיז מועד — גם מייל לכל הקורס (הודעה על מבחן שזז), אבל רק אם יש אירוע כזה ביומן (יהלי בודקת)
MOVE_SUBJECT = re.compile(r"נדח|הוזז|יוזז|זז\b|שינוי\s+(?:מועד|תאריך|שעה|שעת)|מועד\s+חדש|תאריך\s+חדש|הקדמת|דחיית|"
                          r"reschedul|postpone|moved|new date|time change", re.I)

DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
TIME_RE = re.compile(r"\d{1,2}:\d{2}")

def moved_of(got: dict) -> dict | None:
    m = got.get("moved") if isinstance(got, dict) else None
    if not isinstance(m, dict) or not str(m.get("what") or "").strip() or not DAY_RE.fullmatch(str(m.get("new_date") or "")):
        return None
    return {"what": str(m["what"]).strip()[:60],
            "old_date": m["old_date"] if DAY_RE.fullmatch(str(m.get("old_date") or "")) else None,
            "new_date": m["new_date"], "new_time": m["new_time"] if TIME_RE.fullmatch(str(m.get("new_time") or "")) else None}

def judge(ask_ai, mail: dict, body: str, today: date) -> dict | None:
    """תשובת ה-AI, מנוקה; None = לא חשוב ולא מזיז מועד / תשובה לא תקינה.
    לא חשוב אבל מזיז מועד → {"move_only": True, ...} (יהלי מציעה רק אם יש אירוע כזה ביומן)."""
    got = ask_ai(PROMPT.format(today=today.isoformat(), sender=mail["from"][:120], subject=mail["subject"][:200],
                               body=" ".join(body.split())[:1500]))
    moved = moved_of(got)
    if not isinstance(got, dict) or got.get("important") is not True or not str(got.get("summary") or "").strip():
        if moved:
            return {"summary": str(got.get("summary") or mail["subject"]).strip()[:160], "todo": None, "deadline": None,
                    "event": None, "moved": moved, "move_only": True}
        return None
    out = {"summary": str(got["summary"]).strip()[:160], "todo": (str(got.get("todo") or "").strip() or None),
           "deadline": None, "event": None}
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(got.get("deadline") or "")):
        out["deadline"] = got["deadline"]
    ev = got.get("event")
    if isinstance(ev, dict) and ev.get("title") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(ev.get("date") or "")):
        out["event"] = {"title": str(ev["title"])[:80], "date": ev["date"],
                        "time": ev.get("time") if re.fullmatch(r"\d{1,2}:\d{2}", str(ev.get("time") or "")) else None}
    if moved:
        out["moved"] = moved
    return out

def from_name(from_header: str, address: str) -> str:
    name = re.sub(r"\s*<.*", "", from_header or "").strip().strip('"')
    return name or address

def split_daily(items: list, sent_today: int) -> tuple:
    """(בודדות, מקובצות): עד 3 ביום לבד; השאר בהודעה אחת."""
    room = max(0, DAILY_LIMIT - sent_today)
    return items[:room], items[room:]

def ingest_secret() -> str:
    # סוד משותף ליהלי ולבוט המיילים (16.11: טוקני ה-monday שונים בין הבוטים — אי אפשר לגזור). מאור מוסיף בשני ה-repos.
    return os.environ.get("MAIL_INGEST_SECRET", "").strip()
