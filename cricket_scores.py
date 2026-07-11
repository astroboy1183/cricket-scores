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

import io
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import requests
from dotenv import load_dotenv

from agentlib import ask_llm, send_telegram

BASE_DIR = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")

FEED = "https://static.cricinfo.com/rss/livescores.xml"
MAX_LINES = 25  # score lines are short; pass the whole board through
MAX_KEPT = 7    # lines across all sections; the board rarely earns more

# Sunday-evening series stats, computed by US from Cricsheet's ball-by-ball
# archives (keyless, open data) — no stats API needed when you have every
# delivery. 30-day window ≈ every active series.
CRICSHEET_URL = "https://cricsheet.org/downloads/recently_added_30_json.zip"
STATS_SERIES_CAP = 3       # series shown, busiest first
MIN_SERIES_MATCHES = 3     # below this a "series" is noise in a 30d window
STATS_KEYWORDS = (         # series worth stats even without India in them
    "india", "icc", "world cup", "ipl", "wpl", "asia cup",
    "champions trophy", "the hundred", "big bash",
)


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


def fetch_cricsheet_matches():
    """Parsed matches from Cricsheet's 30-day archive (event/gender/teams
    + full innings). One ~1.5 MB zip; raises on fetch failure."""
    resp = requests.get(
        CRICSHEET_URL,
        timeout=90,
        headers={"User-Agent": "Mozilla/5.0 (cricket-scores agent)"},
    )
    resp.raise_for_status()
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    out = []
    for name in archive.namelist():
        if not name.endswith(".json"):
            continue
        try:
            m = json.loads(archive.read(name))
        except ValueError:
            continue  # one malformed file must not sink the stats
        info = m.get("info", {})
        out.append(
            {
                "event": (info.get("event") or {}).get("name", ""),
                "gender": info.get("gender", ""),
                "teams": info.get("teams", []),
                "innings": m.get("innings", []),
            }
        )
    return out


def _tracked_series(event, teams):
    hay = event.lower()
    if any(k in hay for k in STATS_KEYWORDS):
        return True
    return any("india" in t.lower() for t in teams)


def series_stats(matches):
    """'📊 SERIES STATS' block: top run-getters and wicket-takers per
    tracked series, computed deterministically from ball-by-ball data.
    Women's series carry a 🚺 tag. Returns '' when nothing qualifies."""
    groups = {}
    for m in matches:
        if not m["event"] or not _tracked_series(m["event"], m["teams"]):
            continue
        groups.setdefault((m["event"], m["gender"]), []).append(m)
    picked = [
        g for g in sorted(groups.items(), key=lambda kv: -len(kv[1]))
        if len(g[1]) >= MIN_SERIES_MATCHES
    ][:STATS_SERIES_CAP]

    blocks = []
    for (event, gender), ms in picked:
        runs, wkts = {}, {}
        for m in ms:
            for inn in m["innings"]:
                for over in inn.get("overs", []):
                    for d in over.get("deliveries", []):
                        batter = d.get("batter")
                        runs[batter] = (
                            runs.get(batter, 0) + d.get("runs", {}).get("batter", 0)
                        )
                        for w in d.get("wickets", []):
                            # bowler-credited dismissals only
                            if w.get("kind") not in (
                                "run out", "retired hurt", "retired out",
                            ):
                                bowler = d.get("bowler")
                                wkts[bowler] = wkts.get(bowler, 0) + 1
        top_r = sorted(runs.items(), key=lambda kv: -kv[1])[:3]
        top_w = sorted(wkts.items(), key=lambda kv: -kv[1])[:3]
        tag = " 🚺" if gender == "female" else ""
        lines = [f"• {event}{tag} — {len(ms)} matches"]
        if top_r:
            lines.append("  🏏 " + " · ".join(f"{p} {r}" for p, r in top_r))
        if top_w:
            lines.append("  🎯 " + " · ".join(f"{p} {w}" for p, w in top_w))
        blocks.append("\n".join(lines))
    if not blocks:
        return ""
    return "📊 SERIES STATS (last 30 days)\n" + "\n".join(blocks)


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
        "major sides — men's AND women's equally — IPL/WPL/The Hundred. "
        + lunch_rule +
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
        "first within their section. Prefix women's matches with 🚺 "
        "(an India women's line gets both: 🇮🇳🚺).\n"
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

    # Sunday evening: append series leaderboards computed from Cricsheet's
    # ball-by-ball data. Worth sending even on a quiet board — the week's
    # stats stand on their own.
    stats_block = ""
    if ed == "evening" and now.weekday() == 6:
        try:
            stats_block = series_stats(fetch_cricsheet_matches())
        except Exception:
            stats_block = ""  # stats are an enrichment, never a dead run

    if not lines and not stats_block and not forced:
        print("no notable matches — staying silent")
        return

    parts = []
    if lines:
        parts.append("\n".join(lines))
    elif forced:
        parts.append("No notable matches today (forced send).")
    if stats_block:
        parts.append(stats_block)
    send_telegram(f"🏏 Cricket — {now:%a %d %b} ({ed})\n\n" + "\n\n".join(parts))


if __name__ == "__main__":
    main()
