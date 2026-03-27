"""
Upbit Trading Bot Dashboard
실행: streamlit run dashboard.py --server.port 8502
"""
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

def now_kst():
    return datetime.now(tz=KST)

import pandas as pd
import pyupbit
import streamlit as st
import streamlit.components.v1 as components

from config import UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY, STOP_LOSS_PCT, TOP_N_COINS
from data_fetcher import get_top_coins
from indicators import add_indicators
from trader import PROTECTED_TICKERS

POSITIONS_FILE  = Path(__file__).parent / "positions.json"
TRADE_LOG_FILE  = Path(__file__).parent / "trade_log.txt"
EQUITY_LOG_FILE = Path(__file__).parent / "equity_log.csv"
BOT_HEARTBEAT   = Path(__file__).parent / "heartbeat.txt"
BALANCE_FILE    = Path(__file__).parent / "balance.json"

st.set_page_config(page_title="Upbit Bot", page_icon="📊", layout="wide")
st.markdown("<style>footer{display:none} #MainMenu{display:none} header{display:none} .block-container{padding:0!important;max-width:100%!important}</style>", unsafe_allow_html=True)

# ── helpers ─────────────────────────────────────────────────────────
@st.cache_resource
def get_upbit():
    try:
        return pyupbit.Upbit(UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY)
    except:
        return None

upbit = get_upbit()

def load_balance():
    if BALANCE_FILE.exists():
        return json.loads(BALANCE_FILE.read_text(encoding="utf-8"))
    return {"krw": 0, "open_value": 0, "open_pnl": 0, "total": 0}

def load_positions():
    if POSITIONS_FILE.exists():
        return json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
    return {}

def get_prices(tickers):
    if not tickers: return {}
    p = pyupbit.get_current_price(tickers)
    if isinstance(p, (int, float)): return {tickers[0]: p}
    return p or {}

def bot_status():
    if BOT_HEARTBEAT.exists():
        ts = datetime.fromisoformat(BOT_HEARTBEAT.read_text().strip())
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=KST)
        if now_kst() - ts < timedelta(minutes=10):
            return True
    return False

def append_equity(equity):
    with open(EQUITY_LOG_FILE, "a") as f:
        f.write(f"{now_kst().isoformat()},{equity:.0f}\n")

def load_equity_history():
    if not EQUITY_LOG_FILE.exists(): return []
    df = pd.read_csv(EQUITY_LOG_FILE, names=["time","equity"])
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time")
    df["date"] = df["time"].dt.date
    df = df.groupby("date")["equity"].last().reset_index()
    return [{"x": str(r.date), "y": int(r.equity)} for _, r in df.iterrows()]

def get_market_data(tickers):
    try:
        resp = requests.get("https://api.upbit.com/v1/ticker",
                            params={"markets": ",".join(tickers)}, timeout=5)
        return resp.json()
    except:
        return []

def parse_trades():
    trades = []
    if not TRADE_LOG_FILE.exists(): return trades
    for line in TRADE_LOG_FILE.read_text(encoding="utf-8").splitlines():
        if "✅ BUY" in line or "💰 SELL" in line:
            trades.append(line)
    return list(reversed(trades[-30:]))

def get_log_lines():
    if not TRADE_LOG_FILE.exists(): return []
    lines = TRADE_LOG_FILE.read_text(encoding="utf-8").strip().splitlines()
    return list(reversed(lines[-80:]))

@st.cache_data(ttl=60)
def load_chart_ohlcv(ticker, interval):
    count = 120 if interval == "day" else 200
    df = pyupbit.get_ohlcv(ticker, interval=interval, count=count)
    if df is None: return []
    df = add_indicators(df)
    result = []
    for idx, row in df.iterrows():
        ts = int(idx.timestamp())
        result.append({
            "time": ts,
            "open": round(float(row["open"]),4),
            "high": round(float(row["high"]),4),
            "low":  round(float(row["low"]),4),
            "close":round(float(row["close"]),4),
            "volume": round(float(row["volume"]),2),
            "ma5":  round(float(row["ma"]),4)  if not pd.isna(row["ma"])  else None,
            "ma20": round(float(row["ma20"]),4) if not pd.isna(row["ma20"]) else None,
            "bb_upper": round(float(row["bb_upper"]),4) if not pd.isna(row["bb_upper"]) else None,
            "bb_lower": round(float(row["bb_lower"]),4) if not pd.isna(row["bb_lower"]) else None,
            "rsi": round(float(row["rsi"]),2) if not pd.isna(row["rsi"]) else None,
        })
    return result

# ── fetch data ───────────────────────────────────────────────────────
positions   = load_positions()
balance     = load_balance()
krw         = balance["krw"]
open_value  = balance["open_value"]
open_pnl    = balance["open_pnl"]
total       = balance["total"]
open_tickers = list(positions.keys())
prices      = get_prices(open_tickers)

