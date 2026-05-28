# claude-statusline

A compact, two-line [status line](https://docs.claude.com/en/docs/claude-code/statusline)
for Claude Code. Claude Code pipes a JSON status payload to the configured
command on stdin; this script renders it as:

```
ctx ██████░░░░░░░░░░░░░░░░░░ 24% (48k/200k)  ·  Claude Opus 4.7
5h 35% (↻ 2.0h)  ·  7d 70% (↻ 5.1d)  ·  API est. $12.34  ·  session 3h 12m
```

- **Line 1** — context-window usage (progress bar + %, with token counts) and
  the active model. The bar turns green / yellow / red as usage climbs.
- **Line 2** — rate-limit usage for the 5-hour and 7-day windows (each with the
  time remaining until it resets), the API-equivalent cost estimate, and the
  session wall-clock duration.

Sections are omitted gracefully when the corresponding data is absent (e.g.
rate limits only appear for Pro/Max subscribers, and the context line shows
`ctx (no messages yet)` before the first turn).

## About the cost figure

`API est.` is `cost.total_cost_usd`: the client-side *pay-as-you-go,
API-equivalent estimate* — **not** the actual bill of a flat-rate
subscription. For subscribers the rate-limit percentages are the meaningful
budget signal, which is why the cost is explicitly labelled as an estimate.

## Install

Point the `statusLine` command in `~/.claude/settings.json` at the script,
using the absolute path to `statusline.py` on your machine:

```json
{
  "statusLine": {
    "type": "command",
    "command": "python \"E:\\usr\\workspaces\\claude-extensions\\claude-statusline\\statusline.py\""
  }
}
```

The script forces UTF-8 output (the bar uses block characters that the default
Windows console encoding cannot encode) and tolerates a leading BOM on stdin.

## Tests

The pure formatting helpers (`make_bar`, `format_duration`, `reset_in`,
`human_tokens`, `color_for_pct`) and the stdin/stdout edge cases of `main()`
are covered by a pytest suite:

```
python -m pytest
```
