"""Tests for the pure helpers and the stdin/stdout edge cases of statusline.py."""

import io
import sys

import pytest

import statusline
from statusline import (
    color_for_pct,
    format_duration,
    human_tokens,
    make_bar,
    reset_in,
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
