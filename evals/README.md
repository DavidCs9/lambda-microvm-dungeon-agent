# Generated gameplay evaluation

The deterministic evaluation measures five equally weighted safety dimensions:

- generated plans validate before play
- d20 rolls choose exactly one outcome branch
- creative actions can add persistent facts
- only validated changes can complete the objective
- state remains consistent across turns

Run it against any checkout of the project:

```sh
uv run python evals/gameplay_experience.py
```

The score is an engineering safety proxy, not a replacement for playtesting.

## Golden dataset

`golden/` contains hand-authored reference cases for the three model roles: campaign architect,
character architect, and Dungeon Master. The cases are intentionally small and cover the contracts
that matter before comparing models: playable graph, secrets and agency, character grounding, roll
calibration, inventory safety, and earned victory.

Run the deterministic rubric with:

```sh
uv run python evals/golden_dataset.py
```

This is a contract/rubric eval, not exact string matching. A model can use different names and
prose while still passing the behavioral checks. Add a case when a real failure is found; do not
use generated samples as golden truth without human review.

## Managed prompt baseline

The production Sonnet baseline is declared in
`infra/control-plane/workflow/template.yaml` as three `AWS::Bedrock::Prompt` resources and three
immutable `AWS::Bedrock::PromptVersion` snapshots. Deploying the control-plane stack publishes the
prompts and exposes each version ARN as a stack output. The committed candidate manifests record
the exact versions used for historical eval runs; refresh a baseline manifest from those outputs
after deploying a new prompt revision.

Each immutable prompt version contains the system prompt, user template, model, inference
configuration, required tool choice, and Pydantic-derived tool schema. Candidate manifests under
`evals/candidates/` pin one version ARN per role.

Run one or more candidate manifests against the golden set:

```sh
uv run --group tooling python evals/managed_prompt_benchmark.py \
  --candidate evals/candidates/baseline-sonnet46.json \
  --max-quality-drop 5 \
  --output artifacts/managed-prompt-eval.json
```

The first candidate is the quality baseline. A candidate is eligible only when every critical
safety check passes and its overall quality drop is within the configured tolerance. Eligible
candidates are ranked by estimated token cost. Model quality is always measured first-pass: the
evaluator makes one invocation per case and never repairs invalid output.

Cases run concurrently per candidate by default (`--max-workers 6`). Lower the value if Bedrock
throttling becomes a problem, or raise it for short, isolated experiments.

`scripts/publish_managed_prompts.py` is only for temporary model/prompt candidates during
experimentation. It creates immutable prompt versions but does not activate them. After a
candidate passes all evals, activate its runtime pointer explicitly:

```sh
uv run --group tooling python scripts/activate_runtime_config.py \
  --profile personal \
  --region us-east-2 \
  --parameter-name dungeon-agent/bedrock-runtime-config \
  --manifest artifacts/haiku-candidate.json
```

The Lambda workers read the active model and prompt ARN for each role from that SSM parameter at
runtime, so prompt/model experiments and promotion do not require a control-plane deploy. The
CloudFormation stack only bootstraps the parameter name and IAM permission.

During prompt development, run only the affected cases to avoid paying for unchanged roles:

```sh
uv run --group tooling python evals/managed_prompt_benchmark.py \
  --candidate evals/candidates/baseline-sonnet46-campaign-v3.json \
  --case-id campaign-bells-es \
  --case-id campaign-lantern-en
```

## Bedrock architect and Dungeon Master comparison

The model evaluation generates an English and Spanish adventure per candidate, adjudicates the
same creative action, and records structure, agency, state safety, latency, and token usage. Pass
`--model-id` more than once to compare candidates:

```sh
uv run --group tooling python evals/narration_models.py \
  --profile personal \
  --region us-east-2 \
  --model-id us.anthropic.claude-sonnet-4-6 \
  --model-id us.anthropic.claude-haiku-4-5-20251001-v1:0 \
  --max-workers 4
```

Final model selection should include blind human playtests.
