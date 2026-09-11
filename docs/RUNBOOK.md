# Runbook: the three credential-gated steps

Each is one command. None runs in tests. Nothing here deploys.

## 1. Archive the live elevator feed (needs `BART_API_KEY`)

```bash
cd ~/agents-for-humans
printf 'BART_API_KEY=%s\n' "$BART_API_KEY" >> .env      # .env is gitignored; or export it in the shell
nohup make archive > data/archive.log 2>&1 &
sleep 20 && tail -2 data/archive.log && python3 -c "import json;print(json.load(open('data/archive/manifest.json'))['snapshots'][-1])"
```

Writes `data/archive/manifest.json`, one raw payload per poll, and `data/archive/outages.sqlite`
(its own database; `make replay` never touches it). Replay a real archive into the app with
`python -m src.app.replay --reset --seed-demo --archive data/archive/manifest.json`.

## 2. Freeze labels, then the live policy-agreement run (needs AWS credentials + Bedrock access)

```bash
# labels are frozen: tag kb-labels-v1 (Sat Sept 12, 2026)
# credentials: ~/.aws/credentials and ~/.aws/config (region us-west-2); boto3 reads them, no exports needed
# optional: EVAL_MODEL_ID=... in .env (default: the Strands Bedrock model id, a Claude Sonnet profile)
make quota                                   # read-only: AgentCore quotas, Runtime ones starred
make bedrock-smoke                           # one Converse call; stop here if it fails
make eval-live                               # exactly once per variant: enforced, then --no-steering; 200 calls each
make render-claims && make verify
```

`results/policy_agreement.json` becomes the frozen live run (mode, cases_run, cases skipped for
budget, agreement_pct, by-label breakdown, steering guides, model_id, run_at, labels git tag).
`make evals` afterwards writes the mock result to `policy_agreement.mock.json` and leaves the frozen
file alone. A second live run needs `--force-live` on purpose. Then update the README row label from
"provisional" to the live wording and note the replacement in `docs/reports/day-1.md`.

## 3. AgentCore Runtime quota (needs AWS credentials; read-only)

```bash
export AWS_REGION=us-west-2
make quota          # lists every AgentCore quota from Service Quotas; Runtime ones are starred; creates nothing
```

C5 (deploy) waits for an explicit yes after the quota is seen.
