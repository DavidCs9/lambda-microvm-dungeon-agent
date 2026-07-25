# Sandbox control plane

This SAM stack deploys the first real control-plane vertical slice: HTTP API, Lambda, DynamoDB,
and Step Functions Standard workflows (create-campaign + create-session). Session and campaign
records are durable.

The HTTP API is protected by a Cognito User Pool JWT authorizer. Self-registration is disabled;
the stack creates the User Pool and public app client through SAM, while individual users are added
manually after deployment. The WebSocket remains a temporary sandbox path using `playerId`.

After deployment, copy the `ApiUrl`, `WebSocketUrl`, `CognitoUserPoolId`, and
`CognitoUserPoolClientId` outputs into `web/.env.local`. In the Cognito console, create the demo
users administratively and give each a permanent password before they sign in.

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
The template owns each Bedrock managed prompt and immutable version. A small custom resource is
used because the native `AWS::Bedrock::Prompt` provider converts JSON Schema numeric and boolean
values to strings. The workflow and turn-worker functions consume the resulting version ARNs
directly. When changing a prompt definition, also increment its `VersionDescription` revision so
CloudFormation records the intended snapshot. The three version ARNs are exposed as stack outputs
for evals. Campaign, character, and Dungeon Master model IDs are independent template parameters
so an eval winner can be promoted per role without changing runtime code.
