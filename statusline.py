#!/usr/bin/env python3
"""
Claude Code status line — compact, with a configurable layout.

The layout comes from the CLAUDE_STATUSLINE_LAYOUT environment variable
(see DEFAULT_LAYOUT and FIELDS). The default renders two lines:

Line 1:  context-window usage (bar + %)   │   session duration   │   model name
Line 2:  rate-limit usage (5h / 7d)        │   estimated API cost
         each window: "7d 70% (↻ 5.1d · ⇲ 19.5h)" — reset countdown and the
         estimated time until the budget hits 100% at the current pace
         (the 5h window shows only the countdown by default)

The cost shown is `cost.total_cost_usd`: the client-side *pay-as-you-go
API-equivalent estimate*, NOT the actual bill of a flat-rate
subscription. It is labelled "API est." to make that explicit — for a
subscriber the rate-limit percentages are the meaningful budget signal.
"""

import contextlib
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

__version__ = "1.4.0"

# ── ANSI codes ──────────────────────────────────────────────────────────────
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"

BAR_WIDTH = 24
SEP = f" {BLUE}│{RESET} "  # blue vertical-bar separator

# Rate-limit window lengths, matching the "5h" / "7d" labels.
FIVE_HOUR_SECS = 5 * 3600
SEVEN_DAY_SECS = 7 * 86400

# ── Layout ──────────────────────────────────────────────────────────────────
# Fields separated by whitespace, "/" starts a new line, "field:opt,opt"
# selects the parts of a composite field (no options = its default parts).
LAYOUT_ENV = "CLAUDE_STATUSLINE_LAYOUT"
DEFAULT_LAYOUT = "ctx session model / 5h:reset 7d cost"

# Field name -> its options, in rendering order. Every option is a default
# part; a field with no options accepts none.
FIELDS: dict[str, tuple[str, ...]] = {
    "ctx": ("bar", "pct", "tokens"),
    "session": (),
    "model": (),
    "5h": ("reset", "cap"),
    "7d": ("reset", "cap"),
    "cost": (),
}


def make_bar(pct: float, width: int = BAR_WIDTH) -> str:
    """Return a block-character progress bar like ██████░░░░░░░░ ."""
    filled = int(round(pct / 100.0 * width))
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def color_for_pct(pct: float) -> str:
    """Green when low, yellow when moderate, red when high."""
    if pct >= 85:
        return RED
    if pct >= 60:
        return YELLOW
    return GREEN


def format_duration(ms: float) -> str:
    """Adaptive wall-clock duration: '5m', '3h 12m' or '10d 21h'."""
    secs = int(ms) // 1000
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def format_eta(secs: float) -> str:
    """Single largest unit with one decimal: '5.0d', '2.8h' or '47m'."""
    days = secs / 86400.0
    if days >= 1:
        return f"{days:.1f}d"
    hours = secs / 3600.0
    if hours >= 1:
        return f"{hours:.1f}h"
    return f"{secs / 60.0:.0f}m"


def reset_in(epoch_secs: float | None, now: float) -> str:
    """Indicative time left until a rate-limit window resets.

    Formatted by `format_eta`. Returns "" when the timestamp is missing or
    already in the past, so the percentage can be shown without a stale
    countdown.
    """
    if not epoch_secs:
        return ""
    secs = epoch_secs - now
    if secs <= 0:
        return ""
    return format_eta(secs)


def time_to_cap(
    used: float, resets_at: float | None, window_secs: float, now: float
) -> float | None:
    """Seconds until a rate-limit window hits 100% at the average pace so far.

    Linear extrapolation since the window opened:
        elapsed     = window_secs - (resets_at - now)
        time_to_cap = (100 - used) / used * elapsed

    Returns None when there is no reliable estimate: no usage yet, already at
    the cap, `resets_at` missing or in the past, or nothing elapsed (e.g.
    clock skew pushing `resets_at` beyond the window length).
    """
    if used <= 0 or used >= 100 or not resets_at:
        return None
    to_reset = resets_at - now
    if to_reset <= 0:
        return None
    elapsed = window_secs - to_reset
    if elapsed <= 0:
        return None
    return (100 - used) / used * elapsed


