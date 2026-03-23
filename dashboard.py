import streamlit as st
from streamlit_autorefresh import st_autorefresh
import json
import os
import re
import urllib.request
from datetime import datetime, timezone, timedelta
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

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;600;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Syne', sans-serif;
    background-color: #0a0a0f;
    color: #e8e8f0;
}
.stApp { background-color: #0a0a0f; }
h1, h2, h3 { font-family: 'Syne', sans-serif; font-weight: 800; }

.metric-card {
    background: linear-gradient(135deg, #12121a 0%, #1a1a2e 100%);
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    padding: 20px;
    text-align: center;
    height: 100%;
}
.metric-label {
    font-family: 'Space Mono', monospace;
    font-size: 10px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #6060a0;
    margin-bottom: 8px;
}
.metric-value { font-family: 'Space Mono', monospace; font-size: 22px; font-weight: 700; color: #e8e8f0; }
.metric-value.positive { color: #00d4aa; }
.metric-value.negative { color: #ff4466; }
.metric-value.neutral  { color: #8080c0; }
.metric-value.warning  { color: #ffb400; }

.section-title {
    font-family: 'Space Mono', monospace;
    font-size: 11px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: #4040a0;
    border-bottom: 1px solid #1a1a3a;
    padding-bottom: 8px;
    margin: 24px 0 16px 0;
}
.asset-card {
    background: #12121a;
    border: 1px solid #1e1e3a;
    border-radius: 8px;
    padding: 12px 16px;
    text-align: center;
}
.asset-name { font-family: 'Space Mono', monospace; font-size: 11px; color: #6060a0; letter-spacing: 2px; }
.asset-amount { font-family: 'Space Mono', monospace; font-size: 16px; font-weight: 700; color: #ffb400; }
.badge-yes {
    background: rgba(0,212,170,0.15); color: #00d4aa;
    border: 1px solid #00d4aa40; padding: 2px 10px;
    border-radius: 20px; font-family: 'Space Mono', monospace; font-size: 11px; font-weight: 700;
}
.badge-no {
    background: rgba(255,68,102,0.15); color: #ff4466;
    border: 1px solid #ff446640; padding: 2px 10px;
    border-radius: 20px; font-family: 'Space Mono', monospace; font-size: 11px; font-weight: 700;
}
.badge-won { background: rgba(0,212,170,0.1); color: #00d4aa; border: 1px solid #00d4aa30; padding: 2px 10px; border-radius: 20px; font-family: 'Space Mono', monospace; font-size: 11px; }
.badge-lost { background: rgba(255,68,102,0.1); color: #ff4466; border: 1px solid #ff446630; padding: 2px 10px; border-radius: 20px; font-family: 'Space Mono', monospace; font-size: 11px; }
.mono { font-family: 'Space Mono', monospace; font-size: 12px; }
.question-text { font-size: 12px; color: #b0b0d0; }
.pnl-positive { color: #00d4aa; font-family: 'Space Mono', monospace; font-weight: 700; font-size: 12px; }
.pnl-negative { color: #ff4466; font-family: 'Space Mono', monospace; font-weight: 700; font-size: 12px; }
.pnl-neutral  { color: #6060a0; font-family: 'Space Mono', monospace; font-size: 12px; }
.time-urgent  { color: #ff4466; font-family: 'Space Mono', monospace; font-size: 11px; font-weight: 700; }
.time-soon    { color: #ffb400; font-family: 'Space Mono', monospace; font-size: 11px; }
.time-ok      { color: #404060; font-family: 'Space Mono', monospace; font-size: 11px; }
.link-btn { color: #6060c0; font-family: 'Space Mono', monospace; font-size: 11px; text-decoration: none; }
.dry-run-badge {
    background: rgba(255,180,0,0.1); color: #ffb400;
    border: 1px solid #ffb40040; padding: 4px 14px;
    border-radius: 20px; font-family: 'Space Mono', monospace; font-size: 11px;
}
.empty-state { text-align: center; padding: 40px; font-family: 'Space Mono', monospace; font-size: 13px; color: #404060; }
.col-header { font-family: 'Space Mono', monospace; font-size: 10px; color: #303050; letter-spacing: 1px; text-transform: uppercase; }
</style>
""", unsafe_allow_html=True)

# ── Constants ──────────────────────────────────────────────────────────────────
GAMMA_API         = "https://gamma-api.polymarket.com"
TRADE_FILE        = "trades.jsonl"
STARTING_BANKROLL = 10000.0
POLYMARKET_BASE   = "https://polymarket.com/event"


# ── Data class ─────────────────────────────────────────────────────────────────
@dataclass
class TradeRecord:
    timestamp:  str
    market_id:  str
    question:   str
    side:       str
    p_model:    float
    p_market:   float
    edge:       float
    ev:         float
    kelly_f:    float
    bet_size:   float
    order_id:   str
    avg_price:  float
    pnl:        Optional[float]
    outcome:    Optional[float]
    dry_run:    bool = True


# ── Helpers ────────────────────────────────────────────────────────────────────
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


def save_trades(records: list[TradeRecord]):
    with open(TRADE_FILE, "w") as f:
        for r in records:
            f.write(json.dumps(asdict(r)) + "\n")


def fetch_market(question: str) -> dict | None:
    q = question.lower()
    asset = next((a for a in ["bitcoin", "ethereum", "solana", "xrp", "gold"] if a in q), None)
    if not asset:
        return None
    date_m = re.search(
        r'(january|february|march|april|may|june|july|august|'
        r'september|october|november|december)\s+(\d{1,2})', q)
    if not date_m:
        return None
    date_hint = date_m.group(0).replace(" ", "-")
    ts = int(datetime.now(timezone.utc).timestamp() // 60)
    for slug in [f"{asset}-above-on-{date_hint}", f"{asset}-price-above-on-{date_hint}"]:
        try:
            req = urllib.request.Request(
                f"{GAMMA_API}/events?slug={slug}&_={ts}",
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                         "Cache-Control": "no-cache"})
            data = json.loads(urllib.request.urlopen(req, timeout=8).read())
            if not isinstance(data, list):
                continue
            for event in data:
                for m in event.get("markets", []):
                    if m.get("question", "") == question:
                        m["_slug"] = slug
                        return m
        except Exception:
            continue
    return None


def get_yes_price(market: dict) -> float | None:
    try:
        prices = market.get("outcomePrices") or []
        if isinstance(prices, str):
            prices = json.loads(prices)
        return float(prices[0]) if prices else None
    except Exception:
        return None


def polymarket_url(market: dict | None, question: str) -> str:
    if market and market.get("_slug"):
        return f"{POLYMARKET_BASE}/{market['_slug']}"
    # Fallback: construct from question
    q = question.lower()
    asset = next((a for a in ["bitcoin", "ethereum", "solana", "xrp", "gold"] if a in q), "")
    date_m = re.search(r'(january|february|march|april|may|june|july|august|'
                       r'september|october|november|december)\s+(\d{1,2})', q)
    if asset and date_m:
        date_hint = date_m.group(0).replace(" ", "-")
        return f"{POLYMARKET_BASE}/{asset}-above-on-{date_hint}"
    return "https://polymarket.com"


def fmt_time_remaining(end_date_str: str) -> tuple[str, str]:
    """Returns (text, css_class)"""
    if not end_date_str:
        return "—", "time-ok"
    try:
        end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        now    = datetime.now(timezone.utc)
        delta  = end_dt - now
        if delta.total_seconds() < 0:
            return "Expired", "time-urgent"
        hours   = delta.total_seconds() / 3600
        if hours < 1:
            mins = int(delta.total_seconds() / 60)
            return f"{mins}m", "time-urgent"
        elif hours < 6:
            return f"{hours:.1f}h", "time-urgent"
        elif hours < 24:
            return f"{hours:.0f}h", "time-soon"
        else:
            days = hours / 24
            return f"{days:.1f}d", "time-ok"
    except Exception:
        return "—", "time-ok"


def fmt_timestamp(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%m/%d %H:%M")
    except Exception:
        return "—"


def breakeven_price(record: TradeRecord) -> str:
    avg = record.avg_price if record.avg_price and record.avg_price > 0 else record.p_market
    if avg <= 0:
        return "—"
    if record.side == "YES":
        return f"{avg:.3f}"
    else:
        return f"{1.0 - avg:.3f}"


def try_resolve(record: TradeRecord, market: dict) -> tuple[float, float] | None:
    if not market.get("closed", False):
        return None
    end_date = market.get("endDate", "")
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            if end_dt > datetime.now(timezone.utc):
                return None
        except Exception:
            pass
    prices = market.get("outcomePrices") or []
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except Exception:
            return None
    if len(prices) < 2:
        return None
    try:
        yes_price = float(prices[0])
    except (ValueError, TypeError):
        return None
    yes_won = yes_price > 0.5
    bet_won = (record.side == "YES" and yes_won) or (record.side == "NO" and not yes_won)
    avg = record.avg_price if record.avg_price and record.avg_price > 0 else record.p_market
    if bet_won:
        if record.side == "YES":
            entry = avg
        else:
            # For NO trades, avg_price is stored as YES price — convert to NO price
            entry = 1.0 - avg
        pnl     = round(record.bet_size * (1.0 / entry - 1.0), 2) if entry > 0 else 0.0
        outcome = 1.0
    else:
        pnl     = round(-record.bet_size, 2)
        outcome = 0.0
    return outcome, pnl


def run_resolver(trades: list[TradeRecord]) -> tuple[list[TradeRecord], int]:
    resolved_count = 0
    updated = []
    for record in trades:
        if record.outcome is not None:
            updated.append(record)
            continue
        market = fetch_market(record.question)
        if market:
            result = try_resolve(record, market)
            if result:
                outcome, pnl   = result
                record.outcome = outcome
                record.pnl     = pnl
                resolved_count += 1
        updated.append(record)
    return updated, resolved_count


def calc_unrealised(record: TradeRecord, current_yes: float) -> float:
    """Calculate unrealised PnL. avg_price is stored as the side price paid."""
    avg = record.avg_price if record.avg_price and record.avg_price > 0 else record.p_market
    if avg <= 0:
        return 0.0
    if record.side == "YES":
        # avg = YES entry price, current = current YES price
        return round(record.bet_size * (current_yes / avg - 1), 2)
    else:
        # avg = NO entry price (already 1 - yes_price at time of entry)
        current_no = 1.0 - current_yes
        return round(record.bet_size * (current_no / avg - 1), 2) if avg > 0 else 0.0


def pnl_cls(v: float) -> str:
    return "pnl-positive" if v > 0 else ("pnl-negative" if v < 0 else "pnl-neutral")


def fmt(v: float) -> str:
    return f"{'+'if v>=0 else ''}${v:.2f}"


def identify_asset(question: str) -> str:
    q = question.lower()
    if "bitcoin" in q or "btc" in q: return "BTC"
    if "ethereum" in q or "eth" in q: return "ETH"
    if "solana" in q or "sol" in q: return "SOL"
    if "xrp" in q: return "XRP"
    if "gold" in q: return "GOLD"
    return "OTHER"


# ── Render ─────────────────────────────────────────────────────────────────────
def render():
    now     = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M UTC")

    # Load trades — trust outcome field only, no auto-resolving
    # Resolution is handled by the bot locally
    trades = load_trades()
    if not trades:
        trades = []

    open_trades = [t for t in trades if t.outcome is None]
    resolved    = sorted([t for t in trades if t.outcome is not None],
                         key=lambda x: x.timestamp, reverse=True)

    # Live market data
    live_markets = {}
    for t in open_trades:
        m = fetch_market(t.question)
        if m:
            live_markets[t.market_id] = m

    # Totals
    total_invested   = sum(t.bet_size for t in open_trades)
    total_realised   = sum(t.pnl or 0 for t in resolved)
    total_unrealised = sum(
        calc_unrealised(t, get_yes_price(live_markets[t.market_id]))
        for t in open_trades
        if t.market_id in live_markets and get_yes_price(live_markets[t.market_id]) is not None
    )
    total_pnl  = total_realised + total_unrealised
    bankroll   = STARTING_BANKROLL + total_realised
    cash_left  = STARTING_BANKROLL - total_invested
    wins       = sum(1 for t in resolved if (t.pnl or 0) > 0)
    losses     = sum(1 for t in resolved if (t.pnl or 0) <= 0)
    win_rate   = f"{wins/(wins+losses)*100:.0f}%" if (wins + losses) > 0 else "—"
    pnl_pct    = f"{(total_pnl/total_invested*100):+.1f}%" if total_invested > 0 else "—"

    # Last scan time (most recent trade timestamp)
    last_trade_ts = max((t.timestamp for t in trades), default=None)
    if last_trade_ts:
        try:
            lt = datetime.fromisoformat(last_trade_ts)
            age_mins = int((now - lt).total_seconds() / 60)
            last_scan = f"{age_mins}m ago" if age_mins < 60 else f"{age_mins//60}h ago"
        except:
            last_scan = "—"
    else:
        last_scan = "—"

    # ── Header ──────────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns([3, 1, 2])
    with c1:
        st.markdown("# PolyEdge")
        st.markdown("<p style='color:#404060;font-family:Space Mono,monospace;"
                    "font-size:12px;margin-top:-12px'>PAPER TRADING DASHBOARD</p>",
                    unsafe_allow_html=True)
    with c2:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<span class="dry-run-badge">DRY RUN</span>', unsafe_allow_html=True)
    with c3:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(f"<p style='color:#303050;font-family:Space Mono,monospace;"
                    f"font-size:11px;text-align:right'>{now_str}<br>"
                    f"<span style='color:#202040'>Last trade: {last_scan}</span></p>",
                    unsafe_allow_html=True)

    st.markdown("---")

    # ── Metrics ─────────────────────────────────────────────────────────────
    cols = st.columns(8)

    def metric(col, label, value, css="neutral"):
        col.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value {css}">{value}</div>
        </div>""", unsafe_allow_html=True)

    metric(cols[0], "Bankroll",        f"${bankroll:,.2f}")
    metric(cols[1], "Cash Available",  f"${cash_left:,.2f}",
           "positive" if cash_left > 500 else "warning")
    metric(cols[2], "Capital at Risk", f"${total_invested:.2f}",
           "warning" if total_invested > 0 else "neutral")
    metric(cols[3], "PnL % on Risk",   pnl_pct,
           "positive" if total_pnl >= 0 else "negative")
    metric(cols[4], "Total PnL",       fmt(total_pnl),
           "positive" if total_pnl >= 0 else "negative")
    metric(cols[5], "Realised PnL",    fmt(total_realised),
           "positive" if total_realised >= 0 else "negative")
    metric(cols[6], "Unrealised PnL",  fmt(total_unrealised),
           "positive" if total_unrealised >= 0 else "negative")
    metric(cols[7], "Win Rate",        win_rate,
           "positive" if wins > losses else ("negative" if losses > wins else "neutral"))

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Per-asset breakdown ──────────────────────────────────────────────────
    if open_trades:
        st.markdown('<div class="section-title">Capital at Risk by Asset</div>',
                    unsafe_allow_html=True)
        by_asset = defaultdict(float)
        for t in open_trades:
            by_asset[identify_asset(t.question)] += t.bet_size

        acols = st.columns(len(by_asset))
        for col, (asset, amount) in zip(acols, sorted(by_asset.items())):
            pct = amount / total_invested * 100 if total_invested > 0 else 0
            col.markdown(f"""
            <div class="asset-card">
                <div class="asset-name">{asset}</div>
                <div class="asset-amount">${amount:,.2f}</div>
                <div style="font-family:Space Mono,monospace;font-size:10px;color:#404060">{pct:.0f}%</div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

    # ── Open Positions ───────────────────────────────────────────────────────
    st.markdown(f'<div class="section-title">Open Positions ({len(open_trades)})</div>',
                unsafe_allow_html=True)

    if not open_trades:
        st.markdown('<div class="empty-state">No open positions</div>', unsafe_allow_html=True)
    else:
        headers = ["Side", "Stake", "Entry", "Break-even", "Current",
                   "Unreal. PnL", "Market", "Bought", "Closes In", "⏱", "🔗"]
        hcols = st.columns([0.6, 0.7, 0.7, 0.8, 0.7, 0.9, 3.5, 0.9, 0.8, 0.4, 0.4])
        for c, h in zip(hcols, headers):
            c.markdown(f'<p class="col-header">{h}</p>', unsafe_allow_html=True)

        # Sort by closest expiry first
        def get_end(t):
            m = live_markets.get(t.market_id)
            return m.get("endDate", "9999") if m else "9999"

        for t in sorted(open_trades, key=get_end):
            m      = live_markets.get(t.market_id)
            yes_cp  = get_yes_price(m) if m else None
            # Show correct side price in CURRENT column
            cp      = yes_cp if t.side == "YES" else (1.0 - yes_cp if yes_cp is not None else None)
            unr     = calc_unrealised(t, yes_cp) if yes_cp is not None else None
            # Entry price is already stored correctly per side (avg_price = side price)
            entry   = t.avg_price if t.avg_price and t.avg_price > 0 else t.p_market
            be     = breakeven_price(t)
            end_dt = m.get("endDate", "") if m else ""
            time_r, time_cls = fmt_time_remaining(end_dt)
            bought = fmt_timestamp(t.timestamp)
            # Full datetime for tooltip
            close_full = end_dt[:16].replace("T", " ") + " UTC" if end_dt else "—"
            url    = polymarket_url(m, t.question)

            cols = st.columns([0.6, 0.7, 0.7, 0.8, 0.7, 0.9, 3.5, 0.9, 0.8, 0.4, 0.4])
            cols[0].markdown(
                f'<span class="badge-{"yes" if t.side=="YES" else "no"}">{t.side}</span>',
                unsafe_allow_html=True)
            cols[1].markdown(f'<span class="mono">${t.bet_size:.2f}</span>',
                             unsafe_allow_html=True)
            cols[2].markdown(f'<span class="mono">{entry:.3f}</span>',
                             unsafe_allow_html=True)
            cols[3].markdown(f'<span class="mono" style="color:#8080c0">{be}</span>',
                             unsafe_allow_html=True)
            cols[4].markdown(
                f'<span class="mono">{cp:.3f}</span>' if cp else
                '<span class="mono" style="color:#404060">—</span>',
                unsafe_allow_html=True)
            cols[5].markdown(
                f'<span class="{pnl_cls(unr)}">{fmt(unr)}</span>' if unr is not None else
                '<span class="pnl-neutral">—</span>',
                unsafe_allow_html=True)
            cols[6].markdown(f'<span class="question-text">{t.question}</span>',
                             unsafe_allow_html=True)
            cols[7].markdown(
                f'<span class="mono" style="font-size:10px;color:#404060">{bought}</span>',
                unsafe_allow_html=True)
            cols[8].markdown(
                f'<span class="mono" style="font-size:10px;color:#404060" title="{close_full}">{close_full[:10]}</span>',
                unsafe_allow_html=True)
            cols[9].markdown(
                f'<span class="{time_cls}">{time_r}</span>',
                unsafe_allow_html=True)
            cols[10].markdown(
                f'<a href="{url}" target="_blank" class="link-btn">↗</a>',
                unsafe_allow_html=True)

    # ── Resolved Trades ──────────────────────────────────────────────────────
    st.markdown(f'<div class="section-title">Resolved Trades ({len(resolved)})</div>',
                unsafe_allow_html=True)

    if not resolved:
        st.markdown('<div class="empty-state">No resolved trades yet</div>',
                    unsafe_allow_html=True)
    else:
        hcols = st.columns([0.6, 0.8, 0.8, 0.8, 0.8, 4, 0.9])
        for c, h in zip(hcols, ["Side", "Stake", "Result", "PnL", "PnL%", "Market", "Bought"]):
            c.markdown(f'<p class="col-header">{h}</p>', unsafe_allow_html=True)

        for t in resolved:
            won      = (t.pnl or 0) > 0
            pnl_pct_t = f"{((t.pnl or 0)/t.bet_size*100):+.0f}%" if t.bet_size > 0 else "—"
            cols = st.columns([0.6, 0.8, 0.8, 0.8, 0.8, 4, 0.9])
            cols[0].markdown(
                f'<span class="badge-{"yes" if t.side=="YES" else "no"}">{t.side}</span>',
                unsafe_allow_html=True)
            cols[1].markdown(f'<span class="mono">${t.bet_size:.2f}</span>',
                             unsafe_allow_html=True)
            cols[2].markdown(
                f'<span class="badge-{"won" if won else "lost"}">{"WON ✓" if won else "LOST ✗"}</span>',
                unsafe_allow_html=True)
            cols[3].markdown(
                f'<span class="{pnl_cls(t.pnl or 0)}">{fmt(t.pnl or 0)}</span>',
                unsafe_allow_html=True)
            cols[4].markdown(
                f'<span class="{pnl_cls(t.pnl or 0)}">{pnl_pct_t}</span>',
                unsafe_allow_html=True)
            cols[5].markdown(f'<span class="question-text">{t.question}</span>',
                             unsafe_allow_html=True)
            cols[6].markdown(
                f'<span class="mono" style="font-size:10px;color:#404060">{fmt_timestamp(t.timestamp)}</span>',
                unsafe_allow_html=True)

    # ── Footer ───────────────────────────────────────────────────────────────
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown(
        f"<p style='text-align:center;font-family:Space Mono,monospace;"
        f"font-size:10px;color:#202035'>"
        f"{len(open_trades)} open · {len(resolved)} resolved · "
        f"Starting bankroll ${STARTING_BANKROLL:,.2f} · Refreshes every 60s</p>",
        unsafe_allow_html=True)

    col_center = st.columns([3, 1, 3])[1]
    with col_center:
        if st.button("⟳  Refresh Now", use_container_width=True):
            st.rerun()


render()
