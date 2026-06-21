# Block 24A-1 Runtime Smoke Report

- Final status: `BLOCKED_BY_ENV`
- Run ID: `20260620_163912_829a56ae`
- Workspace root: `/Users/hufaofao/Projects/LightRAG/artifacts/block_24a1_runtime_smoke/workspaces/20260620_163912_829a56ae`

## Runtime Config

- Embedding: `openai` / `text-embedding-3-large` / dim `3072` / host `api.openai.com`
- Embedding sends dimensions: `False`
- LLM: `openai` / `gpt-5.4-mini` / host `api.openai.com`
- Local storage: `JsonKVStorage`, `NanoVectorDBStorage`, `NetworkXStorage`, `JsonDocStatusStorage`

## Safety Boundary

- writes_only_under: `/Users/hufaofao/Projects/LightRAG/artifacts/block_24a1_runtime_smoke/workspaces`
- uses_local_storage_only: `True`
- calls_upload_route: `False`
- uses_company_documents: `False`
- modifies_core_api: `False`
- dependency_install_attempted: `False`
- core_diff_check: `No diff in forbidden core/API files for Block 24A-1.
`

## Steps

| Step | Status | Error Code | Evidence |
| --- | --- | --- | --- |
| preflight | `blocked` | `BLOCKED_MISSING_RUNTIME_DEPENDENCY` | `{}` |
| preflight detail | | | `Missing runtime dependency for configured binding: openai` |

## Status Rules

- PASS requires all real model probes and both isolated storage smokes to pass.
- BLOCKED_BY_ENV means runtime environment prevented proof without identifying a LightRAG integration bug.
- FAIL_INTEGRATION means the gateway responded or local storage ran but wrapper/storage semantics failed.
- FAIL_SAFETY means the run touched a forbidden boundary.
