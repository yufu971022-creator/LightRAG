# Block 24B-2.1：Semantic Branch Exit-Evidence Closure

你现在继续在本地 LightRAG 代码仓中工作。

本轮任务：**Block 24B-2.1，准出证据收口**。

这不是新功能开发轮。  
24B-2 的主体实现、图空间隔离、安全边界和测试已通过；本轮只补齐缺失的准出证据、字段语义和报告一致性。

---

## 一、当前已确认通过

当前已有结果：

```text
semantic_branch_executor_implemented = true
pfss_graph_writer_implemented = true
issue_index_implemented = true
graph_space_policy_implemented = true

dsl_full_pfss_write = true
dsl_partial_pfss_write = true
dsl_partial_issue_write = true
raw_only_pfss_write = false
parse_failed_semantic_write = false

namespace_collision_count = 0
pfss_generic_node_overlap_count = 0
pfss_generic_edge_overlap_count = 0
pfss_issue_overlap_count = 0

strategy = EXTERNAL_SIDECAR_REFERENCE
raw_chunk_count_before = 1
raw_chunk_count_after = 1
chunk_vector_count_before = 1
chunk_vector_count_after = 1
duplicate_raw_chunk_count = 0

real_llm_calls_executed = false
original_extract_entities_called = false
original_gleaning_executed = false

live_upload_behavior_changed = false
live_upload_hook_connected = false
auto_write_routing_enabled = false
production_storage_writes_executed = false
neo4j_connected = false
cleanup_passed = true
core_modified_in_this_round = false

38 tests passed
compileall passed
py_compile passed
ruff passed
```

当前未完整证明的只有：

```text
sidecar_alignment_passed
endpoint_closure_passed
forbidden_relation_count
duplicate_semantic_object_count
idempotency_passed
issue_object_written_to_pfss_count
artifacts_complete
```

以及：

```text
real_embedding_smoke_executed = false
real_embedding_smoke_passed = false
```

需要改为更准确的状态语义：

```text
real_embedding_smoke_status = NOT_RUN
```

本轮只处理以上内容。

---

## 二、防止原地打圈

必须严格遵守：

1. 不重新设计 24B-2。
2. 不重写 semantic branch executor。
3. 不修改图空间策略逻辑，除非只是补报告字段。
4. 不重新执行真实 Embedding smoke。
5. 不调用真实 LLM。
6. 不调用原生 extract_entities。
7. 不调用原生 Gleaning。
8. 不修改 `/documents/upload`。
9. 不实现 24C-0。
10. 不修改 LightRAG Core/API。
11. 不安装依赖。
12. 不修改 uv.lock、pyproject.toml、requirements。
13. 只允许读取和修改以下范围：
    - 24B-2 新增的扩展层模块；
    - 24B-2 测试；
    - `artifacts/block_24b2_semantic_branch_isolation/*`
14. 同一测试命令最多运行两次：
    - 首次；
    - 一次定向修复后重跑。
15. 第二次仍失败则停止并记录 unresolved。
16. 准出字段补齐后立即停止。

---

## 三、必须补齐的报告字段

在 24B-2 总报告中加入并明确输出：

```text
sidecar_alignment_passed: bool
endpoint_closure_passed: bool
forbidden_relation_count: int
duplicate_semantic_object_count: int
idempotency_passed: bool
issue_object_written_to_pfss_count: int
artifacts_complete: bool
real_embedding_smoke_status: NOT_RUN | PASS | FAIL | BLOCKED
```

### 字段语义

#### sidecar_alignment_passed

必须验证：

```text
PFSS Graph 中每个已写入 Entity / Relationship
都存在对应 Sidecar 记录；
Sidecar 记录能反向定位 graph object；
数量和 ID 对齐。
```

通过条件：

```text
true
```

#### endpoint_closure_passed

必须验证：

```text
所有 PFSS Relationship 的 src_id 和 tgt_id
均存在于本次或已存在的 PFSS Entity 集合中。
```

通过条件：

```text
true
```

#### forbidden_relation_count

