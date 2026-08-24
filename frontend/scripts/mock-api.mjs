import http from "node:http";

const strategy=(symbol,direction,contract)=>({symbol,price:symbol==="SPY"?642.18:571.42,market_status:"open",data_status:"persisted",last_updated:new Date().toISOString(),bias:{direction,label:`${direction} BIAS`},trade_coverage:{direction,entry_trigger:symbol==="SPY"?642.25:571.2,state:symbol==="SPY"?"READY":"WATCHING"},setup:{state:contract?"selected":"awaiting_contract",strike:contract?643:null,expiration:contract?"2026-08-24":null,dte:contract?0:null,spread:contract?3.5:null,contract},context:{level:"available",known_factors:["vwap_aligned","ema_aligned"],details:null},confirmations:{state:"context_only",items:["EMA aligned"]},market_condition:{regime:"RANGE / CHOP"},session:{pnl:null,trades:0,wins:0,losses:0,win_rate:null}});
const routes={
  "/api/options-desk/SPY":strategy("SPY","CALL","SPY260824C00643000"),
  "/api/options-desk/QQQ":strategy("QQQ","PUT",null),
  "/api/scalp/SPY":{symbol:"SPY",strategy:"SCALP_RESEARCH",mode:"SHADOW",market_status:"open",data_status:"persisted",current:{direction:"CALL",setup_family:"VWAP_CONTINUATION",state:"FORMING",probability:.66,entry_trigger:642.3,invalidation:641.9,maximum_chase:642.5,expected_move:.34,expected_hold_minutes:[3,15]}},
  "/api/scalp/QQQ":{symbol:"QQQ",strategy:"SCALP_RESEARCH",mode:"SHADOW",market_status:"open",data_status:"unavailable",current:null},
  "/api/scalp/SPY/performance":{symbol:"SPY",strategy:"SCALP_RESEARCH",metrics:{triggered_trades:8,win_rate:50,expectancy:3,profit_factor:1.1,net_simulated_pnl:24,maximum_drawdown:40,average_hold_minutes:6,evidence:"INSUFFICIENT"}},
  "/api/scalp/QQQ/performance":{symbol:"QQQ",strategy:"SCALP_RESEARCH",metrics:{triggered_trades:7,win_rate:42.8,expectancy:-1.2,profit_factor:.9,net_simulated_pnl:-8.4,maximum_drawdown:52,average_hold_minutes:7,evidence:"INSUFFICIENT"}},
  "/api/scalp/compare":{strategy:"SCALP_RESEARCH",symbols:{SPY:{triggered_trades:8,win_rate:50,expectancy:3,profit_factor:1.1,net_simulated_pnl:24,maximum_drawdown:40,average_hold_minutes:6,evidence:"INSUFFICIENT"},QQQ:{triggered_trades:7,win_rate:42.8,expectancy:-1.2,profit_factor:.9,net_simulated_pnl:-8.4,maximum_drawdown:52,average_hold_minutes:7,evidence:"INSUFFICIENT"}},normalization:"per triggered contract; realistic P&L primary"},
  "/api/system/status":{status:"ok",market_status:"open",database:"connected",data_freshness:"fresh",worker_status:"healthy",worker_last_success:new Date().toISOString(),provider_status:"not_queried",timestamp:new Date().toISOString()},
};

http.createServer((request,response)=>{const body=routes[request.url];response.setHeader("Access-Control-Allow-Origin","http://localhost:3000");response.setHeader("Content-Type","application/json");response.writeHead(body?200:404);response.end(JSON.stringify(body||{detail:"Not found"}))}).listen(8000,()=>console.log("OptionBeacon mock API on http://localhost:8000"));
