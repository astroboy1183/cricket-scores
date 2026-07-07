#!/usr/bin/env python3
"""Cricket scores.

One Telegram message every morning (~6:17 IST via GitHub Actions) with the
live-score lines worth caring about: anything involving India (incl. India
A / women / U19), international matches between major sides, IPL/WPL.

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

FEED = "http://static.cricinfo.com/rss/livescores.xml"
MAX_LINES = 25  # score lines are short; pass the whole board through


def gather_scores():
    """Every score line on the board — [] if the feed is unreachable."""
    try:
        feed = feedparser.parse(FEED)
        return [e.get("title") for e in feed.entries[:MAX_LINES] if e.get("title")]
    except Exception:
        return []


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
    lines = notable(scores) if scores else []
    forced = bool(os.environ.get("CRICKET_FORCE"))

    if not lines and not forced:
        print("no notable matches — staying silent")
        return

    body = "\n".join(lines) or "No notable matches today (forced send)."
    send_telegram(f"🏏 Cricket — {datetime.now(IST):%a %d %b %Y}\n\n{body}")


if __name__ == "__main__":
    main()
