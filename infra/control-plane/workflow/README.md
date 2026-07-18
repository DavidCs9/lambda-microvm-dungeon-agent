# Create-session workflow skeleton

This stack implements Wave 1's replaceable Step Functions Standard shell. Every setup operation is
an explicit state, while a single inline Lambda provides deterministic stub behavior. Later waves
replace individual operations with focused agent, persistence, and MicroVM adapters without
changing the visible workflow order.

The workflow input is the serialized `CreateSessionWorkflowInput` contract. For local or deployed
failure-path tests it may additionally include these temporary stub controls:

- `forceValidationFailureAt`: operation name that raises a non-retried validation error;
- `forceAuthorizationFailureAt`: operation name that raises a non-retried authorization error;
- `forceRetriableFailureAt`: operation name that raises a retriable dependency error;
- `forceRetriableAttempts`: number of attempts that should fail before succeeding.

The stub records the execution ARN, task timestamps, phase timestamps, and semantic event stubs in
the execution output. It does not claim durable persistence; Wave 1 integration replaces those
hooks with the repository adapters before the first deployed vertical slice.

## Validate without deployment

Run the repository tests and CloudFormation's read-only template validator:

```sh
uv run pytest tests/control_plane/workflow

AWS_PROFILE=personal AWS_REGION=us-east-2 aws cloudformation validate-template \
  --template-body file://infra/control-plane/workflow/template.yaml
```

`cfn-lint` may be used when it is already installed:

```sh
cfn-lint --format json --regions us-east-2 infra/control-plane/workflow/template.yaml
```

## Deploy the lab stack

Deployment is intentionally not part of Wave 1 implementation:

```sh
AWS_PROFILE=personal AWS_REGION=us-east-2 aws cloudformation deploy \
  --stack-name dungeon-agent-control-plane-workflow \
  --template-file infra/control-plane/workflow/template.yaml \
  --capabilities CAPABILITY_IAM \
  --no-fail-on-empty-changeset
```

Step Functions logs exclude execution data. The task stub logs only operation, session ID, and
workflow execution ARN. EventBridge routes `FAILED`, `TIMED_OUT`, and `ABORTED` executions to a
sanitized monitoring Lambda with a dead-letter queue, and CloudWatch alarms expose each outcome.