today_str = now_kst().strftime("%Y-%m-%d")
today_pnl = 0.0
total_trades_count, wins_count, total_pnl_pct_sum = 0, 0, 0.0
if TRADE_LOG_FILE.exists():
    for line in TRADE_LOG_FILE.read_text(encoding="utf-8").splitlines():
        if "💰 SELL" in line and "P&L:" in line:
            try:
                pct = float(line.split("P&L:")[-1].strip().replace("%",""))
                total_trades_count += 1
                if pct > 0: wins_count += 1
                total_pnl_pct_sum += pct
                if today_str in line: today_pnl += pct
            except: pass

win_rate = wins_count / total_trades_count * 100 if total_trades_count else 0
avg_pnl  = total_pnl_pct_sum / total_trades_count if total_trades_count else 0

append_equity(total)
equity_points = load_equity_history()

running = bot_status()
status_label = "Running" if running else "Stopped"
status_color = "#00e676" if running else "#ff1744"
status_bg    = "rgba(0,230,118,0.1)" if running else "rgba(255,23,68,0.1)"
status_border= "rgba(0,230,118,0.25)" if running else "rgba(255,23,68,0.25)"
dot_color    = "#00e676" if running else "#ff1744"

try:
    all_coins = get_top_coins(TOP_N_COINS)
except:
    all_coins = ["KRW-BTC","KRW-ETH","KRW-XRP"]

market_raw = get_market_data(all_coins[:10])
market_rows_html = ""
for i, d in enumerate(market_raw, 1):
    ticker   = d.get("market","")
    price    = d.get("trade_price",0)
    chg      = d.get("signed_change_rate",0) * 100
    is_up    = chg >= 0
    chg_cls  = "mkt-up" if is_up else "mkt-down"
    arr      = "▲" if is_up else "▼"
    lock     = " 🔒" if ticker in PROTECTED_TICKERS else ""
    coin     = ticker.replace("KRW-","")
    market_rows_html += f"""
    <div class="mkt-row">
      <div class="mkt-rank">{i}</div>
      <div class="mkt-coin">{coin}{lock}</div>
      <div class="mkt-price">₩{price:,.1f}</div>
      <div class="mkt-change {chg_cls}">{arr} {abs(chg):.2f}%</div>
    </div>"""

pos_cards_html = ""
if not positions:
    pos_cards_html = '<div style="color:#2a3352;text-align:center;padding:32px;font-size:13px">열린 포지션 없음</div>'
else:
    for ticker, pos in positions.items():
        cp  = prices.get(ticker, pos["buy_price"])
        bp  = pos["buy_price"]
        sp  = bp * (1 - STOP_LOSS_PCT)
        pnl_pct = (cp - bp) / bp * 100
        pnl_krw = pos["amount_krw"] * pnl_pct / 100
        sell_time = datetime.fromisoformat(pos["sell_time"])
        if sell_time.tzinfo is None:
            sell_time = sell_time.replace(tzinfo=KST)
        remaining = sell_time - now_kst()
        rem_str = (f"{int(remaining.total_seconds()//3600)}시간 {int((remaining.total_seconds()%3600)//60)}분 후 매도"
                   if remaining.total_seconds() > 0 else "⚡ 매도 대기")
        price_range = bp * 0.06
        fill_pct = min(max((cp - sp) / (price_range + bp - sp) * 100, 0), 100)
        pnl_class = "pos-pnl-pos" if pnl_pct >= 0 else "pos-pnl-neg"
        bar_class  = "pos-bar-fill-pos" if pnl_pct >= 0 else "pos-bar-fill-neg"
        sign = "+" if pnl_pct >= 0 else ""
        pos_cards_html += f"""
        <div class="pos-card">
          <div class="pos-row1">
            <div><div class="pos-ticker">{ticker}</div><div class="pos-badge">변동성 돌파 <span class="tip" data-tip="당일 시가 + (전일 고가-저가) × 0.5를 현재가가 돌파할 때 발생하는 매수 신호입니다.">ⓘ</span></div></div>
            <div class="{pnl_class}">{sign}{pnl_pct:.2f}%</div>
          </div>
          <div class="pos-bar-wrap">
            <div class="pos-bar-bg"><div class="{bar_class}" style="width:{fill_pct:.1f}%"></div></div>
          </div>
          <div class="pos-row3"><span>🔴 손절 ₩{sp:,.2f}</span><span>현재 ₩{cp:,.2f}</span></div>
          <div class="pos-row4">
            <div class="pos-prices">
              <div class="pos-price-item"><div class="pos-price-label">매수가</div><div class="pos-price-val">₩{bp:,.2f}</div></div>
              <div class="pos-price-item"><div class="pos-price-label">현재가</div><div class="pos-price-val">₩{cp:,.2f}</div></div>
              <div class="pos-price-item"><div class="pos-price-label">손익</div><div class="pos-price-val" style="color:{'var(--green)' if pnl_krw>=0 else 'var(--red)'}">{sign}₩{abs(pnl_krw):,.0f}</div></div>
            </div>
            <div class="pos-deadline">⏱ {rem_str}</div>
          </div>
        </div>"""

