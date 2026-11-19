# Mailbox bot

Organizes Gmail with the bot's 9 colored labels, 3 runs/day via GitHub Actions. Rules first (`rules.py`), then batched gpt-6.1-terra. Telegram only for bills/receipts and failures — Maor wants no mail alerts. Dispatch inputs: `dry_run`, `organize_all`.

## Working with Maor
- Reply in Hebrew; code, commands and commit messages stay in English. Say exactly what you'll do next and what you need from him.
- He often works from iPhone/iPad in cloud sessions, with the Mac off. End every task with a pushed branch and a PR he can merge from the phone. Never push to main yourself.
- Secrets (.env) are not in the repo. If a task needs one, say which and stop.
- Release flow: push to a `test/...` branch, run the workflow with `--ref` so a real Telegram message arrives, and merge to main only after Maor OKs what he sees in Telegram (layout, RTL, accuracy). Read logs before guessing at a fix.
- Keep AI calls cheap; he watches token cost.

## Skills — pick by this map, don't guess
Many skills are enabled on this account, so choose from this table. When a task matches a row, load that skill before you start, and say which one you're using.

**Every task**
| When | Skill |
|---|---|
| New feature, behavior change, or anything to plan | `brainstorming`, then `writing-plans` |
| Carrying out a written plan | `executing-plans`; `subagent-driven-development` if its tasks are independent |
| 2+ unrelated tasks at once | `dispatching-parallel-agents` |
| Bug, failing test, unexpected behavior | `systematic-debugging` — before proposing any fix |
| Writing feature or bugfix code | `test-driven-development` |
| Before saying "done" or opening a PR | `verification-before-completion`, then `requesting-code-review` |
| Got review comments | `receiving-code-review` |
| Wrapping up the branch | `finishing-a-development-branch` |
| Hebrew text a person will read | `hebrew-content-writer`, then `avoid-ai-writing` |
| Writing a prompt for another agent or tool | `prompt-architect` |

**This project**
| When | Skill |
|---|---|
| Telegram API, keyboards, webhooks, Hebrew/RTL messages | `telegram-bot-builder` |
| GitHub Actions workflows, schedules, secrets | `github-actions-il` |