统计最终进入 PFSS payload / PFSS graph 的禁止关系：

```text
has_child
belongs_to
references_to
queries_from
queries_by
contains
related_to
```

通过条件：

```text
0
```

注意：若这些字符串只出现在 blocked issue 或测试 fixture 中，不计入最终 PFSS。

#### duplicate_semantic_object_count

统计同一稳定 semantic_object_id 在 PFSS 中重复写入的数量。

通过条件：

```text
0
```

不得只按 entity_name 判断，优先使用稳定 ID / idempotency key。

#### idempotency_passed

必须执行同一 DSL_FULL 或 DSL_PARTIAL fixture 的第二次隔离写入验证：

```text
PFSS node count 不增加
PFSS edge count 不增加
Issue record count 不增加
Sidecar record count 不增加
稳定 ID 不变化
```

通过条件：

```text
true
```

#### issue_object_written_to_pfss_count

统计所有 Issue 类型对象是否进入 PFSS：

```text
VERSION_REVIEW_REQUIRED
VERSION_CONFLICT
MISSING_EVIDENCE
INVALID_TYPE
INVALID_RELATION
DANGLING_RELATIONSHIP
TERM_AMBIGUITY
REVIEW_REQUIRED
INFO_ONLY
```

通过条件：

```text
0
```

#### artifacts_complete

检查本轮规定 artifacts 全部存在且可解析。

通过条件：

```text
true
```

#### real_embedding_smoke_status

本轮不运行真实 Embedding smoke。

必须输出：

```text
real_embedding_smoke_executed = false
real_embedding_smoke_status = NOT_RUN
```

不得输出：

```text
real_embedding_smoke_passed = false
```

如需兼容旧字段，可以保留：

```text
real_embedding_smoke_passed = null
```

不得用 false 表示未运行。

---

## 四、必须补的测试

在现有 24B-2 测试中增加或确认以下独立测试：

1. `test_sidecar_alignment_for_pfss_objects`
2. `test_pfss_relationship_endpoint_closure`
3. `test_pfss_contains_no_forbidden_relations`
4. `test_pfss_has_no_duplicate_semantic_objects`
5. `test_semantic_branch_second_run_is_idempotent`
6. `test_issue_objects_are_not_written_to_pfss`
7. `test_artifact_completeness_check`
8. `test_real_embedding_not_run_status_is_not_run`
9. `test_report_contains_all_exit_gate_fields`
10. `test_report_is_serializable`
11. `test_no_lightrag_core_modified`

如果已有等价测试，可复用，但测试名称和断言必须清晰可定位。

---

## 五、artifact 完整性检查

必须检查以下文件至少存在：

```text
semantic_branch_report.json
semantic_branch_report.md
graph_space_policy.json
route_execution_results.json
pfss_payload_summary.json
pfss_storage_snapshot.json
generic_storage_snapshot.json
issue_index.json
issue_summary.json
graph_isolation_snapshot.json
source_reference_strategy.json
idempotency_report.json
architecture.mmd
safety_check.json
cleanup_report.json
command_log.txt
git_status_before.txt
git_status_after.txt
core_diff_check.txt
unresolved_questions.md
```

还必须验证：

```text
所有 JSON 可解析；
architecture.mmd 非空；
safety_check.json 含全部安全字段；
core_diff_check.txt 表明本轮未修改 Core；
```

生成：

```text
artifact_validation.json
```

至少包含：

```json
{
  "required_count": 19,
  "existing_count": 19,
  "missing_files": [],
  "json_parse_failures": [],
  "architecture_present": true,
  "safety_report_present": true,
  "core_diff_report_present": true,
  "artifacts_complete": true
}
```

---

## 六、报告中的最终准出区块

在 `semantic_branch_report.md` 末尾增加：

```text
## Exit Gate

- sidecar_alignment_passed:
- endpoint_closure_passed:
- forbidden_relation_count:
- duplicate_semantic_object_count:
- idempotency_passed:
- issue_object_written_to_pfss_count:
- artifacts_complete:
- real_embedding_smoke_status:

Final status:
- PASS / FAIL
```

