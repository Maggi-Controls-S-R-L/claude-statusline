"""Tests for the pure helpers and the stdin/stdout edge cases of statusline.py."""

import io
import json
import re
import sys

import pytest

import statusline
from statusline import (
    FIVE_HOUR_SECS,
    SEVEN_DAY_SECS,
    color_for_pct,
    color_for_ratio,
    format_duration,
    human_tokens,
    make_bar,
    reset_in,
    time_to_cap,
)


# ── make_bar ──────────────────────────────────────────────────────────────
class TestMakeBar:
    def test_empty(self):
        assert make_bar(0) == "░" * 24

    def test_full(self):
        assert make_bar(100) == "█" * 24

    def test_half_default_width(self):
        # round(0.5 * 24) = 12
        assert make_bar(50) == "█" * 12 + "░" * 12

    def test_half_custom_width(self):
        assert make_bar(50, width=10) == "█" * 5 + "░" * 5

    def test_over_100_is_clamped(self):
        assert make_bar(150) == "█" * 24

    def test_negative_is_clamped(self):
        assert make_bar(-20) == "░" * 24

    @pytest.mark.parametrize("pct", [0, 13, 37, 64, 99, 100])
    def test_length_always_equals_width(self, pct):
        assert len(make_bar(pct, width=24)) == 24


# ── format_duration ───────────────────────────────────────────────────────
class TestFormatDuration:
    def test_minutes_only(self):
        assert format_duration(5 * 60 * 1000) == "5m"

    def test_hours_and_minutes(self):
        assert format_duration((3 * 3600 + 12 * 60) * 1000) == "3h 12m"

    def test_days_and_hours(self):
        assert format_duration((10 * 86400 + 21 * 3600) * 1000) == "10d 21h"

    def test_zero(self):
        assert format_duration(0) == "0m"

    def test_sub_minute_floors_to_zero(self):
        assert format_duration(30 * 1000) == "0m"

    def test_exactly_one_hour(self):
        assert format_duration(3600 * 1000) == "1h 0m"

    def test_exactly_one_day(self):
        assert format_duration(86400 * 1000) == "1d 0h"

    def test_float_ms_is_truncated(self):
        assert format_duration(300000.9) == "5m"


# ── reset_in ──────────────────────────────────────────────────────────────
class TestResetIn:
    def test_missing_zero_timestamp(self):
        assert reset_in(0, now=1000) == ""

    def test_missing_none_timestamp(self):
        assert reset_in(None, now=1000) == ""

    def test_in_the_past(self):
        assert reset_in(500, now=1000) == ""

    def test_exactly_now(self):
        assert reset_in(1000, now=1000) == ""

    def test_days(self):
        assert reset_in(2 * 86400, now=0) == "2.0d"

    def test_exactly_one_day(self):
        assert reset_in(86400, now=0) == "1.0d"

    def test_hours(self):
        # 10080 s = 2.8 h
        assert reset_in(10080, now=0) == "2.8h"

    def test_exactly_one_hour(self):
        assert reset_in(3600, now=0) == "1.0h"

    def test_minutes(self):
        assert reset_in(47 * 60, now=0) == "47m"

    def test_just_under_one_hour(self):
        assert reset_in(59 * 60, now=0) == "59m"


