import streamlit as st
from streamlit_autorefresh import st_autorefresh
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import Optional

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PolyEdge Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Auto-refresh every 60 seconds
st_autorefresh(interval=60 * 1000, key="autorefresh")

# ── Custom CSS ─────────────────────────────────────────────────────────────────
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
.metric-value {
    font-family: 'Space Mono', monospace;
    font-size: 24px;
    font-weight: 700;
    color: #e8e8f0;
}
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
.badge-yes {
    background: rgba(0, 212, 170, 0.15);
    color: #00d4aa;
    border: 1px solid #00d4aa40;
    padding: 2px 10px;
    border-radius: 20px;
    font-family: 'Space Mono', monospace;
    font-size: 11px;
    font-weight: 700;
}
.badge-no {
    background: rgba(255, 68, 102, 0.15);
    color: #ff4466;
    border: 1px solid #ff446640;
    padding: 2px 10px;
    border-radius: 20px;
    font-family: 'Space Mono', monospace;
    font-size: 11px;
    font-weight: 700;
}
.badge-won {
    background: rgba(0, 212, 170, 0.1);
    color: #00d4aa;
    border: 1px solid #00d4aa30;
    padding: 2px 10px;
    border-radius: 20px;
    font-family: 'Space Mono', monospace;
    font-size: 11px;
}
.badge-lost {
    background: rgba(255, 68, 102, 0.1);
    color: #ff4466;
    border: 1px solid #ff446630;
    padding: 2px 10px;
    border-radius: 20px;
    font-family: 'Space Mono', monospace;
    font-size: 11px;
}
.badge-open {
    background: rgba(255, 180, 0, 0.1);
    color: #ffb400;
    border: 1px solid #ffb40030;
    padding: 2px 10px;
    border-radius: 20px;
    font-family: 'Space Mono', monospace;
    font-size: 11px;
}
.mono { font-family: 'Space Mono', monospace; font-size: 13px; }
.question-text { font-size: 13px; color: #b0b0d0; }
.pnl-positive { color: #00d4aa; font-family: 'Space Mono', monospace; font-weight: 700; }
.pnl-negative { color: #ff4466; font-family: 'Space Mono', monospace; font-weight: 700; }
.pnl-neutral  { color: #6060a0; font-family: 'Space Mono', monospace; }
.dry-run-badge {
    background: rgba(255, 180, 0, 0.1);
    color: #ffb400;
    border: 1px solid #ffb40040;
    padding: 4px 14px;
    border-radius: 20px;
    font-family: 'Space Mono', monospace;
    font-size: 11px;
    letter-spacing: 1px;
}
.resolved-badge {
    background: rgba(0, 212, 170, 0.08);
    color: #00d4aa;
    border: 1px solid #00d4aa20;
    padding: 2px 8px;
    border-radius: 4px;
    font-family: 'Space Mono', monospace;
    font-size: 10px;
}
.empty-state {
    text-align: center;
    padding: 40px;
    font-family: 'Space Mono', monospace;
    font-size: 13px;
    color: #404060;
}
.col-header {
    font-family: 'Space Mono', monospace;
    font-size: 10px;
    color: #303050;
    letter-spacing: 1px;
    text-transform: uppercase;
}
</style>
""", unsafe_allow_html=True)

# ── Constants ──────────────────────────────────────────────────────────────────
GAMMA_API         = "https://gamma-api.polymarket.com"
TRADE_FILE        = "trades.jsonl"
STARTING_BANKROLL = 10000.0


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


# ── I/O ────────────────────────────────────────────────────────────────────────
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


# ── Gamma API ──────────────────────────────────────────────────────────────────
def fetch_market(question: str) -> dict | None:
    q = question.lower()
    asset = next((a for a in ["bitcoin", "ethereum", "solana", "xrp", "gold"] if a in q), None)
    if not asset:
        return None
    date_m = re.search(
        r'(january|february|march|april|may|june|july|august|'
        r'september|october|november|december)\s+(\d{1,2})', q
    )
    if not date_m:
        return None
    date_hint = date_m.group(0).replace(" ", "-")
    # Cache-bust with current minute so prices are always fresh
    ts = int(datetime.now(timezone.utc).timestamp() // 60)
    for slug in [f"{asset}-above-on-{date_hint}", f"{asset}-price-above-on-{date_hint}"]:
        try:
            req = urllib.request.Request(
                f"{GAMMA_API}/events?slug={slug}&_={ts}",
                headers={
                    "User-Agent":  "Mozilla/5.0",
                    "Accept":      "application/json",
                    "Cache-Control": "no-cache, no-store",
                    "Pragma":      "no-cache",
                }
            )
            data = json.loads(urllib.request.urlopen(req, timeout=8).read())
            if not isinstance(data, list):
                continue
            for event in data:
                for m in event.get("markets", []):
                    if m.get("question", "") == question:
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


# ── Resolver ───────────────────────────────────────────────────────────────────
def try_resolve(record: TradeRecord, market: dict) -> tuple[float, float] | None:
    """Check if market has closed and return (outcome, pnl) or None."""
    if not market.get("closed", False):
        return None

    end_date = market.get("endDate", "")
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            if end_dt > datetime.now(timezone.utc):
                return None  # closed flag but endDate in future — skip
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
        pnl     = round(record.bet_size * (1.0 / avg - 1.0), 2) if avg > 0 else 0.0
        outcome = 1.0
    else:
        pnl     = round(-record.bet_size, 2)
        outcome = 0.0

    return outcome, pnl


def run_resolver(trades: list[TradeRecord]) -> tuple[list[TradeRecord], int]:
    """Resolve any closed markets. Returns updated trades + count resolved."""
    resolved_count = 0
    updated        = []
    for record in trades:
        if record.outcome is not None:
            updated.append(record)
            continue
        market = fetch_market(record.question)
        if market:
            result = try_resolve(record, market)
            if result:
                outcome, pnl    = result
                record.outcome  = outcome
                record.pnl      = pnl
                resolved_count += 1
        updated.append(record)
    return updated, resolved_count


# ── Calculations ───────────────────────────────────────────────────────────────
def calc_unrealised(record: TradeRecord, current_yes: float) -> float:
    avg = record.avg_price if record.avg_price and record.avg_price > 0 else record.p_market
    if avg <= 0:
        return 0.0
    if record.side == "YES":
        return round(record.bet_size * (current_yes / avg - 1), 2)
    else:
        entry_no   = 1.0 - avg
        current_no = 1.0 - current_yes
        return round(record.bet_size * (current_no / entry_no - 1), 2) if entry_no > 0 else 0.0


def pnl_cls(v: float) -> str:
    return "pnl-positive" if v > 0 else ("pnl-negative" if v < 0 else "pnl-neutral")


def fmt(v: float) -> str:
    return f"{'+'if v>=0 else ''}${v:.2f}"


# ── Render ─────────────────────────────────────────────────────────────────────
def render():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Load + resolve
    trades = load_trades()
    if trades:
        trades, n_resolved = run_resolver(trades)
        if n_resolved > 0:
            save_trades(trades)
            st.toast(f"✅ {n_resolved} trade(s) resolved!", icon="🎯")

    open_trades = [t for t in trades if t.outcome is None]
    resolved    = sorted([t for t in trades if t.outcome is not None],
                         key=lambda x: x.timestamp, reverse=True)

    # Live prices for open positions
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
    total_pnl    = total_realised + total_unrealised
    bankroll     = STARTING_BANKROLL + total_realised          # realised only
    cash_left    = STARTING_BANKROLL - total_invested          # money not yet committed
    wins         = sum(1 for t in resolved if (t.pnl or 0) > 0)
    losses       = sum(1 for t in resolved if (t.pnl or 0) <= 0)
    win_rate     = f"{wins/(wins+losses)*100:.0f}%" if (wins + losses) > 0 else "—"

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
                    f"font-size:11px;text-align:right'>{now_str}</p>",
                    unsafe_allow_html=True)

    st.markdown("---")

    # ── Metrics row ─────────────────────────────────────────────────────────
    cols = st.columns(7)

    def metric(col, label, value, css="neutral"):
        col.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value {css}">{value}</div>
        </div>""", unsafe_allow_html=True)

    metric(cols[0], "Bankroll",        f"${bankroll:,.2f}")
    metric(cols[1], "Cash Available",  f"${cash_left:,.2f}",
           "positive" if cash_left > 200 else "warning")
    metric(cols[2], "Capital at Risk", f"${total_invested:.2f}",
           "warning" if total_invested > 0 else "neutral")
    metric(cols[3], "Total PnL",       fmt(total_pnl),
           "positive" if total_pnl >= 0 else "negative")
    metric(cols[4], "Realised PnL",    fmt(total_realised),
           "positive" if total_realised >= 0 else "negative")
    metric(cols[5], "Unrealised PnL",  fmt(total_unrealised),
           "positive" if total_unrealised >= 0 else "negative")
    metric(cols[6], "Win Rate",        win_rate,
           "positive" if wins > losses else ("negative" if losses > wins else "neutral"))

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Open Positions ───────────────────────────────────────────────────────
    st.markdown(f'<div class="section-title">Open Positions ({len(open_trades)})</div>',
                unsafe_allow_html=True)

    if not open_trades:
        st.markdown('<div class="empty-state">No open positions</div>',
                    unsafe_allow_html=True)
    else:
        hcols = st.columns([1, 1, 1, 1, 1, 4, 1])
        for c, h in zip(hcols, ["Side", "Stake", "Entry", "Current",
                                  "Unreal. PnL", "Market", "Expires"]):
            c.markdown(f'<p class="col-header">{h}</p>', unsafe_allow_html=True)

        for t in open_trades:
            m     = live_markets.get(t.market_id)
            cp    = get_yes_price(m) if m else None
            unr   = calc_unrealised(t, cp) if cp is not None else None
            entry = t.avg_price if t.avg_price and t.avg_price > 0 else t.p_market
            end   = (m.get("endDate", "")[:10] if m else "—")
            cols  = st.columns([1, 1, 1, 1, 1, 4, 1])

            cols[0].markdown(
                f'<span class="badge-{"yes" if t.side=="YES" else "no"}">{t.side}</span>',
                unsafe_allow_html=True)
            cols[1].markdown(f'<span class="mono">${t.bet_size:.2f}</span>',
                             unsafe_allow_html=True)
            cols[2].markdown(f'<span class="mono">{entry:.3f}</span>',
                             unsafe_allow_html=True)
            cols[3].markdown(
                f'<span class="mono">{cp:.3f}</span>' if cp else
                '<span class="mono" style="color:#404060">—</span>',
                unsafe_allow_html=True)
            cols[4].markdown(
                f'<span class="{pnl_cls(unr)}">{fmt(unr)}</span>' if unr is not None else
                '<span class="pnl-neutral">—</span>',
                unsafe_allow_html=True)
            cols[5].markdown(f'<span class="question-text">{t.question}</span>',
                             unsafe_allow_html=True)
            cols[6].markdown(
                f'<span class="mono" style="font-size:11px;color:#404060">{end}</span>',
                unsafe_allow_html=True)

    # ── Resolved Trades ──────────────────────────────────────────────────────
    st.markdown(f'<div class="section-title">Resolved Trades ({len(resolved)})</div>',
                unsafe_allow_html=True)

    if not resolved:
        st.markdown('<div class="empty-state">No resolved trades yet</div>',
                    unsafe_allow_html=True)
    else:
        hcols = st.columns([1, 1, 1, 1, 4])
        for c, h in zip(hcols, ["Side", "Stake", "Result", "PnL", "Market"]):
            c.markdown(f'<p class="col-header">{h}</p>', unsafe_allow_html=True)

        for t in resolved:
            won  = (t.pnl or 0) > 0
            cols = st.columns([1, 1, 1, 1, 4])
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
            cols[4].markdown(f'<span class="question-text">{t.question}</span>',
                             unsafe_allow_html=True)

    # ── Footer ───────────────────────────────────────────────────────────────
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown(
        f"<p style='text-align:center;font-family:Space Mono,monospace;"
        f"font-size:10px;color:#202035'>"
        f"{len(open_trades)} open · {len(resolved)} resolved · "
        f"Starting bankroll ${STARTING_BANKROLL:,.2f} · "
        f"Refreshes every 60s</p>",
        unsafe_allow_html=True)

    col_center = st.columns([3, 1, 3])[1]
    with col_center:
        if st.button("⟳  Refresh Now", use_container_width=True):
            st.rerun()


render()
