# .kilocode/rules-code/AGENTS.md - Code Mode Rules for large-model-proxy

## Non-Obvious Coding Rules

- Never use `json.NewDecoder().Decode()` without `DisallowUnknownFields()` for config structs
- `OutputServiceLogs` and `ConsiderStoppedOnProcessExit` use `*bool` pointers - nil means use defaults
- `HealthcheckIntervalMilliseconds > 0` without `HealthcheckCommand` is a validation error
- Multiple services on same port causes validation failure
- Config files support JSONC comments (`//` and `/* */`)