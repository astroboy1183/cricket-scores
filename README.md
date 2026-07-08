# cricket-scores

Notable cricket scores → Telegram, twice daily via GitHub Actions:
~6:17 AM IST (overnight matches) and ~21:47 IST (the day's results).

Filters the ESPN Cricinfo live-scores board down to matches worth
attention. SILENT when nothing notable is on — a message always means
there's a match worth checking. One agent, one task, one bot:
`@jayanth_cricket_bot`.

## How the code works

`cricket_scores.py`, in pipeline order:

- **`gather_scores()`** — parses the Cricinfo live-scores RSS (`FEED`,
  served over HTTPS) and returns up to `MAX_LINES = 25` score lines
  (they're short, so the whole board fits in one prompt). It gives a
  three-way signal so a dead feed is never mistaken for a quiet day:
  `None` when the feed is **unreachable** (network error, HTTP >= 400, or
  a malformed body that recovered no entries), `[]` when the feed was
  reached but the **board is empty**, and the list of score lines
  otherwise.
- **`notable(scores)`** — the one model call, used as a *filter* rather
  than a writer: keep only matches involving India (incl. A / women /
  U19), internationals between major sides, IPL/WPL; copy the kept lines
  **verbatim** (scores must not be paraphrased — an invented score is
  worse than none); output exactly `NONE` when nothing qualifies. The
  code turns `NONE` into an empty list.
- **`main()`** — gather → filter → send *or stay silent*. An unreachable
  feed (`gather_scores()` → `None`) **raises**, failing the run so the
  workflow's failure alert fires — a broken feed must be loud. A reached
  but quiet board just prints to the Actions log ("no notable matches —
  staying silent"). `CRICKET_FORCE=1` overrides silence for testing,
  sending a placeholder line instead.
- **`agentlib.py`** (vendored) — `ask_llm()` one-shot model call;
  `send_telegram()` chunked sends.

## Design notes

- Silent-by-default copied from the eng-blogs agent: for low-volume
  topics, an unconditional daily message trains you to ignore the bot.
- The `NONE` sentinel makes the model's "nothing qualifies" answer
  machine-checkable instead of parsing prose.
- `gather_scores()` returns `None` (not `[]`) on a dead feed so silence
  is reserved for genuinely quiet days; a fetch failure fails the run
  loudly. No fallback score source is wired in: the Cricinfo
  live-scores RSS is the only free feed that publishes the *whole board*
  as verbatim score lines. Cricket news RSS (TOI, NDTV, Cricinfo news)
  carry headlines, not scores, so merging them would poison the
  "copy score lines verbatim" filter; the per-league ESPN scoreboard API
  returns stale last-completed matches and would need league-id
  enumeration. If a reliable second live-scores board appears, merge it
  in `gather_scores()` (dedupe by title) — the `None`/`[]` contract
  already carries the failure signal.
- Each edition has a backup cron an hour later. The dedupe guard uses a
  **3-hour window** (not "today" like the other agents): that pairs each
  backup with its own edition's primary while letting the evening
  edition run after a successful morning one. The daily-review watchdog
  checks that the *cron fired*, not that a message was sent, so silent
  days still count as healthy.

## Ops

- Schedule: `.github/workflows/cricket-scores.yml`
  (morning `47 0 * * *` UTC = 06:17 IST, backup 07:17;
  evening `17 16 * * *` UTC = 21:47 IST, backup 22:47)
- Run now: `gh workflow run cricket-scores.yml -R astroboy1183/cricket-scores`
- Secrets (Actions): `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Local test: `CRICKET_FORCE=1 <any fleet venv>/bin/python cricket_scores.py`
