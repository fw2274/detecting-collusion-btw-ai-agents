# Colosseum: where each task lives

Neither repo ships data or logs. Every task instance is generated from `simulation.seed`, and a run writes its own logs (`data_iteration_*.json`, `summary.jsonl`, blackboard logs) under `logs/`.

Repos (cloned with submodules):
- `repos/colosseum`: experiment runners, configs and the judge (`experiments/collusion/judge_blackboards.py`)
- `repos/Terrarium`: the environments
- `external/CoLLAB` (inside both): the CoLLAB_SEA problem generators used by meeting scheduling

## Hospital
- Env: `repos/Terrarium/terrarium/environments/dcops/hospital/` (patients from `random.seed(seed)`; writes `patients.json`)
- Configs: `repos/colosseum/experiments/persuasion/hospital/configs/`, `repos/colosseum/experiments/agent_misalignment/configs/`

## Jira ticket
- Env: `repos/Terrarium/terrarium/environments/dcops/jira_ticket/` (see `jira_ticket_environment.md`)
- Configs: `repos/colosseum/experiments/collusion/configs/` (topologies, `complete_n6_c2_regret_models`, `three_agents_two_blackboards`), `repos/colosseum/experiments/persuasion/collusion/configs/`

## Meeting scheduling
- Env: `repos/Terrarium/terrarium/environments/dcops/meeting_scheduling/` (adapts CoLLAB v2; instance built from `rng_seed`)
- Generator: `repos/colosseum/external/CoLLAB/problem_layer/meeting_scheduling/`
- Configs: `repos/colosseum/experiments/network_influence/configs/`

## Generating logs
See `repos/colosseum/README.md` (Quickstart). Example:
`uv run ... --config experiments/collusion/configs/quickstart.yaml`
