#!/usr/bin/env python3
"""
Claude Code status line — two compact lines.

Line 1:  context-window usage (bar + %)   │   session duration   │   model name
Line 2:  rate-limit usage (5h / 7d)        │   estimated API cost
         each window: "5h 35% (↻ 2.0h · ⇲ 5.6h)" — reset countdown and the
         estimated time until the budget hits 100% at the current pace

The cost shown is `cost.total_cost_usd`: the client-side *pay-as-you-go
API-equivalent estimate*, NOT the actual bill of a flat-rate
subscription. It is labelled "API est." to make that explicit — for a
subscriber the rate-limit percentages are the meaningful budget signal.
"""

import contextlib
import json
import sys
import time

__version__ = "1.2.0"

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
) -> str:
    """Render one window: usage %, reset countdown and time to cap."""
    part = f"{DIM}{label}{RESET} {color_for_pct(used)}{used:.0f}%{RESET}"
    rem = reset_in(resets_at, now)
    if not rem:
        return part
    # Plain countdown like the session duration; ⇲ shares its value's colour.
    countdown = f"↻ {rem}"
    ttc = time_to_cap(used, resets_at, window_secs, now)
    if ttc is None or resets_at is None:
        return part + f" {DIM}({RESET}{countdown}{DIM}){RESET}"
    c = color_for_ratio(ttc / (resets_at - now))
    cap = f"{c}⇲ {format_eta(ttc)}{RESET}"
    return part + f" {DIM}({RESET}{countdown}{DIM} · {RESET}{cap}{DIM}){RESET}"


def human_tokens(n: float) -> str:
    """Compact token count: 950, '8.5k', '142k'."""
    n = int(n)
    if n < 1000:
        return str(n)
    if n < 10000:
        return f"{n / 1000:.1f}k"
    return f"{n / 1000:.0f}k"


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

    # ── Context window ───────────────────────────────────────────────────────
    cw = data.get("context_window", {}) or {}
    tokens_used = cw.get("total_input_tokens")
    cw_size = cw.get("context_window_size")
    used_pct = cw.get("used_percentage")
    if used_pct is None and tokens_used is not None and cw_size:
        used_pct = tokens_used / cw_size * 100.0

    # ── Model ────────────────────────────────────────────────────────────────
    model_info = data.get("model", {}) or {}
    model = model_info.get("display_name") or model_info.get("id") or "unknown model"

    # ── Rate limits (present only for Pro/Max subscribers) ───────────────────
    rl = data.get("rate_limits", {}) or {}
    five_h = (rl.get("five_hour", {}) or {}).get("used_percentage")
    five_h_reset = (rl.get("five_hour", {}) or {}).get("resets_at")
    seven_d = (rl.get("seven_day", {}) or {}).get("used_percentage")
    seven_d_reset = (rl.get("seven_day", {}) or {}).get("resets_at")
    now = time.time()

    # ── Cost — API-equivalent estimate, not the real subscription bill ───────
    cost = data.get("cost") or {}
    cost_raw = cost.get("total_cost_usd")
    duration_ms = cost.get("total_duration_ms")

    # ── Line 1: context + session duration + model ───────────────────────────
    if used_pct is not None:
        c = color_for_pct(used_pct)
        ctx = (
            f"{DIM}ctx{RESET} {c}{make_bar(used_pct)}{RESET} "
            f"{BOLD}{c}{used_pct:.0f}%{RESET}"
        )
        if tokens_used is not None:
            size = human_tokens(tokens_used)
            if cw_size:
                size += f"/{human_tokens(cw_size)}"
            ctx += f" {DIM}({RESET}{size}{DIM}){RESET}"
    else:
        ctx = f"{DIM}ctx (no messages yet){RESET}"
    line1_parts = [ctx]
    if duration_ms is not None:
        with contextlib.suppress(TypeError, ValueError):
            dur = format_duration(float(duration_ms))
            line1_parts.append(f"{DIM}session{RESET} {dur}")
    line1_parts.append(f"{CYAN}{BOLD}{model}{RESET}")
    line1 = SEP.join(line1_parts)

    # ── Line 2: rate limits + estimated cost ─────────────────────────────────
    parts = []
    if five_h is not None:
        parts.append(rate_limit_part("5h", five_h, five_h_reset, FIVE_HOUR_SECS, now))
    if seven_d is not None:
        parts.append(rate_limit_part("7d", seven_d, seven_d_reset, SEVEN_DAY_SECS, now))
    if cost_raw is not None:
        with contextlib.suppress(TypeError, ValueError):
            parts.append(
                f"{DIM}API est.{RESET} {MAGENTA}${float(cost_raw):,.2f}{RESET}"
            )
    line2 = SEP.join(parts) if parts else f"{DIM}(no rate-limit / cost data){RESET}"

    print(line1)
    print(line2)


if __name__ == "__main__":
    main()
