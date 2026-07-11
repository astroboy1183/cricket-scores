#!/usr/bin/env python3
"""Offline tests for cricket_scores — no network, no API keys required.

Covers gather_scores()'s three-way signal (None = feed unreachable,
[] = board reached but empty, [...] = score lines) and that main()
raises on a dead feed while staying silent on a quiet one.
"""

import unittest
from unittest import mock

import cricket_scores


class FakeFeed:
    """Stand-in for a feedparser result."""

    def __init__(self, entries=None, status=None, bozo=0):
        self.entries = entries or []
        if status is not None:
            self.status = status
        self.bozo = bozo


def _entry(title):
    return {"title": title}


class GatherScoresTest(unittest.TestCase):
    def test_score_lines_returned(self):
        feed = FakeFeed([_entry("India 250/4 v Australia"), _entry("Kent v Surrey")], status=200)
        with mock.patch.object(cricket_scores.feedparser, "parse", return_value=feed):
            self.assertEqual(
                cricket_scores.gather_scores(),
                ["India 250/4 v Australia", "Kent v Surrey"],
            )

    def test_empty_board_is_quiet_not_dead(self):
        # Reached the feed (200) but nothing on the board -> [] (stay silent).
        feed = FakeFeed([], status=200)
        with mock.patch.object(cricket_scores.feedparser, "parse", return_value=feed):
            self.assertEqual(cricket_scores.gather_scores(), [])

    def test_http_error_status_is_dead(self):
        feed = FakeFeed([], status=503)
        with mock.patch.object(cricket_scores.feedparser, "parse", return_value=feed):
            self.assertIsNone(cricket_scores.gather_scores())

    def test_bozo_with_no_entries_is_dead(self):
        # Network/parse failure: feedparser flags bozo and recovers nothing.
        feed = FakeFeed([], bozo=1)
        with mock.patch.object(cricket_scores.feedparser, "parse", return_value=feed):
            self.assertIsNone(cricket_scores.gather_scores())

    def test_bozo_but_entries_recovered_is_kept(self):
        # Malformed tail but real lines parsed -> best-effort, still usable.
        feed = FakeFeed([_entry("India 250/4 v Australia")], status=200, bozo=1)
        with mock.patch.object(cricket_scores.feedparser, "parse", return_value=feed):
            self.assertEqual(cricket_scores.gather_scores(), ["India 250/4 v Australia"])

    def test_exception_is_dead(self):
        with mock.patch.object(cricket_scores.feedparser, "parse", side_effect=OSError("boom")):
            self.assertIsNone(cricket_scores.gather_scores())


class MainBranchingTest(unittest.TestCase):
    def test_dead_feed_raises(self):
        with mock.patch.object(cricket_scores, "load_dotenv"), \
             mock.patch.object(cricket_scores, "gather_scores", return_value=None), \
             mock.patch.object(cricket_scores, "send_telegram") as send:
            with self.assertRaises(RuntimeError):
                cricket_scores.main()
            send.assert_not_called()

    def test_quiet_day_stays_silent(self):
        with mock.patch.object(cricket_scores, "load_dotenv"), \
             mock.patch.object(cricket_scores, "gather_scores", return_value=[]), \
             mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch.object(cricket_scores, "send_telegram") as send:
            cricket_scores.main()  # must not raise
            send.assert_not_called()

    def test_notable_matches_send(self):
        with mock.patch.object(cricket_scores, "load_dotenv"), \
             mock.patch.object(cricket_scores, "gather_scores", return_value=["India 5/0 v Australia"]), \
             mock.patch.object(cricket_scores, "notable", return_value=["India 5/0 v Australia"]), \
             mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch.object(cricket_scores, "send_telegram") as send:
            cricket_scores.main()
            send.assert_called_once()
            self.assertIn("India 5/0 v Australia", send.call_args[0][0])


class EditionTest(unittest.TestCase):
    def _now(self, hour):
        from datetime import datetime
        return datetime(2026, 7, 11, hour, 17, tzinfo=cricket_scores.IST)

    def test_edition_boundaries(self):
        self.assertEqual(cricket_scores.edition(self._now(6)), "morning")
        self.assertEqual(cricket_scores.edition(self._now(13)), "lunch")
        self.assertEqual(cricket_scores.edition(self._now(21)), "evening")

    def test_india_detection_avoids_west_indies(self):
        self.assertTrue(cricket_scores.india_on_board(["India Women 120/2 v England"]))
        self.assertTrue(cricket_scores.india_on_board(["Kent v Surrey", "India A 50/1"]))
        self.assertFalse(cricket_scores.india_on_board(["West Indies 200 v Australia"]))

    def _run_lunch(self, board, send):
        fixed = self._now(13)

        class FixedDT(cricket_scores.datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed.astimezone(tz) if tz else fixed

        with mock.patch.object(cricket_scores, "load_dotenv"), \
             mock.patch.object(cricket_scores, "datetime", FixedDT), \
             mock.patch.object(cricket_scores, "gather_scores", return_value=board), \
             mock.patch.object(cricket_scores, "notable",
                               return_value=[f"🇮🇳 {board[0]}"] if board else []), \
             mock.patch.dict("os.environ", {}, clear=True):
            cricket_scores.main()

    def test_lunch_silent_without_india(self):
        with mock.patch.object(cricket_scores, "send_telegram") as send:
            self._run_lunch(["West Indies 200 v Australia"], send)
            send.assert_not_called()

    def test_lunch_sends_when_india_live(self):
        with mock.patch.object(cricket_scores, "send_telegram") as send:
            self._run_lunch(["India 245/3 v Australia"], send)
            send.assert_called_once()
            self.assertIn("(lunch)", send.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
