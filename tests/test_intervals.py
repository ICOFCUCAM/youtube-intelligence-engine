from youtube_intelligence.core.intervals import merge_intervals, total_length


def test_empty():
    assert merge_intervals([]) == []
    assert total_length([]) == 0


def test_overlapping_and_nested_merge():
    assert merge_intervals([(0, 3), (2.5, 3.5), (1, 2)]) == [(0, 3.5)]
    assert total_length([(0, 3), (2.5, 3.5)]) == 3.5


def test_touching_merge_and_disjoint_stay_apart():
    assert merge_intervals([(0, 1), (1, 2), (5, 6)]) == [(0, 2), (5, 6)]


def test_unsorted_input_and_degenerate_intervals_ignored():
    assert merge_intervals([(5, 6), (0, 1), (3, 3), (4, 2)]) == [(0, 1), (5, 6)]
