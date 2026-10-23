# 📧 מנהל המייל

סורק את ה-Gmail כל ערב עם 5 סוכנים, ושולח עדכונים ל-4 בוטים נפרדים בטלגרם.

## הסוכנים
| סוכן | מה הוא עושה | לאן נשלח |
|---|---|---|
| 🧹 ניקוי | עובר על פרסומות/עדכונים ומעביר לפח מה שלא חשוב | — |
| 🛒 קופונים | שוברים מקרפור ותן ביס — קוד וסכום | בוט הקופונים |
| 🧾 חשבונות וקבלות | ספק, סכום, שולם/לא, כפתור תשלום | בוט הקבלות |
| 📦 משלוחים | סטטוס, מספר מעקב, כפתור מעקב | בוט המשלוחים |
| 🎓 לימודים | ביטול/שינוי/עיכוב שיעור מ-TeachingBox → מעדכן יומן | בוט הלימודים |

מייל שעובד מקבל תווית `Processed_By_Bot` (ומייל שנבדק בניקוי — `Maintenance_Processed`) כדי שלא ייסרק שוב.

## מתי
כל ערב (GitHub Actions, `.github/workflows/academic_calendar_sync.yml`). הרצה ידנית: Actions → "Academic Calendar Sync" → Run workflow.

## קבצים
| קובץ | תפקיד |
|---|---|
| `sync_script.py` | כל הלוגיקה |
| `requirements.txt` | ספריות פייתון |
| `.github/workflows/academic_calendar_sync.yml` | התזמון |
| `.github/workflows/keepalive.yml` | שומר שגיטהאב לא יכבה את התזמון |

## סודות (Settings → Secrets → Actions)
`GOOGLE_CREDENTIALS`, `OPENAI_API_KEY`,
`TELEGRAM_TOKEN` + `CHAT_ID` (לימודים),
`TELEGRAM_TOKEN_COUPONS` + `CHAT_ID_COUPONS`,
`TELEGRAM_TOKEN_RECEIPTS` + `CHAT_ID_RECEIPTS`,
`TELEGRAM_TOKEN_DELIVERIES` + `CHAT_ID_DELIVERIES`
