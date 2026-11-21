from tf import rank


def test_available_periods():
    assert rank.available_periods("2026-11-22", "2026-11-22") == []
    assert rank.available_periods("2026-11-22", "2026-11-23") == [1]
    assert rank.available_periods("2026-11-16", "2026-11-23") == [1, 7]
    assert rank.available_periods("2026-10-24", "2026-11-23") == [1, 7, 30]


def test_period_stats_uses_first_point_inside_the_period():
    s = [("2026-11-10", 100), ("2026-11-15", 150), ("2026-11-17", 170)]
    assert rank.period_stats(s, "2026-11-17", 7) == {"d": 70, "b": 100, "w": 7, "r": 0.7}
    assert rank.period_stats(s, "2026-11-17", 1) is None          # no point on 11-16: nothing to compare
    assert rank.period_stats(s, "2026-11-18", 7) is None          # not seen on the build date


def test_ranks_break_ties_by_total_then_key():
    assert rank.ranks({"a": 5, "b": 5, "c": 9}, {"a": 1, "b": 2}) == {"c": 1, "b": 2, "a": 3}


def test_add_periods_fills_boards():
    series = {"a": [("2026-11-21", 100), ("2026-11-22", 150)],
              "b": [("2026-11-21", 10), ("2026-11-22", 30)],
              "c": [("2026-11-22", 5)]}
    stats = {k: {} for k in series}
    rank.add_periods(stats, series, "2026-11-22", [1], 50, {"a": 150, "b": 30, "c": 5}, new={"b", "c"})
    assert stats["a"]["p"]["1"] == {"d": 50, "b": 100, "w": 1, "r": 0.5, "g": 1, "q": 1}
    assert stats["b"]["p"]["1"] == {"d": 20, "b": 10, "w": 1, "r": 2.0, "g": 2, "n": 1}   # base 10 < 50: no growth rank
    assert stats["c"]["p"]["1"] == {"n": 2}                                               # joined today: on New, last
