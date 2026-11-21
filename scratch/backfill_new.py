"""One-off: run backend/run_ohlc_refresh.py's normal logic for 3 new universe symbols only."""
import sys
sys.path.insert(0, "backend")
import run_ohlc_refresh as R
R.load_universe_symbols = lambda: ["NCPL", "NPL", "PAEL"]
sys.exit(R.main())
