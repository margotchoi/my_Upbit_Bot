# Upbit Auto Trading Bot

## 프로젝트 구조

```
upbit_bot/
├── config.py          # 전략 파라미터 설정
├── indicators.py      # 기술 지표 계산 (RSI, MA, BB, 변동성 돌파)
├── backtest.py        # 백테스트 엔진
├── trader.py          # 실거래 봇 (5분 사이클)
├── dashboard.py       # Streamlit 대시보드
├── data_fetcher.py    # 상위 N개 코인 조회
├── run_live.py        # 실거래 실행 진입점
├── main.py            # 백테스트 실행 진입점
├── balance.json       # 잔고 스냅샷 (봇이 5분마다 업데이트)
├── positions.json     # 열린 포지션
├── equity_log.csv     # 수익 곡선 데이터
├── trade_log.txt      # 거래 기록
└── heartbeat.txt      # 봇 상태 (마지막 실행 시각)
```

## 매매 전략

- **방식**: 변동성 돌파 + RSI + MA + 볼린저 밴드 복합 전략
- **매수 조건**: 현재가 > 시가 + (전일 고저 범위 × K) AND RSI < 60 AND MA5 > MA20
- **매도 조건**: RSI > 70 OR 손절 -2% OR 당일 23:50 이후
- **K값**: 0.5
- **포지션 크기**: 보유 KRW의 20%
- **최대 동시 포지션**: 5개
- **스캔 대상**: 거래량 상위 20개 코인 (스테이블코인 제외)
- **보호 티커**: KRW-DOGE (절대 매매 안 함)
- **사이클 간격**: 5분

## 설정값 (config.py)

```python
K = 0.5
RSI_BUY_MAX = 60
RSI_SELL_MIN = 70
MA_PERIOD = 5
MA_TREND_PERIOD = 20
BB_PERIOD = 20
BB_STD = 2.0
STOP_LOSS_PCT = 0.02
VOLUME_MULTIPLIER = 0.0   # 비활성화
EXCLUDED_TICKERS = {"KRW-USDT", "KRW-USDC", "KRW-DAI"}
INITIAL_CAPITAL = 500_000
POSITION_SIZE_PCT = 0.20
MAX_POSITIONS = 5
MIN_TRADE_KRW = 5_000
TOP_N_COINS = 20
```

## 실행 방법

### 로컬 실행
```bash
# 백테스트
python3 main.py

# 실거래 봇
python3 run_live.py

# 대시보드 (로컬)
streamlit run dashboard.py --server.port 8502
```

### Oracle Cloud 서버 실행
```bash
ssh -i ~/Downloads/ssh-key-2026-03-26.key ubuntu@168.107.33.88
cd my_Upbit_Bot
git pull origin main
nohup python3 run_live.py > bot.log 2>&1 &
tail -f bot.log   # 로그 확인
```

### 봇 종료
```bash
pkill -f run_live.py
```

## 배포 구조

```
로컬 맥북 or Oracle Cloud 서버
    └── run_live.py 실행
        └── 5분마다 balance.json, positions.json 등 업데이트
            └── git push → github.com/margotchoi/my_Upbit_Bot
                └── Streamlit Cloud 자동 반영
                    └── https://myupbitbot.streamlit.app
```

## Streamlit Cloud 설정

- **Repository**: margotchoi/my_Upbit_Bot
- **Branch**: main
- **Main file**: dashboard.py
- **Secrets**:
  ```toml
  UPBIT_ACCESS_KEY = "..."
  UPBIT_SECRET_KEY = "..."
  ```
- 잔고/포지션은 API 직접 호출 없이 `balance.json` 파일에서 읽음
  (Upbit API IP 제한 우회)

## Oracle Cloud 서버 정보

- **IP**: 168.107.33.88
- **OS**: Ubuntu
- **SSH 키**: ~/Downloads/ssh-key-2026-03-26.key
- **코드 경로**: ~/my_Upbit_Bot

## GitHub 인증 (서버)

서버에서 git push 하려면 Personal Access Token 필요:
```bash
git remote set-url origin https://<TOKEN>@github.com/margotchoi/my_Upbit_Bot.git
```

## .env 파일 (로컬 & 서버 모두 필요)

```
UPBIT_ACCESS_KEY=...
UPBIT_SECRET_KEY=...
```
