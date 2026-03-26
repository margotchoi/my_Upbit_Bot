import json
import logging
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pyupbit

from config import (
    UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY,
    RSI_BUY_MAX, RSI_SELL_MIN, STOP_LOSS_PCT,
    POSITION_SIZE_PCT, MAX_POSITIONS, MIN_TRADE_KRW,
    TOP_N_COINS, VOLUME_MULTIPLIER, EXCLUDED_TICKERS,
)
from data_fetcher import get_top_coins, get_ohlcv
from indicators import add_indicators

# ── 절대 건드리지 않을 티커 ──────────────────────────────────────
PROTECTED_TICKERS = {"KRW-DOGE"}

POSITIONS_FILE = Path(__file__).parent / "positions.json"

class KSTFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        ct = datetime.fromtimestamp(record.created, tz=ZoneInfo("Asia/Seoul"))
        return ct.strftime("%Y-%m-%d %H:%M:%S")

_formatter = KSTFormatter("%(asctime)s  %(levelname)s  %(message)s")
_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(_formatter)
_file_handler = logging.FileHandler("trade_log.txt", encoding="utf-8")
_file_handler.setFormatter(_formatter)

logging.basicConfig(level=logging.INFO, handlers=[_stream_handler, _file_handler])
log = logging.getLogger(__name__)


