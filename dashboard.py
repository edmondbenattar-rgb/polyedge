import streamlit as st
from streamlit_autorefresh import st_autorefresh
import json
import os
import urllib.request
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional
from collections import defaultdict

st.set_page_config(page_title="PolyEdge Dashboard", page_icon="📈", layout="wide")

st_autorefresh(interval=60 * 1000, key="autorefresh")

# Tight CSS
st.markdown("""
<style>
.metric-card { background: linear-gradient(135deg, #12121a 0%, #1a1a2e 100%); border: 1px solid #2a2a4a; border-radius: 12px; padding: 16px 10px; text-align: center; }
.metric-label { font-family: 'Space Mono', monospace; font-size: 9.5px; letter-spacing: 1.5px; text-transform: uppercase; color: #6060a0; }
.metric-value { font-family: 'Space Mono', monospace; font-size: 20px; font-weight: 700; }
.metric-value.positive { color: #00d4aa; }
.metric-value.negative { color: #ff4466; }
.section-title { font-family: 'Space Mono', monospace; font-size: 10.5px; letter-spacing: 2px; text-transform: uppercase; color: #4040a0; margin: 20px 0 12px 0; }
.mono { font-family: 'Space Mono', monospace; font-size: 10.8px; }
.question-text { font-size: 10.8px; color: #b0b0d0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.col-header { font-family: 'Space Mono', monospace; font-size: 9.6px; color: #303050; text-transform: uppercase; }
</style>
""", unsafe_allow_html=True)

@dataclass
class TradeRecord:
    timestamp: str
    market_id: str
    question: str
    side: str
    p_model: float
    p_market: float
    edge: float
    ev: float
    kelly_f: float
    bet_size: float
    order_id: str
    avg_price: float
    pnl: Optional[float] = None
    outcome: Optional[float] = None
    dry_run: bool = True

def load_trades():
    if not os.path.exists("trades.jsonl"): return []
    with open("trades.jsonl") as f:
        return [TradeRecord(**json.loads(line.strip())) for line in f if line.strip()]

def fetch_market(market_id):
    try:
        req = urllib.request.Request(f"https://gamma-api.polymarket.com/markets/{market_id}", 
                                   headers={"User-Agent": "Mozilla/5.0"})
        return json.loads(urllib.request.urlopen(req, timeout=8).read())
    except:
        return None

def get_yes_price(market):
    try:
        prices = market.get("outcomePrices") or []
        if isinstance(prices, str): prices = json.loads(prices)
        return float(prices[0])
    except:
        return None

def polymarket_url(market_id):
    return f"https://polymarket.com/market/{market_id}" if market_id else "https://polymarket.com"

def fmt_time_remaining(end_date):
    if not end_date: return "—"
    try:
        end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        delta = end_dt - datetime.now(timezone.utc)
        if delta.total_seconds() < 0: return "Expired"
        hours = delta.total_seconds() / 3600
        if hours < 1: return f"{int(delta.total_seconds()/60)}m"
        if hours < 24: return f"{hours:.0f}h"
        return f"{hours/24:.1f}d"
    except:
        return "—"

def render():
    trades = load_trades()
    open_trades = [t for t in trades if t.outcome is None]
    resolved = [t for t in trades if t.outcome is not None]

    live_markets = {}
    for t in open_trades:
        m = fetch_market(t.market_id)
        if m:
            live_markets[t.market_id] = m

    total_invested = sum(t.bet_size for t in open_trades)
    total_realised = sum(t.pnl or 0 for t in resolved)
    total_unrealised = sum((t.bet_size * ((get_yes_price(live_markets.get(t.market_id)) / t.avg_price - 1) if t.side == "YES" else 
                         ((1 - get_yes_price(live_markets.get(t.market_id))) / (1 - t.avg_price) - 1)) 
                         for t in open_trades if get_yes_price(live_markets.get(t.market_id)) is not None), 0)

    # Header
    st.markdown("# PolyEdge  |  PAPER TRADING")
    cols = st.columns(8)
    cols[0].metric("Bankroll", f"${(10000 + total_realised):,.0f}")
    cols[1].metric("Cash", f"${(10000 - total_invested):,.0f}")
    cols[2].metric("At Risk", f"${total_invested:,.0f}")
    cols[3].metric("Total PnL", f"${total_realised + total_unrealised:,.0f}", delta=f"{total_realised + total_unrealised:,.0f}")
    cols[4].metric("Realised", f"${total_realised:,.0f}")
    cols[5].metric("Unrealised", f"${total_unrealised:,.0f}")
    cols[6].metric("Win Rate", "—")

    # Open Positions
    st.subheader(f"Open Positions ({len(open_trades)})")
    if open_trades:
        for t in open_trades:
            m = live_markets.get(t.market_id)
            current = get_yes_price(m)
            with st.container():
                col1, col2, col3, col4 = st.columns([1,1,2,1])
                col1.write(f"**{t.side}** ${t.bet_size:.0f}")
                col2.write(f"Entry: {t.avg_price:.3f}")
                if current:
                    pnl = t.bet_size * ((current / t.avg_price - 1) if t.side == "YES" else ((1-current) / (1-t.avg_price) - 1))
                    col3.write(f"Current: {current:.3f} | PnL: ${pnl:.0f}")
                col4.write(f"[Open Market]({polymarket_url(t.market_id)})")

    st.subheader(f"Resolved Trades ({len(resolved)})")
    for t in resolved:
        st.write(f"{t.side} ${t.bet_size:.0f} → PnL ${t.pnl or 0:.0f} | {t.question[:80]}...")

render()