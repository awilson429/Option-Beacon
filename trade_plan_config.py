"""Centralized, documented thresholds for the deterministic Trade Plan Engine."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TradePlanConfig:
    minimum_confidence: float = 65.0
    minimum_risk_reward_target_1: float = 1.0
    preferred_risk_reward_target_2: float = 2.0
    entry_zone_atr_width: float = 0.20
    entry_zone_percentage_fallback: float = 0.002
    maximum_late_entry_atr_extension: float = 0.80
    moderate_late_entry_atr_extension: float = 0.40
    maximum_candles_after_trigger: int = 4
    maximum_projected_move_completed: float = 0.70
    minimum_remaining_distance_target_1_atr: float = 0.25
    target_1_atr_multiplier: float = 1.0
    target_2_atr_multiplier: float = 2.0
    stop_atr_buffer: float = 0.15
    breakeven_trigger_method: str = "TARGET_1"
    breakeven_r_multiple: float = 1.0
    trailing_stop_activation_r_multiple: float = 1.5
    trailing_stop_atr_multiplier: float = 0.75
    maximum_hold_minutes: int = 120
    maximum_hold_candles: int = 24
    end_of_day_cutoff: str = "15:50"
    market_timezone: str = "America/New_York"
    minimum_minutes_before_end_of_day: int = 20
    volume_confirmation_threshold: float = 1.20
    market_data_stale_seconds: int = 600
    bullish_rsi_overextension: float = 75.0
    bearish_rsi_overextension: float = 25.0
    consolidation_threshold_atr: float = 0.35
    minimum_atr: float = 0.01
    maximum_data_quality_spread_percent: float = 20.0
    minimum_setup_quality: float = 60.0
    weakening_momentum_penalty: float = 8.0
    late_entry_moderate_penalty: float = 10.0
    late_entry_high_penalty: float = 25.0
    poor_risk_reward_penalty: float = 20.0
    stale_data_penalty: float = 25.0
    trend_conflict_penalty: float = 15.0

    def validate(self) -> list[str]:
        errors = []
        if not 0 <= self.minimum_confidence <= 100:
            errors.append("minimum_confidence must be between 0 and 100")
        if self.minimum_risk_reward_target_1 <= 0:
            errors.append("minimum risk/reward must be positive")
        if self.entry_zone_atr_width <= 0:
            errors.append("entry-zone ATR width must be positive")
        if self.market_data_stale_seconds <= 0:
            errors.append("stale threshold must be positive")
        if self.maximum_hold_minutes <= 0 or self.maximum_hold_candles <= 0:
            errors.append("maximum hold limits must be positive")
        return errors


DEFAULT_TRADE_PLAN_CONFIG = TradePlanConfig()
