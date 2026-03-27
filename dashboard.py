import streamlit as st
from streamlit_autorefresh import st_autorefresh
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional
from collections import defaultdict

# Try to import yfinance, but don't crash if unavailable (Streamlit Cloud compatibility)
try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False

import yfinance as yf

# ── Gold Price Helpers (for accurate current prices on gold markets) ─────────────
def get_gold_spot_price() -> float | None:
    """
    Fetch current gold spot price from Yahoo Finance (GC=F is COMEX Gold futures).
    Returns None if yfinance unavailable or fetch fails.
    """
    if not HAS_YFINANCE:
        return None
    
    try:
        gold = yf.Ticker("GC=F")
        data = gold.history(period="1d")
        if not data.empty:
            return float(data['Close'].iloc[-1])
    except Exception:
        pass
    return None

def gold_price_to_market_price(spot_price: float, target_price: float, side: str = "YES") -> float | None:
    """
    Convert gold spot price to market probability for "settle above $X" markets.
    
    Uses proximity-based mapping:
    - If spot significantly > target: price ≈ 0.85-0.95 (high confidence YES)
    - If spot < target: price ≈ 0.05-0.15 (high confidence NO)
    - If spot ≈ target: price ≈ 0.45-0.55 (uncertain)
    """
    if spot_price is None or target_price is None or target_price <= 0:
        return None
    
    try:
        # Difference as percentage of target
        diff_pct = (spot_price - target_price) / target_price
        
        # Use exponential-like curve: steeper near target, flattens at extremes
        # For diff_pct = 0 (spot == target) -> prob = 0.5
        # For diff_pct = 0.05 (5% above) -> prob ≈ 0.72
        # For diff_pct = -0.05 (5% below) -> prob ≈ 0.28
        prob = 0.5 + 0.45 * (2 / (1 + pow(2.718, -7 * diff_pct)) - 1)
        
        # Clamp to reasonable range [0.02, 0.98]
        prob = max(0.02, min(0.98, prob))
        
        if side == "NO":
            prob = 1.0 - prob
        
        return prob
    except Exception:
        return None

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PolyEdge Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st_autorefresh(interval=60 * 1000, key="autorefresh")

# ── CSS (tight single-line headers + colored metrics) ─────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;600;800&display=swap');

