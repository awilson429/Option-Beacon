import pandas as pd


def calculate_performance(history):
    if len(history) == 0:
        return {
            "total": 0,
            "open": 0,
            "wins": 0,
            "losses": 0,
            "breakevens": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "profit_factor": 0,
        }

    wins = len(history[history["status"] == "WIN"])
    losses = len(history[history["status"] == "LOSS"])
    breakevens = len(history[history["status"] == "BREAKEVEN"])
    open_trades = len(history[history["status"] == "OPEN"])

    completed = wins + losses
    win_rate = (wins / completed * 100) if completed > 0 else 0

    closed = history[history["status"].isin(["WIN", "LOSS", "BREAKEVEN"])]
    pnl_values = pd.to_numeric(closed["pnl_percent"], errors="coerce").fillna(0)

    gross_wins = pnl_values[pnl_values > 0].sum()
    gross_losses = abs(pnl_values[pnl_values < 0].sum())
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else 0

    return {
        "total": len(history),
        "open": open_trades,
        "wins": wins,
        "losses": losses,
        "breakevens": breakevens,
        "win_rate": win_rate,
        "total_pnl": pnl_values.sum(),
        "profit_factor": profit_factor,
    }


def calculate_symbol_stats(history, symbol):
    symbol_history = history[history["symbol"] == symbol]

    if len(symbol_history) == 0:
        return {
            "signals": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "profit_factor": 0,
        }

    wins = len(symbol_history[symbol_history["status"] == "WIN"])
    losses = len(symbol_history[symbol_history["status"] == "LOSS"])

    completed = wins + losses
    win_rate = (wins / completed * 100) if completed > 0 else 0

    closed = symbol_history[symbol_history["status"].isin(["WIN", "LOSS", "BREAKEVEN"])]
    pnl_values = pd.to_numeric(closed["pnl_percent"], errors="coerce").fillna(0)

    gross_wins = pnl_values[pnl_values > 0].sum()
    gross_losses = abs(pnl_values[pnl_values < 0].sum())
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else 0

    return {
        "signals": len(symbol_history),
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
    }


def open_trade_pnl(row, current_price):
    entry = float(row["entry"])

    if row["signal"] == "BUY CALL":
        return ((current_price - entry) / entry) * 100

    if row["signal"] == "BUY PUT":
        return ((entry - current_price) / entry) * 100

    return 0
