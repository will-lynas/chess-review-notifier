"""Offline tests use invented accounts and game IDs, never personal data."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("notifier", ROOT / "chess_review_notifier.py")
n = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(n)

ACCOUNT = "sample-player"
INDEX = "https://api.chess.com/pub/player/sample-player/games/archives"
NOV = "https://api.chess.com/pub/player/sample-player/games/2026/11"
OCT = "https://api.chess.com/pub/player/sample-player/games/2026/10"
NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


def game(number, end=100):
    return {"url": "https://www.chess.com/game/live/" + str(number), "end_time": end}


class PollTests(unittest.TestCase):
    def test_initial_baseline_then_only_new_games_even_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            pages = {INDEX: {"archives": [OCT, NOV]}, OCT: {"games": [game(1001)]}, NOV: {"games": [game(1002)]}}
            links = []
            n.poll(path, ACCOUNT, pages.__getitem__, links.append, NOW)
            self.assertEqual(links, [])
            pages[NOV]["games"].append(game(1003))
            n.poll(path, ACCOUNT, pages.__getitem__, links.append, NOW)
            self.assertEqual(links, ["https://peckchess.com/game-review?game=chesscom%3Asample-player%3A1003"])
            n.poll(path, ACCOUNT, pages.__getitem__, links.append, NOW)
            self.assertEqual(len(links), 1)
            self.assertEqual(json.loads(path.read_text())["seen"], ["1001", "1002", "1003"])

    def test_rollover_recovers_outage_months_without_fetching_old_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            old = NOV.replace("2026/11", "2020/01")
            dec = NOV.replace("2026/11", "2026/12")
            jan = NOV.replace("2026/11", "2027/01")
            pages = {INDEX: {"archives": [old, OCT, NOV]}, OCT: {"games": []}, NOV: {"games": [game(1001)]}}
            n.poll(path, ACCOUNT, pages.__getitem__, lambda _: self.fail("baseline"), NOW)
            pages[INDEX]["archives"] += [dec, jan]
            pages[NOV]["games"].append(game(1002))
            pages[dec] = {"games": [game(1003)]}
            pages[jan] = {"games": [game(1004)]}
            links = []
            n.poll(path, ACCOUNT, pages.__getitem__, links.append, datetime(2027, 1, 1, tzinfo=timezone.utc))
            self.assertEqual(len(links), 3)
            self.assertEqual(json.loads(path.read_text())["month"], "2027/01")

    def test_delayed_archive_discovery_after_outage_is_not_lost(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            pages = {INDEX: {"archives": [NOV]}, NOV: {"games": []}}
            n.poll(path, ACCOUNT, pages.__getitem__, lambda _: None, NOW)
            later = datetime(2027, 3, 1, tzinfo=timezone.utc)
            n.poll(path, ACCOUNT, pages.__getitem__, lambda _: None, later)
            dec = NOV.replace("2026/11", "2026/12")
            pages[INDEX]["archives"].append(dec)
            pages[dec] = {"games": [game(1001)]}
            links = []
            n.poll(path, ACCOUNT, pages.__getitem__, links.append, later)
            self.assertEqual(len(links), 1)
            self.assertTrue(links[0].endswith("1001"))

    def test_failed_fetch_does_not_create_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            pages = {INDEX: {"archives": [OCT, NOV]}, OCT: {"games": [game(1001)]}}
            with self.assertRaises(KeyError):
                n.poll(path, ACCOUNT, pages.__getitem__, lambda _: self.fail("must fetch all first"), NOW)
            self.assertFalse(path.exists())

    def test_successful_deliveries_checkpoint_before_later_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            pages = {INDEX: {"archives": [NOV]}, NOV: {"games": []}}
            n.poll(path, ACCOUNT, pages.__getitem__, lambda _: None, NOW)
            pages[NOV]["games"] = [game(1001), game(1002)]
            def delivery(link):
                if link.endswith("1002"):
                    raise OSError("synthetic failure")
            with self.assertRaises(OSError):
                n.poll(path, ACCOUNT, pages.__getitem__, delivery, NOW)
            self.assertEqual(json.loads(path.read_text())["seen"], ["1001"])
            links = []
            n.poll(path, ACCOUNT, pages.__getitem__, links.append, NOW)
            self.assertEqual(len(links), 1)
            self.assertTrue(links[0].endswith("1002"))

    def test_bad_state_or_account_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            for state in [{"seen": []}, {"version": 1, "username": "other-player", "month": "2026/11", "seen": []}, {"version": 1, "username": ACCOUNT, "month": "2026/13", "seen": []}]:
                path.write_text(json.dumps(state))
                with self.subTest(state=state), self.assertRaises(ValueError):
                    n.poll(path, ACCOUNT, lambda _: self.fail("invalid state"), lambda _: None, NOW)

    def test_malformed_remote_data_never_advances_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            pages = {INDEX: {"archives": [NOV]}, NOV: {"games": []}}
            n.poll(path, ACCOUNT, pages.__getitem__, lambda _: None, NOW)
            original = path.read_bytes()
            for payload in [{"games": [game(1001), {"url": "https://example.com/1002", "end_time": 101}]}, {"games": [game(1001), {"url": game(1002)["url"]}]}, {"games": "broken"}]:
                pages[NOV] = payload
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    n.poll(path, ACCOUNT, pages.__getitem__, lambda _: self.fail("validate all first"), NOW)
                self.assertEqual(path.read_bytes(), original)
            pages[INDEX] = {"archives": ["https://example.com/untrusted"]}
            with self.assertRaises(ValueError):
                n.poll(path, ACCOUNT, pages.__getitem__, lambda _: None, NOW)

    def test_atomic_write_preserves_previous_state_when_replace_fails(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("original")
            with patch.object(n.os, "replace", side_effect=OSError("synthetic failure")):
                with self.assertRaises(OSError):
                    n.save(path, {"seen": []})
            self.assertEqual(path.read_text(), "original")
            self.assertEqual(list(path.parent.iterdir()), [path])


class HttpTests(unittest.TestCase):
    def test_oversize_or_truncated_response_does_not_poison_cached_body(self):
        from io import BytesIO
        from unittest.mock import patch
        class Response(BytesIO):
            headers = {}
        url = "https://example.com/synthetic"
        client = n.Client(timeout=2)
        client.cache[url] = ({}, {"games": []})
        with patch.object(n, "MAX_RESPONSE", 32, create=True), patch.object(n, "urlopen", return_value=Response(b'{"games": []}' + b" " * 32)):
            with self.assertRaises(ValueError):
                client.fetch(url)
        self.assertEqual(client.cache[url][1], {"games": []})
        with patch.object(n, "urlopen", return_value=Response(b'{"games":')):
            with self.assertRaises(ValueError):
                client.fetch(url)
        self.assertEqual(client.cache[url][1], {"games": []})

    def test_http_errors_carry_retry_after_without_discarding_cache(self):
        from email.message import Message
        from io import BytesIO
        from unittest.mock import patch
        headers = Message()
        headers["Retry-After"] = "120"
        client = n.Client(timeout=2)
        url = "https://example.com/synthetic"
        client.cache[url] = ({"If-None-Match": '"old"'}, {"games": []})
        error = n.HTTPError(url, 429, "synthetic limit", headers, BytesIO(b""))
        with patch.object(n, "urlopen", side_effect=error):
            with self.assertRaises(n.FetchError) as raised:
                client.fetch(url)
        self.assertEqual(raised.exception.retry_after, 120)
        self.assertEqual(client.cache[url][1], {"games": []})
        with patch.object(n, "urlopen", side_effect=n.HTTPError(url, 304, "synthetic", {}, BytesIO(b""))):
            self.assertEqual(client.fetch(url), {"games": []})
        for value in ["garbage", "NaN", "-1", None]:
            self.assertEqual(n.retry_after(value), 0)
        self.assertEqual(n.retry_after("Sun, 01 Nov 2026 00:02:00 GMT", now=1793491200), 120)

    def test_conditional_get_reuses_body_after_304(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(dict(self.headers))
                if self.headers.get("If-None-Match") == '"synthetic-v1"':
                    self.send_response(304)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("ETag", '"synthetic-v1"')
                self.send_header("Last-Modified", "Sun, 01 Nov 2026 00:00:00 GMT")
                self.end_headers()
                self.wfile.write(b'{"games": []}')
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            client = n.Client(timeout=2)
            url = f"http://127.0.0.1:{server.server_port}/synthetic"
            self.assertEqual(client.fetch(url), {"games": []})
            self.assertEqual(client.fetch(url), {"games": []})
            self.assertEqual(requests[1]["If-None-Match"], '"synthetic-v1"')
            self.assertIn("If-Modified-Since", requests[1])
            self.assertIn("chess-review-notifier", requests[0]["User-Agent"])
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


class LockTests(unittest.TestCase):
    def test_second_runner_is_rejected_and_crash_does_not_leave_stale_lock(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            code = "import chess_review_notifier as n; from pathlib import Path; import sys;\nwith n.lock(Path(sys.argv[1])): print('acquired')"
            with n.lock(path):
                result = subprocess.run([sys.executable, "-c", code, str(path)], cwd=ROOT, text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("already running", result.stderr)
            crash = code.replace("print('acquired')", "__import__('os')._exit(0)")
            result = subprocess.run([sys.executable, "-c", crash, str(path)], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([sys.executable, "-c", code, str(path)], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "acquired\n")


class DeliveryTests(unittest.TestCase):
    def test_command_receives_literal_argv_and_stdin_without_shell(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "received.json"
            marker = Path(directory) / "must-not-exist"
            link = "https://example.com/$(touch " + str(marker) + ");{literal}"
            code = "import json,pathlib,sys; pathlib.Path(sys.argv[1]).write_text(json.dumps([sys.argv[2:],sys.stdin.read()]))"
            n.emit(link, [sys.executable, "-c", code, str(path), "prefix={url}", "*"], 2)
            self.assertEqual(json.loads(path.read_text()), [["prefix=" + link, "*"], link + "\n"])
            self.assertFalse(marker.exists())
            with self.assertRaises(subprocess.CalledProcessError):
                n.emit(link, [sys.executable, "-c", "raise SystemExit(7)"], 2)
            with self.assertRaises(subprocess.TimeoutExpired):
                n.emit(link, [sys.executable, "-c", "import time; time.sleep(2)"], 0.02)


class CliTests(unittest.TestCase):
    def test_once_failed_fetch_returns_one_without_creating_baseline(self):
        from contextlib import redirect_stderr
        from http.client import IncompleteRead
        from io import StringIO
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            for error in [OSError("synthetic offline"), IncompleteRead(b"partial", 10)]:
                with self.subTest(error=error), patch.object(n.Client, "fetch", side_effect=error), redirect_stderr(StringIO()):
                    self.assertEqual(n.main([ACCOUNT, "--once", "--state", str(path)]), 1)
                    self.assertFalse(path.exists())

    def test_cli_passes_configured_argv_and_timeouts_to_delivery(self):
        from unittest.mock import patch
        month = datetime.now(timezone.utc).strftime("%Y/%m")
        archive = NOV[:-7] + month
        pages = {INDEX: {"archives": [archive]}, archive: {"games": []}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            args = [ACCOUNT.upper(), "--state", str(path), "--once", "--timeout", "4", "--notify-timeout", "5", "--notify-command", "synthetic-sender", "--body", "{url}"]
            with patch.object(n.Client, "fetch", lambda self, url: pages[url]), patch.object(n, "emit") as deliver:
                self.assertEqual(n.main(args), 0)
                pages[archive]["games"].append(game(1001))
                self.assertEqual(n.main(args), 0)
            deliver.assert_called_once_with("https://peckchess.com/game-review?game=chesscom%3Asample-player%3A1001", ["synthetic-sender", "--body", "{url}"], 5)

    def test_invalid_cli_values_are_rejected_before_io(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from unittest.mock import patch
        cases = [["../bad"], ["x" * 26], ["--oops"], [ACCOUNT, "--interval", "0"], [ACCOUNT, "--interval", "nan"], [ACCOUNT, "--timeout", "inf"], [ACCOUNT, "--notify-timeout", "-1"], [ACCOUNT, "--notify-command"]]
        with patch.object(n.Client, "fetch", side_effect=AssertionError("unexpected I/O")), patch.object(n, "lock", side_effect=AssertionError("unexpected I/O")):
            for args in cases:
                with self.subTest(args=args), redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        n.main(args)
                    self.assertEqual(raised.exception.code, 2)

    def test_continuous_polling_backs_off_and_resets_after_success(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            waits = []
            def sleep(delay):
                waits.append(delay)
                if len(waits) == 4:
                    raise KeyboardInterrupt
            with patch.object(n, "poll", side_effect=[None, n.FetchError(429, 45), OSError("synthetic offline"), None]) as polls, patch.object(n.time, "sleep", side_effect=sleep), redirect_stderr(StringIO()) as errors:
                status = n.main([ACCOUNT, "--state", str(Path(directory) / "state.json"), "--interval", "10"])
            self.assertEqual(status, 130)
            self.assertEqual(waits, [10, 45, 40, 10])
            self.assertEqual(polls.call_count, 4)
            self.assertIs(polls.call_args_list[0].args[2].__self__, polls.call_args_list[-1].args[2].__self__)
            self.assertIn("429", errors.getvalue())

    def test_once_cli_uses_persisted_baseline_and_stdout_only_for_new_links(self):
        import subprocess
        import sys
        month = datetime.now(timezone.utc).strftime("%Y/%m")
        archive = NOV[:-7] + month
        code = "import json,sys; import chess_review_notifier as n; from unittest.mock import patch; pages=json.loads(sys.argv[1]);\nwith patch.object(n.Client,'fetch',lambda self,url: pages[url]): raise SystemExit(n.main(sys.argv[2:]))"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            pages = {INDEX: {"archives": [archive]}, archive: {"games": [game(1001)]}}
            def invoke():
                return subprocess.run([sys.executable, "-c", code, json.dumps(pages), ACCOUNT, "--once", "--state", str(path)], cwd=ROOT, capture_output=True, text=True)
            result = invoke()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            pages[archive]["games"].append(game(1002))
            result = invoke()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "https://peckchess.com/game-review?game=chesscom%3Asample-player%3A1002\n")
            self.assertEqual(invoke().stdout, "")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