class UpbitTrader:
    def __init__(self):
        self.upbit = pyupbit.Upbit(UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY)
        self.positions: dict = self._load_positions()
        log.info("UpbitTrader initialized.")
        log.info(f"Protected tickers (never touched): {PROTECTED_TICKERS}")

    # ── Position persistence ────────────────────────────────────────

    def _load_positions(self) -> dict:
        if POSITIONS_FILE.exists():
            return json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
        return {}

    def _save_positions(self):
        POSITIONS_FILE.write_text(
            json.dumps(self.positions, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Balance ─────────────────────────────────────────────────────

    def get_krw_balance(self) -> float:
        bal = self.upbit.get_balance("KRW")
        return float(bal) if bal else 0.0

    def get_coin_balance(self, ticker: str) -> float:
        coin = ticker.replace("KRW-", "")
        bal = self.upbit.get_balance(coin)
        return float(bal) if bal else 0.0

    # ── Signal checks ───────────────────────────────────────────────

    def _get_indicators(self, ticker: str) -> tuple[pd.Series | None, pd.Series | None]:
        """Returns (yesterday_row, today_row) from daily candles."""
        df = get_ohlcv(ticker, days=60)
        if df is None or len(df) < 30:
            return None, None
        df = add_indicators(df)
        return df.iloc[-2], df.iloc[-1]   # yesterday (complete), today (partial)

    def check_buy_signal(self, ticker: str) -> tuple[bool, float | None]:
        yesterday, today = self._get_indicators(ticker)
        if yesterday is None or today is None:
            return False, None

        # Need valid indicators
        for col in ["target", "rsi", "ma", "ma20", "volume_ma20"]:
            if pd.isna(yesterday[col]) or pd.isna(today[col]):
                return False, None

        target_price = today["target"]
        current_price = pyupbit.get_current_price(ticker)
        if not current_price:
            return False, None

        # ── Buy conditions ──
        if target_price <= today["open"]:           # target must be above open
            return False, None
        if current_price < target_price:            # breakout not yet triggered
            return False, None
        if yesterday["rsi"] >= RSI_BUY_MAX:         # RSI < 55 (yesterday's completed)
            return False, None
        if yesterday["close"] <= yesterday["ma"]:   # price above MA5
            return False, None
        if yesterday["close"] <= yesterday["ma20"]: # price above MA20 (trend)
            return False, None
        if today["volume"] < today["volume_ma20"] * VOLUME_MULTIPLIER:  # volume spike
            return False, None

        return True, target_price

    def check_sell_signal(self, ticker: str, position: dict) -> tuple[bool, str]:
        current_price = pyupbit.get_current_price(ticker)
        if not current_price:
            return False, ""

        buy_price = position["buy_price"]
        sell_time = datetime.fromisoformat(position["sell_time"])

        # ── 1. 9AM scheduled sell ──
        if datetime.now() >= sell_time:
            return True, "9AM Sell"

        # ── 2. Stop loss ──
        if current_price <= buy_price * (1 - STOP_LOSS_PCT):
            return True, f"Stop Loss ({(current_price/buy_price - 1)*100:.2f}%)"

        # ── 3. RSI / BB upper (daily candles) ──
        _, today = self._get_indicators(ticker)
        if today is not None:
            if not pd.isna(today["rsi"]) and today["rsi"] > RSI_SELL_MIN:
                return True, f"RSI Overbought ({today['rsi']:.1f})"
            if not pd.isna(today["bb_upper"]) and current_price >= today["bb_upper"]:
                return True, f"BB Upper Break"

        return False, ""

    # ── Order execution ─────────────────────────────────────────────

    def execute_buy(self, ticker: str, amount_krw: float) -> bool:
        try:
            order = self.upbit.buy_market_order(ticker, amount_krw)
            if not order or "error" in order:
                log.error(f"BUY FAILED {ticker}: {order}")
                return False

            now = datetime.now()
            # Sell at 9AM the next calendar day
            next_9am = (now + timedelta(days=1)).replace(
                hour=9, minute=0, second=0, microsecond=0
            )
            current_price = pyupbit.get_current_price(ticker)

            self.positions[ticker] = {
                "buy_price": current_price,
                "amount_krw": round(amount_krw),
                "buy_time": now.isoformat(),
                "sell_time": next_9am.isoformat(),
            }
            self._save_positions()
            log.info(
                f"✅ BUY  {ticker} | price: {current_price:,} | "
                f"amount: {amount_krw:,.0f} KRW | sell by: {next_9am.strftime('%m/%d %H:%M')}"
            )
            return True
        except Exception as e:
            log.error(f"BUY EXCEPTION {ticker}: {e}")
            return False

    def execute_sell(self, ticker: str, reason: str) -> bool:
        try:
            units = self.get_coin_balance(ticker)
            if units <= 0:
                log.warning(f"SELL skipped {ticker}: no balance found")
                del self.positions[ticker]
                self._save_positions()
                return False

            order = self.upbit.sell_market_order(ticker, units)
            if not order or "error" in order:
                log.error(f"SELL FAILED {ticker}: {order}")
                return False

            current_price = pyupbit.get_current_price(ticker)
            buy_price = self.positions[ticker]["buy_price"]
            pnl = (current_price - buy_price) / buy_price * 100 if buy_price else 0

            log.info(
                f"💰 SELL {ticker} | reason: {reason} | "
                f"price: {current_price:,} | P&L: {pnl:+.2f}%"
            )
            del self.positions[ticker]
            self._save_positions()
            return True
        except Exception as e:
            log.error(f"SELL EXCEPTION {ticker}: {e}")
            return False

    # ── Main cycle ───────────────────────────────────────────────────

    def _write_heartbeat(self):
        Path(__file__).parent.joinpath("heartbeat.txt").write_text(
            datetime.now().isoformat(), encoding="utf-8"
        )

    def _save_balance(self):
        """Save balance snapshot to balance.json for Streamlit Cloud dashboard."""
        try:
            krw = self.get_krw_balance()
            open_value = sum(
                pos["amount_krw"] * (
                    float(pyupbit.get_current_price(t) or pos["buy_price"]) / pos["buy_price"]
                )
                for t, pos in self.positions.items()
            )
            open_pnl = sum(
                pos["amount_krw"] * (
                    float(pyupbit.get_current_price(t) or pos["buy_price"]) / pos["buy_price"] - 1
                )
                for t, pos in self.positions.items()
            )
            data = {
                "krw": krw,
                "open_value": open_value,
                "open_pnl": open_pnl,
                "total": krw + open_value,
                "updated_at": datetime.now().isoformat(),
            }
            Path(__file__).parent.joinpath("balance.json").write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            log.warning(f"_save_balance failed: {e}")

    def run_cycle(self):
        self._write_heartbeat()
        log.info("── Cycle start ──────────────────────────────")

        # 1. Check sell conditions for bot-managed positions
        for ticker in list(self.positions.keys()):
            if ticker in PROTECTED_TICKERS:
                continue
            should_sell, reason = self.check_sell_signal(ticker, self.positions[ticker])
            if should_sell:
                self.execute_sell(ticker, reason)
            time.sleep(0.3)

        # 2. Check buy signals
        if len(self.positions) >= MAX_POSITIONS:
            log.info(f"Max positions ({MAX_POSITIONS}) reached. Skipping buy scan.")
            return

        krw = self.get_krw_balance()
        log.info(f"Available KRW: {krw:,.0f}")
        if krw < MIN_TRADE_KRW:
            log.info("Insufficient KRW balance.")
            return

        coins = get_top_coins(TOP_N_COINS)
        for ticker in coins:
            if ticker in PROTECTED_TICKERS:
                log.info(f"  {ticker} — PROTECTED, skip")
                continue
            if ticker in EXCLUDED_TICKERS:
                continue
            if ticker in self.positions:
                continue
            if len(self.positions) >= MAX_POSITIONS:
                break

            signal, target_price = self.check_buy_signal(ticker)
            if signal:
                krw = self.get_krw_balance()
                amount = krw * POSITION_SIZE_PCT
                if amount < MIN_TRADE_KRW:
                    log.info("KRW too low for new position.")
                    break
                self.execute_buy(ticker, amount)

            time.sleep(0.3)   # Rate limit buffer

        log.info(f"Open positions: {list(self.positions.keys()) or 'None'}")
        self._save_balance()

    def _git_push(self):
        """Commit and push data files to GitHub so Streamlit Cloud can read them."""
        repo = Path(__file__).parent
        try:
            # Pull latest code changes first
            subprocess.run(["git", "stash"], cwd=repo, capture_output=True)
            subprocess.run(["git", "pull", "origin", "main", "--rebase"], cwd=repo, capture_output=True)
            subprocess.run(["git", "stash", "pop"], cwd=repo, capture_output=True)
            # Push data files
            subprocess.run(["git", "add", "positions.json", "equity_log.csv", "heartbeat.txt", "trade_log.txt", "balance.json"],
                           cwd=repo, capture_output=True)
            result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo)
            if result.returncode != 0:
                subprocess.run(["git", "commit", "-m", f"bot: data update {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
                               cwd=repo, capture_output=True)
                subprocess.run(["git", "push", "origin", "main"],
                               cwd=repo, capture_output=True)
                log.info("📤 Data pushed to GitHub.")
        except Exception as e:
            log.warning(f"Git push failed: {e}")

    def run(self, interval_seconds: int = 300):
        """Main loop — runs every interval_seconds (default 5 min)."""
        log.info(f"🚀 Live trading started. Cycle interval: {interval_seconds}s")
        log.info(f"KRW balance: {self.get_krw_balance():,.0f}")
        log.info(f"Loaded positions: {list(self.positions.keys()) or 'None'}")

        while True:
            try:
                self.run_cycle()
            except KeyboardInterrupt:
                log.info("Trading stopped by user.")
                break
            except Exception as e:
                log.error(f"Unexpected error in cycle: {e}")

            self._git_push()
            log.info(f"Sleeping {interval_seconds}s until next cycle...\n")
            time.sleep(interval_seconds)