prot_cards_html = ""
prot_prices = get_prices(list(PROTECTED_TICKERS))
for ticker in PROTECTED_TICKERS:
    price = prot_prices.get(ticker, 0)
    coin_bal = float(upbit.get_balance(ticker.replace("KRW-","")) or 0)
    value = price * coin_bal
    coin = ticker.replace("KRW-","")
    prot_cards_html += f"""
    <div style="margin-bottom:16px">
      <div style="font-size:22px;font-weight:800;color:var(--amber);letter-spacing:-0.02em">{coin}</div>
      <div style="font-size:24px;font-weight:700;color:var(--text);font-family:var(--mono);letter-spacing:-0.02em">₩{price:,.1f}</div>
      <div style="font-size:11px;color:var(--text2);font-family:var(--mono);margin-top:4px">보유 {coin_bal:.4f} · 평가 ₩{value:,.0f}</div>
    </div>"""

trade_history_html = ""
all_trades = parse_trades()
for line in all_trades[:8]:
    is_buy = "BUY" in line
    dot_cls = "tl-dot-buy" if is_buy else "tl-dot-sell"
    short = line[20:] if len(line) > 20 else line
    icon = "🟢" if is_buy else "🟠"
    trade_history_html += f'<div class="tl-item"><div class="tl-dot {dot_cls}"></div><div class="tl-content">{icon} {short}</div></div>'
if not all_trades:
    trade_history_html = '<div style="color:#2a3352;font-size:12px;padding:8px 0">거래 내역 없음 — 봇을 시작하면 여기에 표시됩니다</div>'

log_lines_html = ""
for line in get_log_lines():
    if "✅ BUY" in line:   css = "log-buy"
    elif "💰 SELL" in line: css = "log-sell"
    else:                    css = "log-info"
    log_lines_html += f'<div class="{css}">{line}</div>'

equity_js   = json.dumps(equity_points)
candle_data = json.dumps(load_chart_ohlcv(all_coins[0] if all_coins else "KRW-BTC", "day"))
coins_opts  = "".join(f'<option value="{c}">{c}</option>' for c in all_coins)

prot_pnl_info = ""
for ticker in PROTECTED_TICKERS:
    price = prot_prices.get(ticker, 0)
    coin_bal = float(upbit.get_balance(ticker.replace("KRW-","")) or 0)
    chg_val = 0.0
    for d in market_raw:
        if d.get("market") == ticker:
            chg_val = d.get("signed_change_rate",0)*100
            break
    arrow = "▲" if chg_val >= 0 else "▼"
    color = "var(--green)" if chg_val >= 0 else "var(--red)"
    prot_pnl_info = f'<div style="font-size:11px;color:{color};margin-top:2px">{arrow} {abs(chg_val):.2f}% (24h)</div>'

now_str = now_kst().strftime("%Y-%m-%d %H:%M:%S")
initial_capital = 1604107

open_pnl_sign = "+" if open_pnl >= 0 else ""
today_pnl_sign = "+" if today_pnl >= 0 else ""
avg_pnl_sign = "+" if avg_pnl >= 0 else ""
total_return_pct = (total - initial_capital) / initial_capital * 100
total_return_sign = "+" if total_return_pct >= 0 else ""

# ── render ───────────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
:root {{
  --bg:        #050810;
  --surface:   rgba(255,255,255,0.026);
  --surface2:  rgba(255,255,255,0.045);
  --border:    rgba(255,255,255,0.055);
  --border2:   rgba(0,212,255,0.2);
  --cyan:      #00d4ff;
  --cyan-dim:  rgba(0,212,255,0.1);
  --green:     #00e676;
  --green-dim: rgba(0,230,118,0.09);
  --red:       #ff1744;
  --red-dim:   rgba(255,23,68,0.09);
  --amber:     #ffab00;
  --text:      #dde4f0;
  --text2:     #6b7a99;
  --text3:     #2a3352;
  --mono:      'JetBrains Mono', monospace;
  --sans:      'Outfit', sans-serif;
  --r:         14px;
  --r2:        20px;
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:var(--sans);background:var(--bg);color:var(--text);min-height:100vh;overflow-x:hidden}}
body::before{{content:'';position:fixed;inset:0;z-index:0;background-image:radial-gradient(circle,rgba(255,255,255,0.035) 1px,transparent 1px);background-size:28px 28px;pointer-events:none}}
body::after{{content:'';position:fixed;top:0;left:10%;right:10%;height:1px;z-index:0;background:linear-gradient(90deg,transparent,var(--cyan),transparent);box-shadow:0 0 60px 4px rgba(0,212,255,0.15);pointer-events:none}}
.wrap{{position:relative;z-index:1;max-width:1440px;margin:0 auto;padding:0 28px 60px}}
/* HEADER */
header{{padding-top:56px!important}}

