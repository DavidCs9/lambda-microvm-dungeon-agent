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
