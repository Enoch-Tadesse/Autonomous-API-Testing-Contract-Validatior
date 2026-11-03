# Evaluation report

Model: `google_genai:gemini-3.5-flash`. Each scenario ran against a fresh `target_api` server. Regenerate with `python -m eval.run_eval`.

## Success rate

**9/9 scenarios passed.**

| # | Scenario | Result | Confirmed | Steps | Tool calls | LLM errors | Status | Time |
|---|---|---|---|---|---|---|---|---|
| 1 | no bugs (false positive check) | pass | - | 25 | 25 | 0 | complete | 21.5s |
| 2 | BUG_RADIUS_MIN | pass | validation | 28 | 27 | 0 | complete | 24.8s |
| 3 | BUG_DISTANCE_STRING | pass | schema | 26 | 26 | 0 | complete | 37.8s |
| 4 | BUG_MISSING_LNG_500 | pass | server_error | 26 | 26 | 0 | complete | 19.9s |
| 5 | BUG_AUTH_BYPASS | pass | auth | 26 | 26 | 0 | complete | 32.2s |
| 6 | all four bugs | pass | auth, schema, server_error, validation | 31 | 28 | 0 | complete | 25.0s |
| 7 | BUG_RADIUS_MIN + FAULT_503_THEN_OK | pass | validation | 28 | 29 | 0 | complete | 25.3s |
| 8 | FAULT_TIMEOUT_ALWAYS | pass | - | 25 | 29 | 0 | complete | 34.2s |
| 9 | endpoint with no documented errors | pass | - | 27 | 28 | 0 | complete | 20.1s |

Bug detection rate 100% (9/9) · false positives 0 · recovery under faults 100% · findings with valid citations 100% (9/9) · avg steps 26.9 · avg tool calls 27.1 · partial runs 0

## Failures

- 5 task(s) were blocked by the 25-calls-per-endpoint cap and reported inconclusive (scenario 2: 1, scenario 6: 3, scenario 7: 1). Reruns, follow-ups and the model's extra tests share the same endpoint budget.

## Limitations

- Only two endpoints, all GET; no request bodies, mutating calls or real auth flows (one static token).
- Expectations come only from documented status codes and schemas, so business rules are not tested.
- One model, temperature 0, one run per scenario: no variance measured.
- Bugs are seeded and known in advance; the eval measures recall on these four, not on unknown bugs.

## Improvements

- Generate request bodies from schemas and test POST/PUT with `allow_mutating` against a sandbox.
- Spend the per-endpoint call budget by risk instead of in task order.
- Run each scenario several times and with more than one model to measure stability.
- Persist runs with `AsyncSqliteSaver` so the service survives restarts.

## Agentic behavior shown

- **Retry (transient):** `step 03 executor call_http_request: GET /v1/favorites -> 503 -> retry 1/2 -> 503 -> retry 2/2 -> 401 (e_001)` (eval_7)
- **Critique and rerun:** `step 37 validator api_defect:rerun: status_code: expected [400], got 200; range: out-of-range input got HTTP 200. Rerun to confirm` (eval_2)
- **Replan:** `step 40 planner replan: added 2 neighbor tasks around confirmed defects (t_026, t_027)` (eval_2)
- **Fallback tool:** `step 04 executor fallback: web_search failed (no TAVILY_API_KEY set), switching to rag_search` (eval_9)
- **Ask user:** `step 10 ask_user answered: user said: 401` (eval_9)
- **Budget stop:** `step 19 reporter PARTIAL: no findings; stopped by step_budget` (eval_2_budget) (extra run of scenario 2 with `max_steps=6`, not scored)
