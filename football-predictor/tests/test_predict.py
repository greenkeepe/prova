import pytest

from football_predictor.predict import elo_diff_to_1x2


def test_probabilities_sum_to_one():
    for diff in (-800, -400, -65, 0, 65, 200, 800):
        p_home, p_draw, p_away = elo_diff_to_1x2(diff)
        assert p_home + p_draw + p_away == pytest.approx(1.0, abs=1e-9)
        assert p_home >= 0 and p_draw >= 0 and p_away >= 0


def test_even_teams_favor_neither_side():
    p_home, p_draw, p_away = elo_diff_to_1x2(0)
    assert p_home == pytest.approx(p_away, abs=1e-9)


def test_large_home_elo_advantage_makes_home_win_most_likely():
    p_home, p_draw, p_away = elo_diff_to_1x2(500)
    assert p_home > p_draw
    assert p_home > p_away


def test_large_away_elo_advantage_makes_away_win_most_likely():
    p_home, p_draw, p_away = elo_diff_to_1x2(-500)
    assert p_away > p_draw
    assert p_away > p_home


def test_draw_probability_shrinks_as_gap_widens():
    _, p_draw_even, _ = elo_diff_to_1x2(0)
    _, p_draw_lopsided, _ = elo_diff_to_1x2(600)
    assert p_draw_lopsided < p_draw_even
