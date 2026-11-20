from datetime import timedelta

import pytest
from conftest import draws

from dehps_next.ark import ark
from dehps_next.domain import timestamp
from dehps_next.errors import DomainError


def test_maps_historical_winning_ranks_for_both_colors():
    rows = draws(4)
    for row, red, blue in zip(rows, (1, 7, 8, 1), (1, 2, 3, 1), strict=True):
        row.update(red=list(range(red, red + 6)), blue=blue)

    # Red ranks 8–13 win in both historical windows with different numbers.
    # Blue 3 and blue 1 both win at rank 3. In the target window rank 3 is blue 2.
    result = ark(rows, x=2, y=2, z=1, mode="forecast")
    step, = result["steps"]
    assert step["red_rank_order"][:10] == [8, 9, 10, 11, 12, 13, 1, 2, 3, 4]
    assert step["blue_rank_order"] == [3, 1, 2, *range(4, 17)]
    assert step["red"] == [9, 10, 11, 12, 13, 7, 1, 2, 3, 4]
    assert step["blue"] == 2


def test_number_and_position_ties_use_the_smaller_value():
    rows = draws(4)
    for row, blue in zip(rows, (2, 1, 2, 1), strict=True):
        row.update(red=[1, 2, 3, 4, 5, 6], blue=blue)
    # Blue 2 wins at rank 2, then blue 1 wins at rank 1. Both ranks are equally frequent.
    step, = ark(rows, x=2, y=2, z=1, mode="forecast")["steps"]
    assert step["blue_rank_order"] == list(range(1, 17))
    assert step["blue"] == 1


def test_replay_and_forecast_use_the_documented_hundred_draw_windows():
    rows = draws(100)
    replay = ark(rows, x=10, y=5, z=10)
    forecast = ark(rows, x=10, y=5, z=10, mode="forecast")
    assert [step["step"] for step in replay["steps"]] == list(range(1, 11))
    assert [step["target_index"] for step in replay["steps"]] == list(range(91, 101))
    assert forecast["steps"][:9] == replay["steps"][:9]
    assert replay["verified_periods"] == 10
    assert forecast["verified_periods"] == 9
    for result in (replay, forecast):
        for step in result["steps"]:
            t = step["target_index"]
            assert step["frequency_window"] == [rows[t - 11]["issue"], rows[t - 2]["issue"]]
            assert step["rank_window"] == [rows[t - 6]["issue"], rows[t - 2]["issue"]]

    held_out = replay["steps"][-1]
    assert held_out["target_issue"] == "2020100"
    assert held_out["evidence"] == "HISTORICAL_REPLAY"
    assert held_out["red_hits"] == len(set(held_out["red"]) & set(rows[-1]["red"]))
    assert held_out["blue_hit"] == (held_out["blue"] == rows[-1]["blue"])
    pending = forecast["steps"][-1]
    assert pending["target_index"] == 101
    assert pending["evidence"] == "PENDING_DRAW"
    assert pending["target_issue"] is None
    assert pending["red_hits"] is pending["red_coverage"] is pending["blue_hit"] is None


def test_replay_excludes_held_out_result_from_selection_and_forecast_excludes_it_from_coverage():
    rows = draws(6)
    for row in rows:
        row.update(red=[1, 2, 3, 4, 5, 6], blue=1)
    final = dict(rows[-1], red=[28, 29, 30, 31, 32, 33], blue=16)
    changed = [*rows[:-1], final]

    replay = ark(changed, x=2, y=1, z=3)
    original = ark(rows, x=2, y=1, z=3)
    assert replay["steps"][:2] == original["steps"][:2]
    assert replay["steps"][-1]["red"] == original["steps"][-1]["red"]
    assert replay["steps"][-1]["blue"] == original["steps"][-1]["blue"]
    assert replay["red_coverage"] == replay["blue_hit_rate"] == pytest.approx(2 / 3)

    forecast = ark(changed, x=2, y=1, z=3, mode="forecast")
    assert forecast["red_coverage"] == forecast["blue_hit_rate"] == 1
    assert forecast["steps"][-1]["red"] != replay["steps"][-1]["red"]


@pytest.mark.parametrize(("mode", "z", "needed"), [("replay", 1, 16), ("forecast", 1, 15), ("forecast", 2, 17)])
def test_minimum_history(mode, z, needed):
    rows = draws(needed)
    with pytest.raises(DomainError, match=f"Need {needed} draws") as error:
        ark(rows[1:], x=10, y=5, z=z, mode=mode)
    assert error.value.code == "ARK_INSUFFICIENT_HISTORY"

    result = ark(rows, x=10, y=5, z=z, mode=mode)
    assert len(result["steps"]) == z
    assert result["steps"][-1]["target_index"] == needed + (mode == "forecast")
    if mode == "forecast" and z == 1:
        assert result["verified_periods"] == 0
        assert result["red_coverage"] is result["blue_hit_rate"] is None


@pytest.mark.parametrize(
    ("x", "y", "z", "mode"),
    [(0, 1, 1, "replay"), (1, 2, 1, "replay"), (2, 1, 0, "replay"), (2, True, 1, "replay"), (2, 1, 1, "other")],
)
def test_invalid_parameters(x, y, z, mode):
    with pytest.raises(DomainError) as error:
        ark(draws(10), x=x, y=y, z=z, mode=mode)
    assert error.value.code == "ARK_PARAMETERS"


def test_rejects_gaps_and_out_of_order_draws():
    rows = draws(6)
    with pytest.raises(DomainError, match="Gap between"):
        ark([*rows[:3], *rows[4:]], x=2, y=1, z=2)
    with pytest.raises(DomainError, match="strict draw order"):
        ark([rows[1], rows[0], *rows[2:5]], x=2, y=1, z=2)


def test_accepts_issue_number_reset_at_year_boundary():
    rows = draws(4)
    for row, issue in zip(rows, ("2020152", "2021001", "2021002", "2021003"), strict=True):
        row["issue"] = issue
    step, = ark(rows, x=2, y=1, z=1)["steps"]
    assert step["target_issue"] == "2021003"


def test_rejects_labels_unavailable_before_historical_draw_or_current_cutoff():
    rows = draws(4)
    late = dict(rows[0], available_at=rows[2]["draw_at"])
    with pytest.raises(DomainError, match="Prior results unavailable before 2020003") as error:
        ark([late, *rows[1:]], x=2, y=1, z=1)
    assert error.value.code == "ARK_INSUFFICIENT_HISTORY"
    before_latest = timestamp(rows[-1]["available_at"]) - timedelta(seconds=1)
    with pytest.raises(DomainError, match="Result 2020004 was unavailable at cutoff"):
        ark(rows, x=2, y=1, z=1, mode="forecast", as_of=before_latest)
    assert ark(rows, x=2, y=1, z=1, mode="forecast", as_of=rows[-1]["available_at"])["steps"]
