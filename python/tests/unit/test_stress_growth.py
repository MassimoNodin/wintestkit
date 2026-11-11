from stress_growth import check_growth

SERIES = (
    (
        741,
        754,
        742,
        754,
        771,
        732,
        747,
        762,
        744,
        731,
        743,
        752,
        761,
        738,
        751,
        757,
        758,
        731,
        751,
        742,
        757,
    ),
    (
        740,
        756,
        749,
        758,
        768,
        737,
        754,
        761,
        747,
        740,
        758,
        765,
        756,
        735,
        750,
        756,
        760,
        738,
        755,
        751,
        761,
    ),
)


def test_recorded_handle_growth():
    for series in SERIES:
        for trend, expected in ((0, False), (0.05, False), (0.1, True)):
            checkpoints = {
                index * 20: {"handles": value + trend * index * 20, "threads": 1, "private": 1}
                for index, value in enumerate(series)
            }
            assert bool(check_growth("recorded", checkpoints, handles=10)) is expected