# ── time_to_cap ───────────────────────────────────────────────────────────
class TestTimeToCap:
    def test_window_lengths(self):
        assert FIVE_HOUR_SECS == 5 * 3600
        assert SEVEN_DAY_SECS == 7 * 86400

    def test_half_used_at_half_window(self):
        # 50% used after 2.5h of a 5h window -> another 2.5h to the cap.
        assert time_to_cap(50, 9000, FIVE_HOUR_SECS, now=0) == pytest.approx(9000)

    def test_normal_case(self):
        # elapsed = 18000 - 7200 = 10800 s; (100 - 35) / 35 * 10800
        expected = 65 / 35 * 10800
        assert time_to_cap(35, 7200, FIVE_HOUR_SECS, now=0) == pytest.approx(expected)

    def test_now_is_injected(self):
        now = 1_000_000.0
        got = time_to_cap(50, now + 9000, FIVE_HOUR_SECS, now=now)
        assert got == pytest.approx(9000)

    def test_seven_day_window(self):
        # 13% used, 6.4d to reset -> elapsed 0.6d -> 87 / 13 * 0.6d
        resets = 6.4 * 86400
        expected = 87 / 13 * 0.6 * 86400
        got = time_to_cap(13, resets, SEVEN_DAY_SECS, now=0)
        assert got == pytest.approx(expected)

    def test_cap_after_reset_is_still_returned(self):
        # 10% used after 2.5h: cap in 22.5h, well past the reset.
        got = time_to_cap(10, 9000, FIVE_HOUR_SECS, now=0)
        assert got == pytest.approx(81000)

    @pytest.mark.parametrize("used", [0, -5])
    def test_no_usage_is_omitted(self, used):
        assert time_to_cap(used, 9000, FIVE_HOUR_SECS, now=0) is None

    @pytest.mark.parametrize("used", [100, 120])
    def test_at_or_over_cap_is_omitted(self, used):
        assert time_to_cap(used, 9000, FIVE_HOUR_SECS, now=0) is None

    @pytest.mark.parametrize("resets_at", [None, 0])
    def test_missing_reset_is_omitted(self, resets_at):
        assert time_to_cap(35, resets_at, FIVE_HOUR_SECS, now=0) is None

    def test_reset_in_the_past_is_omitted(self):
        assert time_to_cap(35, 500, FIVE_HOUR_SECS, now=1000) is None

    def test_reset_exactly_now_is_omitted(self):
        assert time_to_cap(35, 1000, FIVE_HOUR_SECS, now=1000) is None

    def test_zero_elapsed_is_omitted(self):
        # resets_at exactly one window away -> nothing has elapsed yet.
        assert time_to_cap(35, FIVE_HOUR_SECS, FIVE_HOUR_SECS, now=0) is None

    def test_negative_elapsed_is_omitted(self):
        # resets_at further away than the window length (clock skew).
        assert time_to_cap(35, 20000, FIVE_HOUR_SECS, now=0) is None

    def test_tiny_elapsed_is_not_thresholded(self):
        # No minimum-elapsed threshold: 1 s elapsed still yields an estimate.
        got = time_to_cap(1, FIVE_HOUR_SECS - 1, FIVE_HOUR_SECS, now=0)
        assert got == pytest.approx(99)


# ── color_for_ratio ───────────────────────────────────────────────────────
class TestColorForRatio:
    @pytest.mark.parametrize("ratio", [0, 0.5, 0.999])
    def test_red_when_cap_before_reset(self, ratio):
        assert color_for_ratio(ratio) == statusline.RED

    @pytest.mark.parametrize("ratio", [1, 1.1, 1.249])
    def test_yellow_when_tight(self, ratio):
        assert color_for_ratio(ratio) == statusline.YELLOW

    @pytest.mark.parametrize("ratio", [1.25, 2, 100])
    def test_green_when_comfortable(self, ratio):
        assert color_for_ratio(ratio) == statusline.GREEN


# ── human_tokens ──────────────────────────────────────────────────────────
class TestHumanTokens:
    def test_under_1000(self):
        assert human_tokens(950) == "950"

    def test_zero(self):
        assert human_tokens(0) == "0"

    def test_boundary_999(self):
        assert human_tokens(999) == "999"

    def test_exactly_1000(self):
        assert human_tokens(1000) == "1.0k"

    def test_just_under_10k(self):
        assert human_tokens(8500) == "8.5k"

    def test_boundary_9999_rounds_to_10k(self):
        # 9999 / 1000 = 9.999, formatted with one decimal -> "10.0k"
        assert human_tokens(9999) == "10.0k"

    def test_exactly_10k(self):
        assert human_tokens(10000) == "10k"

    def test_over_10k(self):
        assert human_tokens(142000) == "142k"

    def test_float_is_truncated(self):
        assert human_tokens(8500.9) == "8.5k"


