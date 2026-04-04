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
def get_current_gold_price() -> float | None:
    """
    Robust multi-source gold spot price fetcher.
    Uses the same philosophy as bot.py _get_current_asset_price() for gold.
    
    Tries multiple sources in order:
    1. Yahoo Finance GC=F (COMEX futures) — most accurate
    2. gold-api.com — very reliable
    3. metals.live — simple & fast
    4. Binance PAXG (tokenized gold) — last resort
    
    Returns None if all sources fail.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }
    
    sources = [
        # 1. Yahoo Finance GC=F
        ("https://query1.finance.yahoo.com/v8/finance/chart/GC=F",
         lambda d: float(d.get("chart", {}).get("result", [{}])[0].get("meta", {}).get("regularMarketPrice", 0))),
        
        # 2. gold-api.com
        ("https://api.gold-api.com/price/XAU",
         lambda d: float(d.get("price") or d.get("Price") or 0)),
        
        # 3. metals.live
        ("https://api.metals.live/v1/spot/gold",
         lambda d: float(d.get("price") or 0)),
        
        # 4. Binance PAXG (tokenized gold)
        ("https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT",
         lambda d: float(d.get("price") or 0)),
    ]
    
    for url, extractor in sources:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode())
            price = extractor(data)
            if price and 500 < price < 10000:  # sanity check for gold spot
                return round(price, 2)
        except Exception:
            continue  # try next source
    
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

def get_market_slug_from_api(condition_id: str) -> str | None:
    """
    Fetch the market slug from Gamma API using conditionId.
    This allows us to build correct Polymarket URLs even if bot.py didn't store the slug.
    Returns the market slug needed to construct: /event/{event_slug}/{market_slug}
    """
    if not condition_id or not isinstance(condition_id, str) or not condition_id.startswith("0x"):
        return None
    
    try:
        # Query Gamma API to find the market by conditionId
        req = urllib.request.Request(
            f"{GAMMA_API}/markets?condition_id={condition_id}",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        data = json.loads(urllib.request.urlopen(req, timeout=5).read())
        
        if isinstance(data, list) and len(data) > 0:
            market = data[0]
            if market.get("slug"):
                return market["slug"]
    except Exception:
        pass
    
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
.sell-confirm { color: #ffb400 !important; font-size: 9px !important; padding: 2px 4px !important; }
.sell-execute { color: #ff4466 !important; font-size: 9px !important; padding: 2px 4px !important; }
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
    Build Polymarket URL:
    - "above" markets: https://polymarket.com/event/{asset}-above-on-{date}/
    - "less than"/"below" markets: https://polymarket.com/event/{asset}-price-on-{date}/
    """
    q = question.lower()
    
    # Detect direction: "above" vs "less than"/"below"
    is_above = "above" in q
    is_below = "less than" in q or "below" in q
    
    # GOLD MARKETS
    if "gold" in q or "gc" in q:
        # Extract price target: "above $4400" or "over $4600"
        price_match = re.search(r'(?:over|above)\s+\$?([\d,]+(?:\.\d+)?)', question, re.IGNORECASE)
        # Extract date: "March 2026", "June 2026", etc.
        date_match = re.search(
            r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})',
            question,
            re.IGNORECASE
        )
        
        if price_match and date_match:
            price = price_match.group(1).replace(",", "")
            month = date_match.group(1).lower()
            year = date_match.group(2)
            # Construct event slug: "gc-over-under-jun-2026"
            event_slug = f"gc-over-under-{month}-{year}"
            # Construct market slug: "gc-above-4400-jun-2026"
            market_slug = f"gc-above-{price}-{month}-{year}"
            return f"https://polymarket.com/event/{event_slug}/{market_slug}"
        
        return "https://polymarket.com"
    
    # CRYPTO MARKETS
    asset_map = {
        "bitcoin": "bitcoin",
        "ethereum": "ethereum",
        "solana": "solana",
        "xrp": "xrp",
    }
    
    for asset_name, display_name in asset_map.items():
        if asset_name in q:
            # Extract date
            date_m = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})', q)
            if date_m:
                month = date_m.group(1).lower()
                day = date_m.group(2)
                date_slug = f"{month}-{day}"
                
                # Choose URL format based on direction
                if is_above:
                    # "above" markets: bitcoin-above-on-march-30
                    event_slug = f"{display_name}-above-on-{date_slug}"
                    return f"https://polymarket.com/event/{event_slug}/"
                elif is_below:
                    # "less than"/"below" markets: bitcoin-price-on-march-30
                    event_slug = f"{display_name}-price-on-{date_slug}"
                    return f"https://polymarket.com/event/{event_slug}/"
                else:
                    # Fallback to above format
                    event_slug = f"{display_name}-above-on-{date_slug}"
                    return f"https://polymarket.com/event/{event_slug}/"
            break
    
    # Fallback to Polymarket home
    return "https://polymarket.com"

