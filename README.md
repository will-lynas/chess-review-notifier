# chess-review-notifier

A daemon that sends [Peck](https://peckchess.com) review links after your Chess.com games.

## Run

```sh
python3 chess_review_notifier.py USERNAME
```

The first run skips existing games. Subsequent polls print review links for new games.

It checks every 10 seconds after the previous poll finishes. Chess.com's API can lag behind, so links may take longer to arrive.

## Notifications

Pass a command to send each link wherever you want:

```sh
python3 chess_review_notifier.py sample-player --notify-command /path/to/your-sender '{url}'
```

Put `--notify-command` last. The script replaces `{url}` with the review link and also passes it on stdin. Arguments run without a shell. Your sender should exit zero on success; failures are retried. A timeout or crash after sending can cause a duplicate.

## Options

| Argument / flag | What it does | Default |
| --- | --- | --- |
| `username` | Chess.com account to watch | Required |
| `--interval SECONDS` | Wait between polls | `10` |
| `--once` | Check once and exit | Off |
| `--state FILE` | Save progress here | `~/.local/state/chess-review-notifier/USERNAME.json` |
| `--timeout SECONDS` | HTTP socket timeout | `20` |
| `--notify-timeout SECONDS` | Sender command timeout | `30` |
| `--notify-command COMMAND ...` | Run a sender; put this flag last | Print links |
| `-h`, `--help` | Show help | |

Keep the same state file across restarts so previously reported games stay marked as seen.

## Example — Hermes notifications

```sh
python3 chess_review_notifier.py USERNAME \
  --notify-command hermes send --to telegram:123456789 \
  '[Review your game]({url})'
```

For background operation, run the command with launchd on macOS or systemd on Linux. On macOS, enable `RunAtLoad` and `KeepAlive` in the LaunchAgent plist.

[Testing](TESTING.md)

## Requirements

Python 3.9+ · Linux / macOS
