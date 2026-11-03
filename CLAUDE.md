# Mailbox bot

Organizes Gmail with the bot's 9 colored labels, 3 runs/day via GitHub Actions. Rules first (`rules.py`), then batched gpt-4o-mini. Telegram only for bills/receipts and failures — Maor wants no mail alerts. Dispatch inputs: `dry_run`, `organize_all`.

## Working with Maor
- Reply in Hebrew; code, commands and commit messages stay in English. Say exactly what you'll do next and what you need from him.
- He often works from iPhone/iPad in cloud sessions, with the Mac off. End every task with a pushed branch and a PR he can merge from the phone. Never push to main yourself.
- Secrets (.env) are not in the repo. If a task needs one, say which and stop.
- Release flow: push to a `test/...` branch, run the workflow with `--ref` so a real Telegram message arrives, and merge to main only after Maor OKs what he sees in Telegram (layout, RTL, accuracy). Read logs before guessing at a fix.
- Keep AI calls cheap; he watches token cost.