@st.cache_data(ttl=300, show_spinner=False)
def fetch_visual_resolution(market_id: str, question: str, side: str, avg_price: float) -> dict | None:
    """
    Fetch final outcome from Gamma API for an expired-but-unresolved trade.
    Cached per (market_id, side, avg_price) for 5 minutes to avoid hammering
    the API on every Streamlit rerun.

    Returns dict with keys: yes_won, pnl, bet_won — or None if API unavailable.
    Never writes to trades.jsonl. Read-only, display-only.
    """
    m = fetch_market(question, market_id)
    if not m:
        return None

    prices = m.get("outcomePrices") or []
    if isinstance(prices, str):
        try:
            import ast
            prices = ast.literal_eval(prices)
        except Exception:
            return None

    if len(prices) < 2:
        return None

    try:
        yes_price = float(prices[0])
    except (ValueError, TypeError):
        return None

    # Only resolve if the market has actually settled (price snapped to 0 or 1)
    if 0.05 < yes_price < 0.95:
        return None  # still live / not yet resolved by Polymarket

    yes_won  = yes_price > 0.5
    bet_won  = (side == "YES" and yes_won) or (side == "NO" and not yes_won)
    entry    = avg_price if avg_price > 0 else 0.5

    if bet_won:
        effective_entry = entry    # avg_price is always side-specific; no flip for NO
        pnl = round(entry * (1.0 / effective_entry - 1.0), 2) if effective_entry > 0 else 0.0
    else:
        pnl = -avg_price  # will be scaled by bet_size at render time

    return {"yes_won": yes_won, "bet_won": bet_won, "raw_pnl_multiplier": pnl}


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
        # Use 12:00 UTC — Polymarket settles crypto markets around midday.
        # Using 23:59:59 caused same-day markets to stay in Open until midnight.
        return f"{year}-{month:02d}-{day:02d}T12:00:00Z"
    
    return None

def fmt_timestamp(ts: str) -> str:
    try: return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%m/%d %H:%M")
    except: return "—"

def breakeven_price(record: TradeRecord) -> str:
    avg = record.avg_price if getattr(record, 'avg_price', 0) > 0 else record.p_market
    if avg <= 0: return "—"
    return f"{avg:.3f}" if record.side == "YES" else f"{1.0 - avg:.3f}"

def calc_unrealised(record: TradeRecord, current_yes: float | None) -> float:
    if current_yes is None or current_yes <= 0 or current_yes >= 1:
        return 0.0
    avg = record.avg_price if getattr(record, 'avg_price', 0) > 0 else record.p_market
    if avg <= 0:
        return 0.0
    if record.side == "YES":
        curr_price = current_yes
        entry = avg
    else:
        curr_price = 1.0 - current_yes
        entry = avg                # avg_price already stores the NO price (side-specific)
    if entry <= 0:
        return 0.0
    if curr_price <= 0:
        return -record.bet_size
    if curr_price >= 1:
        return round(record.bet_size * (1.0 / entry - 1.0), 2)
    return round(record.bet_size * (curr_price / entry - 1.0), 2)

def pnl_cls(v: float) -> str:
    return "pnl-positive" if v > 0 else ("pnl-negative" if v < 0 else "pnl-neutral")

def confidence_tier(edge: float) -> tuple[str, str]:
    if edge >= 0.30: return "HIGH", "badge-high"
    elif edge >= 0.18: return "MED", "badge-medium"
    return "LOW", "badge-low"

def fmt(v: float) -> str:
    return f"{'+' if v >= 0 else ''}${v:.2f}"

