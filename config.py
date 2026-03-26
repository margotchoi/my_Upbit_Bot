import os
from dotenv import load_dotenv

load_dotenv()

UPBIT_ACCESS_KEY = os.getenv("UPBIT_ACCESS_KEY", "")
UPBIT_SECRET_KEY = os.getenv("UPBIT_SECRET_KEY", "")

# ── Strategy parameters ──
K = 0.5                  # Volatility breakout factor
RSI_PERIOD = 14
RSI_BUY_MAX = 60         # Buy only when RSI < 60
RSI_SELL_MIN = 70        # Sell when RSI > 70
MA_PERIOD = 5            # 5-day moving average
MA_TREND_PERIOD = 20     # 20-day trend filter
BB_PERIOD = 20           # Bollinger Bands period
BB_STD = 2.0             # Bollinger Bands std multiplier
STOP_LOSS_PCT = 0.02     # Stop loss at -2%
VOLUME_MULTIPLIER = 0.0  # Volume filter disabled
EXCLUDED_TICKERS = {"KRW-USDT", "KRW-USDC", "KRW-DAI"}  # Stablecoins

# ── Trading ──
INITIAL_CAPITAL = 500_000    # 초기 자본 50만원
POSITION_SIZE_PCT = 0.20     # 보유 자본의 20%씩 투자
MAX_POSITIONS = 5            # 최대 동시 보유 포지션 수
MIN_TRADE_KRW = 5_000        # 최소 주문 금액
UPBIT_FEE = 0.0005           # 업비트 수수료 0.05% (매수+매도 = 0.1% 왕복)
TOP_N_COINS = 20             # Scan top N coins by 24h volume

# ── Backtest ──
BACKTEST_DAYS = 365
