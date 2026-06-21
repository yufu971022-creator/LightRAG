# Unresolved Questions

- RUNTIME_CONFIRMATION_REQUIRED: the live server process may pass CLI arguments or environment variables not visible to this static/dry-run probe.
- RUNTIME_CONFIRMATION_REQUIRED: model access cannot be confirmed without a network call, which was intentionally not executed.
- RUNTIME_CONFIRMATION_REQUIRED: production storage contents and historical vector dimensions cannot be confirmed unless the configured working_dir or remote storage is inspected in the target runtime.
- RUNTIME_CONFIRMATION_REQUIRED: no deployed process table was inspected, so effective runtime workspace may differ from .env/default parsing.
- DSL working_dir is unset in the parsed config, so canary/module mode creates a temp directory at runtime.