def manual_sell(record: TradeRecord) -> tuple[bool, str]:
    """
    Execute a manual sell for an open trade.
    1. Fresh-fetches current YES price from Gamma API.
    2. Computes final PnL using calc_unrealised logic.
    3. Rewrites the matching line in trades.jsonl with outcome + pnl set.
    Returns (success: bool, message: str).
    """
    # Fresh fetch — bypass page-load cache entirely
    m = fetch_market(record.question, record.market_id)
    if m is None:
        return False, "❌ Could not fetch market price. Gamma API unavailable — try again."

    yes_price = get_yes_price(m)
    if yes_price is None:
        return False, "❌ Market returned no price data. Try again in a moment."

    # Compute final PnL (same formula as calc_unrealised)
    avg = record.avg_price if getattr(record, 'avg_price', 0) > 0 else record.p_market
    if avg <= 0:
        return False, "❌ Invalid entry price on record — cannot compute PnL."

    if record.side == "YES":
        curr_price = yes_price
        entry = avg
    else:
        curr_price = 1.0 - yes_price
        entry = avg                # avg already IS the NO price, no flip needed

    if entry <= 0:
        return False, "❌ Invalid entry price computed — cannot sell."

    # Clamp to valid range
    curr_price = max(0.001, min(0.999, curr_price))
    final_pnl  = round(record.bet_size * (curr_price / entry - 1.0), 2)

    # Outcome: 1.0 if curr_price > entry (profitable), 0.0 otherwise — manual sell marker
    outcome_val = round(curr_price, 6)  # store sell price as outcome for audit trail

    # Rewrite trades.jsonl — find matching market_id line, update it
    if not os.path.exists(TRADE_FILE):
        return False, "❌ trades.jsonl not found."

    lines = []
    matched = False
    with open(TRADE_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                lines.append(line)
                continue
            try:
                data = json.loads(line)
                if data.get("market_id") == record.market_id and data.get("timestamp") == record.timestamp and data.get("outcome") is None:
                    data["outcome"]      = outcome_val
                    data["pnl"]          = final_pnl
                    data["manual_sell"]  = True
                    data["sell_time"]    = datetime.now(timezone.utc).isoformat()
                    line = json.dumps(data)
                    matched = True
            except Exception:
                pass
            lines.append(line)

    if not matched:
        return False, "❌ Trade not found in trades.jsonl (already resolved?)."

    with open(TRADE_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")

    direction = "profit" if final_pnl >= 0 else "loss"
    return True, f"✅ Sold at {curr_price:.3f} · PnL: {fmt(final_pnl)} ({direction})"


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
    now = datetime.now(timezone.utc)

    # ── Pre-fetch all unresolved markets (used for both classification + live prices) ──
    # This gives us the API's real endDate so we never misclassify a trade as expired
    # based on the hardcoded T12:00:00Z guess in extract_expiry_from_question.
    all_unresolved = [tr for tr in trades if tr.outcome is None]
    live_markets: dict = {}
    for t in all_unresolved:
        m = fetch_market(t.question, t.market_id)
        if m:
            live_markets[t.market_id] = m

    # ── Classify trades ───────────────────────────────────────────────────────
    # truly_open        : outcome=None AND not yet expired
    # visually_resolved : outcome=None BUT end_date has passed → fetch outcome from API
    # resolved          : outcome is set (bot has written the final result)
    truly_open        = []
    visually_resolved = []
    for t in all_unresolved:
        m = live_markets.get(t.market_id)
        # Prefer API endDate (accurate); fall back to regex extraction
        end_str = (m.get("endDate", "") if m else "") or extract_expiry_from_question(t.question) or ""
        if end_str:
            try:
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                if end_dt < now:
                    visually_resolved.append(t)
                    continue
            except Exception:
                pass
        truly_open.append(t)

    open_trades = truly_open
    bot_resolved = sorted([t for t in trades if t.outcome is not None],
                          key=lambda x: x.timestamp, reverse=True)

    # ── Visual resolution: fetch outcomes for expired trades ──────────────────
    # Cached per (market_id, side, avg_price), TTL=300s. Read-only — no file writes.
    vr_results: dict[str, dict] = {}  # market_id → resolution dict
    for t in visually_resolved:
        res = fetch_visual_resolution(t.market_id, t.question, t.side, t.avg_price or t.p_market)
        if res:
            vr_results[t.market_id] = res

    # Build combined resolved list: bot-resolved first, then visually-resolved
    # Visually-resolved get a synthetic pnl for display; outcome stays None in JSON
    resolved_display = list(bot_resolved)
    for t in sorted(visually_resolved, key=lambda x: x.timestamp, reverse=True):
        res = vr_results.get(t.market_id)
        if res:
            # Compute actual pnl from bet_size
            bet_won = res["bet_won"]
            entry   = t.avg_price if t.avg_price > 0 else t.p_market
            eff_entry = entry      # avg_price is always side-specific; no flip for NO
            pnl_vis = round(t.bet_size * (1.0 / eff_entry - 1.0), 2) if (bet_won and eff_entry > 0) else round(-t.bet_size, 2)
            # Attach visual resolution as extra attrs (display only)
            t._vis_pnl     = pnl_vis        # type: ignore[attr-defined]
            t._vis_won     = bet_won         # type: ignore[attr-defined]
            t._vis_pending = True            # type: ignore[attr-defined]  ← bot hasn't written yet
        else:
            t._vis_pnl     = None            # type: ignore[attr-defined]
            t._vis_won     = None            # type: ignore[attr-defined]
            t._vis_pending = True            # type: ignore[attr-defined]
        resolved_display.append(t)

    # ── Metrics ───────────────────────────────────────────────────────────────
    total_invested   = sum(t.bet_size for t in open_trades)
    total_realised   = sum(t.pnl or 0 for t in bot_resolved)
    # Include visually-resolved pnl in unrealised display so totals add up
    total_unrealised = sum(calc_unrealised(t, get_yes_price(live_markets.get(t.market_id))) for t in open_trades)
    total_pnl        = total_realised + total_unrealised
    bankroll         = STARTING_BANKROLL + total_realised
    cash_left        = STARTING_BANKROLL - total_invested
    wins   = sum(1 for t in bot_resolved if (t.pnl or 0) > 0)
    losses = len(bot_resolved) - wins
    win_rate = f"{wins/(wins+losses)*100:.0f}%" if wins + losses > 0 else "—"
    pnl_pct  = f"{(total_pnl/total_invested*100):+.1f}%" if total_invested > 0 else "—"

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
        if "sell_pending" not in st.session_state:
            st.session_state.sell_pending = None  # market_id awaiting confirmation
        if "sell_msg" not in st.session_state:
            st.session_state.sell_msg = None

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
            ("bought", "Bought", 0.88), ("closes_in", "Closes In", 0.72), (None, "🔗", 0.38), (None, "SELL", 0.55)
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
            
            # Determine market type
            is_gold_market = "gold" in t.question.lower() or "gc" in t.question.lower()
            
            # Get current price: try API first
            yes_cp = get_yes_price(m) if m else None
            
            # Robust gold fallback: multi-source spot price → market inference
            if yes_cp is None and is_gold_market:
                spot_price = get_current_gold_price()
                if spot_price:
                    # Improved regex: handles "above $3200", "over 3150", "below $2900", etc.
                    target_match = re.search(
                        r'(?:above|over|below|under)\s*\$?([\d,]+(?:\.\d+)?)',
                        t.question,
                        re.IGNORECASE
                    )
                    if target_match:
                        try:
                            target_price = float(target_match.group(1).replace(",", ""))
                            is_above = any(
                                word in t.question.lower()
                                for word in ["above", "over", "higher"]
                            )
                            yes_cp = gold_price_to_market_price(
                                spot_price,
                                target_price,
                                side="YES" if is_above else "NO"
                            )
                        except Exception:
                            pass  # regex parse failed, skip
            
            # Universal fallback for ALL assets (crypto + gold)
            # Use entry price if live price unavailable
            if yes_cp is None:
                yes_cp = t.avg_price if getattr(t, 'avg_price', 0) > 0 else t.p_market
            
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

            # Sell button — two-click confirmation per row
            row_key = f"{t.market_id}_{t.timestamp}"
            is_pending = st.session_state.sell_pending == row_key
            if is_pending:
                if cols[12].button("sure?", key=f"sell_confirm_{row_key}", use_container_width=True):
                    success, msg = manual_sell(t)
                    st.session_state.sell_pending = None
                    st.session_state.sell_msg = msg
                    st.rerun()
            else:
                if cols[12].button("✕ sell", key=f"sell_{row_key}", use_container_width=True):
                    st.session_state.sell_pending = row_key
                    st.rerun()

        # Show sell result message (success or error) above the table
        if st.session_state.sell_msg:
            st.info(st.session_state.sell_msg)
            st.session_state.sell_msg = None

    # Resolved Trades
    st.markdown(f'<div class="section-title">RESOLVED TRADES ({len(resolved_display)})</div>', unsafe_allow_html=True)
    if not resolved_display:
        st.markdown('<div class="empty-state">No resolved trades yet</div>', unsafe_allow_html=True)
    else:
        hcols = st.columns([0.6, 0.75, 0.95, 0.85, 0.7, 5.0, 0.95, 0.95])
        for c, h in zip(hcols, ["Side", "Stake", "Result", "PnL", "PnL%", "Market", "Bought", "Closed"]):
            c.markdown(f'<p class="col-header">{h}</p>', unsafe_allow_html=True)

        for t in resolved_display:
            is_vis = getattr(t, "_vis_pending", False)

            if is_vis:
                # Visually-resolved: outcome fetched from Gamma, not yet written by bot
                vis_won = getattr(t, "_vis_won", None)
                vis_pnl = getattr(t, "_vis_pnl", None)

                if vis_won is None:
                    # Gamma API couldn't confirm yet — show as "Awaiting"
                    result_html = '<span style="color:#606080;font-size:10px">⏳ Awaiting</span>'
                    pnl_val     = 0.0
                    pnl_str     = "—"
                    pnl_pct_str = "—"
                else:
                    result_html = (
                        '<span class="badge-won">WON ✓</span> '
                        '<span style="color:#404060;font-size:9px">✅ bot pending</span>'
                        if vis_won else
                        '<span class="badge-lost">LOST ✗</span> '
                        '<span style="color:#404060;font-size:9px">✅ bot pending</span>'
                    )
                    pnl_val     = vis_pnl or 0.0
                    pnl_str     = fmt(pnl_val)
                    pnl_pct_str = f"{pnl_val/t.bet_size*100:+.0f}%" if t.bet_size > 0 else "—"

                end_str      = extract_expiry_from_question(t.question) or ""
                expiry_disp  = fmt_timestamp(end_str) if end_str else "—"

                cols = st.columns([0.6, 0.75, 0.95, 0.85, 0.7, 5.0, 0.95, 0.95])
                conf_label, conf_cls = confidence_tier(t.edge)
                cols[0].markdown(f'<span class="badge-{"yes" if t.side=="YES" else "no"}">{t.side}</span> <span class="{conf_cls}">{conf_label}</span>', unsafe_allow_html=True)
                cols[1].markdown(f'<span class="mono">${t.bet_size:.2f}</span>', unsafe_allow_html=True)
                cols[2].markdown(result_html, unsafe_allow_html=True)
                cols[3].markdown(f'<span class="{pnl_cls(pnl_val)}">{pnl_str}</span>', unsafe_allow_html=True)
                cols[4].markdown(f'<span class="{pnl_cls(pnl_val)}">{pnl_pct_str}</span>', unsafe_allow_html=True)
                cols[5].markdown(f'<span class="question-text">{t.question}</span>', unsafe_allow_html=True)
                cols[6].markdown(f'<span class="mono">{fmt_timestamp(t.timestamp)}</span>', unsafe_allow_html=True)
                cols[7].markdown(f'<span class="mono">{expiry_disp}</span>', unsafe_allow_html=True)

            else:
                # Bot-resolved: outcome + pnl written to trades.jsonl
                won         = (t.pnl or 0) > 0
                pnl_pct_t   = f"{((t.pnl or 0)/t.bet_size*100):+.0f}%" if t.bet_size > 0 else "—"
                m           = live_markets.get(t.market_id)
                end_dt      = m.get("endDate", "") if m else ""
                if not end_dt:
                    end_dt  = extract_expiry_from_question(t.question) or ""
                expiry_disp = fmt_timestamp(end_dt) if end_dt else "—"

                cols = st.columns([0.6, 0.75, 0.95, 0.85, 0.7, 5.0, 0.95, 0.95])
                conf_label, conf_cls = confidence_tier(t.edge)
                cols[0].markdown(f'<span class="badge-{"yes" if t.side=="YES" else "no"}">{t.side}</span> <span class="{conf_cls}">{conf_label}</span>', unsafe_allow_html=True)
                cols[1].markdown(f'<span class="mono">${t.bet_size:.2f}</span>', unsafe_allow_html=True)
                cols[2].markdown(f'<span class="badge-{"won" if won else "lost"}">{"WON ✓" if won else "LOST ✗"}</span>', unsafe_allow_html=True)
                cols[3].markdown(f'<span class="{pnl_cls(t.pnl or 0)}">{fmt(t.pnl or 0)}</span>', unsafe_allow_html=True)
                cols[4].markdown(f'<span class="{pnl_cls(t.pnl or 0)}">{pnl_pct_t}</span>', unsafe_allow_html=True)
                cols[5].markdown(f'<span class="question-text">{t.question}</span>', unsafe_allow_html=True)
                cols[6].markdown(f'<span class="mono">{fmt_timestamp(t.timestamp)}</span>', unsafe_allow_html=True)
                cols[7].markdown(f'<span class="mono">{expiry_disp}</span>', unsafe_allow_html=True)

    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown(f"<p style='text-align:center;font-family:Space Mono,monospace;font-size:10px;color:#202035'>{len(open_trades)} open · {len(visually_resolved)} awaiting bot · {len(bot_resolved)} resolved · Bankroll ${STARTING_BANKROLL:,.0f}</p>", unsafe_allow_html=True)


render()