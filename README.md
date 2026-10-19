# claude-statusline

[![CI](https://github.com/Maggi-Controls-S-R-L/claude-statusline/actions/workflows/ci.yml/badge.svg)](https://github.com/Maggi-Controls-S-R-L/claude-statusline/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%E2%80%933.13-blue.svg)](https://www.python.org/)

A compact [status line](https://code.claude.com/docs/en/statusline) for Claude
Code. Claude Code pipes a JSON status payload to the configured command on
stdin; with the default layout this script renders it as:

```
ctx ██████░░░░░░░░░░░░░░░░░░ 24% (48k/200k) │ session 3h 12m │ Claude Opus 4.7
5h 35% (↻ 2.0h) │ 7d 70% (↻ 5.1d · ⇲ 19.5h) │ API est. $12.34
```

## Features

- **Context-window bar** that turns green → yellow → red as usage climbs, with
  compact token counts (`48k/200k`).
- **Session wall-clock duration** and the **active model** name.
- **Rate-limit usage** for the rolling 5-hour and 7-day windows, each with the
  time remaining until it resets (`↻`) and, by default on the 7-day window
  only, a colour-coded estimate of when the budget runs out at the current
  pace (`⇲`).
- **API-equivalent cost estimate**.
- **Configurable layout** — choose the fields, their order and the number of
  lines with one environment variable (see
  [Configuring the layout](#configuring-the-layout)).
- **Graceful degradation** — sections are omitted when their data is absent
  (rate limits only appear for Pro/Max subscribers; the context line shows
  `ctx (no messages yet) │ session 0m │ <model>` before the first turn).
- **UTF-8 / BOM-safe** — forces UTF-8 output (the bar uses block characters the
  default Windows console encoding cannot encode) and tolerates a leading BOM
  on stdin.
- **Zero dependencies** — pure Python standard library.

## What it shows

With the default layout, fields are grouped by topic:

- **Line 1 — the session:** context-window usage (bar + %, with token counts),
  the session duration, and the active model. The session segment is omitted
  when `cost.total_duration_ms` is absent.
- **Line 2 — the budget:** rate-limit usage (5h with its reset countdown, 7d
  with its reset countdown and time-to-cap estimate) and the API-equivalent
  cost estimate. The line is omitted when none of these are available.

## Configuring the layout

The fields, their order and the number of lines are set by the
`CLAUDE_STATUSLINE_LAYOUT` environment variable. When it is unset or blank,
the default applies:

```
ctx session model / 5h:reset 7d cost
```

Syntax:

- **Fields** are separated by whitespace; the ` │ ` separator is inserted
  between the fields that render.
- **`/`** starts a new line, so a layout can have one, two or more lines.
- **`field:opt,opt`** selects the parts of a composite field; a field without
  options shows its default parts. The parts always render in the order of the
  table below, whatever the order of the options.

| Field     | Shows                          | Options                | Default parts  |
| --------- | ------------------------------ | ---------------------- | -------------- |
| `ctx`     | context-window usage           | `bar`, `pct`, `tokens` | all            |
| `session` | session duration               | —                      | —              |
| `model`   | active model                   | —                      | —              |
| `5h`      | 5-hour rate-limit usage        | `reset`, `cap`         | `reset`, `cap` |
| `7d`      | 7-day rate-limit usage         | `reset`, `cap`         | `reset`, `cap` |
| `cost`    | API-equivalent cost estimate   | —                      | —              |

`reset` is the countdown to the window reset (`↻`), `cap` the time-to-cap
estimate (`⇲`); the usage percentage is always shown. The default layout
picks `5h:reset`: on a window of at most five hours the percentage already
says most of it, and the average-pace extrapolation is noisy. The layout
before version 1.4 is one string away: `ctx session model / 5h 7d cost`.

Behaviour:

- Fields without data are omitted together with their separator, and a line
  with nothing to show is dropped. Before the first message `ctx` reads
  `ctx (no messages yet)`. If no field of the layout has data, the status line
  is blank.
- The status line never fails on a bad layout: an unknown field, an unknown
  option, options on a field that takes none, or an empty option list (`5h:`)
  render the whole token as a red `?token` in its position, so a typo is
  visible instead of silently ignored. Field and option names are lowercase.
- Extra whitespace and empty lines (leading, trailing or repeated `/`) are
  ignored; a field listed twice is shown twice.

Set the variable in the `env` block of the Claude Code settings, for example
globally in `~/.claude/settings.json`:

```json
{
  "env": { "CLAUDE_STATUSLINE_LAYOUT": "ctx session model / 5h:reset 7d cost" }
}
```

Claude Code passes `env` variables to the status line command and picks up
changes live, without restarting the session. `env` is merged **per key**
across settings scopes, so a project can override just the layout in its
`.claude/settings.local.json` and keep every other variable from the global
settings:

```json
{
  "env": { "CLAUDE_STATUSLINE_LAYOUT": "ctx model / 5h:reset,cap 7d" }
}
```

The override is independent of the `statusLine` block: it needs only that
key, and applies whichever command `statusLine` runs.

## About the time-to-cap estimate

`⇲` answers *"at this pace, when do I hit the limit?"* for each rate-limit
window. It is a linear extrapolation of the **average pace since the window
opened**, computed from `used_percentage`, `resets_at` and the current time:

```
elapsed     = window_length − (resets_at − now)
time_to_cap = (100 − used) / used × elapsed
```

The window lengths are fixed at **5 hours** and **7 days**, matching the `5h` /
`7d` labels. The value uses the same format as the reset countdown and is
shown even when it lands after the reset, where it tells how much headroom is
left. Its colour compares it with the time left until the reset
(`r = time_to_cap / time_to_reset`):

| Colour | Condition       | Meaning                                           |
| ------ | --------------- | ------------------------------------------------- |
| red    | `r < 1`         | the budget runs out before the reset              |
| yellow | `1 ≤ r < 1.25`  | reaches the reset, but uses >80% of what is left  |
| green  | `r ≥ 1.25`      | uses at most 80% of what is left before the reset |

It is an estimate, not a forecast: bursty usage early in a window makes it
noisy, and no minimum-elapsed threshold hides that. The field is omitted when
usage is `0` or already `100%`, when `resets_at` is missing or past, or when
no time has elapsed in the window (e.g. clock skew).

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

Verify the install with `claude-statusline --version`.

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

### Tip — keep time-based fields live while idle

By default Claude Code re-runs the status line only on events (a new message,
`/compact`, a permission change). The session duration, the reset
countdowns and the time-to-cap estimates therefore freeze whenever the session
sits idle. Add the optional `refreshInterval` field to also re-run the command
on a fixed timer:

```json
{
  "statusLine": {
    "type": "command",
    "command": "claude-statusline",
    "refreshInterval": 60
  }
}
```

`60` (seconds) is the sweet spot: the finest field shown is the session
duration in whole minutes, so refreshing more often just redraws identical
output, while refreshing less often lets the minute counter lag. The script is
pure standard library with no subprocess calls, so a once-a-minute refresh is
negligible.

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

## Contributing

Development setup, checks, the branching and TDD workflow, previewing your
changes live in Claude Code, and the release process are described in
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © Maggi Controls S.R.L.
