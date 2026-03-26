import pandas as pd
from config import RSI_PERIOD, MA_PERIOD, MA_TREND_PERIOD, BB_PERIOD, BB_STD, K


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # RSI
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD).mean()
    avg_loss = loss.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD).mean()
    rs = avg_gain / avg_loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # MA5 (short-term) + MA20 (trend filter)
    df["ma"] = df["close"].rolling(MA_PERIOD).mean()
    df["ma20"] = df["close"].rolling(MA_TREND_PERIOD).mean()

    # Volume MA20 (for breakout confirmation)
    df["volume_ma20"] = df["volume"].rolling(MA_TREND_PERIOD).mean()

    # Bollinger Bands
    bb_ma = df["close"].rolling(BB_PERIOD).mean()
    bb_std = df["close"].rolling(BB_PERIOD).std()
    df["bb_upper"] = bb_ma + BB_STD * bb_std
    df["bb_lower"] = bb_ma - BB_STD * bb_std

    # Volatility breakout target price
    prev_range = df["high"].shift(1) - df["low"].shift(1)
    df["target"] = df["open"] + prev_range * K

    return df
