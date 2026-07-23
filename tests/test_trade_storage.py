from trade_storage import (
    close_position,
    create_position,
    load_open_positions,
    load_positions,
    load_recommendations,
    record_recommendation,
    update_position_premium,
)


def test_create_and_close_position(tmp_path):
    db_file = tmp_path / "trades.db"
    position_id = create_position(
        symbol="SPY",
        direction="Bullish",
        option_type="CALL",
        strike=600,
        expiration="2026-08-21",
        entry_premium=4.25,
        contracts=1,
        entry_underlying_price=601.5,
        current_stop=599.0,
        target_1=604.0,
        target_2=606.0,
        target_3=608.0,
        original_plan={"trigger_price": 601.0},
        entry_notes="Test entry",
        db_file=str(db_file),
    )

    open_positions = load_open_positions(db_file=str(db_file))
    assert len(open_positions) == 1
    assert open_positions[0]["id"] == position_id
    assert open_positions[0]["symbol"] == "SPY"

    close_position(position_id, exit_premium=5.1, exit_notes="Test exit", db_file=str(db_file))

    assert load_open_positions(db_file=str(db_file)) == []
    closed = load_positions(status="CLOSED", db_file=str(db_file))
    assert len(closed) == 1
    assert closed[0]["exit_premium"] == 5.1


def test_record_recommendation_skips_duplicate_score_and_action(tmp_path):
    db_file = tmp_path / "trades.db"
    position_id = create_position(
        symbol="SPY",
        direction="Bullish",
        option_type="CALL",
        strike=600,
        expiration="2026-08-21",
        entry_premium=4.25,
        contracts=1,
        entry_underlying_price=601.5,
        current_stop=599.0,
        target_1=604.0,
        target_2=606.0,
        target_3=608.0,
        original_plan={"trigger_price": 601.0},
        db_file=str(db_file),
    )
    recommendation = {
        "exit_score": 20,
        "exit_label": "Hold",
        "coach_action": "Hold",
        "coach_next_step": "Continue following the plan.",
        "exit_reasons": ["No major exit flags."],
    }

    first_id = record_recommendation(position_id, recommendation, db_file=str(db_file))
    second_id = record_recommendation(position_id, recommendation, db_file=str(db_file))

    assert first_id == second_id
    assert len(load_recommendations(position_id, db_file=str(db_file))) == 1


def test_recommendation_history_keeps_action_changes(tmp_path):
    db_file = tmp_path / "trades.db"
    position_id = create_position(
        symbol="SPY",
        direction="Bullish",
        option_type="CALL",
        strike=600,
        expiration="2026-08-21",
        entry_premium=4.25,
        contracts=1,
        entry_underlying_price=601.5,
        current_stop=599.0,
        target_1=604.0,
        target_2=606.0,
        target_3=608.0,
        original_plan={"trigger_price": 601.0},
        db_file=str(db_file),
    )

    record_recommendation(
        position_id,
        {
            "exit_score": 20,
            "exit_label": "Hold",
            "coach_action": "Hold",
            "coach_next_step": "Continue following the plan.",
            "exit_reasons": ["No major exit flags."],
        },
        db_file=str(db_file),
    )
    record_recommendation(
        position_id,
        {
            "exit_score": 25,
            "exit_label": "Hold",
            "coach_action": "Move stop to breakeven",
            "coach_next_step": "Protect the trade.",
            "exit_reasons": ["Current premium profit is 20%."],
            "current_profit_percent": 20,
            "peak_profit_percent": 20,
            "profit_giveback_percent": 0,
        },
        db_file=str(db_file),
    )

    recommendations = load_recommendations(position_id, db_file=str(db_file))

    assert len(recommendations) == 2
    assert recommendations[0]["coach_action"] == "Move stop to breakeven"


def test_update_position_premium_tracks_peak(tmp_path):
    db_file = tmp_path / "trades.db"
    position_id = create_position(
        symbol="SPY",
        direction="Bullish",
        option_type="CALL",
        strike=600,
        expiration="2026-08-21",
        entry_premium=4.0,
        contracts=1,
        entry_underlying_price=601.5,
        current_stop=599.0,
        target_1=604.0,
        target_2=606.0,
        target_3=608.0,
        original_plan={"trigger_price": 601.0},
        db_file=str(db_file),
    )

    update_position_premium(position_id, 6.0, db_file=str(db_file))
    updated = update_position_premium(position_id, 5.0, db_file=str(db_file))

    assert updated["current_premium"] == 5.0
    assert updated["peak_premium"] == 6.0
