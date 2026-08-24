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
}
