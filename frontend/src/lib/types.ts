export type SymbolCode = "SPY" | "QQQ";

export interface StrategyState {
  symbol: SymbolCode;
  price: number | null;
  market_status: string;
  data_status: string;
  last_updated: string | null;
  bias: { direction: string | null; label: string | null };
  trade_coverage: { direction: string | null; entry_trigger: number | null; state: string };
  setup: {
    state: string; strike: number | null; expiration: string | null; dte: number | null;
    spread: number | null; contract: string | null;
    score?: number | null; entry_zone?: [number, number] | null; maximum_chase?: number | null;
    bid?: number | null; ask?: number | null; stop?: number | null; targets?: number[] | null;
    risk_reward?: number | null; delta?: number | null; volume?: number | null; open_interest?: number | null;
  };
  context: { level: string; known_factors: string[]; details: Record<string, unknown> | null };
  confirmations: { state: string; items: string[] };
  market_condition: { regime: string | null };
  session: { pnl: number | null; trades: number; wins: number; losses: number; win_rate: number | null };
}

export interface ScalpCurrent {
  direction?: string | null; setup_family?: string | null; state?: string | null;
  probability?: number | null; entry_trigger?: number | null; entry_zone?: [number, number] | null;
  invalidation?: number | null; maximum_chase?: number | null; expected_move?: number | null;
  expected_hold_minutes?: [number, number] | null; contract?: string | null;
  features?: Record<string, unknown>;
}

export interface ScalpState {
  symbol: SymbolCode; strategy: "SCALP_RESEARCH"; mode: "SHADOW";
  market_status: string; data_status: string; current: ScalpCurrent | null;
}

export interface PerformanceMetrics {
  opportunities?: number; triggered_trades?: number; win_rate?: number | null;
  expectancy?: number | null; profit_factor?: number | null; net_simulated_pnl?: number | null;
  maximum_drawdown?: number | null; average_hold_minutes?: number | null; evidence?: string;
}

export interface PerformanceResponse { symbol: SymbolCode; strategy: string; metrics: PerformanceMetrics }
export interface ComparisonResponse { strategy: string; symbols: Record<SymbolCode, PerformanceMetrics>; normalization: string }
export interface SystemStatus {
  status: string; market_status: string; database: string; data_freshness: string;
  worker_status: string; worker_last_success: string | null; provider_status: string; timestamp: string;
}

export interface TradeRow {
  id: string; opportunity_id: string; symbol: string | null; direction: string | null;
  setup: string | null; status: string; opened_at: string | null; closed_at: string | null;
  entry_price: number | null; last_price: number | null; exit_price: number | null;
  realized_result: number | null; exit_reason: string | null; metadata: Record<string, unknown>;
}

export interface HomeTrade {
  id: string; symbol: string | null; direction: string | null; strategy: string; lane_role: string;
  status: string; setup: string | null; entry_price: number | null; current_price: number | null;
  contract: string | null; pnl: number | null; opened_at: string | null; closed_at: string | null; event: string;
}

export interface TradeDeskHome {
  as_of: string; data_status: string;
  session: { realized_pnl:number|null; unrealized_pnl:number|null; total_pnl:number|null; trades:number; wins:number; losses:number; win_rate:number|null; active_trades:number };
  active: HomeTrade[];
  lanes: { key:string; label:string; role:string; active_trades:number; trades_today:number; realized_pnl:number|null; description:string }[];
  recent_activity: HomeTrade[];
  accounts: CapitalLane[];
  capital_decisions: CapitalDecision[];
}

export interface CapitalLane {
  lane:string; data_status:string; starting_capital:number; current_equity:number|null;
  cash_available:number|null; capital_committed:number|null; net_pnl:number|null;
  return_pct:number|null; realized_pnl:number|null; unrealized_pnl:number|null;
  fees:number|null; slippage:number|null; peak_equity:number|null;
  current_drawdown_pct:number|null; maximum_drawdown_pct:number|null; daily_pnl:number|null;
  open_risk:number|null; open_positions:number; risk_state:string; readiness_status:string;
  metrics:{trades?:number; expectancy?:number|null; profit_factor?:number|null; rejected_opportunities?:number; capital_efficiency_pct?:number|null};
  positions:{position_id:string;lane:string;opportunity_id:string;symbol:string;direction:string|null;strategy:string;contract_symbol:string|null;strike:number|null;expiration:string|null;dte:number|null;entry_premium:number|null;current_premium:number|null;quantity:number;capital_committed:number;initial_dollar_risk:number;unrealized_pnl:number;realized_pnl:number|null;entry_timestamp:string;time_in_trade_seconds:number|null;stop:number|null;targets:number[];status:string}[];
  updated_at:string|null;
}

export interface CapitalDecision {
  decision_id:string; lane:string; opportunity_id:string; symbol:string; direction:string|null;
  state:string; reason_code:string; explanation:string; proposed_contract:string|null;
  proposed_quantity:number; proposed_capital_required:number; proposed_dollar_risk:number;
  proposed_account_risk_pct:number; decided_at:string;
}

export interface ActiveTrade extends TradeRow {
  lane:"OB"|"BROAD"; lane_role:"AUTHORITATIVE"|"PAPER"; strategy:string|null;
  data_status:string; contract_symbol:string|null; strike:number|null;
  option_type:string|null; expiration:string|null; dte:number|null; quantity:number|null;
  entry_timestamp:string|null; underlying_entry:number|null; option_entry_premium:number|null;
  capital_committed:number|null; initial_dollar_risk:number|null; account_risk_pct:number|null;
  current_dollar_risk:number|null; latest_underlying:number|null; latest_option_mark:number|null;
  unrealized_pnl:number|null; unrealized_return_pct:number|null; time_in_trade_seconds:number|null;
  data_freshness:string; mark_timestamp:string|null; stop:number|null; target_1:number|null;
  target_2:number|null; target_3:number|null; breakeven_state:string|null;
  maximum_hold_minutes:number|null; exit_score:number|null; exit_label?:string|null; exit_state:string|null;
  trade_coach_state?:string|null; trade_coach_status:string|null; thesis_state?:string|null; thesis_status:string|null; momentum_state:string|null;
  structure_state:string|null; target_progress:string|null; stop_management_state:string|null;
  management_reason?:string|null; management_updated_at?:string|null;
  last_management_update:string|null; management_data_status:string;
}

