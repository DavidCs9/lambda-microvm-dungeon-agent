# Architecture

The lab separates orchestration from untrusted execution:

1. A local agent orchestrator calls the selected model.
2. The orchestrator sends narrowly scoped actions to an authenticated MicroVM endpoint.
3. Each player session receives a dedicated Lambda MicroVM and workspace.
4. Lifecycle hooks preserve and validate state across suspend and resume.

The initial server intentionally implements state operations only. Arbitrary code execution will be added only with MicroVM isolation, resource limits, no AWS credentials, and restricted network egress.
