# Testing

Run the suite with Python 3.9+:

```sh
python3 -m unittest discover -s tests -v
```

Tests use invented game data, a local HTTP server and harmless subprocesses. They do not contact Chess.com or send notifications.

The suite covers first-run baselines, duplicate suppression, restarts, month rollover, archive catch-up, partial delivery failures, atomic state writes, locking, conditional HTTP requests, backoff and command arguments.

GitHub Actions runs the suite on Linux and macOS with Python 3.9 and the latest stable Python 3.

## Live checks

Use a separate state file when testing against a real account:

```sh
python3 chess_review_notifier.py sample-player --state ./state/test.json --once
```

The first successful run should print nothing. Run it again after completing a game to check that a new review link appears. Reuse the state file; deleting it creates a new baseline.

To measure notification latency, record when the game ends and when its link appears. HTTP response time and cache headers alone do not establish that delay.
