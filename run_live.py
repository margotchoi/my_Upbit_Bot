"""
실거래 실행 스크립트

실행 방법:
    python3 run_live.py
"""
import sys
from trader import UpbitTrader, PROTECTED_TICKERS
from config import (
    POSITION_SIZE_PCT, MAX_POSITIONS, STOP_LOSS_PCT,
    RSI_BUY_MAX, VOLUME_MULTIPLIER, TOP_N_COINS,
)


def main():
    print("=" * 55)
    print("  Upbit Live Trader")
    print("=" * 55)

    trader = UpbitTrader()
    krw = trader.get_krw_balance()

    print(f"\n  현재 KRW 잔고     : {krw:>12,.0f} 원")
    print(f"  보호 티커          : {', '.join(PROTECTED_TICKERS)}")
    print(f"  매매 대상          : 거래량 상위 {TOP_N_COINS}개 코인")
    print(f"  포지션당 투자 비율 : {POSITION_SIZE_PCT*100:.0f}% ({krw*POSITION_SIZE_PCT:,.0f}원)")
    print(f"  최대 동시 포지션   : {MAX_POSITIONS}개")
    print(f"  손절 기준          : -{STOP_LOSS_PCT*100:.0f}%")
    print(f"  RSI 매수 기준      : < {RSI_BUY_MAX}")
    print(f"  거래량 배수        : {VOLUME_MULTIPLIER}x 이상")
    print()

    if trader.positions:
        print(f"  현재 열린 포지션   : {list(trader.positions.keys())}")
    else:
        print("  현재 열린 포지션   : 없음")

    print()
    print("  ⚠️  실제 자금으로 거래됩니다.")
    print("  ⚠️  KRW-DOGE는 절대 건드리지 않습니다.")
    print()

    confirm = input("  거래를 시작하시겠습니까? (yes 입력 시 시작): ").strip().lower()
    if confirm != "yes":
        print("취소되었습니다.")
        sys.exit(0)

    print()
    trader.run(interval_seconds=300)  # 5분 간격


if __name__ == "__main__":
    main()
