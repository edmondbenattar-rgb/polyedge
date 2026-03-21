import streamlit as st
from streamlit_autorefresh import st_autorefresh
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

# ── Page config ───────────────────────────────────────────────────────────────
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
    padding: 24px;
    text-align: center;
}
.metric-label {
    font-family: 'Space Mono', monospace;
    font-size: 11px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #6060a0;
    margin-bottom: 8px;
}
.metric-value {
    font-family: 'Space Mono', monospace;
    font-size: 28px;
    font-weight: 700;
    color: #e8e8f0;
}
.metric-value.positive { color: #00d4aa; }
.metric-value.negative { color: #ff4466; }
.metric-value.neutral  { color: #8080c0; }

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

.trade-row {
    background: #12121a;
    border: 1px solid #1e1e3a;
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 16px;
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
.mono { font-family: 'Space Mono', monospace; font-size: 13px; }
.question-text { font-size: 14px; color: #b0b0d0; flex: 1; }
.pnl-positive { color: #00d4aa; font-family: 'Space Mono', monospace; font-weight: 700; }
.pnl-negative { color: #ff4466; font-family: 'Space Mono', monospace; font-weight: 700; }
.pnl-neutral  { color: #6060a0; font-family: 'Space Mono', monospace; }

.header-bar {
    background: linear-gradient(90deg, #0d0d1a 0%, #12122a 50%, #0d0d1a 100%);
    border-bottom: 1px solid #1e1e3a;
    padding: 20px 0;
    margin-bottom: 32px;
}
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
.empty-state {
    text-align: center;
    padding: 40px;
    color: #3030608;
    font-family: 'Space Mono', monospace;
    font-size: 13px;
    color: #404060;
}
</style>
""", unsafe_allow_html=True)

# ── Constants ──────────────────────────────────────────────────────────────────
GAMMA_API        = "https://gamma-api.polymarket.com"
TRADE_FILE       = "trades.jsonl"
STARTING_BANKROLL = 1000.0


# ── Data classes ───────────────────────────────────────────────────────────────
@dataclass
class TradeRecord:
    timestamp:   str
    market_id:   str
    question:    str
    side:        str
    p_model:     float
    p_market:    float
    edge:        float
    ev:          float
    kelly_f:     float
    bet_size:    float
    order_id:    str
    avg_price:   float
    pnl:         Optional[float]
    outcome:     Optional[float]
    dry_run:     bool = True


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
    slug = f"{asset}-above-on-{date_hint}"
    try:
        req = urllib.request.Request(
            f"{GAMMA_API}/events?slug={slug}",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        )
        data = json.loads(urllib.request.urlopen(req, timeout=8).read())
        if not isinstance(data, list):
            return None
        for event in data:
            for m in event.get("markets", []):
                if m.get("question", "") == question:
                    return m
    except Exception:
        return None
    return None


def get_current_price(record: TradeRecord) -> float | None:
    m = fetch_market(record.question)
    if not m:
        return None
    try:
        prices = m.get("outcomePrices") or []
        if isinstance(prices, str):
            prices = json.loads(prices)
        return float(prices[0]) if prices else None
    except Exception:
        return None


def calc_unrealised(record: TradeRecord, current_yes: float) -> float:
    avg = record.avg_price if record.avg_price and record.avg_price > 0 else record.p_market
    if avg <= 0:
        return 0.0
    if record.side == "YES":
        return round(record.bet_size * (current_yes / avg - 1), 2)
    else:
        entry_no   = 1.0 - avg
        current_no = 1.0 - current_yes
        if entry_no <= 0:
            return 0.0
        return round(record.bet_size * (current_no / entry_no - 1), 2)


def pnl_color(v: float) -> str:
    if v > 0: return "pnl-positive"
    if v < 0: return "pnl-negative"
    return "pnl-neutral"


def fmt_pnl(v: float) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}${v:.2f}"


# ── Main render ────────────────────────────────────────────────────────────────
def render():
    trades     = load_trades()
    open_trades = [t for t in trades if t.outcome is None]
    resolved    = sorted([t for t in trades if t.outcome is not None],
                         key=lambda x: x.timestamp, reverse=True)

    # Fetch live prices for open positions
    live_prices = {}
    for t in open_trades:
        live_prices[t.market_id] = get_current_price(t)

    # Compute totals
    total_invested   = sum(t.bet_size for t in open_trades)
    total_realised   = sum(t.pnl or 0 for t in resolved)
    total_unrealised = sum(
        calc_unrealised(t, live_prices[t.market_id])
        for t in open_trades
        if live_prices.get(t.market_id) is not None
    )
    total_pnl    = total_realised + total_unrealised
    bankroll     = STARTING_BANKROLL + total_realised
    wins         = sum(1 for t in resolved if (t.pnl or 0) > 0)
    losses       = sum(1 for t in resolved if (t.pnl or 0) <= 0)
    win_rate     = f"{wins/(wins+losses)*100:.0f}%" if (wins + losses) > 0 else "—"
    now_str      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Header ──────────────────────────────────────────────────────────────
    col_title, col_badge, col_time = st.columns([3, 1, 2])
    with col_title:
        st.markdown("# PolyEdge")
        st.markdown("<p style='color:#404060;font-family:Space Mono,monospace;font-size:12px;margin-top:-12px'>PAPER TRADING DASHBOARD</p>", unsafe_allow_html=True)
    with col_badge:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<span class="dry-run-badge">DRY RUN</span>', unsafe_allow_html=True)
    with col_time:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(f"<p style='color:#303050;font-family:Space Mono,monospace;font-size:11px;text-align:right'>{now_str}</p>", unsafe_allow_html=True)

    st.markdown("---")

    # ── Metrics ─────────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)

    def metric(col, label, value, css_class="neutral"):
        col.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value {css_class}">{value}</div>
        </div>""", unsafe_allow_html=True)

    pnl_cls = "positive" if total_pnl >= 0 else "negative"
    re_cls  = "positive" if total_realised >= 0 else "negative"
    ur_cls  = "positive" if total_unrealised >= 0 else "negative"

    metric(c1, "Bankroll",       f"${bankroll:,.2f}")
    metric(c2, "Total PnL",      fmt_pnl(total_pnl),       pnl_cls)
    metric(c3, "Realised PnL",   fmt_pnl(total_realised),  re_cls)
    metric(c4, "Unrealised PnL", fmt_pnl(total_unrealised), ur_cls)
    metric(c5, "Win Rate",       win_rate, "positive" if wins > losses else "neutral")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Open Positions ───────────────────────────────────────────────────────
    st.markdown(f'<div class="section-title">Open Positions ({len(open_trades)})</div>',
                unsafe_allow_html=True)

    if not open_trades:
        st.markdown('<div class="empty-state">No open positions</div>', unsafe_allow_html=True)
    else:
        cols = st.columns([1, 1, 1, 1, 1, 4, 1])
        for c, h in zip(cols, ["Side", "Stake", "Entry", "Current", "Unreal. PnL", "Market", "Expires"]):
            c.markdown(f"<p style='font-family:Space Mono,monospace;font-size:10px;color:#303050;letter-spacing:1px;text-transform:uppercase'>{h}</p>", unsafe_allow_html=True)

        for t in open_trades:
            cp    = live_prices.get(t.market_id)
            unr   = calc_unrealised(t, cp) if cp is not None else None
            entry = t.avg_price if t.avg_price and t.avg_price > 0 else t.p_market
            cols  = st.columns([1, 1, 1, 1, 1, 4, 1])

            side_html = f'<span class="badge-{"yes" if t.side=="YES" else "no"}">{t.side}</span>'
            cols[0].markdown(side_html, unsafe_allow_html=True)
            cols[1].markdown(f'<span class="mono">${t.bet_size:.2f}</span>', unsafe_allow_html=True)
            cols[2].markdown(f'<span class="mono">{entry:.3f}</span>', unsafe_allow_html=True)
            cols[3].markdown(f'<span class="mono">{cp:.3f}</span>' if cp else '<span class="mono">—</span>', unsafe_allow_html=True)

            if unr is not None:
                cols[4].markdown(f'<span class="{pnl_color(unr)}">{fmt_pnl(unr)}</span>', unsafe_allow_html=True)
            else:
                cols[4].markdown('<span class="pnl-neutral">—</span>', unsafe_allow_html=True)

            cols[5].markdown(f'<span class="question-text">{t.question}</span>', unsafe_allow_html=True)

            # Parse end date from market
            m = fetch_market(t.question)
            end = m.get("endDate", "")[:10] if m else "—"
            cols[6].markdown(f'<span class="mono" style="font-size:11px;color:#404060">{end}</span>', unsafe_allow_html=True)

    # ── Resolved Trades ──────────────────────────────────────────────────────
    st.markdown(f'<div class="section-title">Resolved Trades ({len(resolved)})</div>',
                unsafe_allow_html=True)

    if not resolved:
        st.markdown('<div class="empty-state">No resolved trades yet</div>', unsafe_allow_html=True)
    else:
        cols = st.columns([1, 1, 1, 1, 4])
        for c, h in zip(cols, ["Side", "Stake", "Result", "PnL", "Market"]):
            c.markdown(f"<p style='font-family:Space Mono,monospace;font-size:10px;color:#303050;letter-spacing:1px;text-transform:uppercase'>{h}</p>", unsafe_allow_html=True)

        for t in resolved:
            cols = st.columns([1, 1, 1, 1, 4])
            won  = (t.pnl or 0) > 0
            side_html   = f'<span class="badge-{"yes" if t.side=="YES" else "no"}">{t.side}</span>'
            result_html = f'<span class="badge-{"won" if won else "lost"}">{"WON ✓" if won else "LOST ✗"}</span>'
            pnl_html    = f'<span class="{pnl_color(t.pnl or 0)}">{fmt_pnl(t.pnl or 0)}</span>'

            cols[0].markdown(side_html,   unsafe_allow_html=True)
            cols[1].markdown(f'<span class="mono">${t.bet_size:.2f}</span>', unsafe_allow_html=True)
            cols[2].markdown(result_html, unsafe_allow_html=True)
            cols[3].markdown(pnl_html,    unsafe_allow_html=True)
            cols[4].markdown(f'<span class="question-text">{t.question}</span>', unsafe_allow_html=True)

    # ── Footer ───────────────────────────────────────────────────────────────
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown(
        f"<p style='text-align:center;font-family:Space Mono,monospace;font-size:10px;"
        f"color:#202035'>{len(trades)} total trades · "
        f"${total_invested:.2f} at risk · "
        f"Starting bankroll ${STARTING_BANKROLL:,.2f}</p>",
        unsafe_allow_html=True
    )

    # Auto-refresh button
    st.markdown("<br>", unsafe_allow_html=True)
    col_center = st.columns([3, 1, 3])[1]
    with col_center:
        if st.button("⟳  Refresh", use_container_width=True):
            st.rerun()


render()
