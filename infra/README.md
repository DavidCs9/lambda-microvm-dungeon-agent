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
