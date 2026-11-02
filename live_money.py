"""בדיקה חיה (רק בענף test/money-monday, יימחק לפני main): 2 חשבונות Splitwise + 2 קבלות עסק אמיתיים → monday.
לא נוגע בתוויות Gmail ולא ביומן."""
import sync_script as m

gmail, calendar = m.get_google_services()
for msg_id in ["1a18beb19089a3d8", "1a18beb5ac0e214a", "1a18beb19089a3d8"]:  # השלישי — שלא נוצר פעמיים
    mail = m.metadata(gmail, msg_id)
    print("splitwise:", mail["subject"], "→ paid?", m.handle_bill(gmail, calendar, mail))
for msg_id in ["1a199081911e6cc2", "1a16f4ede356f5aa"]:
    mail = m.metadata(gmail, msg_id)
    vendor = m.business_vendor(mail["sender"], mail["subject"])
    print("expense:", mail["sender"], "|", mail["subject"], "→", vendor)
    assert vendor
    m.handle_expense(gmail, mail, vendor)

for board, ids in (("אישיות", ["1a18beb19089a3d8", "1a18beb5ac0e214a"]), ("עסקים", ["1a199081911e6cc2", "1a16f4ede356f5aa"])):
    b = next(x for x in m.monday_gql("{ boards(state: active, limit: 100) { id name type columns { id title } } }")["boards"]
             if board in x["name"])
    col = {c["title"]: c["id"] for c in b["columns"]}
    for i in ids:
        q = {"rules": [{"column_id": col["הערות"], "compare_value": [i], "operator": "contains_text"}]}
        items = m.monday_gql("query ($ids: [ID!], $q: ItemsQuery) { boards(ids: $ids) { items_page(limit: 5, query_params: $q)"
                             " { items { name group { title } column_values { column { title } text } } } } }",
                             ids=[b["id"]], q=q)["boards"][0]["items_page"]["items"]
        assert len(items) == 1, (i, items)
        cols = {cv["column"]["title"]: cv["text"] for cv in items[0]["column_values"]}
        print("monday:", items[0]["name"], "|", items[0]["group"]["title"], "|",
              {k: cols.get(k) for k in ("סטטוס", "דדליין", "סוג", "סכום (₪)")}, "|", (cols.get("הערות") or "").replace("\n", " ⏎ "))
print("failures:", m.FAILURES)
assert not m.FAILURES
print("ok")
