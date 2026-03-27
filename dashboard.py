import streamlit as st
from streamlit_autorefresh import st_autorefresh
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import Optional
from collections import defaultdict

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PolyEdge Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st_autorefresh(interval=60 * 1000, key="autorefresh")

# ── CSS (unchanged) ───────────────────────────────────────────────────────────
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;600;800&display=swap');
html, body, [class*="css"] { font-family: 'Syne', sans-serif; background-color: #0a0a0f; color: #e8e8f0; }
.stApp { background-color: #0a0a0f; }
h1, h2, h3 { font-family: 'Syne', sans-serif; font-weight: 800; }
/* ... keep all your existing CSS exactly as before ... */
.metric-card { background: linear-gradient(135deg, #12121a 0%, #1a1a2e 100%); border: 1px solid #2a2a4a; border-radius: 12px; padding: 20px; text-align: center; height: 100%; }
.metric-label { font-family: 'Space Mono', monospace; font-size: 10px; letter-spacing: 2px; text-transform: uppercase; color: #6060a0; margin-bottom: 8px; }
.metric-value { font-family: 'Space Mono', monospace; font-size: 22px; font-weight: 700; color: #e8e8f0; }
.metric-value.positive { color: #00d4aa; } .metric-value.negative { color: #ff4466; } .metric-value.neutral { color: #8080c0; } .metric-value.warning { color: #ffb400; }
/* ... (I kept it short here — copy your full CSS block from the previous version) ... */
</style>""", unsafe_allow_html=True)

# ── Constants ──────────────────────────────────────────────────────────────────
GAMMA_API         = "https://gamma-api.polymarket.com"
TRADE_FILE        = "trades.jsonl"
STARTING_BANKROLL = 10000.0
POLYMARKET_BASE   = "https://polymarket.com/event"


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
    pnl: Optional[float]
    outcome: Optional[float]
    dry_run: bool = True


# ── Fixed Helpers ──────────────────────────────────────────────────────────────
def load_trades() -> list[TradeRecord]:
    if not os.path.exists(TRADE_FILE):
        return []
    records = []
    with open(TRADE_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(TradeRecord(**json.loads(line)))
                except Exception:
                    pass
    return records


def fetch_market_by_id(market_id: str) -> dict | None:
    """Correct single-market endpoint: /markets/{id}"""
    try:
        req = urllib.request.Request(
            f"{GAMMA_API}/markets/{market_id}",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        )
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        if isinstance(data, dict):
            data["_slug"] = data.get("slug") or data.get("conditionId", "unknown")
            return data
        return None
    except Exception:
        return None


def _fetch_market_by_question(question: str) -> dict | None:
    """Original slug fallback (kept for speed on crypto)."""
    q = question.lower()
    asset = next((a for a in ["bitcoin", "ethereum", "solana", "xrp", "gold"] if a in q), None)
    if not asset:
        return None
    date_m = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})', q)
    if not date_m:
        return None
    date_hint = date_m.group(0).replace(" ", "-")
    ts = int(datetime.now(timezone.utc).timestamp() // 60)
    for slug in [f"{asset}-above-on-{date_hint}", f"{asset}-price-above-on-{date_hint}"]:
        try:
            req = urllib.request.Request(
                f"{GAMMA_API}/events?slug={slug}&_={ts}",
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
            )
            data = json.loads(urllib.request.urlopen(req, timeout=8).read())
            if isinstance(data, list):
                for event in data:
                    for m in event.get("markets", []):
                        if m.get("question", "") == question:
                            m["_slug"] = slug
                            return m
        except Exception:
            continue
    return None


def fetch_market(question: str, market_id: str = None) -> dict | None:
    """Fixed: Prefer correct /markets/{id} endpoint, then fallback."""
    if market_id:
        m = fetch_market_by_id(market_id)
        if m:
            return m
    return _fetch_market_by_question(question)


def get_yes_price(market: dict) -> float | None:
    try:
        prices = market.get("outcomePrices") or []
        if isinstance(prices, str):
            prices = json.loads(prices)
        return float(prices[0]) if prices else None
    except Exception:
        return None


# Rest of your functions (fmt_time_remaining, fmt_timestamp, breakeven_price, calc_unrealised, pnl_cls, confidence_tier, fmt, identify_asset, polymarket_url) remain exactly the same as in your original or my previous version.

# ── Render function (only small change: use the fixed fetch_market) ─────────────
def render():
    # ... (keep everything from your original render() up to the live_markets block)

    # Live market data — now correctly using market_id
    live_markets = {}
    for t in open_trades:
        m = fetch_market(t.question, market_id=t.market_id)   # ← fixed call
        if m:
            live_markets[t.market_id] = m

    # ... rest of your render() code stays identical (totals, open positions table, resolved trades, etc.)

    # In the open positions loop, it will now correctly pull endDate and outcomePrices

# (Copy the full render() body from your original dashboard.py — only the fetch_market call above is updated)

render()