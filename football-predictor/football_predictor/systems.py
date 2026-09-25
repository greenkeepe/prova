"""Totocalcio-style betting systems: integrale (full) and ridotto (reduced).

Definitions used here, matching how Italian "sistemi" work in practice:

- You pick one or more signs (1/X/2, or fewer with a "doppia chance") per
  match. A *scenario* is one combination of the real results, restricted
  to the signs you actually picked per match — a system can only ever
  guarantee something about scenarios where the real result was among
  your picks for every match; if you didn't pick the actual sign on a
  match, no system can save that match.
- **Sistema integrale**: every combination of your picks, one column per
  scenario. Guarantees the top prize (all correct) if reality falls
  inside your picks, because every such scenario is literally played.
- **Sistema ridotto**: a subset of columns that still guarantees at
  least `min_correct` matches right, for *any* scenario inside your
  picks, using fewer columns than the integrale.

Real ridotto systems are published as combinatorial covering-design
tables (SNAI-style). We do not have access to those tables, and it would
be dishonest to fabricate one and label it "guaranteed" without proof.
Instead this module *constructs* a reduced system with a greedy
set-cover heuristic and then *exhaustively verifies* the guarantee by
checking every scenario is actually covered before returning it. The
column count therefore may be larger than an optimal published table for
the same guarantee, but the guarantee itself is provably correct, not
assumed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

DEFAULT_MAX_SCENARIOS = 20_000


class SystemTooLargeError(ValueError):
    pass


@dataclass
class SystemResult:
    match_labels: list[str]
    picks_per_match: list[list[str]]
    columns: list[tuple[str, ...]]
    guarantee: int
    total_scenarios: int
    stake_per_column: float
    kind: str  # "integrale" | "ridotto"

    @property
    def num_columns(self) -> int:
        return len(self.columns)

    @property
    def total_cost(self) -> float:
        return round(self.num_columns * self.stake_per_column, 2)

    @property
    def savings_vs_integral(self) -> float:
        if self.total_scenarios == 0:
            return 0.0
        return round(1 - self.num_columns / self.total_scenarios, 4)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "matches": self.match_labels,
            "picks_per_match": self.picks_per_match,
            "num_columns": self.num_columns,
            "total_scenarios": self.total_scenarios,
            "guaranteed_min_correct": self.guarantee,
            "stake_per_column": self.stake_per_column,
            "total_cost": self.total_cost,
            "savings_vs_integral": self.savings_vs_integral,
            "columns": [list(c) for c in self.columns],
        }


def _scenario_space(picks_per_match: list[list[str]]) -> list[tuple[str, ...]]:
    for i, picks in enumerate(picks_per_match):
        if not picks:
            raise ValueError(f"Match {i} has no signs selected")
        if len(set(picks)) != len(picks):
            raise ValueError(f"Match {i} has duplicate signs: {picks}")
    return list(product(*picks_per_match))


def full_system(
    picks_per_match: list[list[str]],
    match_labels: list[str] | None = None,
    stake_per_column: float = 1.0,
) -> SystemResult:
    """Sistema integrale: every combination of the chosen signs."""
    scenarios = _scenario_space(picks_per_match)
    labels = match_labels or [f"Match {i+1}" for i in range(len(picks_per_match))]
    return SystemResult(
        match_labels=labels,
        picks_per_match=picks_per_match,
        columns=scenarios,
        guarantee=len(picks_per_match),
        total_scenarios=len(scenarios),
        stake_per_column=stake_per_column,
        kind="integrale",
    )


def reduced_system(
    picks_per_match: list[list[str]],
    min_correct: int,
    match_labels: list[str] | None = None,
    stake_per_column: float = 1.0,
    max_scenarios: int = DEFAULT_MAX_SCENARIOS,
) -> SystemResult:
    """Sistema ridotto: fewer columns, with a verified min_correct guarantee.

    Raises SystemTooLargeError if the scenario space exceeds max_scenarios
    — the greedy construction below is O(rounds * scenarios^2), so this
    cap exists to fail fast instead of hanging on a huge system.
    """
    n = len(picks_per_match)
    if not (1 <= min_correct <= n):
        raise ValueError(f"min_correct must be between 1 and {n}, got {min_correct}")

    scenarios = _scenario_space(picks_per_match)
    total = len(scenarios)
    if total > max_scenarios:
        raise SystemTooLargeError(
            f"Scenario space has {total} combinations, above the safety cap of "
            f"{max_scenarios}. Reduce the number of matches, the signs per match, "
            f"or pass a higher max_scenarios if you accept the runtime cost."
        )
    if min_correct == n:
        # No reduction possible: guaranteeing every match correct requires
        # playing every scenario, i.e. the integrale itself.
        labels = match_labels or [f"Match {i+1}" for i in range(n)]
        return SystemResult(
            match_labels=labels, picks_per_match=picks_per_match, columns=scenarios,
            guarantee=n, total_scenarios=total, stake_per_column=stake_per_column,
            kind="ridotto",
        )

    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "numpy is required for reduced-system generation (pip install numpy)"
        ) from exc

    # Encode each match's signs as small integers so agreement-counting is
    # a vectorized array comparison instead of a Python-level loop.
    code_maps = [{sign: i for i, sign in enumerate(picks)} for picks in picks_per_match]
    scenario_codes = np.array(
        [[code_maps[m][sign] for m, sign in enumerate(s)] for s in scenarios],
        dtype=np.int8,
    )  # shape (total, n)

    uncovered_mask = np.ones(total, dtype=bool)
    chosen_indices: list[int] = []

    while uncovered_mask.any():
        # agreement[i, j] = matches where candidate i agrees with scenario j
        agreement = (scenario_codes[:, None, :] == scenario_codes[None, :, :]).sum(axis=2)
        covers = agreement >= min_correct  # (candidates, scenarios)
        newly_covered_count = covers[:, uncovered_mask].sum(axis=1)
        best = int(newly_covered_count.argmax())
        if newly_covered_count[best] == 0:
            # Should not happen: every scenario at least covers itself.
            best = int(np.flatnonzero(uncovered_mask)[0])
        chosen_indices.append(best)
        uncovered_mask &= ~covers[best]

    chosen = [scenarios[i] for i in chosen_indices]

    # Exhaustive verification: every scenario must be covered by at least
    # one chosen column at >= min_correct agreement. This is what lets us
    # call the guarantee "verified" rather than assumed.
    chosen_codes = scenario_codes[chosen_indices]  # (k, n)
    agreement_all = (scenario_codes[:, None, :] == chosen_codes[None, :, :]).sum(axis=2)
    if not bool((agreement_all >= min_correct).any(axis=1).all()):
        raise AssertionError("internal error: greedy construction failed to cover all scenarios")

    labels = match_labels or [f"Match {i+1}" for i in range(n)]
    return SystemResult(
        match_labels=labels,
        picks_per_match=picks_per_match,
        columns=chosen,
        guarantee=min_correct,
        total_scenarios=total,
        stake_per_column=stake_per_column,
        kind="ridotto",
    )
