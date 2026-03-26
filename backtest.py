import pandas as pd
from indicators import add_indicators
from data_fetcher import get_top_coins, get_ohlcv
from config import (
    RSI_BUY_MAX, RSI_SELL_MIN, STOP_LOSS_PCT,
    INITIAL_CAPITAL, POSITION_SIZE_PCT, MAX_POSITIONS, MIN_TRADE_KRW,
    UPBIT_FEE, TOP_N_COINS, VOLUME_MULTIPLIER, EXCLUDED_TICKERS,
)


# ── Signal generation ──────────────────────────────────────────────

def get_coin_signals(ticker: str) -> list[dict]:
    """Return all buy signals for a single coin (pre-calculated entry/exit)."""
    df = get_ohlcv(ticker)
    if df is None:
        return []

    df = add_indicators(df)
    signals = []

    for i in range(30, len(df) - 1):
        row = df.iloc[i]
        nxt = df.iloc[i + 1]

        # ── Buy conditions ──
        if pd.isna(row["target"]) or pd.isna(row["rsi"]) or pd.isna(row["ma"]) or pd.isna(row["ma20"]):
            continue
        if row["target"] <= row["open"]:
            continue
        if row["high"] < row["target"]:
            continue
        if row["rsi"] >= RSI_BUY_MAX:
            continue
        if row["close"] <= row["ma"]:          # MA5 trend
            continue
        if row["close"] <= row["ma20"]:        # MA20 trend (added)
            continue
        if not pd.isna(row["volume_ma20"]) and row["volume"] < row["volume_ma20"] * VOLUME_MULTIPLIER:
            continue  # Volume confirmation

        buy_price = row["target"]
        stop_price = buy_price * (1 - STOP_LOSS_PCT)

        # ── Sell price determination ──
        if nxt["open"] <= stop_price:
            sell_price = nxt["open"]
            exit_reason = "Stop Loss (gap)"
        elif nxt["low"] <= stop_price:
            sell_price = stop_price
            exit_reason = "Stop Loss"
        elif not pd.isna(nxt["bb_upper"]) and nxt["high"] >= nxt["bb_upper"]:
            sell_price = nxt["bb_upper"]
            exit_reason = "BB Upper"
        elif not pd.isna(nxt["rsi"]) and nxt["rsi"] > RSI_SELL_MIN:
            sell_price = nxt["close"]
            exit_reason = "RSI Overbought"
        else:
            sell_price = nxt["open"]
            exit_reason = "9AM Sell"

        # Net return after fees (buy fee + sell fee)
        gross_pnl = (sell_price - buy_price) / buy_price
        net_pnl = gross_pnl - 2 * UPBIT_FEE

        signals.append({
            "ticker": ticker,
            "buy_date": df.index[i],
            "sell_date": df.index[i + 1],
            "buy_price": round(buy_price, 4),
            "sell_price": round(sell_price, 4),
            "pnl_pct": round(net_pnl * 100, 3),
            "exit_reason": exit_reason,
        })

    return signals


# ── Portfolio simulation ───────────────────────────────────────────

