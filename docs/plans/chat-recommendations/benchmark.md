# Chat Recommendations post-processing benchmark (D-12)

Revision: workspace-761a-on-c912cb6747; cases: 20; planned results: 180; unavailable: 0.

| arm | schema-valid % | min/max ok mem/wf % | oracle pass % | duplicate % | usefulness (0-2) | p50 s | p95 s | cost / 1k turns (regular / promo USD) |
|---|---|---|---|---|---|---|---|---|
| mercury-low | 100.0 | 100.0/100.0 | 93.3 | 33.3 | 1.5 (n=10) | 2.391 | 4.302 | 1.7245 / 0.8623 |
| gemini-lite | 100.0 | 100.0/100.0 | 96.7 | 0.0 | 1.5 (n=10) | 1.907 | 2.279 | 2.7884 / 2.7884 |
| gemini-flash | 100.0 | 100.0/100.0 | 91.7 | 22.2 | 1.4 (n=10) | 10.251 | 17.805 | 15.3659 / 7.683 |

Pricing (USD per 1M input/output tokens, regular list; promo currently effective): mercury-low (0.2, 0.7) (promo (0.1, 0.35)) from backend/providers/inception.yml mercury-3 costs + temporary_prices; gemini-lite (0.3, 2.5) (promo (0.3, 2.5)) from backend/providers/google.yml gemini-3.5-flash-lite costs; gemini-flash (1.5, 7.5) (promo (0.75, 3.75)) from backend/providers/google.yml gemini-3.8-flash costs + temporary_prices

## Decision (D-12 rule)

{
  "decision": "stay on gemini-lite",
  "baseline_schema_or_count_failure_pct": 0.0,
  "arms": {
    "mercury-low": {
      "oracle_gain_points": -3.4,
      "p95_latency_ratio": 1.89,
      "cost_ratio_regular": 0.62,
      "cost_ratio_promo": 0.31,
      "eligible": false
    },
    "gemini-flash": {
      "oracle_gain_points": -5.0,
      "p95_latency_ratio": 7.81,
      "cost_ratio_regular": 5.51,
      "cost_ratio_promo": 2.76,
      "eligible": false
    }
  }
}
