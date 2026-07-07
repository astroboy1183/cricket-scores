# cricket-scores

Notable cricket scores → Telegram, ~6:17 AM IST via GitHub Actions.

Filters the ESPN Cricinfo live-scores board down to matches worth
attention. SILENT when nothing notable is on — a message always means
there's a match worth checking. One agent, one task, one bot:
`@jayanth_cricket_bot`.

## How the code works

`cricket_scores.py`, in pipeline order:

- **`gather_scores()`** — parses the Cricinfo live-scores RSS (`FEED`)
  and returns up to `MAX_LINES = 25` score lines (they're short, so the
  whole board fits in one prompt). Returns `[]` on any feed failure
  instead of raising.
- **`notable(scores)`** — the one model call, used as a *filter* rather
  than a writer: keep only matches involving India (incl. A / women /
  U19), internationals between major sides, IPL/WPL; copy the kept lines
  **verbatim** (scores must not be paraphrased — an invented score is
  worse than none); output exactly `NONE` when nothing qualifies. The
  code turns `NONE` into an empty list.
- **`main()`** — gather → filter → send *or stay silent*. The silence
  path just prints to the Actions log ("no notable matches — staying
  silent"). `CRICKET_FORCE=1` overrides silence for testing, sending a
  placeholder line instead.
- **`agentlib.py`** (vendored) — `ask_llm()` one-shot model call;
  `send_telegram()` chunked sends.

## Design notes

- Silent-by-default copied from the eng-blogs agent: for low-volume
  topics, an unconditional daily message trains you to ignore the bot.
- The `NONE` sentinel makes the model's "nothing qualifies" answer
  machine-checkable instead of parsing prose.
- Two crons + dedupe guard: backup at 07:17 IST delivers only if the
  06:17 primary was dropped or failed. The daily-review watchdog checks
  that the *cron fired*, not that a message was sent, so silent days
  still count as healthy.

## Ops

- Schedule: `.github/workflows/cricket-scores.yml`
  (`47 0 * * *` UTC = 06:17 IST; backup 07:17)
- Run now: `gh workflow run cricket-scores.yml -R astroboy1183/cricket-scores`
- Secrets (Actions): `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Local test: `CRICKET_FORCE=1 <any fleet venv>/bin/python cricket_scores.py`
