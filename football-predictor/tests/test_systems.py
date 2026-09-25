from itertools import product

import pytest

from football_predictor import systems


def test_full_system_covers_every_combination():
    picks = [["1", "X"], ["1"], ["1", "X", "2"]]
    result = systems.full_system(picks, match_labels=["A", "B", "C"], stake_per_column=2.0)
    assert result.kind == "integrale"
    assert result.num_columns == 2 * 1 * 3
    assert result.total_cost == pytest.approx(result.num_columns * 2.0)
    assert set(result.columns) == set(product(*picks))


def test_reduced_system_guarantee_is_exhaustively_verified():
    picks = [["1", "X"], ["1", "2"], ["1", "X"], ["1", "2"], ["1", "X"]]
    n = len(picks)
    min_correct = 4
    result = systems.reduced_system(picks, min_correct)

    assert result.kind == "ridotto"
    assert result.guarantee == min_correct
    # The reduced system must use no more columns than the full integrale,
    # and strictly fewer whenever a genuine reduction is possible.
    assert result.num_columns <= result.total_scenarios

    # Re-verify the guarantee independently of the module's own internal
    # check: every possible scenario must be within (n - min_correct)
    # mismatches of at least one played column.
    all_scenarios = list(product(*picks))
    for scenario in all_scenarios:
        best_agreement = max(
            sum(1 for a, b in zip(col, scenario) if a == b) for col in result.columns
        )
        assert best_agreement >= min_correct, f"scenario {scenario} not covered"


def test_reduced_system_with_min_correct_equal_to_n_is_the_integrale():
    picks = [["1", "X"], ["1", "2"]]
    result = systems.reduced_system(picks, min_correct=2)
    assert result.num_columns == 4  # no reduction possible when demanding all correct


def test_reduced_system_rejects_invalid_min_correct():
    picks = [["1"], ["1", "X"]]
    with pytest.raises(ValueError):
        systems.reduced_system(picks, min_correct=0)
    with pytest.raises(ValueError):
        systems.reduced_system(picks, min_correct=3)


def test_scenario_space_cap_is_enforced():
    picks = [["1", "X", "2"]] * 10  # 3**10 = 59049
    with pytest.raises(systems.SystemTooLargeError):
        systems.reduced_system(picks, min_correct=8, max_scenarios=1000)


def test_duplicate_signs_are_rejected():
    with pytest.raises(ValueError):
        systems.full_system([["1", "1"]])


def test_savings_vs_integral_is_nonnegative_and_bounded():
    picks = [["1", "X"], ["1", "2"], ["1", "X"], ["1", "2"]]
    result = systems.reduced_system(picks, min_correct=3)
    assert 0 <= result.savings_vs_integral < 1
