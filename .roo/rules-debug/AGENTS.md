# .kilocode/rules-debug/AGENTS.md - Debug Mode Rules for large-model-proxy

## Non-Obvious Debug Rules

- This is a single-binary Go application (`package main`) - all code lives in root directory, no separate packages
- Use `log.Printf()` for debugging - logs include date, time, and microseconds
- `monitorResourceAvailability()` runs in a goroutine per resource; Resources use `*int` pointers in `resourcesAvailable` map
- Check `CheckCommand` output - it must be a single integer string (e.g., `echo 16384`)
- Default `CheckIntervalMilliseconds` is 1000ms if not specified
- `interrupted` global flag controls lock behavior during shutdown; when `interrupted = true`, all mutex operations use `TryLock()` to avoid deadlocks
- `SIGINT`, `SIGTERM`, `os.Interrupt` all trigger shutdown sequence
- Config uses JSONC format - verify comments aren't causing parse errors
- `ServiceUrl` three-state pattern: unset/null/value - check for unintended null values
- `ResourceAvailable` accepts both integers and objects - verify format