# ── color_for_pct ─────────────────────────────────────────────────────────
class TestColorForPct:
    def test_green_when_low(self):
        assert color_for_pct(0) == statusline.GREEN
        assert color_for_pct(59.9) == statusline.GREEN

    def test_yellow_when_moderate(self):
        assert color_for_pct(60) == statusline.YELLOW
        assert color_for_pct(84.9) == statusline.YELLOW

    def test_red_when_high(self):
        assert color_for_pct(85) == statusline.RED
        assert color_for_pct(100) == statusline.RED


# ── main() — stdin/stdout edge cases ──────────────────────────────────────
class _FakeStdin:
    """Minimal stand-in for sys.stdin exposing a .buffer with raw bytes."""

    def __init__(self, data: bytes):
        self.buffer = io.BytesIO(data)


def run_main(monkeypatch, capsys, raw: bytes) -> str:
    monkeypatch.setattr(sys, "stdin", _FakeStdin(raw))
    statusline.main()
    return capsys.readouterr().out


class TestMain:
    def test_handles_leading_bom(self, monkeypatch, capsys):
        payload = b"\xef\xbb\xbf" + (
            b'{"context_window":{"total_input_tokens":1000,'
            b'"context_window_size":200000},"model":{"display_name":"Test Model"}}'
        )
        out = run_main(monkeypatch, capsys, payload)
        assert "Test Model" in out
        assert "ctx" in out
        assert out.count("\n") == 2  # exactly two printed lines

    def test_invalid_json_exits_zero(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            run_main(monkeypatch, capsys, b"not json at all")
        assert exc.value.code == 0

    def test_empty_stdin_exits_zero(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            run_main(monkeypatch, capsys, b"")
        assert exc.value.code == 0

    def test_none_percentages(self, monkeypatch, capsys):
        payload = (
            b'{"context_window":{"used_percentage":null},"model":{"display_name":"M"}}'
        )
        out = run_main(monkeypatch, capsys, payload)
        assert "no messages yet" in out
        assert "no rate-limit / cost data" in out

    def test_percentage_computed_from_tokens(self, monkeypatch, capsys):
        payload = (
            b'{"context_window":{"total_input_tokens":100000,'
            b'"context_window_size":200000},"model":{"id":"the-model"}}'
        )
        out = run_main(monkeypatch, capsys, payload)
        assert "50%" in out
        assert "the-model" in out  # falls back to model id

    def test_reset_in_past_shows_no_countdown(self, monkeypatch, capsys):
        payload = (
            b'{"rate_limits":{"five_hour":{"used_percentage":35,"resets_at":1000}},'
            b'"model":{"display_name":"M"}}'
        )
        out = run_main(monkeypatch, capsys, payload)
        assert "5h" in out
        assert "35%" in out
        assert "↻" not in out

    def test_reset_in_future_shows_countdown(self, monkeypatch, capsys):
        monkeypatch.setattr(statusline.time, "time", lambda: 1_000_000.0)
        resets = 1_000_000 + 7200  # +2.0h
        payload = (
            f'{{"rate_limits":{{"five_hour":{{"used_percentage":35,"resets_at":{resets}}}}},'
            '"model":{"display_name":"M"}}'
        ).encode()
        out = run_main(monkeypatch, capsys, payload)
        assert "↻ 2.0h" in out

    def test_non_numeric_cost_is_ignored(self, monkeypatch, capsys):
        payload = b'{"cost":{"total_cost_usd":"oops"},"model":{"display_name":"M"}}'
        out = run_main(monkeypatch, capsys, payload)
        assert "API est." not in out

    def test_full_payload(self, monkeypatch, capsys):
        monkeypatch.setattr(statusline.time, "time", lambda: 0.0)
        payload = (
            b'{"context_window":{"total_input_tokens":8500,"context_window_size":200000},'
            b'"model":{"display_name":"Claude Opus 4.7"},'
            b'"rate_limits":{"five_hour":{"used_percentage":35,"resets_at":7200},'
            b'"seven_day":{"used_percentage":70,"resets_at":172800}},'
            b'"cost":{"total_cost_usd":12.34,"total_duration_ms":11520000}}'
        )
        out = run_main(monkeypatch, capsys, payload)
        assert "Claude Opus 4.7" in out
        assert "API est." in out
        assert "$12.34" in out
        assert "session" in out
        assert "3h 12m" in out
        assert "5h" in out
        assert "7d" in out


# ── main() — session duration placement (issue #2) ───────────────────────
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def run_lines(monkeypatch, capsys, raw: bytes) -> tuple[str, str]:
    """Run main() and return its two output lines with ANSI codes stripped."""
    out = run_main(monkeypatch, capsys, raw)
    lines = _ANSI_RE.sub("", out).splitlines()
    assert len(lines) == 2
    return lines[0], lines[1]


class TestSessionPlacement:
    FULL = (
        b'{"context_window":{"total_input_tokens":48000,"context_window_size":200000},'
        b'"model":{"display_name":"Claude Opus 4.7"},'
        b'"rate_limits":{"five_hour":{"used_percentage":35,"resets_at":7200},'
        b'"seven_day":{"used_percentage":70,"resets_at":440640}},'
        b'"cost":{"total_cost_usd":12.34,"total_duration_ms":11520000}}'
    )

    def test_full_payload_layout(self, monkeypatch, capsys):
        monkeypatch.setattr(statusline.time, "time", lambda: 0.0)
        line1, line2 = run_lines(monkeypatch, capsys, self.FULL)
        assert line1 == (
            "ctx " + "█" * 6 + "░" * 18 + " 24% (48k/200k)"
            " │ session 3h 12m │ Claude Opus 4.7"
        )
        assert line2 == (
            "5h 35% (↻ 2.0h · ⇲ 5.6h) │ 7d 70% (↻ 5.1d · ⇲ 19.5h) │ API est. $12.34"
        )

    def test_session_sits_between_context_and_model(self, monkeypatch, capsys):
        monkeypatch.setattr(statusline.time, "time", lambda: 0.0)
        line1, _ = run_lines(monkeypatch, capsys, self.FULL)
        assert line1.index("ctx") < line1.index("session") < line1.index("Claude")

    def test_session_not_on_line_2(self, monkeypatch, capsys):
        monkeypatch.setattr(statusline.time, "time", lambda: 0.0)
        _, line2 = run_lines(monkeypatch, capsys, self.FULL)
        assert "session" not in line2
        assert "3h 12m" not in line2

    def test_session_keeps_dim_label_and_bold_value(self, monkeypatch, capsys):
        payload = (
            b'{"cost":{"total_duration_ms":11520000},"model":{"display_name":"M"}}'
        )
        out = run_main(monkeypatch, capsys, payload)
        line1 = out.splitlines()[0]
        dim, bold, reset = statusline.DIM, statusline.BOLD, statusline.RESET
        assert f"{dim}session{reset} {bold}3h 12m{reset}" in line1

    def test_pre_first_turn(self, monkeypatch, capsys):
        # Before the first turn Claude Code already sends total_duration_ms.
        payload = b'{"model":{"display_name":"M"},"cost":{"total_duration_ms":0}}'
        line1, line2 = run_lines(monkeypatch, capsys, payload)
        assert line1 == "ctx (no messages yet) │ session 0m │ M"
        assert line2 == "(no rate-limit / cost data)"

    def test_missing_duration_omits_segment(self, monkeypatch, capsys):
        payload = b'{"model":{"display_name":"M"},"cost":{"total_cost_usd":1.5}}'
        line1, line2 = run_lines(monkeypatch, capsys, payload)
        assert line1 == "ctx (no messages yet) │ M"
        assert line2 == "API est. $1.50"

    def test_missing_cost_object_omits_segment(self, monkeypatch, capsys):
        payload = b'{"model":{"display_name":"M"}}'
        line1, _ = run_lines(monkeypatch, capsys, payload)
        assert line1 == "ctx (no messages yet) │ M"

    def test_null_duration_omits_segment(self, monkeypatch, capsys):
        payload = b'{"model":{"display_name":"M"},"cost":{"total_duration_ms":null}}'
        line1, _ = run_lines(monkeypatch, capsys, payload)
        assert line1 == "ctx (no messages yet) │ M"

    def test_non_numeric_duration_is_ignored(self, monkeypatch, capsys):
        payload = b'{"model":{"display_name":"M"},"cost":{"total_duration_ms":"oops"}}'
        line1, line2 = run_lines(monkeypatch, capsys, payload)
        assert line1 == "ctx (no messages yet) │ M"
        assert "session" not in line2

    def test_line_2_fallback_when_only_duration_present(self, monkeypatch, capsys):
        payload = (
            b'{"context_window":{"used_percentage":50},'
            b'"model":{"display_name":"M"},"cost":{"total_duration_ms":300000}}'
        )
        line1, line2 = run_lines(monkeypatch, capsys, payload)
        assert line1.endswith("50% │ session 5m │ M")
        assert line2 == "(no rate-limit / cost data)"


# ── main() — time-to-cap field (issue #3) ────────────────────────────────
def _rl_payload(window: str, used: float, resets_at: float | None) -> bytes:
    win: dict[str, float] = {"used_percentage": used}
    if resets_at is not None:
        win["resets_at"] = resets_at
    payload = {"rate_limits": {window: win}, "model": {"display_name": "M"}}
    return json.dumps(payload).encode()


class TestTimeToCapField:
    @pytest.fixture(autouse=True)
    def _freeze_time(self, monkeypatch):
        monkeypatch.setattr(statusline.time, "time", lambda: 0.0)

    def test_placed_after_reset_countdown(self, monkeypatch, capsys):
        _, line2 = run_lines(monkeypatch, capsys, _rl_payload("five_hour", 35, 7200))
        assert line2 == "5h 35% (↻ 2.0h · ⇲ 5.6h)"

    def test_seven_day_window(self, monkeypatch, capsys):
        resets = 6.4 * 86400
        _, line2 = run_lines(monkeypatch, capsys, _rl_payload("seven_day", 13, resets))
        assert line2 == "7d 13% (↻ 6.4d · ⇲ 4.0d)"

    def test_minutes_format(self, monkeypatch, capsys):
        # elapsed 10800 s; 20 / 80 * 10800 = 2700 s = 45m
        _, line2 = run_lines(monkeypatch, capsys, _rl_payload("five_hour", 80, 7200))
        assert line2 == "5h 80% (↻ 2.0h · ⇲ 45m)"

    def test_brackets_and_separator_are_dim(self, monkeypatch, capsys):
        out = run_main(monkeypatch, capsys, _rl_payload("five_hour", 35, 7200))
        dim, reset = statusline.DIM, statusline.RESET
        assert f"{dim}({reset}" in out
        assert f"{dim} · {reset}" in out
        assert f"{dim}){reset}" in out

    def _value_colour(self, monkeypatch, capsys, used, resets_at, text):
        # The ⇲ symbol shares the colour of its value.
        out = run_main(monkeypatch, capsys, _rl_payload("five_hour", used, resets_at))
        for colour in (statusline.RED, statusline.YELLOW, statusline.GREEN):
            if f"{colour}⇲ {text}{statusline.RESET}" in out:
                return colour
        raise AssertionError(f"{text!r} not found coloured in {out!r}")

    def test_red_when_cap_before_reset(self, monkeypatch, capsys):
        # cap in 45m, reset in 2.0h -> r = 0.375
        colour = self._value_colour(monkeypatch, capsys, 80, 7200, "45m")
        assert colour == statusline.RED

    def test_yellow_at_ratio_one(self, monkeypatch, capsys):
        # 50% after 2.5h, reset in 2.5h -> cap exactly at the reset (r = 1)
        colour = self._value_colour(monkeypatch, capsys, 50, 9000, "2.5h")
        assert colour == statusline.YELLOW

    def test_yellow_when_tight(self, monkeypatch, capsys):
        # 45% after 2.5h -> cap in 55/45 * 2.5h = 3.1h, r = 1.22
        colour = self._value_colour(monkeypatch, capsys, 45, 9000, "3.1h")
        assert colour == statusline.YELLOW

    def test_green_when_comfortable(self, monkeypatch, capsys):
        # 40% after 2.5h -> cap in 3.8h, r = 1.5
        colour = self._value_colour(monkeypatch, capsys, 40, 9000, "3.8h")
        assert colour == statusline.GREEN

    def test_usage_colour_unchanged(self, monkeypatch, capsys):
        out = run_main(monkeypatch, capsys, _rl_payload("five_hour", 80, 7200))
        assert f"{statusline.YELLOW}80%{statusline.RESET}" in out

    def test_omitted_when_used_is_zero(self, monkeypatch, capsys):
        _, line2 = run_lines(monkeypatch, capsys, _rl_payload("five_hour", 0, 7200))
        assert line2 == "5h 0% (↻ 2.0h)"

    def test_omitted_when_at_cap(self, monkeypatch, capsys):
        _, line2 = run_lines(monkeypatch, capsys, _rl_payload("five_hour", 100, 7200))
        assert line2 == "5h 100% (↻ 2.0h)"

    def test_omitted_when_reset_missing(self, monkeypatch, capsys):
        _, line2 = run_lines(monkeypatch, capsys, _rl_payload("five_hour", 35, None))
        assert line2 == "5h 35%"

    def test_omitted_when_reset_in_past(self, monkeypatch, capsys):
        monkeypatch.setattr(statusline.time, "time", lambda: 10_000.0)
        _, line2 = run_lines(monkeypatch, capsys, _rl_payload("five_hour", 35, 500))
        assert line2 == "5h 35%"

    def test_omitted_when_no_time_elapsed(self, monkeypatch, capsys):
        payload = _rl_payload("five_hour", 35, FIVE_HOUR_SECS)
        _, line2 = run_lines(monkeypatch, capsys, payload)
        assert line2 == "5h 35% (↻ 5.0h)"

    def test_omitted_on_clock_skew(self, monkeypatch, capsys):
        payload = _rl_payload("seven_day", 35, SEVEN_DAY_SECS + 86400)
        _, line2 = run_lines(monkeypatch, capsys, payload)
        assert line2 == "7d 35% (↻ 8.0d)"

    def test_absent_percentage_omits_segment(self, monkeypatch, capsys):
        payload = b'{"rate_limits":{"five_hour":{}},"model":{"display_name":"M"}}'
        _, line2 = run_lines(monkeypatch, capsys, payload)
        assert line2 == "(no rate-limit / cost data)"


# ── --version flag ─────────────────────────────────────────────────────────
class TestVersionFlag:
    def test_version_flag_prints_version_and_skips_stdin(self, monkeypatch, capsys):
        # No stdin is set: --version must short-circuit before reading it.
        monkeypatch.setattr(sys, "argv", ["claude-statusline", "--version"])
        statusline.main()
        out = capsys.readouterr().out
        assert "claude-statusline" in out
        assert statusline.__version__ in out

    def test_short_version_flag(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["claude-statusline", "-V"])
        statusline.main()
        assert statusline.__version__ in capsys.readouterr().out


# ── main() — readability of times and separators (issue #10) ──────────────
class TestReadability:
    @pytest.fixture(autouse=True)
    def _freeze_time(self, monkeypatch):
        monkeypatch.setattr(statusline.time, "time", lambda: 0.0)

    def test_reset_countdown_is_bold_like_session(self, monkeypatch, capsys):
        out = run_main(monkeypatch, capsys, _rl_payload("five_hour", 35, 7200))
        bold, reset = statusline.BOLD, statusline.RESET
        assert f"{bold}↻ 2.0h{reset}" in out

    def test_reset_countdown_is_bold_without_time_to_cap(self, monkeypatch, capsys):
        out = run_main(monkeypatch, capsys, _rl_payload("five_hour", 0, 7200))
        dim, bold, reset = statusline.DIM, statusline.BOLD, statusline.RESET
        assert f"{dim}({reset}{bold}↻ 2.0h{reset}{dim}){reset}" in out

    def test_field_separator_is_dim_vertical_bar(self, monkeypatch, capsys):
        payload = b'{"model":{"display_name":"M"},"cost":{"total_duration_ms":0}}'
        out = run_main(monkeypatch, capsys, payload)
        dim, reset = statusline.DIM, statusline.RESET
        assert f" {dim}│{reset} " in out.splitlines()[0]
        assert "·" not in out
