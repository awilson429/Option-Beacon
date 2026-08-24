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
