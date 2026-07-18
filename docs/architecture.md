# Architecture

The lab separates orchestration from untrusted execution:

1. A local agent orchestrator calls the selected model.
2. The orchestrator sends narrowly scoped actions to the authenticated FastAPI endpoint.
3. Each player session receives a dedicated Lambda MicroVM and workspace.
4. Lifecycle hooks preserve and validate state across suspend and resume.

The FastAPI backend intentionally implements state operations only. Its OpenAPI contract can support a separate web client later. Arbitrary code execution will be added only with MicroVM isolation, resource limits, no AWS credentials, and restricted network egress.

The master orchestrator runs outside the MicroVM. It owns the Bedrock conversation, MicroVM lifecycle, short-lived endpoint token, and player loop. The MicroVM remains a narrow state and tool-execution boundary rather than receiving model credentials.
