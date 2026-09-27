from datetime import datetime

import pytest

from nightshift.schedule import DAY, parse_times, seconds_until


def at(h, m=0):
    return datetime(2026, 9, 25, h, m)


class TestParseTimes:
    def test_sorts_and_dedupes(self):
        assert parse_times("21:00, 09:00,21:00") == [(9, 0), (21, 0)]

    def test_tolerates_spacing_and_trailing_comma(self):
        assert parse_times("  00:30 ,  ") == [(0, 30)]

    @pytest.mark.parametrize("bad", ["", "9", "09-00", "24:00", "09:60", "-1:00", "aa:bb"])
    def test_rejects_malformed(self, bad):
        with pytest.raises(ValueError):
            parse_times(bad)


class TestSecondsUntil:
    def test_later_today(self):
        assert seconds_until(at(8), [(9, 0)]) == 3600

    def test_rolls_over_to_tomorrow(self):
        assert seconds_until(at(10), [(9, 0)]) == DAY - 3600

    def test_picks_the_nearest_slot(self):
        assert seconds_until(at(10), [(9, 0), (21, 0), (12, 30)]) == 2.5 * 3600

    def test_a_slot_at_this_exact_minute_is_tomorrow(self):
        # Otherwise the loop would fire again the instant a run finishes.
        assert seconds_until(at(9), [(9, 0)]) == DAY

    def test_ignores_seconds_of_the_current_time(self):
        now = datetime(2026, 9, 25, 8, 59, 30)
        assert seconds_until(now, [(9, 0)]) == 30

    def test_midnight_slot_from_late_evening(self):
        assert seconds_until(at(23, 30), [(0, 30)]) == 3600
