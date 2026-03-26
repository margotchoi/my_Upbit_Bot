import sys
from backtest import run_backtest, print_summary


def main():
    print("=" * 55)
    print("  Upbit Auto Trading Bot")
    print("=" * 55)
    print()
    print("  [1] Run Backtest")
    print("  [2] Live Trading  (coming soon)")
    print()

    choice = input("Select mode (1/2): ").strip()

    if choice == "1":
        try:
            top_n = input("How many top coins to scan? (default: 20): ").strip()
            top_n = int(top_n) if top_n.isdigit() else 20

            days_input = input("Backtest period in days? (default: 365): ").strip()
            import config
            config.BACKTEST_DAYS = int(days_input) if days_input.isdigit() else 365

            print()
            trades_df, equity_df = run_backtest(top_n)
            if not trades_df.empty:
                print_summary(trades_df, equity_df)

                save = input("Save detailed results to CSV? (y/n): ").strip().lower()
                if save == "y":
                    path = "backtest_results.csv"
                    trades_df.to_csv(path, index=False, encoding="utf-8-sig")
                    print(f"Saved to {path}")
        except KeyboardInterrupt:
            print("\nAborted.")
            sys.exit(0)

    elif choice == "2":
        print("\nLive trading is not yet implemented. Coming soon!")

    else:
        print("Invalid choice.")
        sys.exit(1)


if __name__ == "__main__":
    main()
