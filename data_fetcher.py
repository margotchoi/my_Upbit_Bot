import requests
import pyupbit
import pandas as pd
from config import TOP_N_COINS, BACKTEST_DAYS


def get_top_coins(n: int = TOP_N_COINS) -> list[str]:
    """Return top N KRW coins sorted by 24h trade volume."""
    tickers = pyupbit.get_tickers(fiat="KRW")

    # Fetch 24h ticker info in chunks (Upbit allows max 100 at a time)
    chunk_size = 100
    all_data = []
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i: i + chunk_size]
        markets = ",".join(chunk)
        resp = requests.get(
            "https://api.upbit.com/v1/ticker",
            params={"markets": markets},
            timeout=10,
        )
        resp.raise_for_status()
        all_data.extend(resp.json())

    df = pd.DataFrame(all_data)
    df = df[["market", "acc_trade_price_24h"]].copy()
    df["acc_trade_price_24h"] = pd.to_numeric(df["acc_trade_price_24h"], errors="coerce")
    df = df.dropna().sort_values("acc_trade_price_24h", ascending=False)

    return df["market"].head(n).tolist()


MIN_LISTING_DAYS = 180  # 최소 180일 이상 상장된 코인만 허용


def get_ohlcv(ticker: str, days: int = BACKTEST_DAYS) -> pd.DataFrame | None:
    """Fetch daily OHLCV data for a ticker."""
    df = pyupbit.get_ohlcv(ticker, interval="day", count=days)
    if df is None or len(df) < MIN_LISTING_DAYS:
        print(f"(skipped — only {len(df) if df is not None else 0} days of data)")
        return None
    return df