html, body, [class*="css"] { font-family: 'Syne', sans-serif; background-color: #0a0a0f; color: #e8e8f0; }
.stApp { background-color: #0a0a0f; }

.metric-card {
    background: linear-gradient(135deg, #12121a 0%, #1a1a2e 100%);
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    padding: 16px 10px;
    text-align: center;
    height: 100%;
}
.metric-label { font-family: 'Space Mono', monospace; font-size: 9.2px; letter-spacing: 1.8px; text-transform: uppercase; color: #6060a0; margin-bottom: 6px; }
.metric-value { font-family: 'Space Mono', monospace; font-size: 20px; font-weight: 700; }

.metric-value.positive { color: #00d4aa !important; }
.metric-value.negative { color: #ff4466 !important; }
.metric-value.neutral  { color: #e8e8f0 !important; }
.metric-value.warning  { color: #ffb400 !important; }

.section-title {
    font-family: 'Space Mono', monospace;
    font-size: 10.2px;
    letter-spacing: 2.5px;
    text-transform: uppercase;
    color: #4040a0;
    border-bottom: 1px solid #1a1a3a;
    padding-bottom: 6px;
    margin: 20px 0 12px 0;
}

.asset-card { background: #12121a; border: 1px solid #1e1e3a; border-radius: 8px; padding: 10px; text-align: center; }
.asset-name { font-size: 10.5px; color: #6060a0; }
.asset-amount { font-size: 15px; font-weight: 700; color: #ffb400; }

.badge-yes, .badge-no, .badge-won, .badge-lost, .badge-high, .badge-medium, .badge-low {
    padding: 1px 8px; border-radius: 16px; font-family: 'Space Mono', monospace; font-size: 10px; font-weight: 700;
}
.badge-yes { background: rgba(0,212,170,0.15); color: #00d4aa; border: 1px solid #00d4aa40; }
.badge-no { background: rgba(255,68,102,0.15); color: #ff4466; border: 1px solid #ff446640; }
.badge-won { background: rgba(0,212,170,0.1); color: #00d4aa; }
.badge-lost { background: rgba(255,68,102,0.1); color: #ff4466; }
.badge-high { background: rgba(0,212,100,0.15); color: #00d464; }
.badge-medium { background: rgba(255,200,0,0.15); color: #ffc800; }
.badge-low { background: rgba(160,160,255,0.15); color: #a0a0ff; }

.mono { font-family: 'Space Mono', monospace; font-size: 10.6px; }
.question-text { font-size: 10.6px; color: #b0b0d0; line-height: 1.25; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pnl-positive { color: #00d4aa; font-family: 'Space Mono', monospace; font-weight: 700; font-size: 11.5px; }
.pnl-negative { color: #ff4466; font-family: 'Space Mono', monospace; font-weight: 700; font-size: 11.5px; }
.pnl-neutral  { color: #6060a0; font-family: 'Space Mono', monospace; font-size: 11.5px; }
.time-urgent, .time-soon, .time-ok { font-family: 'Space Mono', monospace; font-size: 10.4px; font-weight: 700; }
.link-btn { color: #6060c0; font-size: 11px; text-decoration: none; }
.dry-run-badge { background: rgba(255,180,0,0.1); color: #ffb400; border: 1px solid #ffb40040; padding: 3px 12px; border-radius: 20px; font-size: 10.5px; }
.empty-state { text-align: center; padding: 40px; font-size: 13px; color: #404060; }

/* Tight single-line column headers */
.col-header { 
    font-family: 'Space Mono', monospace; 
    font-size: 9.4px; 
    color: #303050; 
    letter-spacing: 0.6px; 
    text-transform: uppercase; 
    padding: 4px 0;
    white-space: nowrap;
}
.stButton > button {
    font-size: 9.4px !important;
    padding: 4px 6px !important;
    height: auto !important;
    min-height: 28px !important;
    white-space: nowrap;
}
</style>
""", unsafe_allow_html=True)

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
    pnl: Optional[float] = None
    outcome: Optional[float] = None
    dry_run: bool = True

# ── API Helpers ────────────────────────────────────────────────────────────────
def load_trades() -> list[TradeRecord]:
    if not os.path.exists(TRADE_FILE): return []
    records = []
    skipped = []
    with open(TRADE_FILE) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                
                # Ensure all required fields exist with fallbacks
                required_fields = {
                    'timestamp': '',
                    'market_id': '',
                    'question': '',
                    'side': 'YES',
                    'p_model': 0.0,
                    'p_market': 0.0,
                    'edge': 0.0,
                    'ev': 0.0,
                    'kelly_f': 0.0,
                    'bet_size': 0.0,
                    'order_id': '',
                    'avg_price': 0.0,
                    'pnl': None,
                    'outcome': None,
                    'dry_run': True,
                }
                
                # Fill in missing fields with defaults
                for key, default in required_fields.items():
                    if key not in data:
                        data[key] = default
                
                # Only extract fields the dataclass expects (ignore extras)
                filtered_data = {k: data[k] for k in required_fields.keys()}
                record = TradeRecord(**filtered_data)
                records.append(record)
                
            except Exception as e:
                skipped.append({
                    'line': line_num,
                    'error': str(e),
                    'data': data if 'data' in locals() else line[:80]
                })
    
    # Log warnings if trades were skipped
    if skipped:
        print(f"⚠️  WARNING: {len(skipped)} trades skipped from {TRADE_FILE}")
        for item in skipped[:3]:  # Show first 3 only
            print(f"   Line {item['line']}: {item['error']}")
        if len(skipped) > 3:
            print(f"   ... and {len(skipped) - 3} more")
    
    return records

def fetch_market_by_id(market_id: str) -> dict | None:
    try:
        req = urllib.request.Request(f"{GAMMA_API}/markets/{market_id}", headers={"User-Agent": "Mozilla/5.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        if isinstance(data, dict):
            data["_slug"] = data.get("slug") or data.get("conditionId", "unknown")
            data["_source"] = "market_id"
            return data
        return None
    except Exception as e:
        # Silently fail, will try question-based fallback
        return None

def _fetch_market_by_question(question: str) -> dict | None:
    q = question.lower()
    asset = next((a for a in ["bitcoin","ethereum","solana","xrp","gold"] if a in q), None)
    if not asset: return None
    
    # Try multiple date formats: "June 24", "June-24", "June 2026", "June-2026"
    date_m = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s*[-\s]?(\d{1,4})', q)
    if not date_m: return None
    date_hint = date_m.group(0).replace(" ", "-").lower()
    ts = int(datetime.now(timezone.utc).timestamp() // 60)
    
    # Build slug list with variations for gold
    slugs = [f"{asset}-above-on-{date_hint}", f"{asset}-price-above-on-{date_hint}"]
    if asset == "gold":
        slugs = [f"gc-above-on-{date_hint}", f"gc-above-{date_hint}", f"gold-above-on-{date_hint}"] + slugs
    
    for slug in slugs:
        try:
            req = urllib.request.Request(f"{GAMMA_API}/events?slug={slug}&_={ts}", headers={"User-Agent": "Mozilla/5.0"})
            data = json.loads(urllib.request.urlopen(req, timeout=8).read())
            if isinstance(data, list):
                for event in data:
                    for m in event.get("markets", []):
                        if m.get("question") == question:
                            m["_slug"] = slug
                            m["_source"] = "question"
                            return m
        except:
            continue
    return None

def fetch_market(question: str, market_id: str = None) -> dict | None:
    """Fetch market data, trying market_id first, then question-based lookup."""
    if market_id:
        m = fetch_market_by_id(market_id)
        if m:
            if not m.get("_slug") and m.get("slug"):
                m["_slug"] = m["slug"]
            return m
    return _fetch_market_by_question(question)

def get_yes_price(market: dict) -> float | None:
    """Get YES price from market data, with fallback to cached price."""
    if market is None:
        return None
    try:
        prices = market.get("outcomePrices") or []
        if isinstance(prices, str): 
            prices = json.loads(prices)
        if prices and len(prices) > 0:
            return float(prices[0])
    except:
        pass
    
    # Fallback: check if market has cached/stale price data
    if market.get("_cached_yes_price"):
        return market.get("_cached_yes_price")
    
    return None

def polymarket_url(market: dict | None, question: str, market_id: str = None) -> str:
    """
    Build Polymarket URL using market_id (conditionId) as primary source.
    The market_id is the on-chain unique identifier for each specific market.
    Using /market/{conditionId} is the most reliable way to route to the exact trade.
    """
    # ALWAYS use market_id (conditionId) if provided — it's the unique identifier
    if market_id:
        return f"https://polymarket.com/market/{market_id}"
    
    # Fallback: if no market_id but we have market object, try to extract conditionId from API response
    if market:
        if market.get("conditionId"):
            return f"https://polymarket.com/market/{market['conditionId']}"
        if market.get("_slug"):
            return f"{POLYMARKET_BASE}/{market['_slug']}"
        if market.get("slug"):
            return f"{POLYMARKET_BASE}/{market['slug']}"

    # Last resort: Fallback to question-based extraction (less accurate but works offline)
    q = question.lower()
    
    # Gold: extract price target from question
    if "gold" in q or "gc" in q:
        price_match = re.search(r'(?:over|above)\s+\$?([\d,]+(?:\.\d+)?)', question, re.IGNORECASE)
        if price_match:
            price = price_match.group(1).replace(",", "")
            return f"{POLYMARKET_BASE}/gc-over-under-jun-2026/gc-above-{price}-jun-2026"
        return f"{POLYMARKET_BASE}/gc-over-under-jun-2026"
    
    # Crypto: extract asset, direction, date, and target price
    asset_map = {
        "bitcoin": ("bitcoin", "btc"),
        "ethereum": ("ethereum", "eth"),
        "solana": ("solana", "sol"),
        "xrp": ("xrp", "xrp"),
    }
    
    for asset_name, (display_name, _) in asset_map.items():
        if asset_name in q:
            date_m = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})', q)
            if date_m:
                month = date_m.group(1).lower()
                day = date_m.group(2)
                date_slug = f"{month}-{day}"
                
                price_m = re.search(r'(?:over|above)\s+\$?([\d,]+(?:\.\d+)?)', question, re.IGNORECASE)
                if price_m:
                    price = price_m.group(1).replace(",", "")
                    market_slug = f"{display_name}-above-{price}-{date_slug}"
                else:
                    market_slug = f"{display_name}-above-{date_slug}"
                
                return f"{POLYMARKET_BASE}/{market_slug}/{market_slug}"
            break
    
    return "https://polymarket.com"

def fmt_time_remaining(end_date_str: str) -> tuple[str, str]:
    if not end_date_str: return "—", "time-ok"
    try:
        end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        delta = end_dt - datetime.now(timezone.utc)
        if delta.total_seconds() < 0: return "Expired", "time-urgent"
        hours = delta.total_seconds() / 3600
        if hours < 1: return f"{int(delta.total_seconds()/60)}m", "time-urgent"
        elif hours < 6: return f"{hours:.1f}h", "time-urgent"
        elif hours < 24: return f"{hours:.0f}h", "time-soon"
        else: return f"{hours/24:.1f}d", "time-ok"
    except:
        return "—", "time-ok"

def extract_expiry_from_question(question: str) -> str | None:
    """Extract ISO date from question text. Gold markets: 'June 2026' → '2026-06-30'"""
    q = question.lower()
    
    # Month mapping
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12
    }
    
    # Try to find "Month Year" pattern (e.g., "June 2026")
    date_m = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})', q)
    if date_m:
        month = months[date_m.group(1)]
        year = int(date_m.group(2))
        # Last trading day of month (e.g., June 30)
        last_day = 30 if month in [4, 6, 9, 11] else (29 if month == 2 else 31)
        return f"{year}-{month:02d}-{last_day}T23:59:59Z"
    
    # Fallback: try "Month Day" pattern
    date_m = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})', q)
    if date_m:
        month = months[date_m.group(1)]
        day = int(date_m.group(2))
        year = datetime.now().year
        return f"{year}-{month:02d}-{day:02d}T23:59:59Z"
    
    return None

def fmt_timestamp(ts: str) -> str:
    try: return datetime.fromisoformat(ts).strftime("%m/%d %H:%M")
    except: return "—"

def breakeven_price(record: TradeRecord) -> str:
    avg = record.avg_price if getattr(record, 'avg_price', 0) > 0 else record.p_market
    if avg <= 0: return "—"
    return f"{avg:.3f}" if record.side == "YES" else f"{1.0 - avg:.3f}"

def calc_unrealised(record: TradeRecord, current_yes: float | None) -> float:
    if current_yes is None: return 0.0
    avg = record.avg_price if getattr(record, 'avg_price', 0) > 0 else record.p_market
    if avg <= 0: return 0.0
    if record.side == "YES":
        return round(record.bet_size * (current_yes / avg - 1), 2)
    else:
        current_no = 1.0 - current_yes
        return round(record.bet_size * (current_no / avg - 1), 2) if avg > 0 else 0.0

def pnl_cls(v: float) -> str:
    return "pnl-positive" if v > 0 else ("pnl-negative" if v < 0 else "pnl-neutral")

def confidence_tier(edge: float) -> tuple[str, str]:
    if edge >= 0.30: return "HIGH", "badge-high"
    elif edge >= 0.18: return "MED", "badge-medium"
    return "LOW", "badge-low"

def fmt(v: float) -> str:
    return f"{'+' if v >= 0 else ''}${v:.2f}"

def identify_asset(question: str) -> str:
    q = question.lower()
    if "bitcoin" in q or "btc" in q: return "BTC"
    if "ethereum" in q or "eth" in q: return "ETH"
    if "solana" in q or "sol" in q: return "SOL"
    if "xrp" in q: return "XRP"
    if "gold" in q or "gc" in q: return "GOLD"
    return "OTHER"

# ── Render ─────────────────────────────────────────────────────────────────────
def render():
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M UTC")

    trades = load_trades()
    open_trades = [t for t in trades if t.outcome is None]
    resolved = sorted([t for t in trades if t.outcome is not None], key=lambda x: x.timestamp, reverse=True)

    live_markets = {}
    for t in open_trades:
        m = fetch_market(t.question, t.market_id)
        if m:
            live_markets[t.market_id] = m

    total_invested = sum(t.bet_size for t in open_trades)
    total_realised = sum(t.pnl or 0 for t in resolved)
    total_unrealised = sum(calc_unrealised(t, get_yes_price(live_markets.get(t.market_id))) for t in open_trades)
    total_pnl = total_realised + total_unrealised
    bankroll = STARTING_BANKROLL + total_realised
    cash_left = STARTING_BANKROLL - total_invested
    wins = sum(1 for t in resolved if (t.pnl or 0) > 0)
    losses = len(resolved) - wins
    win_rate = f"{wins/(wins+losses)*100:.0f}%" if wins + losses > 0 else "—"
    pnl_pct = f"{(total_pnl/total_invested*100):+.1f}%" if total_invested > 0 else "—"

    last_scan = "—"
    if trades:
        try:
            age = int((now - datetime.fromisoformat(max(t.timestamp for t in trades))).total_seconds() / 60)
            last_scan = f"{age}m ago" if age < 60 else f"{age//60}h ago"
        except:
            pass

    # Header + Metrics
    c1, c2, c3 = st.columns([3, 1, 2])
    with c1: 
        st.markdown("# PolyEdge")
        st.markdown("<p style='color:#404060;font-size:12px;margin-top:-12px'>PAPER TRADING DASHBOARD</p>", unsafe_allow_html=True)
    with c2: st.markdown('<span class="dry-run-badge">DRY RUN</span>', unsafe_allow_html=True)
    with c3: st.markdown(f"<p style='color:#303050;font-size:11px;text-align:right'>{now_str}<br>Last: {last_scan}</p>", unsafe_allow_html=True)

    st.markdown("---")

    cols = st.columns(8)
    def metric(col, label, value, is_positive=None):
        css = "neutral"
        if is_positive is not None:
            css = "positive" if is_positive else "negative"
        col.markdown(f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value {css}">{value}</div></div>', unsafe_allow_html=True)

    metric(cols[0], "BANKROLL", f"${bankroll:,.1f}")
    metric(cols[1], "CASH AVAILABLE", f"${cash_left:,.1f}", cash_left > 500)
    metric(cols[2], "CAPITAL AT RISK", f"${total_invested:,.2f}")
    metric(cols[3], "PNL % ON RISK", pnl_pct, total_pnl >= 0)
    metric(cols[4], "TOTAL PNL", fmt(total_pnl), total_pnl >= 0)
    metric(cols[5], "REALISED PNL", fmt(total_realised), total_realised >= 0)
    metric(cols[6], "UNREALISED PNL", fmt(total_unrealised), total_unrealised >= 0)
    metric(cols[7], "WIN RATE", win_rate, wins > losses)

    st.markdown("<br>", unsafe_allow_html=True)

    if open_trades:
        st.markdown('<div class="section-title">CAPITAL AT RISK BY ASSET</div>', unsafe_allow_html=True)
        by_asset = defaultdict(float)
        for t in open_trades:
            by_asset[identify_asset(t.question)] += t.bet_size
        acols = st.columns(len(by_asset))
        for col, (asset, amount) in zip(acols, sorted(by_asset.items())):
            pct = amount / total_invested * 100 if total_invested > 0 else 0
            col.markdown(f'<div class="asset-card"><div class="asset-name">{asset}</div><div class="asset-amount">${amount:,.2f}</div><div style="font-size:10px;color:#404060">{pct:.0f}%</div></div>', unsafe_allow_html=True)

    # Open Positions
    st.markdown(f'<div class="section-title">OPEN POSITIONS ({len(open_trades)})</div>', unsafe_allow_html=True)

    if not open_trades:
        st.markdown('<div class="empty-state">No open positions</div>', unsafe_allow_html=True)
    else:
        if "sort_col" not in st.session_state:
            st.session_state.sort_col = "bought"
            st.session_state.sort_asc = False

        def sort_key(t):
            m = live_markets.get(t.market_id)
            yes_cp = get_yes_price(m) if m else None
            cp = yes_cp if t.side == "YES" else (1.0 - yes_cp if yes_cp else None)
            unr = calc_unrealised(t, yes_cp)
            col = st.session_state.sort_col
            if col == "side": return t.side
            if col == "conf": return t.edge
            if col == "stake": return t.bet_size
            if col == "entry": return t.avg_price or 0
            if col == "current": return cp or 0
            if col == "pnl": return unr
            if col == "pnlpct": return unr / t.bet_size if t.bet_size else 0
            if col == "market": return t.question.lower()
            if col == "bought": return t.timestamp
            if col == "closes_in":
                return m.get("endDate", "9999") if m else "9999"
            return ""

        sorted_trades = sorted(open_trades, key=sort_key, reverse=not st.session_state.sort_asc)

        SORT_COLS = [
            ("side", "Side", 0.52), ("conf", "Conf", 0.52), ("stake", "Stake", 0.72),
            ("entry", "Entry", 0.62), (None, "BE", 0.62), ("current", "Current", 0.62),
            ("pnl", "Unreal PnL", 0.88), ("pnlpct", "PnL%", 0.68), ("market", "Market", 5.0),
            ("bought", "Bought", 0.88), ("closes_in", "Closes In", 0.72), (None, "🔗", 0.38)
        ]

        hcols = st.columns([c[2] for c in SORT_COLS])
        for widget, (key, label, _) in zip(hcols, SORT_COLS):
            if key:
                active = st.session_state.sort_col == key
                arrow = " ↑" if active and st.session_state.sort_asc else " ↓" if active else ""
                if widget.button(f"{label}{arrow}", key=f"sort_{key}", use_container_width=True):
                    if st.session_state.sort_col == key:
                        st.session_state.sort_asc = not st.session_state.sort_asc
                    else:
                        st.session_state.sort_col = key
                        st.session_state.sort_asc = True
                    st.rerun()
            else:
                widget.markdown(f'<p class="col-header">{label}</p>', unsafe_allow_html=True)

        for t in sorted_trades:
            m = live_markets.get(t.market_id)
            
            # Determine if this is a gold market
            is_gold_market = "gold" in t.question.lower() or "gc" in t.question.lower()
            
            # Get current price: try API first, then gold spot price for gold markets
            yes_cp = get_yes_price(m) if m else None
            
            if yes_cp is None and is_gold_market:
                # For gold markets, fetch real spot price and convert to probability
                spot_price = get_gold_spot_price()
                # Extract target price from question: "Will Gold (GC) settle over $5,600..."
                target_m = re.search(r'\$?([\d,]+(?:\.\d+)?)', t.question)
                if spot_price and target_m:
                    target_price = float(target_m.group(1).replace(",", ""))
                    yes_cp = gold_price_to_market_price(spot_price, target_price, side="YES")
            
            # Convert to side-aware price
            cp = yes_cp if t.side == "YES" else (1.0 - yes_cp if yes_cp is not None else None)
            
            # Display logic
            if cp is not None:
                cp_display = f"{cp:.3f}"
                is_live_price = True
            else:
                # Price unavailable
                cp_display = "—"
                is_live_price = False
            
            unr = calc_unrealised(t, yes_cp)
            entry = t.avg_price if getattr(t, 'avg_price', 0) > 0 else t.p_market
            be = breakeven_price(t)
            end_dt = m.get("endDate", "") if m else ""
            # Fallback: extract date from question if API didn't provide endDate
            if not end_dt:
                end_dt = extract_expiry_from_question(t.question) or ""
            time_r, time_cls = fmt_time_remaining(end_dt)
            bought = fmt_timestamp(t.timestamp)
            url = polymarket_url(m, t.question, t.market_id)

            cols = st.columns([c[2] for c in SORT_COLS])
            conf_label, conf_cls = confidence_tier(t.edge)

            cols[0].markdown(f'<span class="badge-{"yes" if t.side=="YES" else "no"}">{t.side}</span>', unsafe_allow_html=True)
            cols[1].markdown(f'<span class="{conf_cls}">{conf_label}</span>', unsafe_allow_html=True)
            cols[2].markdown(f'<span class="mono">${t.bet_size:.2f}</span>', unsafe_allow_html=True)
            cols[3].markdown(f'<span class="mono">{entry:.3f}</span>', unsafe_allow_html=True)
            cols[4].markdown(f'<span class="mono" style="color:#8080c0">{be}</span>', unsafe_allow_html=True)
            # Current price: show live if available, else show "—"
            price_style = "color:#ffffff" if is_live_price else "color:#404060"
            cols[5].markdown(f'<span class="mono" style="{price_style}">{cp_display}</span>', unsafe_allow_html=True)
            cols[6].markdown(f'<span class="{pnl_cls(unr)}">{fmt(unr)}</span>', unsafe_allow_html=True)
            pnl_pct_str = f"{'+' if unr >= 0 else ''}{unr/t.bet_size*100:.1f}%" if t.bet_size > 0 else "—"
            cols[7].markdown(f'<span class="{pnl_cls(unr)}">{pnl_pct_str}</span>', unsafe_allow_html=True)
            cols[8].markdown(f'<span class="question-text">{t.question}</span>', unsafe_allow_html=True)
            cols[9].markdown(f'<span class="mono">{bought}</span>', unsafe_allow_html=True)
            cols[10].markdown(f'<span class="{time_cls}">{time_r}</span>', unsafe_allow_html=True)
            cols[11].markdown(f'<a href="{url}" target="_blank" class="link-btn">↗</a>', unsafe_allow_html=True)

    # Resolved Trades
    st.markdown(f'<div class="section-title">RESOLVED TRADES ({len(resolved)})</div>', unsafe_allow_html=True)
    if not resolved:
        st.markdown('<div class="empty-state">No resolved trades yet</div>', unsafe_allow_html=True)
    else:
        hcols = st.columns([0.6, 0.75, 0.75, 0.85, 0.7, 5.0, 0.95])
        for c, h in zip(hcols, ["Side", "Stake", "Result", "PnL", "PnL%", "Market", "Date"]):
            c.markdown(f'<p class="col-header">{h}</p>', unsafe_allow_html=True)

        for t in resolved:
            won = (t.pnl or 0) > 0
            pnl_pct_t = f"{((t.pnl or 0)/t.bet_size*100):+.0f}%" if t.bet_size > 0 else "—"
            cols = st.columns([0.6, 0.75, 0.75, 0.85, 0.7, 5.0, 0.95])
            conf_label, conf_cls = confidence_tier(t.edge)
            cols[0].markdown(f'<span class="badge-{"yes" if t.side=="YES" else "no"}">{t.side}</span> <span class="{conf_cls}">{conf_label}</span>', unsafe_allow_html=True)
            cols[1].markdown(f'<span class="mono">${t.bet_size:.2f}</span>', unsafe_allow_html=True)
            cols[2].markdown(f'<span class="badge-{"won" if won else "lost"}">{"WON ✓" if won else "LOST ✗"}</span>', unsafe_allow_html=True)
            cols[3].markdown(f'<span class="{pnl_cls(t.pnl or 0)}">{fmt(t.pnl or 0)}</span>', unsafe_allow_html=True)
            cols[4].markdown(f'<span class="{pnl_cls(t.pnl or 0)}">{pnl_pct_t}</span>', unsafe_allow_html=True)
            cols[5].markdown(f'<span class="question-text">{t.question}</span>', unsafe_allow_html=True)
            cols[6].markdown(f'<span class="mono">{fmt_timestamp(t.timestamp)}</span>', unsafe_allow_html=True)

    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown(f"<p style='text-align:center;font-family:Space Mono,monospace;font-size:10px;color:#202035'>{len(open_trades)} open · {len(resolved)} resolved · Bankroll ${STARTING_BANKROLL:,.0f}</p>", unsafe_allow_html=True)


render()