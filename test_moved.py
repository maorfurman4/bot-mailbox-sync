"""🔁 C2 (16.11): מייל שמזיז מועד → יהלי (גם מייל לכל הקורס — רק המועד, לא כרטיס "חשוב"). בלי רשת, נתונים מומצאים.
python test_moved.py — ✅/❌. MAIL_DIR=<תיקייה> — על קוד אחר."""
import io
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

ME = "maor.test@example.com"
def mail(sender, subject, to=ME, **h):
    hh = {"From": f"X <{sender}>", "To": to, "Cc": "", **h}
    return {"id": f"id-{sender}", "sender": sender, "from": hh["From"], "subject": subject, "snippet": "x", "headers": hh,
            "labels": [], "thread": "t"}
MOVED = {"what": "מבחן הסתברות", "old_date": "2026-12-01", "new_date": "2026-12-03", "new_time": "09:00"}

SUBJECTS = [("שינוי מועד מבחן בהסתברות", True), ("המבחן נדחה ליום חמישי", True), ("מועד חדש לתרגול", True),
            ("Your appointment has been rescheduled", True), ("Exam postponed", True),
            ("סיכום שיעור 5", False), ("הזמנה שלך נשלחה", False), ("קבלה על תשלום", False)]
for subj, expect in SUBJECTS:
    def run(subj=subj, expect=expect):
        import important
        assert bool(important.MOVE_SUBJECT.search(subj)) == expect
    check(f"נושא «{subj}» → מועד זז? {expect}", run)

def judge_move_only():
    import important
    j = lambda ans: important.judge(lambda p: ans, mail("a@afeka.ac.il", "x"), "b", date(2026, 11, 16))  # noqa: E731
    got = j({"important": False, "summary": "המבחן זז", "moved": MOVED})
    assert got["move_only"] is True and got["moved"] == MOVED
    assert j({"important": False, "moved": {"what": "", "new_date": "2026-12-03"}}) is None  # בלי שם — לא
    assert j({"important": False, "moved": {"what": "מבחן", "new_date": "בקרוב"}}) is None  # בלי תאריך — לא
    both = j({"important": True, "summary": "x", "moved": MOVED})
    assert both["moved"] == MOVED and not both.get("move_only")
check("AI: «moved» נקרא; לא חשוב אבל זז → move_only; בלי שם/תאריך תקין — נזרק", judge_move_only)

def prompt_has_moved():
    import important
    assert '"moved"' in important.PROMPT and "old_date" in important.PROMPT
check("ההנחיה ל-AI מבקשת גם moved", prompt_has_moved)

class Exec:
    def __init__(self, v): self.v = v
    def execute(self): return self.v
class FakeGmail:
    def __init__(self): self.modified = []
    def users(self): return self
    def getProfile(self, userId): return Exec({"emailAddress": ME})
    def messages(self): return self
    def get(self, userId, id, format): return Exec({"payload": {}, "internalDate": "0"})
    def list(self, **k): return Exec({"messages": []})
    def modify(self, userId, id, body): self.modified.append(id); return Exec({})

def flow(mails, answers):
    import sync_script as S
    saved = (S.ask_ai, S.requests.post, S.extract_body, S.label_id, S.PREFS, S.OPENAI_API_KEY, S.DRY_RUN)
    posts = []
    S.ask_ai = lambda prompt: answers.pop(0)
    S.requests.post = lambda url, **k: posts.append(k["json"]) or type("R", (), {"ok": True, "status_code": 200})()
    S.extract_body, S.label_id = (lambda *a, **k: "גוף"), (lambda gmail, name, color=None: "LBL")
    S.PREFS = {"important": [], "not_important": [], "block": []}
    S.OPENAI_API_KEY, S.DRY_RUN = "k", False
    os.environ["MAIL_INGEST_SECRET"] = "s"
    g = FakeGmail()
    try:
        with redirect_stdout(io.StringIO()):
            S.send_important(g, mails)
    finally:
        (S.ask_ai, S.requests.post, S.extract_body, S.label_id, S.PREFS, S.OPENAI_API_KEY, S.DRY_RUN) = saved
    return posts, g

def course_wide_move():
    everyone = ", ".join([ME] + [f"s{n}@afeka.ac.il" for n in range(30)])
    posts, g = flow([mail("lecturer@afeka.ac.il", "שינוי מועד מבחן בהסתברות", to=everyone, **{"List-Id": "<c>"})],
                    [{"important": True, "summary": "המבחן זז ל-3.12", "moved": MOVED}])
    items = posts[0]["items"]
    assert len(items) == 1 and items[0]["move_only"] is True and items[0]["moved"] == MOVED and posts[0]["combined"] == []
    assert g.modified == []  # לא נספר במכסת ה-3
check("מייל לכל הקורס «שינוי מועד מבחן» → נשלח רק כמועד שזז (move_only), לא נספר במכסה", course_wide_move)

def course_wide_no_move():
    everyone = ", ".join([ME] + [f"s{n}@afeka.ac.il" for n in range(30)])
    posts, _ = flow([mail("lecturer@afeka.ac.il", "שינוי מועד מבחן", to=everyone)], [{"important": True, "summary": "x"}])
    assert posts == []  # ה-AI לא מצא מועד — מייל לכולם לא נשלח
    posts, _ = flow([mail("lecturer@afeka.ac.il", "סיכום שיעור 5", to=everyone)], [])
    assert posts == []  # בלי מילת "זז" בנושא — לא נשאל בכלל
check("מייל לכולם בלי מועד שזז → לא נשלח (ובלי מילת שינוי בנושא — בלי AI)", course_wide_no_move)

def personal_with_move():
    posts, _ = flow([mail("dana.levi@gmail.com", "שינוי שעה לפגישה")],
                    [{"important": True, "summary": "הפגישה זזה ל-14:00", "todo": "לאשר", "moved": {**MOVED, "what": "פגישה עם דנה"}}])
    item = posts[0]["items"][0]
    assert not item.get("move_only") and item["moved"]["what"] == "פגישה עם דנה" and item["todo"] == "לאשר"
check("מייל אישי שמזיז מועד → כרטיס רגיל + המועד", personal_with_move)

print("\nok" if not FAILED else f"\n{len(FAILED)} נכשלו")
sys.exit(1 if FAILED else 0)
