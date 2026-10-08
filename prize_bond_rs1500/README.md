# Rs.1500 Prize Bond – pattern audit (draws 80–107)

`python3 analysis.py` re-runs everything from `raw/*.csv` (SBP BSC Sukkur result printouts). To add a draw, drop the new file (for example `raw/108.csv`) into the folder and re-run. The run takes about 2 minutes with 10,000 Monte Carlo histories (`--sims`). You need pandas, numpy, scipy and matplotlib.

| File | Contents |
|---|---|
| `draws_clean.csv` | draw_no, draw_date, prize_tier, prize_amount, number (6-char string) |
| `validation.csv` | per-draw counts and data-quality checks |
| `results_table.csv` | every test: observed, null expectation, p, BH and Bonferroni p, conclusion |
| `backtest.csv` | walk-forward hits per rule per test draw |
| `repeat_numbers.csv`, `top_prizes.csv` | numbers that won more than once; 1st/2nd prize history |
| `charts/*.png`, `report.html` | figures, and the self-contained report with the charts embedded |
| `run_log.txt` | console output of the last run (validation table and each test section) |