只有满足以下全部条件时才能输出 PASS：

```text
sidecar_alignment_passed = true
endpoint_closure_passed = true
forbidden_relation_count = 0
duplicate_semantic_object_count = 0
idempotency_passed = true
issue_object_written_to_pfss_count = 0
artifacts_complete = true
real_embedding_smoke_status = NOT_RUN
all tests passed
compileall passed
py_compile passed
ruff passed
core_modified_in_this_round = false
```

---

## 七、运行命令

先执行测试收集一次：

```bash
.venv/bin/python -m pytest \
  lightrag_ext/us_dsl/tests/test_graph_space_policy.py \
  lightrag_ext/us_dsl/tests/test_issue_index.py \
  lightrag_ext/us_dsl/tests/test_pfss_graph_writer.py \
  lightrag_ext/us_dsl/tests/test_semantic_branch_executor.py \
  lightrag_ext/us_dsl/tests/test_graph_isolation_smoke.py \
  --collect-only -q
```

然后运行完整验证：

```bash
.venv/bin/python - <<'PY'
import subprocess
import sys

commands = [
    [
        ".venv/bin/python", "-m", "pytest",
        "lightrag_ext/us_dsl/tests/test_graph_space_policy.py",
        "-q",
    ],
    [
        ".venv/bin/python", "-m", "pytest",
        "lightrag_ext/us_dsl/tests/test_issue_index.py",
        "-q",
    ],
    [
        ".venv/bin/python", "-m", "pytest",
        "lightrag_ext/us_dsl/tests/test_pfss_graph_writer.py",
        "-q",
    ],
    [
        ".venv/bin/python", "-m", "pytest",
        "lightrag_ext/us_dsl/tests/test_semantic_branch_executor.py",
        "-q",
    ],
    [
        ".venv/bin/python", "-m", "pytest",
        "lightrag_ext/us_dsl/tests/test_graph_isolation_smoke.py",
        "-q",
    ],
    [
        ".venv/bin/python", "-m", "compileall",
        "-q", "lightrag_ext",
    ],
    [
        ".venv/bin/python", "-m", "py_compile",
        "lightrag/prompt.py",
    ],
    [
        ".venv/bin/python", "-m", "ruff", "check",
        "lightrag_ext", "lightrag/prompt.py",
    ],
]

for command in commands:
    print("RUN:", " ".join(command), flush=True)
    try:
        result = subprocess.run(command, timeout=300)
    except subprocess.TimeoutExpired:
        print("TIMEOUT:", " ".join(command))
        sys.exit(124)

    if result.returncode != 0:
        sys.exit(result.returncode)
PY
```

重新生成报告：

```bash
.venv/bin/python -m \
  lightrag_ext.us_dsl.scripts.run_semantic_branch_isolation_smoke \
  --output-dir artifacts/block_24b2_semantic_branch_isolation \
  --fixture-suite \
  --no-real-embedding \
  --generic-isolation-smoke \
  --cleanup
```

如果 runner 不支持 `--no-real-embedding`，使用当前默认离线模式，但不得运行真实 Embedding。

---

## 八、最终 artifact 校验脚本

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path

root = Path("artifacts/block_24b2_semantic_branch_isolation")

required_files = [
    "semantic_branch_report.json",
    "semantic_branch_report.md",
    "graph_space_policy.json",
    "route_execution_results.json",
    "pfss_payload_summary.json",
    "pfss_storage_snapshot.json",
    "generic_storage_snapshot.json",
    "issue_index.json",
    "issue_summary.json",
    "graph_isolation_snapshot.json",
    "source_reference_strategy.json",
    "idempotency_report.json",
    "architecture.mmd",
    "safety_check.json",
    "cleanup_report.json",
    "command_log.txt",
    "git_status_before.txt",
    "git_status_after.txt",
    "core_diff_check.txt",
    "unresolved_questions.md",
]

missing = [name for name in required_files if not (root / name).exists()]

