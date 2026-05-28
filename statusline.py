#!/usr/bin/env python3
"""
Claude Code status line — two compact lines.

Line 1:  context-window usage (bar + %)   ·   model name
Line 2:  rate-limit usage (5h / 7d)        ·   estimated API cost

The cost shown is `cost.total_cost_usd`: the client-side *pay-as-you-go
API-equivalent estimate*, NOT the actual bill of a flat-rate
subscription. It is labelled "API est." to make that explicit — for a
subscriber the rate-limit percentages are the meaningful budget signal.
"""

import json
import sys
import time

# ── ANSI codes ──────────────────────────────────────────────────────────────
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"

BAR_WIDTH = 24
SEP = f"  {DIM}·{RESET}  "  # dim middle-dot separator


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


def reset_in(epoch_secs: float, now: float) -> str:
    """Indicative time left until a rate-limit window resets.

    Uses a single largest unit with one decimal: '5.0d', '2.8h' or '47m'.
    Returns "" when the timestamp is missing or already in the past, so the
    percentage can be shown without a stale countdown.
    """
    if not epoch_secs:
        return ""
    secs = epoch_secs - now
    if secs <= 0:
        return ""
    days = secs / 86400.0
    if days >= 1:
        return f"{days:.1f}d"
    hours = secs / 3600.0
    if hours >= 1:
        return f"{hours:.1f}h"
    return f"{secs / 60.0:.0f}m"


def human_tokens(n: float) -> str:
    """Compact token count: 950, '8.5k', '142k'."""
    n = int(n)
    if n < 1000:
        return str(n)
    if n < 10000:
        return f"{n / 1000:.1f}k"
    return f"{n / 1000:.0f}k"


def main() -> None:
    # Force UTF-8 output: the bar uses block characters the default
    # Windows console encoding (cp1252) cannot encode, which would crash
    # `print` and produce no status line at all.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

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

    # ── Line 1: context + model ──────────────────────────────────────────────
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
            ctx += f" {DIM}({size}){RESET}"
    else:
        ctx = f"{DIM}ctx (no messages yet){RESET}"
    line1 = ctx + SEP + f"{CYAN}{BOLD}{model}{RESET}"

    # ── Line 2: rate limits + estimated cost ─────────────────────────────────
    parts = []
    if five_h is not None:
        c = color_for_pct(five_h)
        part = f"{DIM}5h{RESET} {c}{five_h:.0f}%{RESET}"
        rem = reset_in(five_h_reset, now)
        if rem:
            part += f" {DIM}(↻ {rem}){RESET}"
        parts.append(part)
    if seven_d is not None:
        c = color_for_pct(seven_d)
        part = f"{DIM}7d{RESET} {c}{seven_d:.0f}%{RESET}"
        rem = reset_in(seven_d_reset, now)
        if rem:
            part += f" {DIM}(↻ {rem}){RESET}"
        parts.append(part)
    if cost_raw is not None:
        try:
            parts.append(
                f"{DIM}API est.{RESET} {MAGENTA}${float(cost_raw):,.2f}{RESET}"
            )
        except (TypeError, ValueError):
            pass
    if duration_ms is not None:
        try:
            parts.append(
                f"{DIM}session{RESET} {BOLD}{format_duration(float(duration_ms))}{RESET}"
            )
        except (TypeError, ValueError):
            pass
    line2 = SEP.join(parts) if parts else f"{DIM}(no rate-limit / cost data){RESET}"

    print(line1)
    print(line2)


if __name__ == "__main__":
    main()
