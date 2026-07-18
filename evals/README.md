# Gameplay experience evaluation

This original black-box evaluation was defined before the structured one-shot game engine was
completed. It measures five equally weighted gameplay dimensions:

- player agency: at least two successful endings are reachable through different strategies
- guidance and information: every turn exposes an objective, consequence, and optional ideas
- danger and challenge: danger changes over time and a loss condition is reachable
- state consistency: revisions advance and acquired inventory remains stable
- world depth: the API exposes structured gameplay state rather than narration alone

Run it against any checkout of the project:

```sh
uv run python evals/gameplay_experience.py
```

The score is a deterministic engineering proxy, not a replacement for playtesting. Narration
quality should be evaluated separately with human players.

## Bedrock model comparison

The narration evaluation runs identical resolved scenes in English and Spanish, then records
instruction adherence, state grounding, agency preservation, presentation safety, latency, and
token usage. Pass `--model-id` more than once to compare candidates:

```sh
uv run --group tooling python evals/narration_models.py \
  --profile personal \
  --region us-east-2 \
  --model-id us.amazon.nova-micro-v1:0
```

Automated language and grounding checks are useful for regressions, but final model selection
should include blind human review of the saved sample narrations.
