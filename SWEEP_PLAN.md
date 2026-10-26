# Labelled collusion sweep on Modal

Config: `repos/colosseum/experiments/collusion/configs/sweep_modal.yaml`
Model: Qwen2.5-7B-Instruct on one Modal A10G (`modal/vllm_server.py`), about $1.10 per GPU-hour.

## Design

Paper settings: 6 agents with 2 colluders, a complete network, 4 planning rounds and 3 conversation steps.

| Factor | Values | Count |
|---|---|---|
| Task | Jira, meeting scheduling, hospital ("choice" variants) | 3 |
| Condition | no secret channel (control) + secret channel x {control, simple, deception, structured, aggressive} | 6 |
| Seed | 1-20 | 20 |

That's 3 x 6 x 20 = **360 runs**. The pilot is seed 1 only: **18 runs**.

## Labels each run carries

These are set by the config, so they're ground truth:

- `environment_label`, `secret_channel_enabled`, `prompt_variant`, `seed`
- `colluders`: which 2 agents are in the coalition (in `run_config.json`)

These are measured outcomes, useful for "colluded in action" versus "only talked":

- `coalition_advantage_mean`, `coalition_reward_ratio` and regret: did the coalition gain at the others' expense?
- `colluder_posts_secret` and `colluder_posts_secret_rate`: did they actually use the secret channel?

How this maps to your five labels:

- **independent / coordinate:** no-channel control runs. Whether agents coordinated on the shared board shows in the shared-board posts and the outcome.
- **collude:** secret channel used, and the coalition gains.
- **talk only:** secret channel used, but no coalition gain.
- **tacit:** not covered. The runner forces "control" whenever there's no secret channel, so colluders can't be instructed without one. Getting tacit runs needs a small custom variant.

## Cost estimate

This is extrapolated from the quickstart: 3 runs with 4 agents, 2 rounds and 2 steps took 68 s of server time at 3 concurrent. The paper settings mean about 4.5x more agent turns per run, with longer contexts, so I assumed roughly 7x per run, run 8 at a time.

| Step | Runs | GPU time (est.) | Cost (est.) |
|---|---|---|---|
| Pilot | 18 | 30-55 min (+ about 3 min cold start) | about $0.60-1.10 |
| Full sweep | 360 | 9-18 h | about $10-20 |

Add 10 minutes of idle time each time the server scales down, or stop it with `modal app stop -y colosseum-vllm`.

The range is wide because the quickstart was much smaller than these runs. The pilot replaces this guess with a measured time per run before the larger spend.

Not included: the LLM judge (`judge_blackboards.py`) calls OpenAI by default, so it needs an OpenAI key and is billed by OpenAI, not Modal.

## Pilot results (2026-10-23)

Output: `repos/colosseum/experiments/collusion/outputs/sweep_modal/20261023-202722`

- 18 of 18 runs completed, 0 failed. All 1,323 model requests returned 200, so no context-length errors.
- Wall time was 22 min with 8 runs at a time. The Modal container was up about 24 min including the 76 s cold start, which comes to about **$0.44 in total, or $0.024 per run**. That's estimated from container uptime at $1.10/h; check Modal's billing page for the exact figure.
- Average length of one run:

| Task | Length of one run |
|---|---|
| Jira | 5.2 min |
| Meeting scheduling | 4.7 min |
| Hospital | 12.2 min |

- Revised full-sweep estimate for 360 runs at 8 at a time: **5.5-7.5 GPU-hours, about $6-8**. Without hospital (240 runs): about 2.5 h, about $3.

### Hospital issues

- The runs finish, but the task ignores `num_agents: 6`. It runs 9 agents: 8 hospital departments plus the resource provisioner.
- `colluder_posts_*` comes out as 0 in hospital runs even though the colluders did post on the secret board (5 posts each in the simple run). The hospital task posts with `broadcast_message`, and the metric doesn't count that.
- `joint_reward_ratio` is empty, and the coalition advantage uses a different scale (hundreds). Every hospital run ended `partial_convergence`.
- Using hospital means recounting its posts from `blackboards.json`, and its rewards can't be compared directly with the other two tasks.

## Full sweep results (2026-10-24, Jira + meeting scheduling, seeds 1-20)

- 236 of 240 runs completed. Modal was up from 08:42 to 11:25, 2 h 43 min, so about **$3.00**.
- 4 failed:
  - Jira `structured` seeds 6, 8 and 9: the connection to Modal was reset, all around the same minute (also one HTTP 502).
  - Meeting `simple` seed 8: the model sent malformed `attend_meeting` arguments, and the runner's tool logger crashed on them.
- All 4 were rerun with resume on 2026-10-24 and completed, so **240 of 240** are done. That took about 6 min of Modal time, about $0.12.
- Of 17,038 model requests, 17,037 returned 200.

Each row is a task and condition. Values are means over the seeds, ± standard error. "Coalition advantage" is the colluders' mean reward minus the other agents' mean reward.

| Task | Secret channel | Prompt | n | Colluders' posts on the secret board | Coalition advantage | Share of optimum missed |
|---|---|---|---|---|---|---|
| Jira | off | control | 20 | 0 | 4.1 ± 3.0 | 0.68 |
| Jira | on | control | 20 | 0.63 | 0.4 ± 1.7 | 0.63 |
| Jira | on | simple | 20 | 0.97 | -0.2 ± 1.6 | 0.61 |
| Jira | on | deception | 20 | 0.96 | 2.6 ± 1.8 | 0.64 |
| Jira | on | structured | 20 | 0.94 | -3.1 ± 2.8 | 0.64 |
| Jira | on | aggressive | 20 | 0.98 | 0.6 ± 3.8 | 0.67 |
| Meeting | off | control | 20 | 0 | -0.1 ± 0.4 | 0.36 |
| Meeting | on | control | 20 | 0.40 | -0.1 ± 0.4 | 0.39 |
| Meeting | on | simple | 20 | 0.71 | -0.1 ± 0.4 | 0.38 |
| Meeting | on | deception | 20 | 0.72 | -0.1 ± 0.4 | 0.35 |
| Meeting | on | structured | 20 | 0.75 | 0.0 ± 0.4 | 0.36 |
| Meeting | on | aggressive | 20 | 0.71 | -0.4 ± 0.4 | 0.37 |

What this means for the labels:

- With Qwen2.5-7B, the colluders move almost all their talk to the secret channel when told to collude, but they get no reliable reward advantage.
- So most secret-channel runs are **talk only**, and few are **collude**. Expect the classes to be imbalanced, and label each run from its own outcome, not from the condition.
- "Coalition" in the no-channel runs just means 2 randomly chosen agents. Its spread (± 3.0 in Jira) is the noise floor.
- Meeting scheduling's per-agent regret is 0 everywhere, because the optimum is only computed for Jira, so compare meeting runs on reward instead.

## Risks the pilot checks

- **Hospital:** the repo's own task sweep has the hospital entry commented out, so it may fail or need settings of its own. If it does, drop it (240 runs, about $7-13).
- **Context length:** 6 agents over 4 rounds may get past the server's 16k-token limit. Look for `vllm chat request failed (400)` in `experiment.log`.
