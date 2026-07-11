#!/usr/bin/env python3
"""Cricket scores.

Three Telegram editions a day via GitHub Actions:

  morning (~6:17 IST) — overnight matches
  lunch   (~13:37 IST) — SILENT unless an India side is on the board;
                          on India match days you get a midday score
  evening (~21:47 IST) — the day's results

The board (ESPN Cricinfo live-scores RSS) is filtered to matches worth
caring about — anything involving India (incl. India A / women / U19),
internationals between major sides, IPL/WPL — and formatted into
sections inferred from each line's own text:

  🔴 LIVE      🇮🇳-flagged, India first
  ✅ RESULTS   wins stated as wins
  📅 UPCOMING  matches listed but not started

Score NUMBERS are always copied verbatim from the board — a paraphrased
score is worse than none. SILENT when nothing notable is on — a message
always means there's a match worth checking. Set CRICKET_FORCE=1 to send
regardless (used for testing).

(A structured-data upgrade — series names, day/session status, fixture
times — is parked pending a cricketdata.org API key; every keyless
structured source is bot-walled. The RSS is the reliable spine.)

Hard failures raise and land in the Actions log.
"""

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
from dotenv import load_dotenv

from agentlib import ask_llm, send_telegram

BASE_DIR = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")

FEED = "https://static.cricinfo.com/rss/livescores.xml"
MAX_LINES = 25  # score lines are short; pass the whole board through
MAX_KEPT = 7    # lines across all sections; the board rarely earns more


def edition(now):
    """morning / lunch / evening by IST hour — labels the message and
    drives the lunch-only silence rule."""
    if now.hour < 10:
        return "morning"
    if now.hour < 17:
        return "lunch"
    return "evening"


def india_on_board(scores):
    """Deterministic gate for the lunch edition: is any India side listed?

    Substring match is safe here — 'West Indies' does not contain
    'india', while 'India A' / 'India Women' / 'Indian Board XI' do."""
    return any("india" in s.lower() for s in scores)


def gather_scores():
    """Score lines from the live board.

    Distinguishes a dead feed from a quiet one so main() can be loud on
    real breakage and silent on a genuinely empty board:

    - ``None`` — the feed is unreachable (network error, HTTP >= 400, or an
      unparseable body with nothing recovered). A real failure: raise.
    - ``[]``   — the feed was reached but the board is empty. Nothing on;
      stay silent.
    - ``[...]``— up to ``MAX_LINES`` score lines.
    """
    try:
        feed = feedparser.parse(FEED)
    except Exception:
        return None
    # feedparser rarely raises: it flags transport/parse trouble on the
    # result instead. An HTTP error status, or a bozo (malformed) response
    # that recovered no entries, both mean "could not fetch the board".
    status = getattr(feed, "status", None)
    if status is not None and status >= 400:
        return None
    if getattr(feed, "bozo", 0) and not feed.entries:
        return None
    return [e.get("title") for e in feed.entries[:MAX_LINES] if e.get("title")]


def notable(scores, ed="morning"):
    """Model filters AND sections the board; returns [] when nothing
    qualifies. Lines are kept verbatim inside the sections."""
    lunch_rule = (
        "This is the LUNCH edition: keep ONLY matches involving an India "
        "side — nothing else qualifies at lunchtime.\n"
        if ed == "lunch"
        else ""
    )
    prompt = (
        "Below is every match on today's cricket live-score board, one line "
        "each. Keep ONLY matches worth my attention: anything involving "
        "India (incl. India A / women / U19), international matches between "
        "major sides, IPL/WPL. " + lunch_rule +
        "\nFormat the kept lines into these sections, inferring each line's "
        "state from its own text:\n\n"
        "🔴 LIVE — matches in progress (a live board line has innings "
        "scores and no result phrase)\n"
        "✅ RESULTS — lines whose text already states a result ('won by', "
        "'beat', 'match drawn', 'match tied')\n"
        "📅 UPCOMING — matches listed but not started (no innings score "
        "on the line)\n\n"
        "Rules:\n"
        "- Copy each kept line VERBATIM after its marker — never alter "
        "team names, scores or overs. Numbers must match the board "
        "exactly.\n"
        "- Prefix lines involving an India side with 🇮🇳 and put them "
        "first within their section.\n"
        "- Omit any section with no lines. No commentary, no extra text.\n"
        f"- At most {MAX_KEPT} lines across all sections.\n"
        "If nothing qualifies, output exactly: NONE\n\n"
        + "\n".join(f"- {s}" for s in scores)
    )
    reply = ask_llm(prompt, max_tokens=400).strip()
    if reply == "NONE":
        return []
    return [l for l in reply.splitlines() if l.strip()]


def main():
    load_dotenv(BASE_DIR / ".env")
    now = datetime.now(IST)
    ed = edition(now)
    forced = bool(os.environ.get("CRICKET_FORCE"))

    scores = gather_scores()
    if scores is None:
        # Dead feed is real breakage, not a quiet day: raise so the run
        # fails and the workflow's failure alert fires.
        raise RuntimeError(f"cricket live-score feed unreachable: {FEED}")

    # Lunch exists ONLY for India match days — a deterministic gate, so
    # ordinary lunchtimes cost nothing (and no model call is made).
    if ed == "lunch" and not india_on_board(scores) and not forced:
        print("lunch edition: no India side on the board — staying silent")
        return

    lines = notable(scores, ed) if scores else []
    if not lines and not forced:
        print("no notable matches — staying silent")
        return

    body = "\n".join(lines) or "No notable matches today (forced send)."
    send_telegram(f"🏏 Cricket — {now:%a %d %b} ({ed})\n\n{body}")


if __name__ == "__main__":
    main()