/* HEADER */
header{{display:flex;align-items:center;justify-content:space-between;padding:22px 0 26px;border-bottom:1px solid var(--border);margin-bottom:30px}}
.logo{{display:flex;align-items:center;gap:14px}}
.logo-icon{{width:38px;height:38px;background:linear-gradient(135deg,var(--cyan),#0066ff);border-radius:10px;display:grid;place-items:center;font-size:18px;box-shadow:0 0 24px rgba(0,212,255,0.28)}}
.logo-text{{font-size:18px;font-weight:700;letter-spacing:-0.02em}}
.logo-sub{{font-size:11px;color:var(--text2);font-weight:400;letter-spacing:0.06em;text-transform:uppercase;margin-top:2px}}
.header-right{{display:flex;align-items:center;gap:14px}}
.status-badge{{display:flex;align-items:center;gap:7px;background:{status_bg};border:1px solid {status_border};border-radius:100px;padding:5px 14px;font-size:12px;font-weight:600;color:{status_color}}}
.status-dot{{width:7px;height:7px;border-radius:50%;background:{dot_color};box-shadow:0 0 6px {dot_color};{'animation:pulse 2s infinite' if running else ''}}}
@keyframes pulse{{0%,100%{{opacity:1;transform:scale(1)}}50%{{opacity:0.5;transform:scale(0.85)}}}}
.last-update{{font-size:11px;color:var(--text3);font-family:var(--mono)}}
.btn-refresh{{background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:7px 16px;font-size:12px;font-weight:600;color:var(--text2);cursor:pointer;font-family:var(--sans);transition:all 0.2s}}
.btn-refresh:hover{{border-color:var(--cyan);color:var(--cyan);background:var(--cyan-dim)}}

/* SECTION LABEL */
.section-label{{font-size:10px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;color:var(--text3);margin:32px 0 14px;display:flex;align-items:center;gap:10px}}
.section-label::after{{content:'';flex:1;height:1px;background:var(--border)}}

/* CARDS */
.cards-4{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--r2);padding:22px 24px;transition:border-color 0.25s,transform 0.25s,box-shadow 0.25s;animation:fadeUp 0.5s ease both}}
.card:hover{{border-color:var(--border2);transform:translateY(-2px);box-shadow:0 8px 32px rgba(0,212,255,0.06)}}
.card-cyan{{border-top:2px solid var(--cyan)}}
.card-green{{border-top:2px solid var(--green)}}
.card-amber{{border-top:2px solid var(--amber)}}
.card-label{{font-size:10px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;color:var(--text2);margin-bottom:10px;display:flex;align-items:center;gap:6px}}
.card-value{{font-size:26px;font-weight:700;letter-spacing:-0.03em;line-height:1;font-family:var(--mono);color:var(--text)}}
.card-delta{{margin-top:10px;font-size:11px;font-weight:600;display:inline-flex;align-items:center;gap:4px;padding:3px 9px;border-radius:6px}}
.delta-pos{{color:var(--green);background:var(--green-dim)}}
.delta-neg{{color:var(--red);background:var(--red-dim)}}
.delta-neu{{color:var(--text2);background:var(--surface2)}}

/* TOOLTIP */
.tip{{display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;border-radius:50%;background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.12);color:var(--text3);font-size:9px;font-weight:700;cursor:help;position:relative;vertical-align:middle;font-style:normal;transition:all 0.15s;font-family:var(--sans);flex-shrink:0}}
.tip:hover{{background:var(--cyan-dim);border-color:rgba(0,212,255,0.4);color:var(--cyan)}}
.tip::after{{content:attr(data-tip);position:absolute;bottom:calc(100% + 8px);left:50%;transform:translateX(-50%);background:#0b1120;border:1px solid rgba(0,212,255,0.25);border-radius:10px;padding:10px 14px;font-size:11px;color:#94a3b8;line-height:1.6;white-space:normal;min-width:200px;max-width:260px;z-index:9999;opacity:0;pointer-events:none;transition:opacity 0.2s;text-align:left;font-weight:400;letter-spacing:0;text-transform:none;box-shadow:0 8px 32px rgba(0,0,0,0.5)}}
.tip:hover::after{{opacity:1}}

/* CHART BOX */
.chart-box{{background:var(--surface);border:1px solid var(--border);border-radius:var(--r2);padding:24px;animation:fadeUp 0.5s ease both}}
.chart-header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px}}
.chart-title{{font-size:13px;font-weight:600;color:var(--text)}}
.chart-meta{{font-size:11px;color:var(--text2);font-family:var(--mono);margin-top:4px}}
.chart-legend{{display:flex;gap:16px}}
.legend-item{{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text2)}}
.legend-dot{{width:8px;height:8px;border-radius:50%}}

/* TWO COL */
.col-2{{display:grid;grid-template-columns:1.4fr 1fr;gap:14px;align-items:start}}

