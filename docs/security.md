# Security boundaries

- Treat model output and player input as untrusted.
- Never place developer or AWS credentials in the MicroVM image or runtime payload.
- Lambda MicroVMs use public internet egress by default. Before enabling agent-generated code execution, route egress through a customer-managed VPC connector with deny-by-default security-group and network controls.
- Scope MicroVM authentication tokens to port 8080 and a short expiration.
- Enforce command time, process, memory, input, and output limits before enabling code execution.
- Create one MicroVM per player session; do not multiplex tenant workspaces.
- Use lifecycle hooks to refresh expiring credentials and flush state.
- Terminate sessions and delete disposable AWS resources after every lab run.
- Never log authentication tokens, secrets, prompts containing secrets, or raw credentials.
