# cricket-scores

Notable cricket scores → Telegram, ~6:17 AM IST via GitHub Actions.

Filters the ESPN Cricinfo live-scores board down to matches worth
attention: India (incl. A / women / U19), internationals between major
sides, IPL/WPL. SILENT when nothing notable is on — a message always
means there's a match worth checking.

One agent, one task, one bot.
Part of the personal-agents fleet (`[feed] → [filter] → [Telegram]`).

- Schedule: `.github/workflows/cricket-scores.yml` (`47 0 * * *` UTC = 06:17 IST; backup 07:17 with dedupe guard)
- Run now: `gh workflow run cricket-scores.yml -R astroboy1183/cricket-scores`
- Secrets (Actions): `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