json_failures = []
for path in root.glob("*.json"):
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        json_failures.append({"file": path.name, "error": str(exc)})

report = json.loads(
    (root / "semantic_branch_report.json").read_text(encoding="utf-8")
)

required_fields = [
    "sidecar_alignment_passed",
    "endpoint_closure_passed",
    "forbidden_relation_count",
    "duplicate_semantic_object_count",
    "idempotency_passed",
    "issue_object_written_to_pfss_count",
    "artifacts_complete",
    "real_embedding_smoke_status",
]

missing_fields = [field for field in required_fields if field not in report]

validation = {
    "required_count": len(required_files),
    "existing_count": len(required_files) - len(missing),
    "missing_files": missing,
    "json_parse_failures": json_failures,
    "missing_report_fields": missing_fields,
    "architecture_present": (root / "architecture.mmd").exists()
        and bool((root / "architecture.mmd").read_text().strip()),
    "safety_report_present": (root / "safety_check.json").exists(),
    "core_diff_report_present": (root / "core_diff_check.txt").exists(),
}

validation["artifacts_complete"] = (
    not validation["missing_files"]
    and not validation["json_parse_failures"]
    and not validation["missing_report_fields"]
    and validation["architecture_present"]
    and validation["safety_report_present"]
    and validation["core_diff_report_present"]
)

(root / "artifact_validation.json").write_text(
    json.dumps(validation, indent=2, ensure_ascii=False),
    encoding="utf-8",
)

print(json.dumps(validation, indent=2, ensure_ascii=False))

if not validation["artifacts_complete"]:
    raise SystemExit(1)
PY
```

---

## 九、Core 检查

```bash
git diff --name-only -- \
  lightrag/lightrag.py \
  lightrag/operate.py \
  lightrag/prompt.py \
  lightrag/api \
  > artifacts/block_24b2_semantic_branch_isolation/core_diff_check.txt
```

不得覆盖用户已有改动。  
必须判断“本轮是否新增 Core 修改”，而不是假设工作区绝对干净。

---

## 十、准出标准

通过条件：

1. 所有新增准出字段存在；
2. `sidecar_alignment_passed = true`；
3. `endpoint_closure_passed = true`；
4. `forbidden_relation_count = 0`；
5. `duplicate_semantic_object_count = 0`；
6. `idempotency_passed = true`；
7. `issue_object_written_to_pfss_count = 0`；
8. `artifacts_complete = true`；
9. `real_embedding_smoke_status = NOT_RUN`；
10. 所有测试通过；
11. compileall / py_compile / ruff 通过；
12. 本轮未修改 LightRAG Core/API；
13. 未调用真实 LLM；
14. 未执行生产存储写入；
15. 未开始 Block 24C-0。

不通过条件：

1. 用 `real_embedding_smoke_passed=false` 表示未运行；
2. Issue 对象进入 PFSS；
3. Sidecar 数量或 ID 不对齐；
4. 存在悬空关系；
5. 存在 forbidden relation；
6. 第二次执行增加节点、边、Issue 或 Sidecar；
7. artifacts 不完整；
8. 为收口而重写主体功能；
9. 修改 Core；
10. 开始下一 Block。

---

## 十一、完成后只输出

```text
Block: 24B-2.1

Exit Gate:
- sidecar_alignment_passed:
- endpoint_closure_passed:
- forbidden_relation_count:
- duplicate_semantic_object_count:
- idempotency_passed:
- issue_object_written_to_pfss_count:
- artifacts_complete:
- real_embedding_smoke_status:

Tests:
- collected_count:
- passed_count:
- failed_count:
- compileall:
- py_compile:
- ruff:

Safety:
- real_llm_calls_executed:
- production_storage_writes_executed:
- neo4j_connected:
- core_modified_in_this_round:

Final:
- block_24b2_status:
- recommended_next_block:

Artifacts:
- artifacts/block_24b2_semantic_branch_isolation
```

只有全部准出项满足时：

```text
block_24b2_status = PASS
recommended_next_block = Block 24C-0
```

完成后立即停止。