/* POSITION CARD */
.pos-card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:18px 20px;margin-bottom:10px;transition:border-color 0.2s}}
.pos-card:hover{{border-color:var(--border2)}}
.pos-row1{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px}}
.pos-ticker{{font-size:15px;font-weight:700;color:var(--text)}}
.pos-badge{{font-size:10px;font-weight:600;color:var(--cyan);background:var(--cyan-dim);border-radius:5px;padding:2px 8px;margin-top:4px;display:inline-flex;align-items:center;gap:5px}}
.pos-pnl-pos{{font-size:20px;font-weight:700;color:var(--green);font-family:var(--mono)}}
.pos-pnl-neg{{font-size:20px;font-weight:700;color:var(--red);font-family:var(--mono)}}
.pos-bar-wrap{{margin:10px 0}}
.pos-bar-bg{{background:rgba(255,255,255,0.06);height:4px;border-radius:100px;overflow:hidden}}
.pos-bar-fill-pos{{height:100%;background:linear-gradient(90deg,#0066ff,var(--green));border-radius:100px;transition:width 1s ease}}
.pos-bar-fill-neg{{height:100%;background:linear-gradient(90deg,var(--red),#ff6d00);border-radius:100px;transition:width 1s ease}}
.pos-row3{{display:flex;justify-content:space-between;font-size:11px;color:var(--text2);font-family:var(--mono);margin-top:8px}}
.pos-row4{{display:flex;justify-content:space-between;align-items:center;margin-top:10px;padding-top:10px;border-top:1px solid var(--border)}}
.pos-prices{{display:flex;gap:16px;font-size:11px}}
.pos-price-item{{display:flex;flex-direction:column;gap:2px}}
.pos-price-label{{color:var(--text3);font-size:9px;letter-spacing:0.08em;text-transform:uppercase}}
.pos-price-val{{color:var(--text);font-family:var(--mono);font-size:12px;font-weight:500}}
.pos-deadline{{font-size:11px;color:var(--amber);font-family:var(--mono)}}

/* RIGHT PANEL */
.right-panel{{display:flex;flex-direction:column;gap:14px}}
.mini-card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--r2);padding:20px 22px}}
.mini-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}}
.mini-title{{font-size:10px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:var(--text2);display:flex;align-items:center;gap:6px}}
.lock-badge{{font-size:10px;font-weight:700;color:var(--amber);background:rgba(255,171,0,0.1);border:1px solid rgba(255,171,0,0.2);border-radius:5px;padding:2px 8px}}

/* MARKET */
.mkt-row{{display:flex;align-items:center;justify-content:space-between;padding:9px 4px;border-bottom:1px solid rgba(255,255,255,0.03);border-radius:6px;transition:background 0.15s}}
.mkt-row:last-child{{border-bottom:none}}
.mkt-row:hover{{background:var(--surface2)}}
.mkt-rank{{width:18px;font-size:10px;color:var(--text3);font-family:var(--mono)}}
.mkt-coin{{font-size:13px;font-weight:600;color:var(--text);flex:1;padding-left:8px}}
.mkt-price{{font-size:12px;color:var(--text2);font-family:var(--mono);flex:1;text-align:right}}
.mkt-change{{font-size:12px;font-weight:700;font-family:var(--mono);width:72px;text-align:right}}
.mkt-up{{color:var(--green)}}.mkt-down{{color:var(--red)}}

/* TIMELINE */
.tl-item{{display:flex;gap:10px;align-items:flex-start;margin-bottom:8px}}
.tl-dot{{width:8px;height:8px;border-radius:50%;margin-top:4px;flex-shrink:0}}
.tl-dot-buy{{background:var(--green);box-shadow:0 0 6px var(--green)}}
.tl-dot-sell{{background:var(--amber);box-shadow:0 0 6px var(--amber)}}
.tl-content{{flex:1;font-size:12px;color:var(--text2);font-family:var(--mono);line-height:1.5}}

/* CHART CONTROLS */
.chart-controls{{display:flex;gap:8px;align-items:center}}
.coin-select{{background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:5px 12px;color:var(--text);font-family:var(--sans);font-size:12px;cursor:pointer;outline:none}}
.coin-select:focus{{border-color:var(--cyan)}}
.interval-btn{{background:transparent;border:1px solid var(--border);border-radius:8px;padding:5px 12px;color:var(--text2);font-family:var(--sans);font-size:12px;cursor:pointer;transition:all 0.15s}}
.interval-btn:hover,.interval-btn.active{{background:var(--cyan-dim);border-color:var(--cyan);color:var(--cyan)}}

/* LOG */
.log-toggle{{width:100%;background:var(--surface);border:1px solid var(--border);border-radius:var(--r2);padding:16px 22px;display:flex;justify-content:space-between;align-items:center;cursor:pointer;color:var(--text2);font-family:var(--sans);font-size:13px;font-weight:500;transition:all 0.2s}}
.log-toggle:hover{{border-color:var(--border2);color:var(--text)}}
.log-body{{background:var(--surface);border:1px solid var(--border);border-top:none;border-radius:0 0 var(--r2) var(--r2);overflow:hidden;max-height:0;transition:max-height 0.4s ease}}
.log-body.open{{max-height:300px}}
.log-inner{{padding:16px 22px;max-height:260px;overflow-y:auto;font-family:var(--mono);font-size:11px;line-height:1.9}}
.log-inner::-webkit-scrollbar{{width:4px}}
.log-inner::-webkit-scrollbar-thumb{{background:var(--text3);border-radius:2px}}
.log-buy{{color:var(--green)}}.log-sell{{color:var(--amber)}}.log-info{{color:var(--text3)}}

@keyframes fadeUp{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:translateY(0)}}}}
.card:nth-child(1){{animation-delay:0.05s}}.card:nth-child(2){{animation-delay:0.10s}}
.card:nth-child(3){{animation-delay:0.15s}}.card:nth-child(4){{animation-delay:0.20s}}

