#!/usr/bin/env python3
"""Watch completed Chess.com games and emit Peck review links (stdlib only)."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import fcntl
from http.client import HTTPException
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def seconds(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be finite and greater than zero")
    return number


def emit(url, command=None, timeout=30):
    if command:
        subprocess.run([part.replace("{url}", url) for part in command],
                       input=url + "\n", text=True, check=True, timeout=timeout, shell=False)
    else:
        print(url, flush=True)


@contextmanager
def lock(path):
    """Advisory single-host lock; keep the lock file to avoid inode races."""
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise OSError("already running for this state file") from error
        yield


class FetchError(OSError):
    def __init__(self, status, retry_after=0):
        super().__init__(f"Chess.com HTTP {status}")
        self.retry_after = retry_after


def retry_after(value, now=None):
    if not value:
        return 0
    try:
        if re.fullmatch(r"[0-9]+", value):
            return int(value)
        return max(0, parsedate_to_datetime(value).timestamp() - (time.time() if now is None else now))
    except (ValueError, TypeError, OverflowError):
        return 0


MAX_RESPONSE = 32 * 1024 * 1024


class Client:
    def __init__(self, timeout):
        self.timeout = timeout
        self.cache = {}

    def fetch(self, url):
        headers = {"User-Agent": "chess-review-notifier/1.0", "Accept": "application/json"}
        cached = self.cache.get(url)
        if cached:
            headers.update(cached[0])
        try:
            with urlopen(Request(url, headers=headers), timeout=self.timeout) as response:
                body = response.read(MAX_RESPONSE + 1)
                if len(body) > MAX_RESPONSE:
                    raise ValueError("API response exceeds 32 MiB limit")
                payload = json.loads(body)
                validators = {}
                for field, conditional in [("ETag", "If-None-Match"), ("Last-Modified", "If-Modified-Since")]:
                    if response.headers.get(field):
                        validators[conditional] = response.headers[field]
                self.cache[url] = (validators, payload)
                return payload
        except HTTPError as error:
            try:
                if error.code == 304 and cached:
                    return cached[1]
                raise FetchError(error.code, retry_after(error.headers.get("Retry-After"))) from error
            finally:
                error.close()

MONTH = r"[0-9]{4}/(?:0[1-9]|1[0-2])"
GAME = re.compile(r"https://www\.chess\.com/game/(?:live|daily)/([0-9]+)")


def save(path, state):
    """Replace state atomically; never truncate a previous checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load(path, username):
    if not path.exists():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(state, dict) or state.get("version") != 1
            or state.get("username") != username
            or not isinstance(state.get("month"), str)
            or not re.fullmatch(MONTH, state["month"])
            or not isinstance(state.get("archives"), list)
            or any(not isinstance(x, str) or not re.fullmatch(MONTH, x) for x in state["archives"])
            or not isinstance(state.get("seen"), list)
            or any(not isinstance(x, str) or not re.fullmatch(r"[0-9]+", x) for x in state["seen"])):
        raise ValueError("invalid state or different account; use a separate state file")
    return state


def items(payload, key):
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        raise ValueError(f"invalid API {key} list")
    return payload[key]


def poll(path, username, fetch, deliver, now):
    path = Path(path)
    state = load(path, username)
    month = now.strftime("%Y/%m")
    year, number = map(int, (state["month"] if state else month).split("/"))
    first = f"{year if number > 1 else year - 1:04}/{number - 1 if number > 1 else 12:02}"
    base = f"https://api.chess.com/pub/player/{username}/games/"
    archives = items(fetch(base + "archives"), "archives")
    if any(not isinstance(url, str) or not re.fullmatch(re.escape(base) + MONTH, url) for url in archives):
        raise ValueError("invalid archive URL")
    known = set(state["archives"]) if state else {url[-7:] for url in archives}
    games = []
    for archive in sorted(set(archives)):
        if archive[-7:] <= month and (archive[-7:] >= first or archive[-7:] not in known):
            for game in items(fetch(archive), "games"):
                if (not isinstance(game, dict) or not isinstance(game.get("url"), str)
                        or not GAME.fullmatch(game["url"])
                        or type(game.get("end_time")) is not int or game["end_time"] < 0):
                    raise ValueError("invalid completed game")
                games.append((game["end_time"], GAME.fullmatch(game["url"]).group(1)))
    # Fetch and validate the entire snapshot before baselining or delivering.
    baseline = state is None
    if baseline:
        state = {"version": 1, "username": username, "month": month, "seen": [], "archives": []}
    seen = set(state["seen"])
    for _, game_id in sorted(games):
        if game_id in seen:
            continue
        if not baseline:
            deliver("https://peckchess.com/game-review?" + urlencode({"game": f"chesscom:{username}:{game_id}"}))
        seen.add(game_id)
        if not baseline:
            state["seen"] = sorted(seen)
            save(path, state)
    state["seen"] = sorted(seen)
    state["month"] = month
    state["archives"] = sorted(known | {url[-7:] for url in archives if url[-7:] <= month})
    save(path, state)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username", help="Chess.com username")
    parser.add_argument("--state", type=Path, help="state file (default: ~/.local/state/chess-review-notifier/USERNAME.json)")
    parser.add_argument("--once", action="store_true", help="poll once and exit")
    parser.add_argument("--interval", type=seconds, default=10, help="seconds between polls (default: 10)")
    parser.add_argument("--timeout", type=seconds, default=20, help="HTTP timeout in seconds (default: 20)")
    parser.add_argument("--notify-timeout", type=seconds, default=30, help="notification command timeout (default: 30)")
    parser.add_argument("--notify-command", nargs=argparse.REMAINDER, help="last option: executable and argv; {url} is replaced, URL also goes to stdin")
    args = parser.parse_args(argv)
    if args.notify_command == []:
        parser.error("--notify-command requires an executable")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,25}", args.username):
        parser.error("username must contain 1–25 ASCII letters, digits, underscores or hyphens")
    args.username = args.username.lower()
    path = (args.state or Path.home() / ".local/state/chess-review-notifier" / (args.username + ".json")).expanduser().resolve()
    try:
        with lock(path):
            client = Client(timeout=args.timeout)
            failures = 0
            while True:
                delay = args.interval
                try:
                    poll(path, args.username, client.fetch,
                         lambda url: emit(url, args.notify_command, args.notify_timeout), datetime.now(timezone.utc))
                    failures = 0
                except (OSError, ValueError, HTTPException, subprocess.SubprocessError) as error:
                    print(f"error: {error}", file=sys.stderr)
                    if args.once:
                        return 1
                    failures = min(failures + 1, 8)
                    delay = max(args.interval, min(300, args.interval * 2 ** failures), getattr(error, "retry_after", 0))
                if args.once:
                    return 0
                time.sleep(delay)
    except (OSError, ValueError, HTTPException, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
