# chess-review-notifier

Watch a Chess.com account and get a [Peck](https://peckchess.com) review link after each game.

## Run

Requires Python 3.9+ on Linux or macOS. No extra packages or Chess.com login needed.

```sh
git clone https://github.com/will-lynas/chess-review-notifier.git
cd chess-review-notifier
python3 chess_review_notifier.py sample-player
```

Replace `sample-player` with your username. The first run skips existing games. Leave it running to print links for new games, or stop it with Ctrl-C.

It checks every 10 seconds after the previous poll finishes. Chess.com's API can lag behind, so links may take longer to arrive.

## Notifications

Pass a command to send each link wherever you want:

```sh
python3 chess_review_notifier.py sample-player --notify-command /path/to/your-sender '{url}'
```

Put `--notify-command` last. The script replaces `{url}` with the review link and also passes it on stdin. Arguments run without a shell. Your sender should exit zero on success; failures are retried. A timeout or crash after sending can cause a duplicate.

## Options

- `--interval 30`: wait 30 seconds between polls instead of 10.
- `--once`: check once and exit.
- `--state ./state/player.json`: choose where progress is saved. The default is `~/.local/state/chess-review-notifier/USERNAME.json`.
- `--help`: show all options.

Keep the same state file across restarts so previously reported games stay marked as seen.

[Testing](TESTING.md)
