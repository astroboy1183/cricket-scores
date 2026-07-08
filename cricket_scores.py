#!/usr/bin/env python3
"""Cricket scores.

Two Telegram editions a day via GitHub Actions — ~6:17 IST (overnight
matches) and ~21:47 IST (the day's results) — with the live-score lines
worth caring about: anything involving India (incl. India A / women /
U19), international matches between major sides, IPL/WPL.

One agent, one task, one bot. SILENT when nothing notable is on — a
message always means there's a match worth checking. Set CRICKET_FORCE=1
to send regardless (used for testing).

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


def notable(scores):
    """Model filters the board; returns [] when nothing qualifies."""
    prompt = (
        "Below is every match on today's cricket live-score board, one line "
        "each. Keep ONLY matches worth my attention: anything involving "
        "India (incl. India A / women / U19), international matches between "
        "major sides, IPL/WPL. Copy the kept score lines verbatim, one per "
        "line, 5 max. If nothing qualifies, output exactly: NONE\n\n"
        + "\n".join(f"- {s}" for s in scores)
    )
    reply = ask_llm(prompt, max_tokens=300).strip()
    if reply == "NONE":
        return []
    return [l for l in reply.splitlines() if l.strip()]


def main():
    load_dotenv(BASE_DIR / ".env")
    scores = gather_scores()
    if scores is None:
        # Dead feed is real breakage, not a quiet day: raise so the run
        # fails and the workflow's failure alert fires.
        raise RuntimeError(f"cricket live-score feed unreachable: {FEED}")
    lines = notable(scores) if scores else []
    forced = bool(os.environ.get("CRICKET_FORCE"))

    if not lines and not forced:
        print("no notable matches — staying silent")
        return

    body = "\n".join(lines) or "No notable matches today (forced send)."
    send_telegram(f"🏏 Cricket — {datetime.now(IST):%a %d %b %Y}\n\n{body}")


if __name__ == "__main__":
    main()
