import os

from finnhub_universe import DEFAULT_TOP_MOVER_COUNT, MAX_TOP_MOVER_COUNT, top_mover_count


def test_top_mover_count_uses_default_when_missing():
    original = os.environ.pop("OPTION_BEACON_TOP_MOVER_COUNT", None)
    try:
        assert top_mover_count() == DEFAULT_TOP_MOVER_COUNT
    finally:
        if original is not None:
            os.environ["OPTION_BEACON_TOP_MOVER_COUNT"] = original


def test_top_mover_count_is_capped():
    original = os.environ.get("OPTION_BEACON_TOP_MOVER_COUNT")
    os.environ["OPTION_BEACON_TOP_MOVER_COUNT"] = "500"
    try:
        assert top_mover_count() == MAX_TOP_MOVER_COUNT
    finally:
        if original is None:
            os.environ.pop("OPTION_BEACON_TOP_MOVER_COUNT", None)
        else:
            os.environ["OPTION_BEACON_TOP_MOVER_COUNT"] = original


def test_top_mover_count_has_floor():
    original = os.environ.get("OPTION_BEACON_TOP_MOVER_COUNT")
    os.environ["OPTION_BEACON_TOP_MOVER_COUNT"] = "2"
    try:
        assert top_mover_count() == 10
    finally:
        if original is None:
            os.environ.pop("OPTION_BEACON_TOP_MOVER_COUNT", None)
        else:
            os.environ["OPTION_BEACON_TOP_MOVER_COUNT"] = original
