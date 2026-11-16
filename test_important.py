"""📣 מייל חשוב (16.11): קפדני — אישי בלבד, AI, עד 3 ביום, העדפות מ-prefs.json. בלי רשת, נתונים מומצאים (ה-repo היה ציבורי).
python test_important.py — ✅/❌. MAIL_DIR=<תיקייה> — על קוד אחר (אדום-ירוק)."""
import io
import json
import os
import sys
from contextlib import redirect_stdout
from datetime import date

sys.path.insert(0, os.environ.get("MAIL_DIR") or os.path.dirname(os.path.abspath(__file__)))
FAILED = []

def check(name, fn):
    try:
        fn()
        print(f"✅ {name}")
    except Exception as ex:  # noqa: BLE001
        FAILED.append(name)
        print(f"❌ {name} — {type(ex).__name__}: {ex}")

def I():
    import important
    return important

ME = "maor.test@example.com"

def mail(sender="dana.levi@gmail.com", frm=None, subject="שאלה על הפרויקט", to=ME, cc="", **headers):
    h = {"From": frm or f"Dana Levi <{sender}>", "To": to, "Cc": cc, **headers}
    return {"id": f"id-{sender}", "sender": sender, "from": h["From"], "subject": subject, "snippet": "x", "headers": h,
            "labels": ["INBOX"], "thread": "t"}

# ── מה נחשב אישי ─────────────────────────────────────────────────────────────
PERSONAL = [
    ("מאדם, רק אליי", mail(), True),
    ("List-Unsubscribe → רשימת תפוצה", mail(**{"List-Unsubscribe": "<mailto:u@x.com>"}), False),
    ("List-Id", mail(**{"List-Id": "<course.afeka>"}), False),
    ("Precedence: bulk", mail(Precedence="bulk"), False),
    ("noreply", mail(sender="noreply@afeka.ac.il"), False),
    ("do-not-reply", mail(sender="do-not-reply@service.gov.il"), False),
    ("נשלח לכולם (6 נמענים)", mail(to=", ".join([ME] + [f"s{n}@afeka.ac.il" for n in range(5)])), False),
    ("אני לא ב-To/Cc (Bcc / undisclosed)", mail(to="undisclosed-recipients:;"), False),
    ("אני ב-Cc עם עוד 2", mail(to="a@x.com, b@x.com", cc=ME), True),
]
for name, m, expect in PERSONAL:
    check(f"אישי? {name} → {expect}", lambda m=m, expect=expect: (_ for _ in ()).throw(AssertionError()) if I().is_personal(m, ME) != expect else None)

# ── העדפות: 👍/👎/🚫 לפי כתובת, דומיין, או מילה ("אפקה חשוב") ───────────────────────
def prefs_match():
    p = {"important": ["word:אפקה"], "not_important": ["word:מכבי", "news.example.com"], "block": ["spam@x.com"]}
    pref = I().pref_of
    assert pref(p, "lecturer@afeka.ac.il", "Dr. Cohen <lecturer@afeka.ac.il>") == "important"  # אפקה → afeka
    assert pref(p, "info@maccabi4u.co.il", "מכבי שירותי בריאות <info@maccabi4u.co.il>") == "not_important"
    assert pref(p, "a@news.example.com", "x") == "not_important" and pref(p, "spam@x.com", "x") == "block"
    assert pref(p, "dana.levi@gmail.com", "Dana") is None
check("העדפות: «אפקה» תופס afeka.ac.il, «מכבי» בשם השולח, דומיין, כתובת; 🚫 גובר", prefs_match)

def prefs_file_missing_or_bad():
    assert I().load_prefs("/nonexistent/prefs.json") == {"important": [], "not_important": [], "block": []}
check("prefs.json חסר / שבור → ריק (לא נופל)", prefs_file_missing_or_bad)

