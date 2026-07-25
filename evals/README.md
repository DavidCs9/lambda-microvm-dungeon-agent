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

## Bedrock architect and Dungeon Master comparison

The model evaluation generates an English and Spanish adventure per candidate, adjudicates the
same creative action, and records structure, agency, state safety, latency, and token usage. Pass
`--model-id` more than once to compare candidates:

```sh
uv run --group tooling python evals/narration_models.py \
  --profile personal \
  --region us-east-2 \
  --model-id us.anthropic.claude-sonnet-4-6
```

Final model selection should include blind human playtests.
