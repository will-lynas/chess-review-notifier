# chess-review-notifier

A small, standalone Python CLI that watches completed Chess.com games and emits [Peck](https://peckchess.com) review links.

## Run

Python 3.9+ on Linux or macOS. No packages, account login, or API key required. Download this repository, then:

```sh
python3 chess_review_notifier.py sample-player
python3 chess_review_notifier.py sample-player --once
python3 chess_review_notifier.py sample-player --interval 30 --state ./state/player.json
```

Replace `sample-player` with the account to watch. Usernames are case-insensitive. The default interval is 10 seconds **after** each poll finishes. Stop continuous polling with Ctrl-C.

The first successful poll silently establishes a baseline; it does not notify for existing games. Later polls emit one URL per newly discovered game, for example (invented account and game):

```text
https://peckchess.com/game-review?game=chesscom%3Asample-player%3A1003
```

To install the command name without packaging:

```sh
mkdir -p "$HOME/.local/bin"
install -m 755 chess_review_notifier.py "$HOME/.local/bin/chess-review-notifier"
# With ~/.local/bin on PATH:
chess-review-notifier sample-player
```

## Delivery

By default links go to stdout, flushed immediately. Diagnostics go to stderr. To use your own sender, put `--notify-command` **last**, followed by its executable and separate arguments:

```sh
python3 chess_review_notifier.py sample-player --notify-command /usr/bin/printf '%s\n' '{url}'
# Or a sender that reads one URL from stdin:
python3 chess_review_notifier.py sample-player --notify-command /path/to/your-sender
```

Each literal `{url}` in an argument is replaced with the link. The link plus a newline is also supplied on stdin. Arguments are passed directly, never through a shell: pipes, redirects, wildcards and shell expressions are not interpreted. Use only trusted commands; they run with your own permissions, environment and working directory. Prefer an absolute executable path. The sender must exit zero on success. `--notify-timeout` bounds the direct child (default 30 seconds), not remote delivery or detached descendants. Sender stdout/stderr are inherited.

## State and reliability

- State defaults to `~/.local/state/chess-review-notifier/USERNAME.json`, separate from the source. Use one stable state file per account on a local filesystem. It contains the username, seen game IDs and archive progress; it grows with game history. Keep it private and backed up.
- State is replaced atomically with restrictive file permissions. An advisory lock prevents overlapping runners using the same resolved state path on one host. Do not delete the adjacent `.lock` file while a runner is active; the lock is automatically released when the process exits.
- Polls check the current and previous UTC months, catch up after downtime, and fetch newly discovered archives. Older archives already listed at baseline are treated as historical without downloading them. Failed fetches or malformed data do not advance state. Corrupt state or an account mismatch is not silently reset. Removing state establishes a fresh baseline, so do not delete it to fix a delivery failure.
- Successfully delivered games are checkpointed individually. A sender failure leaves that game retryable. **Delivery is not exactly-once:** a crash between sending and saving, a timeout, or a sender reporting failure after delivering can cause a duplicate. Stdout flush or exit zero confirms only local acceptance, not that a person received the message. An idempotent sender can deduplicate by URL.
- Requests are serial and conditional (`ETag`/`Last-Modified`, cached in memory). Continuous mode backs off on errors (up to five minutes, or longer for `Retry-After`) and resets after success. `--once` attempts a single poll and exits 0 on success, 1 on failure; invalid arguments exit 2 and Ctrl-C exits 130. `--timeout` sets the HTTP socket timeout (default 20 seconds), not a total poll deadline. Responses above 32 MiB are rejected.

**Not a real-time feed.** Chess.com's public API/CDN can return cached or delayed data. Polling every 10 seconds does not guarantee notification within 10 seconds of a game ending, and a short HTTP response time does not measure game-publication delay. Games not yet exposed by the API at baseline may be reported later. Changes to old, already-known archives outside the catch-up window are not continually rescanned. See the [official API caching guidance](https://www.chess.com/news/view/published-data-api).

This tool emits links; it does not run an engine, upload games, or verify Peck's import availability for every game type. Scheduling and notification transports are external choices, not runtime dependencies.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Tests use invented fixtures, a loopback HTTP server, and harmless subprocesses. They do not contact Chess.com or send notifications. The GitHub Actions workflow runs the same suite.