export interface JournalMetrics {
  total_trades:number; wins:number; losses:number; breakeven:number; win_rate:number|null;
  realized_pnl:number|null; average_winner:number|null; average_loser:number|null;
  profit_factor:number|null; average_return_pct:number|null; average_hold_seconds:number|null;
}

export interface JournalTrade {
  trade_id:string; opportunity_id:string; lane:"OB"|"BROAD"; lane_role:string;
  symbol:string|null; direction:string|null; status:string; strategy:string|null;
  contract_symbol:string|null; strike:number|null; option_type:string|null;
  expiration:string|null; dte:number|null; quantity:number|null;
  entry_timestamp:string|null; underlying_entry:number|null; option_entry_premium:number|null;
  capital_committed:number|null; initial_dollar_risk:number|null; exit_timestamp:string|null;
  underlying_exit:number|null; option_exit_premium:number|null; exit_reason:string|null;
  hold_duration_seconds:number|null; realized_pnl:number|null; realized_return_pct:number|null;
  r_multiple:number|null; mfe_dollars:number|null; mae_dollars:number|null;
  mfe_pct:number|null; mae_pct:number|null; result:string; initial_stop:number|null;
  target_1:number|null; target_2:number|null; target_3:number|null;
  management_history_available:boolean; management_snapshot_count:number;
  final_exit_score:number|null; final_management_label:string|null; final_management_at:string|null;
  data_quality:string; missing_data:string[]; source_version:string|null;
}

export interface JournalResponse {
  as_of:string; data_status:string; total_count:number; limit:number; offset:number;
  summary:JournalMetrics; lanes:(JournalMetrics & {lane:"OB"|"BROAD"})[];
  control_research:JournalMetrics|null; trades:JournalTrade[];
}

export interface TradeManagementSnapshot {
  snapshot_id:string; trade_id:string; opportunity_id:string; lane:string; lane_role:string;
  symbol:string; contract_symbol:string|null; captured_at:string; source_timestamp:string|null;
  trade_status:string|null; quantity:number|null; entry_timestamp:string|null;
  entry_premium:number|null; latest_option_mark:number|null; latest_underlying:number|null;
  mark_timestamp:string|null; time_in_trade_seconds:number|null; current_stop:number|null;
  target_1:number|null; target_2:number|null; target_3:number|null; breakeven_state:string|null;
  maximum_hold_minutes:number|null; exit_score:number|null; exit_label:string|null;
  trade_coach_state:string|null; thesis_state:string|null; momentum_state:string|null;
  structure_state:string|null; target_progress:string|null; stop_management_state:string|null;
  management_reason:string|null; management_version:string|null; management_source:string;
  unrealized_pnl:number|null; unrealized_return_pct:number|null; current_managed_risk:number|null;
  data_freshness:string|null; stale:boolean; missing_data:string[]; state_fingerprint:string;
}

export interface ScannerSectionStatus {
  section:string; data_status:string; message:string|null;
}

export interface ScannerHealth {
  state:string; message:string; market_data_state:string; worker_status:string;
  provider_status:string; data_freshness:string; last_started_at:string|null;
  last_completed_at:string|null; last_success_at:string|null; last_error_at:string|null;
  last_error_message:string|null; scan_duration_seconds:number|null;
  symbols_processed:number|null; symbols_attempted:number|null; symbol_count:number|null;
  results:number|null; failures:number|null; expected_interval_seconds:number|null;
  next_expected_at:string|null;
}

export interface ScannerInstrument {
  symbol:SymbolCode; data_status:string; underlying_price:number|null;
  direction:string|null; setup:string|null; score:number|null; confidence:number|null;
  signal_state:string; observed_at:string|null; signal_age_seconds:number|null;
  freshness:string; actionable:boolean; context:Record<string,unknown>;
}

export interface ScannerLaneDecision {
  lane:"OB"|"BROAD"; data_status:string; state:string|null; reason_code:string|null;
  explanation:string|null; proposed_contract:string|null; proposed_quantity:number|null;
  proposed_capital_required:number|null; proposed_dollar_risk:number|null;
  proposed_account_risk_pct:number|null; decided_at:string|null;
}

export interface ScannerOpportunity {
  opportunity_id:string; symbol:SymbolCode; direction:string|null; strategy:string|null;
  observed_at:string; score:number|null; confidence:number|null; contract:string|null;
  entry:number|null; stop:number|null; targets:number[]; status:string; actionable:boolean;
  data_status:string; freshness:string; context:Record<string,unknown>;
  lane_decisions:ScannerLaneDecision[];
}

export interface ScannerActivity {
  activity_id:string; event_type:string; occurred_at:string; symbol:string|null;
  direction:string|null; opportunity_id:string|null; lane:string|null; status:string;
  reason_code:string|null; description:string;
}

export interface ScannerResponse {
  as_of:string; market_status:string; data_status:string;
  research_control_role:"RESEARCH_CONTROL_ONLY"; health:ScannerHealth;
  instruments:ScannerInstrument[]; opportunities:ScannerOpportunity[];
  recent_activity:ScannerActivity[]; sections:ScannerSectionStatus[];
}
