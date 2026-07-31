# .kilocode/rules-architect/AGENTS.md - Architect Mode Rules for large-model-proxy

## Non-Obvious Architectural Constraints

### Concurrency Model
- Package-level globals hold all state (`config`, `resourceManager`, `serviceConfigByName`, `interrupted`)
- `serviceMutex` protects all ResourceManager maps
- Each resource monitor runs in its own goroutine
- Each service proxy runs in its own goroutine
- OpenAI API and Management API run in separate goroutines

### Key Design Patterns
- **Three-state ServiceUrl**: `ServiceUrlOption` distinguishes unset/null/value for URL templating
- **Resource pointer optimization**: `resourcesAvailable` uses `*int` to avoid read locks
- **Shutdown safety**: `interrupted` flag switches from `Lock()` to `TryLock()` to prevent deadlocks
- **Slot management**: llama-server slot persistence via HTTP calls to `/slots/{id}` endpoints
- **Dynamic resources**: `ResourceAvailable` supports both static integers and dynamic `CheckCommand` polling

### Extension Points
- New service types: Add to `ServiceConfig` struct and update validation
- New resource types: Add to `ResourcesAvailable` map (no code changes needed)