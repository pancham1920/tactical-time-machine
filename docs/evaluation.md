# Evaluation

The [40 cases](../tests/fixtures/evaluation_cases.json) contain questions,
reference SQL and literal expected scalar values. Offline verification checks
each reference query against its expected value on the
[fictional fixture](../tests/fixtures/sample_football.json). It does not test Gemini.
Cases cover joins, dates, nulls, aggregates and derived points/value changes.

Live evaluation sends only the question and a request to end with `RESULT: <number>`.
Gold SQL and answers are not sent to the model. Each question gets fresh state.
Exact numeric matching does not measure prose faithfulness or tactical quality.
The [eight qualitative cases](../tests/fixtures/analyst_review_cases.json) remain
a separate manual review resource.

## Actual run: October 15, 2026

[Raw answers, SQL, event transcripts and hashes](evaluation/live-2026-10-15.json)

| Metric | Observed |
| --- | --- |
| Model | gemini-2.5-flash |
| Offline reference cases verified | 40/40 |
| Live attempted / planned | 4/40 |
| Completed / exact numeric correct | 3 / 3 |
| Exact correctness including failed attempts | 3/4 (75%) |
| Successful SQL / returned tool results | 3/3 (100%) |
| Median / nearest-rank p95 attempt latency | 3.01s / 3.67s |
| Not run | 36 |

Match, club and player counts returned 8, 4 and 6 correctly. Question four
(2024 season match count, expected 6) hit a provider quota error before returning
a tool result. The run stopped; remaining cases are `not_run`. Raw provider
exception text is omitted to avoid leaking sensitive details.

Latency measures the agent graph, including model/tool work, not browser round
trips. It includes the failed attempt and excludes inter-question pauses. SQL
success counts returned tool results; a failure before a tool response is not
included in that denominator. Three easy count questions cannot establish general
accuracy. No wrong-answer example was observed; broader success is unmeasured.

## Reproduce

```bash
# Offline, no API key or full dataset:
venv/bin/python -m scripts.evaluate_agent

# Optional live calls: confirm your billing/quota settings first.
venv/bin/python -m scripts.evaluate_agent --live --max-cases 40 --delay 10 --output build/evaluation/new-run.json
```

Output must be a new file. The runner creates an isolated temporary database,
saves after each question, and stops on the first provider/runtime error. It does
not retry provider failures or enable billing. Each question may require multiple
model calls, including bounded SQL correction. Repeat within your available quota
before publishing stronger metrics. Reports include database/case hashes.
