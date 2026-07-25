# Sandbox control plane

This SAM stack deploys the first real control-plane vertical slice: HTTP API, Lambda, DynamoDB,
and Step Functions Standard workflows (create-campaign + create-session). Session and campaign
records are durable.

The sandbox API is intentionally simple and public. Send `x-player-id` on every request; it becomes
the session owner. This is convenient for the lab and must be replaced with JWT authentication
before treating the endpoint as a real product.

## Deploy

Prefer GitHub Actions: **Deploy control plane sandbox** (see [infra/README.md](../../README.md)).
That workflow packages the Lambda bundle, uploads to the bootstrap artifact bucket, and updates
`dungeon-agent-control-plane-sandbox` in `us-east-2`.

Manual laptop deploys still work if you need them:

```bash
uv pip install --target dist/control-plane-bundle \
  --python-version 3.14 \
  --python-platform aarch64-manylinux2014 \
  --only-binary :all: \
  'pydantic>=2.11,<3' 'boto3>=1.43.51' 'aws-lambda-powertools>=3.20'
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
The template owns each `AWS::Bedrock::Prompt` and immutable `AWS::Bedrock::PromptVersion`; the
workflow and turn-worker functions consume those version resources directly. When changing a
prompt definition, also increment its version resource `Description` revision so CloudFormation
creates a new production snapshot. The three version ARNs are exposed as stack outputs for evals.
Campaign, character, and Dungeon Master model IDs are independent template parameters so an eval
winner can be promoted per role without changing runtime code.
