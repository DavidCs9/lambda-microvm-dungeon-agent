# Sandbox control plane

This SAM stack deploys the first real control-plane vertical slice: HTTP API, Lambda, DynamoDB,
and a Step Functions Standard workflow. Session records, phases, and events are durable. The
adventure, character, and MicroVM operations remain lightweight Wave 1 stubs and will be replaced
without changing the visible workflow order.

The sandbox API is intentionally simple and public. Send `x-player-id` on every request; it becomes
the session owner. This is convenient for the lab and must be replaced with JWT authentication
before treating the endpoint as a real product.

## Package and deploy

Build the ARM64 Lambda bundle, package it into the existing private artifact bucket, and deploy:

```bash
uv pip install --target dist/control-plane-bundle \
  --python-version 3.14 \
  --python-platform aarch64-manylinux2014 \
  --only-binary :all: \
  'pydantic>=2.11,<3' 'boto3>=1.43.51'
cp -R src/dungeon_agent dist/control-plane-bundle/

sam package \
  --template-file infra/control-plane/workflow/template.yaml \
  --s3-bucket YOUR_ARTIFACT_BUCKET \
  --s3-prefix artifacts/control-plane \
  --output-template-file dist/control-plane-packaged.yaml \
  --region us-east-2

aws cloudformation deploy \
  --template-file dist/control-plane-packaged.yaml \
  --stack-name dungeon-agent-control-plane-sandbox \
  --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND \
  --region us-east-2
```

The current sandbox is deployed in `us-east-2` as `dungeon-agent-control-plane-sandbox`.