# ── ה-AI: רק true מפורש, תשובה לא תקינה = לא חשוב ──────────────────────────────────
def judge_strict():
    j = lambda answer: I().judge(lambda prompt: answer, mail(), "גוף", date(2026, 11, 16))  # noqa: E731
    assert j({"important": False, "summary": "x"}) is None
    assert j({"important": "true", "summary": "x"}) is None  # לא True מפורש
    assert j("garbage") is None and j({"important": True, "summary": ""}) is None
    got = j({"important": True, "summary": "המבחן בהסתברות זז", "todo": "לבדוק את המועד החדש", "deadline": "2026-11-20",
             "event": {"title": "מבחן הסתברות", "date": "2026-12-03", "time": "9:00"}})
    assert got == {"summary": "המבחן בהסתברות זז", "todo": "לבדוק את המועד החדש", "deadline": "2026-11-20",
                   "event": {"title": "מבחן הסתברות", "date": "2026-12-03", "time": "9:00"}}, got
    assert j({"important": True, "summary": "x", "deadline": "מחר", "event": {"title": "x", "date": "בקרוב"}})["event"] is None
check("AI: רק important=true מפורש; תאריכים לא תקינים נזרקים", judge_strict)

def prompt_is_strict():
    p = I().PROMPT
    assert "לכולם" in p and "אם לא בטוח — false" in p and "{body}" in p
check("ההנחיה ל-AI: הודעה לכולם / לא בטוח → false", prompt_is_strict)

def daily_cap():
    s = I().split_daily
    assert s([1, 2, 3, 4, 5], 0) == ([1, 2, 3], [4, 5])
    assert s([1, 2], 2) == ([1], [2]) and s([1, 2], 5) == ([], [1, 2])
check("עד 3 ביום; השאר — הודעה אחת מקובצת", daily_cap)

def secret_from_env():
    os.environ["MAIL_INGEST_SECRET"] = " s3cret \n"
    assert I().ingest_secret() == "s3cret"
check("הסוד מול יהלי — MAIL_INGEST_SECRET (אותו ערך בשני ה-repos)", secret_from_env)

# ── זרימה מלאה בבוט המיילים (Gmail מזויף) ───────────────────────────────────────
class Exec:
    def __init__(self, v): self.v = v
    def execute(self): return self.v

class FakeGmail:
    def __init__(self, sent_today=0):
        self.sent_today, self.modified = sent_today, []
    def users(self): return self
    def getProfile(self, userId): return Exec({"emailAddress": ME})
    def messages(self): return self
    def get(self, userId, id, format): return Exec({"payload": {}, "internalDate": "0"})
    def list(self, **k): return Exec({"messages": [{"id": f"s{n}"} for n in range(self.sent_today)]})
    def modify(self, userId, id, body): self.modified.append((id, body)); return Exec({})
    def labels(self): return self

def flow(mails, answers, sent_today=0, prefs=None):
    import sync_script as S
    saved = (S.ask_ai, S.requests.post, S.extract_body, S.label_id, S.PREFS, S.OPENAI_API_KEY, S.MONDAY_API_TOKEN, S.DRY_RUN)
    posts = []
    S.ask_ai = lambda prompt: answers.pop(0)
    S.requests.post = lambda url, **k: posts.append((url, k)) or type("R", (), {"ok": True, "status_code": 200})()
    S.extract_body = lambda *a, **k: "גוף המייל"
    S.label_id = lambda gmail, name, color=None: "LBL"
    S.PREFS = prefs or {"important": [], "not_important": [], "block": []}
    S.OPENAI_API_KEY, S.MONDAY_API_TOKEN, S.DRY_RUN = "k", "tok", False
    os.environ["MAIL_INGEST_SECRET"] = "s3cret"
    gmail, out = FakeGmail(sent_today), io.StringIO()
    try:
        with redirect_stdout(out):
            n = S.send_important(gmail, mails)
    finally:
        (S.ask_ai, S.requests.post, S.extract_body, S.label_id, S.PREFS, S.OPENAI_API_KEY, S.MONDAY_API_TOKEN, S.DRY_RUN) = saved
    return n, posts, gmail, out.getvalue()

YES = {"important": True, "summary": "מבקשת לשלוח את הדוח עד חמישי", "todo": "לשלוח דוח", "deadline": "2026-11-19", "event": None}
NO = {"important": False, "summary": "עדכון כללי"}

