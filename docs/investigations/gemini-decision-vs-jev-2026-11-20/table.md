| purpose | model | calls | valid | 429 | blocked | p50 ms | p95 ms | question accuracy (valid) |
|---|---|---|---|---|---|---|---|---|
| photo relevance | jev | 24 | 24 | 0 | 0 | 170 | 185 | 0.875 |
| photo relevance | gemini | 24 | 24 | 0 | 0 | 278 | 604 | 1.000 |
| postprocessing | jev | 120 | 120 | 0 | 0 | 161 | 193 | 0.732 |
| postprocessing | gemini | 120 | 120 | 0 | 0 | 221 | 486 | 0.890 |
| routing (app/focus) | jev | 102 | 102 | 0 | 0 | 197 | 229 | 0.963 |
| routing (app/focus) | gemini | 102 | 102 | 0 | 0 | 357 | 504 | 0.963 |
| routing (preprocess) | jev | 150 | 150 | 0 | 0 | 193 | 220 | 0.983 |
| routing (preprocess) | gemini | 150 | 147 | 0 | 3 | 373 | 547 | 0.990 |
| safety (prompt injection) | jev | 120 | 120 | 0 | 0 | 159 | 187 | 0.842 |
| safety (prompt injection) | gemini | 120 | 120 | 0 | 0 | 215 | 323 | 1.000 |
| search relevance | jev | 57 | 57 | 0 | 0 | 160 | 192 | 0.965 |
| search relevance | gemini | 57 | 57 | 0 | 0 | 213 | 331 | 1.000 |
| shopping relevance | jev | 36 | 36 | 0 | 0 | 171 | 244 | 1.000 |
| shopping relevance | gemini | 36 | 36 | 0 | 0 | 386 | 1150 | 1.000 |
| voice end-of-turn | jev | 126 | 126 | 0 | 0 | 157 | 180 | 1.000 |
| voice end-of-turn | gemini | 126 | 126 | 0 | 0 | 217 | 320 | 1.000 |
| web browsing | jev | 75 | 75 | 0 | 0 | 174 | 216 | 0.938 |
| web browsing | gemini | 75 | 75 | 0 | 0 | 265 | 613 | 0.875 |