def simulate_portfolio(all_signals: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Simulate portfolio with dynamic position sizing.

    Rules:
      - Position size = POSITION_SIZE_PCT × available cash
      - Max MAX_POSITIONS open at once
      - Close positions before opening new ones each day
    """
    cash = INITIAL_CAPITAL
    open_positions: list[dict] = []
    closed_trades: list[dict] = []
    equity_history: list[dict] = []

    # Group signals by buy date
    signals_by_date: dict = {}
    for sig in all_signals:
        signals_by_date.setdefault(sig["buy_date"], []).append(sig)

    # All relevant dates (union of buy + sell dates), sorted
    all_dates = sorted(
        set(s["buy_date"] for s in all_signals) |
        set(s["sell_date"] for s in all_signals)
    )

    for date in all_dates:
        # ── 1. Close positions due on or before this date ──
        remaining = []
        for pos in open_positions:
            if pos["sell_date"] <= date:
                returns = pos["amount"] * (1 + pos["pnl_pct"] / 100)
                cash += returns
                closed_trades.append({
                    **pos,
                    "pnl_krw": round(returns - pos["amount"]),
                    "cash_after": round(cash),
                })
            else:
                remaining.append(pos)
        open_positions = remaining

        # ── 2. Open new positions ──
        if date in signals_by_date:
            for signal in signals_by_date[date]:
                if len(open_positions) >= MAX_POSITIONS:
                    break
                position_size = cash * POSITION_SIZE_PCT
                if position_size < MIN_TRADE_KRW:
                    break
                cash -= position_size
                open_positions.append({**signal, "amount": round(position_size)})

        # ── 3. Record equity (cash + open position value) ──
        open_value = sum(p["amount"] for p in open_positions)
        equity_history.append({
            "date": date,
            "equity": round(cash + open_value),
        })

    # Close any remaining open positions at last known price (mark-to-market)
    for pos in open_positions:
        cash += pos["amount"]  # assume break-even for unclosed
        closed_trades.append({
            **pos,
            "pnl_krw": 0,
            "cash_after": round(cash),
            "exit_reason": pos["exit_reason"] + " (unclosed)",
        })

    return closed_trades, equity_history


# ── Entry point ────────────────────────────────────────────────────

def run_backtest(top_n: int = TOP_N_COINS) -> tuple[pd.DataFrame, pd.DataFrame]:
    print(f"Fetching top {top_n} coins by volume...")
    coins = get_top_coins(top_n)
    print(f"Coins: {', '.join(coins)}\n")

    all_signals = []
    for i, ticker in enumerate(coins, 1):
        if ticker in EXCLUDED_TICKERS:
            print(f"  [{i:02d}/{top_n}] Skipping {ticker} (stablecoin)")
            continue
        print(f"  [{i:02d}/{top_n}] Generating signals for {ticker}...", end=" ")
        signals = get_coin_signals(ticker)
        print(f"{len(signals)} signals")
        all_signals.extend(signals)

    if not all_signals:
        print("No signals found.")
        return pd.DataFrame(), pd.DataFrame()

    print(f"\nSimulating portfolio (initial capital: {INITIAL_CAPITAL:,} KRW)...")
    trades, equity_history = simulate_portfolio(all_signals)

    return pd.DataFrame(trades), pd.DataFrame(equity_history)


def print_summary(trades_df: pd.DataFrame, equity_df: pd.DataFrame):
    from tabulate import tabulate

    final_equity = equity_df["equity"].iloc[-1]
    total_return_pct = (final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    # Max drawdown
    equity_df = equity_df.copy()
    equity_df["peak"] = equity_df["equity"].cummax()
    equity_df["drawdown"] = (equity_df["equity"] - equity_df["peak"]) / equity_df["peak"] * 100
    max_drawdown = equity_df["drawdown"].min()

    total = len(trades_df)
    wins = (trades_df["pnl_krw"] > 0).sum()
    win_rate = wins / total * 100 if total else 0
    avg_pnl_pct = trades_df["pnl_pct"].mean()
    total_pnl_krw = trades_df["pnl_krw"].sum()

    print("\n" + "=" * 55)
    print("  PORTFOLIO BACKTEST SUMMARY")
    print("=" * 55)
    print(f"  Initial capital  : {INITIAL_CAPITAL:>10,} KRW")
    print(f"  Final equity     : {final_equity:>10,} KRW")
    print(f"  Total return     : {total_return_pct:>+10.1f}%")
    print(f"  Total P&L        : {total_pnl_krw:>+10,} KRW")
    print(f"  Max drawdown     : {max_drawdown:>+10.1f}%")
    print(f"  Total trades     : {total:>10}")
    print(f"  Win rate         : {win_rate:>10.1f}%")
    print(f"  Avg return/trade : {avg_pnl_pct:>+10.2f}%")
    print("=" * 55)

    print("\n  Exit reason breakdown:")
    reason_df = (
        trades_df.groupby("exit_reason")["pnl_pct"]
        .agg(count="count", avg_pnl="mean")
        .reset_index()
    )
    print(tabulate(reason_df, headers="keys", tablefmt="simple",
                   showindex=False, floatfmt=".2f"))

    print("\n  Per-coin summary (sorted by total P&L):")
    coin_df = (
        trades_df.groupby("ticker")
        .agg(
            trades=("pnl_pct", "count"),
            win_rate=("pnl_krw", lambda x: (x > 0).mean() * 100),
            avg_pnl=("pnl_pct", "mean"),
            total_pnl=("pnl_krw", "sum"),
        )
        .reset_index()
        .sort_values("total_pnl", ascending=False)
    )
    print(tabulate(coin_df, headers="keys", tablefmt="simple",
                   showindex=False, floatfmt=".1f"))
    print()