def color_for_ratio(ratio: float) -> str:
    """Traffic light for time_to_cap / time_to_reset.

    Red when the cap comes before the reset, yellow when the cap lands less
    than 25% of the time-to-reset after the reset (at the current pace, more
    than 80% of the *remaining* budget is used before the reset), green
    otherwise (at most 80% of the remaining budget).
    """
    if ratio < 1:
        return RED
    if ratio < 1.25:
        return YELLOW
    return GREEN


def rate_limit_part(
    label: str,
    used: float,
    resets_at: float | None,
    window_secs: float,
    now: float,
    reset: bool = True,
    cap: bool = True,
) -> str:
    """Render one window: usage %, reset countdown and time to cap.

    `reset` / `cap` select the bracketed parts; a part without data is
    skipped, and the brackets go away when none is left.
    """
    part = f"{DIM}{label}{RESET} {color_for_pct(used)}{used:.0f}%{RESET}"
    extras = []
    rem = reset_in(resets_at, now)
    if reset and rem:
        # Plain countdown like the session duration.
        extras.append(f"↻ {rem}")
    ttc = time_to_cap(used, resets_at, window_secs, now)
    if cap and ttc is not None and resets_at is not None:
        # ⇲ shares its value's colour.
        c = color_for_ratio(ttc / (resets_at - now))
        extras.append(f"{c}⇲ {format_eta(ttc)}{RESET}")
    if not extras:
        return part
    inner = f"{DIM} · {RESET}".join(extras)
    return part + f" {DIM}({RESET}{inner}{DIM}){RESET}"


def human_tokens(n: float) -> str:
    """Compact token count: 950, '8.5k', '142k'."""
    n = int(n)
    if n < 1000:
        return str(n)
    if n < 10000:
        return f"{n / 1000:.1f}k"
    return f"{n / 1000:.0f}k"


@dataclass
class Status:
    """The subset of the status payload the fields render; None = no data."""

    used_pct: float | None = None
    tokens_used: float | None = None
    cw_size: float | None = None
    model: str = "unknown model"
    five_h: float | None = None
    five_h_reset: float | None = None
    seven_d: float | None = None
    seven_d_reset: float | None = None
    cost_usd: float | None = None
    duration_ms: float | None = None


