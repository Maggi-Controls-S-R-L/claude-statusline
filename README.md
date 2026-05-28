# claude-statusline

[![CI](https://github.com/Maggi-Controls-S-R-L/claude-statusline/actions/workflows/ci.yml/badge.svg)](https://github.com/Maggi-Controls-S-R-L/claude-statusline/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%E2%80%933.13-blue.svg)](https://www.python.org/)

A compact, two-line [status line](https://code.claude.com/docs/en/statusline)
for Claude Code. Claude Code pipes a JSON status payload to the configured
command on stdin; this script renders it as:

```
ctx ██████░░░░░░░░░░░░░░░░░░ 24% (48k/200k)  ·  Claude Opus 4.7
5h 35% (↻ 2.0h)  ·  7d 70% (↻ 5.1d)  ·  API est. $12.34  ·  session 3h 12m
```

## Features

- **Context-window bar** that turns green → yellow → red as usage climbs, with
  compact token counts (`48k/200k`).
- **Active model** name.
- **Rate-limit usage** for the rolling 5-hour and 7-day windows, each with the
  time remaining until it resets.
- **API-equivalent cost estimate** and **session wall-clock duration**.
- **Graceful degradation** — sections are omitted when their data is absent
  (rate limits only appear for Pro/Max subscribers; the context line shows
  `ctx (no messages yet)` before the first turn).
- **UTF-8 / BOM-safe** — forces UTF-8 output (the bar uses block characters the
  default Windows console encoding cannot encode) and tolerates a leading BOM
  on stdin.
- **Zero dependencies** — pure Python standard library.

## What it shows

- **Line 1** — context-window usage (bar + %, with token counts) and the active model.
- **Line 2** — rate-limit usage (5h / 7d, with reset countdowns), the cost
  estimate, and the session duration.

## About the cost figure

`API est.` is `cost.total_cost_usd`: the client-side *pay-as-you-go,
API-equivalent estimate* — **not** the actual bill of a flat-rate subscription.
For subscribers the rate-limit percentages are the meaningful budget signal,
which is why the cost is explicitly labelled as an estimate.

## Installation

### Option A — install as a command (recommended)

```sh
pipx install git+https://github.com/Maggi-Controls-S-R-L/claude-statusline
```

Then point the `statusLine` command in `~/.claude/settings.json` at the
installed entry point:

```json
{
  "statusLine": {
    "type": "command",
    "command": "claude-statusline"
  }
}
```

### Option B — run the script directly

Clone the repository and reference `statusline.py` by its absolute path:

```json
{
  "statusLine": {
    "type": "command",
    "command": "python \"/absolute/path/to/claude-statusline/statusline.py\""
  }
}
```

## Status line schema

The script reads the JSON object Claude Code writes to stdin, documented at
<https://code.claude.com/docs/en/statusline>. It consumes a subset of the
fields:

- `context_window.total_input_tokens`, `context_window.context_window_size`,
  `context_window.used_percentage`
- `model.display_name` (falling back to `model.id`)
- `rate_limits.five_hour` / `rate_limits.seven_day` — `used_percentage`, `resets_at`
- `cost.total_cost_usd`, `cost.total_duration_ms`

Unrecognised fields are ignored, so the script keeps working as the schema grows.

## Development

```sh
python -m pip install -U pip        # pip >= 25.1 for --group
pip install -e . --group dev
ruff check .
ruff format --check .
mypy statusline.py
```

## Testing

The project uses **pytest**. The suite covers the pure formatting helpers
(`make_bar`, `format_duration`, `reset_in`, `human_tokens`, `color_for_pct`)
and the stdin/stdout edge cases of `main()` (BOM input, missing or past
`resets_at`, `None` percentages, invalid JSON):

```sh
pytest
```

## License

[MIT](LICENSE) © Maggi Controls S.R.L.
