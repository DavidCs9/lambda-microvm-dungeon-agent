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
