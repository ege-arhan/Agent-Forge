# LIMITED REAL-MODEL VALIDATION — results (plan: benchmark)

**REAL MODEL** results. Provider: **OpenCode Go** (`opencode-go`). Offline/scripted
results are stored separately and are not part of this file.

- Date: 2026-09-27T01:33:10+00:00 to 2026-09-27T01:36:12+00:00
- AgentForge: 0.1.0 (commit `6d4812b`)
- Endpoint: `https://opencode.ai/zen/go/v1`
- Authentication: env (OPENCODE_API_KEY); verified by a successful model call
- Task executions: 10 (cap 10)
- Token budget per task: 150000; model-call retries: none
- Secret scan of stored results and logs: clean

| Model | Phase | Task | Success | Tests | Score | Tool calls (errors) | Steps | Retries | Duration (s) | Avg model-call latency (ms) | Tokens in/out/total | Cost | Failure |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| REAL MODEL · OpenCode Go · DeepSeek V4.1 Flash (`deepseek-v4.1-flash`) | task-a | add-cli-flag | yes | yes | 1 | 9 (0) | 9 | 0 | 22.873 | 2242.778 | 18604 / 1445 / 20049 | NOT AVAILABLE | — |
| REAL MODEL · OpenCode Go · DeepSeek V4.1 Flash (`deepseek-v4.1-flash`) | task-b | pagination-off-by-one | yes | yes | 1 | 8 (0) | 6 | 0 | 13.475 | 2125.5 | 11849 / 922 / 12771 | NOT AVAILABLE | — |
| REAL MODEL · OpenCode Go · MiMo-V2.6-Flash (`mimo-v2.6-flash`) | task-a | add-cli-flag | yes | yes | 1 | 6 (0) | 5 | 0 | 23.26 | 4320 | 8592 / 857 / 9449 | NOT AVAILABLE | — |
| REAL MODEL · OpenCode Go · MiMo-V2.6-Flash (`mimo-v2.6-flash`) | task-b | pagination-off-by-one | yes | yes | 1 | 7 (0) | 5 | 0 | 25.088 | 4883.6 | 8705 / 716 / 9421 | NOT AVAILABLE | — |
| REAL MODEL · OpenCode Go · Muse Spark 1.3 Contributor (`muse-spark-1.3-contributor`) | task-a | add-cli-flag | yes | yes | 1 | 6 (0) | 6 | 0 | 29.235 | 4564.333 | 13128 / 1765 / 14893 | NOT AVAILABLE | — |
| REAL MODEL · OpenCode Go · Muse Spark 1.3 Contributor (`muse-spark-1.3-contributor`) | task-b | pagination-off-by-one | yes | yes | 1 | 7 (0) | 7 | 0 | 17.505 | 2407.286 | 15633 / 1174 / 16807 | NOT AVAILABLE | — |
| REAL MODEL · OpenCode Go · GLM-5.3 Flash (`glm-5.3-flash`) | task-a | add-cli-flag | yes | yes | 1 | 5 (0) | 4 | 0 | 14.041 | 3118.25 | 6159 / 886 / 7045 | NOT AVAILABLE | — |
| REAL MODEL · OpenCode Go · GLM-5.3 Flash (`glm-5.3-flash`) | task-b | pagination-off-by-one | yes | yes | 1 | 8 (0) | 6 | 0 | 9.186 | 1422.167 | 10397 / 1155 / 11552 | NOT AVAILABLE | — |
| REAL MODEL · OpenCode Go · Kimi K2.7 Code (`kimi-k2.7-code`) | task-a | add-cli-flag | yes | yes | 1 | 7 (0) | 5 | 0 | 10.947 | 1856.2 | 5620 / 387 / 6007 | NOT AVAILABLE | — |
| REAL MODEL · OpenCode Go · Kimi K2.7 Code (`kimi-k2.7-code`) | task-b | pagination-off-by-one | yes | yes | 1 | 6 (0) | 6 | 0 | 14.531 | 2315.833 | 7566 / 723 / 8289 | NOT AVAILABLE | — |

Cost: NOT AVAILABLE (AgentForge does not read billing).