def flow_sends_only_important():
    mails = [mail("dana.levi@gmail.com"), mail("yoav.k@gmail.com"), mail("noreply@shop.example.com")]
    n, posts, gmail, log = flow(mails, [dict(YES), dict(NO)])
    assert n == 1 and len(posts) == 1
    url, k = posts[0]
    assert url.endswith("?ingest=mail") and k["headers"]["X-Ingest-Secret"] == "s3cret"
    items = k["json"]["items"]
    assert len(items) == 1 and items[0]["sender"] == "dana.levi@gmail.com" and items[0]["todo"] == "לשלוח דוח"
    assert "id" not in items[0] and items[0]["link"].startswith("https://mail.google.com/")
    assert gmail.modified == [("id-dana.levi@gmail.com", {"addLabelIds": ["LBL"]})]  # נספר להיום
    assert "dana" not in log and "דוח" not in log  # בלוג — רק מספרים
check("זרימה: noreply לא נשאל בכלל; AI אומר לא — לא נשלח; חשוב — נשלח ליהלי עם הסוד; בלוג רק מספרים", flow_sends_only_important)

def flow_cap():
    mails = [mail(f"p{n}.x@gmail.com") for n in range(3)]
    n, posts, _, _ = flow(mails, [dict(YES) for _ in range(3)], sent_today=2)
    k = posts[0][1]["json"]
    assert len(k["items"]) == 1 and len(k["combined"]) == 2 and n == 3
check("כבר נשלחו 2 היום → אחד לבד, השניים הנוספים בהודעה מקובצת", flow_cap)

def flow_prefs():
    mails = [mail("lecturer@afeka.ac.il", frm="Dr. Cohen <lecturer@afeka.ac.il>", **{"List-Id": "<course>"}),
             mail("info@maccabi4u.co.il", frm="מכבי <info@maccabi4u.co.il>")]
    prefs = {"important": ["word:אפקה"], "not_important": ["word:מכבי"], "block": []}
    n, posts, _, _ = flow(mails, [{"important": False}], prefs=prefs)  # ה-AI אומר "לא" על אפקה — 👍 גובר
    items = posts[0][1]["json"]["items"]
    assert n == 1 and [i["sender"] for i in items] == ["lecturer@afeka.ac.il"]
check("👍 «אפקה חשוב» → נשלח גם מרשימת תפוצה וגם כשה-AI לא בטוח; 👎 «מכבי» → לעולם לא", flow_prefs)

def flow_no_secret():
    import sync_script as S
    saved = S.FAILURES[:]
    os.environ["MAIL_INGEST_SECRET"] = ""
    try:
        assert S.send_important(FakeGmail(), [mail()]) == 0 and "MAIL_INGEST_SECRET" in S.FAILURES[-1]
    finally:
        S.FAILURES[:] = saved
check("אין MAIL_INGEST_SECRET → לא שולח, ושורה בדוח התקלות", flow_no_secret)

def flow_nothing():
    n, posts, _, _ = flow([mail("yoav.k@gmail.com")], [dict(NO)])
    assert n == 0 and posts == []
check("אין מייל חשוב → לא שולחים כלום ליהלי", flow_nothing)

def blocked_by_prefs():
    import sync_script as S
    saved = S.PREFS
    S.PREFS = {"important": [], "not_important": [], "block": ["spammer@example.com"]}
    try:
        assert S.is_blocked("spammer@example.com") and S.decide("spammer@example.com", "hello", "other") == "block"
    finally:
        S.PREFS = saved
check("🚫 מיהלי (prefs.json) → חסום כמו rules.BLOCK: לפח בריצה הבאה", blocked_by_prefs)

def prefs_file_in_repo():
    path = os.path.join(os.environ.get("MAIL_DIR") or os.path.dirname(os.path.abspath(__file__)), "prefs.json")
    assert set(json.load(open(path, encoding="utf-8"))) == {"important", "not_important", "block"}
check("prefs.json קיים ב-repo (יהלי מעדכנת אותו)", prefs_file_in_repo)

print("\nok" if not FAILED else f"\n{len(FAILED)} נכשלו:\n" + "\n".join(f"· {f}" for f in FAILED))
sys.exit(1 if FAILED else 0)
