# Infrastructure

`bootstrap.yaml` creates only lab-scoped resources in `us-east-2`:

- Artifact S3 bucket
- Least-privilege MicroVM image build role
- A private, encrypted, versioned artifact bucket with seven-day artifact expiration
- A least-privilege Lambda MicroVM image build role

Deploy it with a short-lived authenticated profile:

```sh
AWS_PROFILE=personal AWS_REGION=us-east-2 aws cloudformation deploy \
  --stack-name lambda-microvm-dungeon-agent-bootstrap \
  --template-file infra/bootstrap.yaml \
  --capabilities CAPABILITY_IAM \
  --no-fail-on-empty-changeset
```

The bucket is intentionally configured for deletion because this is a disposable lab. Empty all object versions before deleting the stack.

## GitHub release role

AWS publishing is deliberately separate from ordinary CI. The tag-driven release workflow uses
GitHub OIDC and never stores AWS access keys in GitHub.

First configure the account-level GitHub Actions OIDC provider with:

- Provider URL: `https://token.actions.githubusercontent.com`
- Audience: `sts.amazonaws.com`

Then obtain `ArtifactBucketName` and `MicrovmBuildRoleArn` from the bootstrap stack outputs and
deploy the release role:

```sh
AWS_PROFILE=personal AWS_REGION=us-east-2 aws cloudformation deploy \
  --stack-name lambda-microvm-dungeon-agent-github-release \
  --template-file infra/github-release-role.yaml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    GitHubOidcProviderArn=<github-oidc-provider-arn> \
    ArtifactBucketName=<artifact-bucket-name> \
    MicrovmBuildRoleArn=<microvm-build-role-arn> \
  --no-fail-on-empty-changeset
```

The trust policy uses GitHub's immutable OIDC subject format, including the repository owner and
repository numeric IDs. It accepts only jobs using this repository's `release` environment.

Create a GitHub environment named `release`, restrict its deployment branches/tags to version
tags, and configure:

- `AWS_RELEASE_ROLE_ARN` from the release stack output
- `AWS_REGION=us-east-2`
- `AWS_BOOTSTRAP_STACK=lambda-microvm-dungeon-agent-bootstrap`

Protecting the environment with required reviewers adds a manual approval boundary after the tag
passes verification but before AWS publishing begins.

## Control plane sandbox deploy (GitHub Actions)

Manual `sam package` / `cloudformation deploy` from a laptop is replaced by
[`.github/workflows/deploy-control-plane.yml`](../.github/workflows/deploy-control-plane.yml).

It runs on:

- `workflow_dispatch` (manual)
- pushes to `main` that touch `infra/control-plane/**` or `src/dungeon_agent/control_plane/**`

### One-time setup

1. Create a GitHub Environment named `sandbox` (no reviewers needed for the lab).
2. Deploy the OIDC deploy role (reuses the existing GitHub OIDC provider and bootstrap bucket):

```sh
OIDC_PROVIDER_ARN="$(AWS_PROFILE=personal AWS_REGION=us-east-2 aws iam list-open-id-connect-providers \
  --query "OpenIDConnectProviderList[?ends_with(Arn, 'token.actions.githubusercontent.com')].Arn | [0]" \
  --output text)"
ARTIFACT_BUCKET="$(AWS_PROFILE=personal AWS_REGION=us-east-2 aws cloudformation describe-stacks \
  --stack-name lambda-microvm-dungeon-agent-bootstrap \
  --query "Stacks[0].Outputs[?OutputKey=='ArtifactBucketName'].OutputValue" \
  --output text)"

AWS_PROFILE=personal AWS_REGION=us-east-2 aws cloudformation deploy \
  --stack-name lambda-microvm-dungeon-agent-github-deploy \
  --template-file infra/control-plane/github-deploy-role.yaml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    GitHubOidcProviderArn="${OIDC_PROVIDER_ARN}" \
    ArtifactBucketName="${ARTIFACT_BUCKET}" \
  --no-fail-on-empty-changeset
```

3. Configure sandbox environment variables:

- `AWS_DEPLOY_ROLE_ARN` from stack output `GitHubControlPlaneDeployRoleArn`
- `AWS_REGION=us-east-2`
- `AWS_BOOTSTRAP_STACK=lambda-microvm-dungeon-agent-bootstrap`
- `AWS_CONTROL_PLANE_STACK=dungeon-agent-control-plane-sandbox`

4. Trigger **Deploy control plane sandbox** from the Actions tab (or merge a control-plane change to `main`).

