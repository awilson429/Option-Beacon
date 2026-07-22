from trade_storage import close_position, create_position, load_open_positions, load_positions


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