@media(max-width:1100px){{.cards-4{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:900px){{.col-2{{grid-template-columns:1fr}}}}
@media(max-width:600px){{.cards-4{{grid-template-columns:1fr}}.wrap{{padding:0 14px 40px}}}}
</style>
</head>
<body><div class="wrap">

<!-- HEADER -->
<header>
  <div class="logo">
    <div class="logo-icon">📊</div>
    <div><div class="logo-text">Upbit Trading Bot</div><div class="logo-sub">Automated Strategy · KRW Market</div></div>
  </div>
  <div class="header-right">
    <div class="status-badge"><div class="status-dot"></div>{status_label}</div>
    <div class="last-update">Updated {now_str}</div>
    <button class="btn-refresh" onclick="location.reload()">↻ Refresh</button>
  </div>
</header>

<!-- ASSET OVERVIEW -->
<div class="section-label">Asset Overview</div>
<div class="cards-4">
  <div class="card card-cyan">
    <div class="card-label">총 자산 <span class="tip" data-tip="현금(KRW) + 열린 포지션 평가금액의 합계입니다.">ⓘ</span></div>
    <div class="card-value">₩{total:,.0f}</div>
    <div class="card-delta {'delta-pos' if total_return_pct>=0 else 'delta-neg'}">{'▲' if total_return_pct>=0 else '▼'} {total_return_sign}{total_return_pct:.1f}%  누적</div>
  </div>
  <div class="card">
    <div class="card-label">KRW 잔고 <span class="tip" data-tip="현재 업비트 계좌에 있는 원화 잔고입니다. 새 포지션 매수에 사용됩니다.">ⓘ</span></div>
    <div class="card-value">₩{krw:,.0f}</div>
    <div class="card-delta delta-neu">가용 잔고</div>
  </div>
  <div class="card card-green">
    <div class="card-label">미실현 손익 <span class="tip" data-tip="현재 열린 포지션의 평가 손익입니다. 매도하기 전까지는 확정되지 않습니다.">ⓘ</span></div>
    <div class="card-value">{open_pnl_sign}₩{abs(open_pnl):,.0f}</div>
    <div class="card-delta {'delta-pos' if open_pnl>=0 else 'delta-neg'}">{'▲' if open_pnl>=0 else '▼'} {open_pnl_sign}{abs(open_pnl/(open_value-open_pnl)*100) if open_value-open_pnl>0 else 0:.2f}%</div>
  </div>
  <div class="card">
    <div class="card-label">오늘 실현 손익 <span class="tip" data-tip="오늘 날짜에 매도 완료된 거래들의 손익 합산입니다.">ⓘ</span></div>
    <div class="card-value">{today_pnl_sign}{today_pnl:.2f}%</div>
    <div class="card-delta {'delta-pos' if today_pnl>=0 else 'delta-neg'}">오늘 기준</div>
  </div>
</div>

<!-- TRADE STATS -->
<div class="section-label" style="margin-top:14px">Trade Statistics</div>
<div class="cards-4">
  <div class="card">
    <div class="card-label">누적 거래 수 <span class="tip" data-tip="봇이 실행된 이후 완료된 총 매매 횟수(매도 기준)입니다.">ⓘ</span></div>
    <div class="card-value">{total_trades_count}</div>
    <div class="card-delta delta-neu">승 {wins_count} / 패 {total_trades_count - wins_count}</div>
  </div>
  <div class="card card-green">
    <div class="card-label">승률 <span class="tip" data-tip="수익이 난 거래 수 ÷ 전체 거래 수 × 100입니다. 50% 이상이면 양호합니다.">ⓘ</span></div>
    <div class="card-value">{win_rate:.1f}%</div>
    <div class="card-delta {'delta-pos' if win_rate>=50 else 'delta-neg'}">목표 50% {'달성' if win_rate>=50 else '미달'}</div>
  </div>
  <div class="card">
    <div class="card-label">평균 수익/거래 <span class="tip" data-tip="거래 1건당 평균 수익률입니다. 업비트 수수료(0.05% × 2)가 포함됩니다.">ⓘ</span></div>
    <div class="card-value">{avg_pnl_sign}{avg_pnl:.2f}%</div>
    <div class="card-delta {'delta-pos' if avg_pnl>=0 else 'delta-neg'}">수수료 포함</div>
  </div>
  <div class="card card-cyan">
    <div class="card-label">열린 포지션 <span class="tip" data-tip="현재 보유 중인 코인 수입니다. 최대 5개까지 동시에 보유할 수 있습니다.">ⓘ</span></div>
    <div class="card-value">{len(positions)} <span style="font-size:14px;color:var(--text2)">/ 5</span></div>
    <div class="card-delta delta-neu">슬롯 여유 {5-len(positions)}개</div>
  </div>
</div>

<!-- EQUITY CURVE -->
<div class="section-label">Equity Curve</div>
<div class="chart-box">
  <div class="chart-header">
    <div>
      <div class="chart-title">포트폴리오 가치 추이 <span class="tip" data-tip="대시보드를 열 때마다 현재 자산을 기록합니다. 초기 자본 ₩{initial_capital:,}으로 시작했습니다.">ⓘ</span></div>
      <div class="chart-meta">초기 자본 ₩{initial_capital:,} → 현재 ₩{total:,.0f}</div>
    </div>
    <div class="chart-legend">
      <div class="legend-item"><div class="legend-dot" style="background:var(--cyan)"></div>자산</div>
      <div class="legend-item"><div class="legend-dot" style="background:var(--text3);width:16px;height:2px;border-radius:0"></div>초기자본</div>
    </div>
  </div>
  <canvas id="equityChart" height="80"></canvas>
</div>

<!-- POSITIONS + RIGHT -->
<div class="section-label">Positions & Market</div>
<div class="col-2">
  <div>
    <div style="font-size:11px;font-weight:600;color:var(--text2);margin-bottom:10px;display:flex;align-items:center;gap:6px">
      열린 포지션 <span class="tip" data-tip="봇이 매수한 후 아직 매도하지 않은 코인들입니다. 다음날 오전 9시에 자동 매도됩니다.">ⓘ</span>
    </div>
    {pos_cards_html}
  </div>
  <div class="right-panel">
    <div class="mini-card">
      <div class="mini-header">
        <div class="mini-title">보호 티커 <span class="tip" data-tip="봇이 절대 건드리지 않는 코인입니다. 기존 보유 자산을 보호합니다.">ⓘ</span></div>
        <div class="lock-badge">🔒 PROTECTED</div>
      </div>
      {prot_cards_html}
      {prot_pnl_info}
    </div>
    <div class="mini-card">
      <div class="mini-header" style="margin-bottom:10px">
        <div class="mini-title">시장 현황 (24h) <span class="tip" data-tip="거래량 상위 코인들의 24시간 가격 변동률입니다.">ⓘ</span></div>
        <div style="font-size:10px;color:var(--text3);font-family:var(--mono)">LIVE</div>
      </div>
      {market_rows_html}
    </div>
    <div class="mini-card">
      <div style="font-size:11px;font-weight:600;color:var(--text2);margin-bottom:12px;display:flex;align-items:center;gap:6px">
        최근 거래 <span class="tip" data-tip="봇이 실행한 최근 매수/매도 이력입니다. 🟢 매수, 🟠 매도를 나타냅니다.">ⓘ</span>
      </div>
      <div>{trade_history_html}</div>
    </div>
  </div>
</div>

<!-- PRICE CHART -->
<div class="section-label">Price Chart</div>
<div class="chart-box">
  <div class="chart-header">
    <div class="chart-controls">
      <select class="coin-select" id="coinSelect">{coins_opts}</select>
      <button class="interval-btn active" onclick="changeInterval('day',this)">일봉</button>
      <button class="interval-btn" onclick="changeInterval('240',this)">4시간</button>
      <button class="interval-btn" onclick="changeInterval('60',this)">1시간</button>
      <button class="interval-btn" onclick="changeInterval('15',this)">15분</button>
    </div>
    <div class="chart-legend">
      <div class="legend-item"><div class="legend-dot" style="background:#4ade80"></div>MA5 <span class="tip" data-tip="5일 이동평균선. 단기 추세를 나타냅니다. 매수 조건 중 하나입니다.">ⓘ</span></div>
      <div class="legend-item"><div class="legend-dot" style="background:#f472b6"></div>MA20 <span class="tip" data-tip="20일 이동평균선. 중기 추세를 나타냅니다. 가격이 MA20 위에 있을 때만 매수합니다.">ⓘ</span></div>
      <div class="legend-item"><div class="legend-dot" style="background:var(--amber)"></div>BB <span class="tip" data-tip="볼린저밴드. 상단 돌파 시 매도 신호입니다.">ⓘ</span></div>
    </div>
  </div>
  <div id="priceChart" style="height:360px"></div>
  <div style="margin-top:4px">
    <div style="font-size:10px;color:var(--text3);margin-bottom:4px;display:flex;align-items:center;gap:5px">RSI <span class="tip" data-tip="상대강도지수(Relative Strength Index). 60 미만이면 매수 조건 충족, 70 초과 시 매도 신호입니다.">ⓘ</span></div>
    <div id="rsiChart" style="height:90px"></div>
  </div>
</div>

<!-- TRADE LOG -->
<div class="section-label">Trade Log</div>
<div>
  <button class="log-toggle" onclick="this.nextElementSibling.classList.toggle('open');this.querySelector('.ti').style.transform=this.nextElementSibling.classList.contains('open')?'rotate(180deg)':''">
    <span>📄 전체 거래 로그</span>
    <span class="ti" style="transition:transform 0.3s;font-size:11px">▼</span>
  </button>
  <div class="log-body">
    <div class="log-inner">{log_lines_html}</div>
  </div>
</div>

</div>
<script>
// EQUITY CHART
(function(){{
  const raw = {equity_js};
  if(raw.length < 2) return;
  const ctx = document.getElementById('equityChart').getContext('2d');
  const g = ctx.createLinearGradient(0,0,0,200);
  g.addColorStop(0,'rgba(0,212,255,0.18)'); g.addColorStop(1,'rgba(0,212,255,0.01)');
  new Chart(ctx,{{
    type:'line',
    data:{{
      labels: raw.map(p=>p.x),
      datasets:[
        {{data:raw.map(p=>p.y),borderColor:'#00d4ff',borderWidth:2,backgroundColor:g,fill:true,tension:0.4,pointRadius:0,pointHoverRadius:4,pointHoverBackgroundColor:'#00d4ff'}},
        {{data:raw.map(()=>{initial_capital}),borderColor:'rgba(255,255,255,0.06)',borderWidth:1,borderDash:[4,4],fill:false,pointRadius:0}}
      ]
    }},
    options:{{
      responsive:true,
      plugins:{{legend:{{display:false}},tooltip:{{mode:'index',intersect:false,backgroundColor:'rgba(5,8,16,0.95)',borderColor:'rgba(0,212,255,0.3)',borderWidth:1,titleColor:'#6b7a99',bodyColor:'#dde4f0',callbacks:{{label:c=>`₩${{c.raw.toLocaleString()}}`}}}}}},
      scales:{{
        x:{{grid:{{color:'rgba(255,255,255,0.04)'}},ticks:{{color:'#2a3352',font:{{size:10}},maxTicksLimit:10}}}},
        y:{{grid:{{color:'rgba(255,255,255,0.04)'}},ticks:{{color:'#2a3352',font:{{size:10,family:'JetBrains Mono'}},callback:v=>`₩${{(v/1000).toFixed(0)}}k`}}}}
      }}
    }}
  }});
}})();

// PRICE CHART
const allCandleData = {candle_data};
let priceChart=null, rsiChartObj=null, candleSeries, ma5S, ma20S, bbUS, bbLS, volS, rsiS;

function buildChart(data){{
  if(priceChart){{ priceChart.remove(); rsiChartObj.remove(); }}
  const el=document.getElementById('priceChart'), re=document.getElementById('rsiChart');
  el.innerHTML=''; re.innerHTML='';

  const opts={{layout:{{background:{{color:'transparent'}},textColor:'#4b5675'}},grid:{{vertLines:{{color:'rgba(255,255,255,0.03)'}},horzLines:{{color:'rgba(255,255,255,0.03)'}}}},crosshair:{{mode:LightweightCharts.CrosshairMode.Normal}},rightPriceScale:{{borderColor:'rgba(255,255,255,0.05)'}},timeScale:{{borderColor:'rgba(255,255,255,0.05)',timeVisible:true}}}};

  priceChart=LightweightCharts.createChart(el,{{...opts,height:360}});
  candleSeries=priceChart.addCandlestickSeries({{upColor:'#00e676',downColor:'#ff1744',borderUpColor:'#00e676',borderDownColor:'#ff1744',wickUpColor:'#00e676',wickDownColor:'#ff1744'}});
  candleSeries.setData(data.map(d=>{{return{{time:d.time,open:d.open,high:d.high,low:d.low,close:d.close}}}}));

  ma5S=priceChart.addLineSeries({{color:'#4ade80',lineWidth:1,priceLineVisible:false}});
  ma5S.setData(data.filter(d=>d.ma5).map(d=>{{return{{time:d.time,value:d.ma5}}}}));
  ma20S=priceChart.addLineSeries({{color:'#f472b6',lineWidth:1,priceLineVisible:false}});
  ma20S.setData(data.filter(d=>d.ma20).map(d=>{{return{{time:d.time,value:d.ma20}}}}));
  bbUS=priceChart.addLineSeries({{color:'rgba(255,171,0,0.45)',lineWidth:1,lineStyle:2,priceLineVisible:false}});
  bbUS.setData(data.filter(d=>d.bb_upper).map(d=>{{return{{time:d.time,value:d.bb_upper}}}}));
  bbLS=priceChart.addLineSeries({{color:'rgba(255,171,0,0.45)',lineWidth:1,lineStyle:2,priceLineVisible:false}});
  bbLS.setData(data.filter(d=>d.bb_lower).map(d=>{{return{{time:d.time,value:d.bb_lower}}}}));

  rsiChartObj=LightweightCharts.createChart(re,{{...opts,height:90}});
  rsiS=rsiChartObj.addLineSeries({{color:'#a78bfa',lineWidth:1.5,priceLineVisible:false}});
  rsiS.setData(data.filter(d=>d.rsi).map(d=>{{return{{time:d.time,value:d.rsi}}}}));
  const l55=rsiChartObj.addLineSeries({{color:'rgba(0,230,118,0.3)',lineWidth:1,lineStyle:2,priceLineVisible:false}});
  const l70=rsiChartObj.addLineSeries({{color:'rgba(255,23,68,0.3)',lineWidth:1,lineStyle:2,priceLineVisible:false}});
  if(data.length){{
    l55.setData(data.map(d=>{{return{{time:d.time,value:55}}}}));
    l70.setData(data.map(d=>{{return{{time:d.time,value:70}}}}));
  }}
  priceChart.timeScale().fitContent();
  rsiChartObj.timeScale().fitContent();

  priceChart.timeScale().subscribeVisibleLogicalRangeChange(r=>{{
    if(r) rsiChartObj.timeScale().setVisibleLogicalRange(r);
  }});
}}

buildChart(allCandleData);

function changeInterval(iv, btn){{
  document.querySelectorAll('.interval-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
}}
</script>
</body></html>"""

components.html(html, height=4600, scrolling=True)