def _to_float(value: Any) -> float | None:
    """float(value), or None when it is missing, not a number or not finite.

    The payload is not trusted: a string, NaN or an infinity must not crash
    the status line, so such a value counts as "no data".
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_status(data: dict[str, Any]) -> Status:
    """Extract the rendered fields from the JSON payload Claude Code sends."""
    # ── Context window ───────────────────────────────────────────────────────
    cw = data.get("context_window", {}) or {}
    tokens_used = _to_float(cw.get("total_input_tokens"))
    cw_size = _to_float(cw.get("context_window_size"))
    used_pct = _to_float(cw.get("used_percentage"))
    if used_pct is None and tokens_used is not None and cw_size:
        used_pct = tokens_used / cw_size * 100.0

    # ── Model ────────────────────────────────────────────────────────────────
    model_info = data.get("model", {}) or {}
    model = model_info.get("display_name") or model_info.get("id") or "unknown model"

    # ── Rate limits (present only for Pro/Max subscribers) ───────────────────
    rl = data.get("rate_limits", {}) or {}
    five_h = rl.get("five_hour", {}) or {}
    seven_d = rl.get("seven_day", {}) or {}

    # ── Cost — API-equivalent estimate, not the real subscription bill ───────
    cost = data.get("cost") or {}

    return Status(
        used_pct=used_pct,
        tokens_used=tokens_used,
        cw_size=cw_size,
        model=model,
        five_h=_to_float(five_h.get("used_percentage")),
        five_h_reset=_to_float(five_h.get("resets_at")),
        seven_d=_to_float(seven_d.get("used_percentage")),
        seven_d_reset=_to_float(seven_d.get("resets_at")),
        cost_usd=_to_float(cost.get("total_cost_usd")),
        duration_ms=_to_float(cost.get("total_duration_ms")),
    )


def parse_layout(layout: str) -> list[list[str]]:
    """Split a layout string into lines of field tokens.

    "/" separates lines and whitespace separates fields, so extra spaces and
    empty lines (leading, trailing or repeated "/") are ignored. A layout with
    no fields at all (unset, blank, only "/") falls back to DEFAULT_LAYOUT.
    """
    lines = [line.split() for line in layout.split("/")]
    lines = [tokens for tokens in lines if tokens]
    return lines or parse_layout(DEFAULT_LAYOUT)


def context_part(status: Status, opts: set[str]) -> str | None:
    """Render the context window with the selected parts (bar, pct, tokens)."""
    if status.used_pct is None:
        return f"{DIM}ctx (no messages yet){RESET}"
    c = color_for_pct(status.used_pct)
    parts = []
    if "bar" in opts:
        parts.append(f"{c}{make_bar(status.used_pct)}{RESET}")
    if "pct" in opts:
        parts.append(f"{BOLD}{c}{status.used_pct:.0f}%{RESET}")
    if "tokens" in opts and status.tokens_used is not None:
        size = human_tokens(status.tokens_used)
        if status.cw_size:
            size += f"/{human_tokens(status.cw_size)}"
        # Bracketed as a detail of the bar / %; bare when shown alone.
        parts.append(f"{DIM}({RESET}{size}{DIM}){RESET}" if parts else size)
    if not parts:
        return None
    return f"{DIM}ctx{RESET} " + " ".join(parts)


def render_field(token: str, status: Status, now: float) -> str | None:
    """Render one layout token, or None when its field has no data.

    An unknown field, an unknown option, options on a field that takes none,
    or an empty option list render the whole token as a red "?token", so a
    typo shows up in place instead of being silently dropped.
    """
    name, colon, opts_text = token.partition(":")
    allowed = FIELDS.get(name)
    if allowed is None:
        return f"{RED}?{token}{RESET}"
    opts = set(allowed)
    if colon:
        # Stray commas are tolerated; repeated options are merged.
        opts = {opt for opt in opts_text.split(",") if opt}
        if not opts or not opts <= set(allowed):
            return f"{RED}?{token}{RESET}"

    if name == "ctx":
        return context_part(status, opts)
    if name == "session":
        if status.duration_ms is None:
            return None
        return f"{DIM}session{RESET} {format_duration(status.duration_ms)}"
    if name == "model":
        return f"{CYAN}{BOLD}{status.model}{RESET}"
    if name in ("5h", "7d"):
        if name == "5h":
            used, resets_at, window = status.five_h, status.five_h_reset, FIVE_HOUR_SECS
        else:
            used, resets_at, window = (
                status.seven_d,
                status.seven_d_reset,
                SEVEN_DAY_SECS,
            )
        if used is None:
            return None
        return rate_limit_part(
            name,
            used,
            resets_at,
            window,
            now,
            reset="reset" in opts,
            cap="cap" in opts,
        )
    if name == "cost":
        if status.cost_usd is None:
            return None
        return f"{DIM}API est.{RESET} {MAGENTA}${status.cost_usd:,.2f}{RESET}"
    # Every FIELDS entry needs a branch above; fail loudly in the tests.
    raise AssertionError(f"no renderer for field {name!r}")


def render(status: Status, layout: str, now: float) -> list[str]:
    """Render the status line, one string per output line.

    Fields without data are omitted together with their separator, and a
    line with nothing to show is dropped — possibly every line, in which
    case the status line is simply blank.
    """
    lines = []
    for tokens in parse_layout(layout):
        parts = [
            part
            for token in tokens
            if (part := render_field(token, status, now)) is not None
        ]
        if parts:
            lines.append(SEP.join(parts))
    return lines


def main() -> None:
    if "--version" in sys.argv[1:] or "-V" in sys.argv[1:]:
        print(f"claude-statusline {__version__}")
        return

    # Force UTF-8 output: the bar uses block characters the default
    # Windows console encoding (cp1252) cannot encode, which would crash
    # `print` and produce no status line at all.
    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    # Read stdin as raw bytes and decode with utf-8-sig so a leading BOM
    # (some shells add one when piping) does not break the JSON parse.
    raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    layout = os.environ.get(LAYOUT_ENV, "")
    for line in render(parse_status(data), layout, time.time()):
        print(line)


if __name__ == "__main__":
    main()
