# .kilocode/rules-ask/AGENTS.md - Ask Mode Rules for large-model-proxy

## Non-Obvious Documentation Context

- `large-model-proxy` is a Go 1.26 HTTP proxy that manages LLM backend services (like llama-server) with resource-aware scheduling, idle timeout management, OpenAI-compatible API (`/v1/completions`, `/v1/chat/completions`, `/v1/models`), Management API (`/status`), and slot persistence for llama-server (`--parallel`, `--slots`, `--slot-save-path`)

- Config file uses JSONC format with these top-level sections: `ResourcesAvailable` (map of resource names to amounts - static integers or dynamic via `CheckCommand`), `Services` (array of service configurations), `OpenAiApi` (optional OpenAI-compatible API endpoint), `ManagementApi` (optional management API endpoint)

- Service Configuration key options: `Name`, `ListenPort`, `Command`, `Args` (parsed with `shlex`), `HealthcheckCommand`, `HealthcheckIntervalMilliseconds`, `ResourceRequirements`, `ServiceUrl` (three-state pattern: unset/null/override for URL templating), `OpenAiApi`, `OpenAiApiModels`