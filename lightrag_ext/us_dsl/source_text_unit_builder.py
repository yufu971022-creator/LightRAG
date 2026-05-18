from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from .dsl_types import DslCompiledResult, SourceTextUnit, UsBlock


SECTION_TYPES = {
    "us_header",
    "gwt",
    "business_rule",
    "field_table",
    "api_desc",
    "state_rule",
    "task_rule",
    "message_rule",
    "migration_rule",
    "report_rule",
    "dfx_rule",
    "acceptance_criteria",
    "ui_reference",
    "unknown",
}

GWT_MARKERS = ("【As】", "【I Want】", "【So That】", "【Given】", "【When】", "【Then】")
US_CONTEXT_MARKERS = GWT_MARKERS + (
    "【业务规则】",
    "详细业务规则",
    "业务规则",
    "字段/规则表",
    "DFX / 异常处理",
    "验收标准",
)
US_TITLE_RE = re.compile(
    r"^\s*(US[A-Za-z0-9_-]*\d[A-Za-z0-9_-]*)[ \t]+(.+?)\s*$",
    re.IGNORECASE,
)
NUMERIC_TITLE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s+(.+?)\s*$")
MAJOR_SECTION_RE = re.compile(r"^\s*\d+[.．、]\s*.+")
BUSINESS_RULE_NUMBER_RE = re.compile(r"^\s*\d+(?:\.\d+)+[.．、]")
LOWER_SNAKE_RE = re.compile(r"^[a-z]+(?:_[a-z0-9]+)+$")
MARKDOWN_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")

FIELD_HEADER_TERMS = (
    "字段名称",
    "字段类型",
    "是否必填",
    "字段来源",
    "定义与说明",
    "Name",
    "Type",
    "Required",
    "Source",
    "Description",
)
API_TERMS = ("API", "接口", "入参", "出参", "MQ", "MQS", "回调", "外部系统", "集成")
STATE_TERMS = (
    "状态",
    "Status",
    "Approve",
    "Reject",
    "Submit",
    "Cancel",
    "Waiting for",
    "Completed",
    "Deleted",
)
TASK_TERMS = (
    "待办",
    "Task Name",
    "Current Handler",
    "Transfer To",
    "接收人",
    "转审",
    "清除待办",
)
MESSAGE_TERMS = (
    "提示",
    "message",
    "No permission",
    "Not Found",
    "The field is required",
    "Please",
)
MIGRATION_TERMS = ("迁移", "初始化", "历史数据", "刷数", "源表", "目标表")
REPORT_TERMS = (
    "查询",
    "报表",
    "导出",
    "列表",
    "结果列",
    "分页",
    "排序",
    "筛选",
)
REPORT_PRIMARY_TERMS = ("查询", "报表", "导出", "结果列", "分页", "排序", "筛选")
DFX_TERMS = ("DFX", "异常处理")
ACCEPTANCE_TERMS = ("验收标准", "Acceptance Criteria")
UI_REFERENCE_TERMS = ("是否涉及页面", "UX稿", "页面引用", "页面参考")


@dataclass(frozen=True)
class _LineInfo:
    text: str
    start: int
    end: int
    line_no: int


@dataclass(frozen=True)
class _TitleCandidate:
    us_id: str | None
    title: str
    line_index: int


@dataclass(frozen=True)
class _SectionRange:
    section_type: str
    start_line_index: int
    end_line_index: int


def stable_hash(text: str, prefix: str) -> str:
    return f"{prefix}{hashlib.md5(text.encode('utf-8')).hexdigest()[:12]}"


def detect_us_blocks(content: str) -> list[UsBlock]:
    lines = _split_lines(content)
    if not lines:
        return []

    candidates = _find_title_candidates(lines)
    if not candidates:
        candidates = _find_gwt_fallback_candidates(lines)
    if not candidates:
        return []

    blocks: list[UsBlock] = []
    for index, candidate in enumerate(candidates):
        next_line_index = (
            candidates[index + 1].line_index if index + 1 < len(candidates) else len(lines)
        )
        start_line = lines[candidate.line_index]
        end_line = lines[next_line_index - 1]
        start = start_line.start
        end = end_line.end
        blocks.append(
            UsBlock(
                us_id=candidate.us_id,
                title=candidate.title,
                start=start,
                end=end,
                line_start=start_line.line_no,
                line_end=end_line.line_no,
                text=content[start:end],
            )
        )

    return blocks


def build_source_text_units(
    content: str,
    document_id: str,
    dsl_result: DslCompiledResult | dict[str, Any] | None = None,
    file_path: str | None = None,
) -> list[SourceTextUnit]:
    lines = _split_lines(content)
    mappings = _extract_dsl_mappings(dsl_result)
    blocks = detect_us_blocks(content)

    if not blocks:
        return [
            _make_source_text_unit(
                content=content,
                document_id=document_id,
                us_id=None,
                feature_key=None,
                domain_code=None,
                section_type=_classify_section(content) if content.strip() else "unknown",
                chunk_index=0,
                start=0,
                end=len(content),
                line_start=1,
                line_end=max(1, len(lines)),
                file_path=file_path,
            )
        ]

    units: list[SourceTextUnit] = []
    for block in blocks:
        feature_key, domain_code, preferred_section_type = _mapping_for_us(
            block.us_id, mappings
        )
        block_sections = _split_block_sections(block, lines, content)
        if not block_sections:
            block_sections = [
                _SectionRange(
                    section_type=preferred_section_type or _classify_section(block.text),
                    start_line_index=block.line_start - 1,
                    end_line_index=block.line_end - 1,
                )
            ]

        for section in block_sections:
            if section.section_type not in SECTION_TYPES:
                section_type = preferred_section_type or "unknown"
            elif section.section_type == "unknown" and preferred_section_type:
                section_type = preferred_section_type
            else:
                section_type = section.section_type

            start_line = lines[section.start_line_index]
            end_line = lines[section.end_line_index]
            chunk_index = len(units)
            units.append(
                _make_source_text_unit(
                    content=content,
                    document_id=document_id,
                    us_id=block.us_id,
                    feature_key=feature_key,
                    domain_code=domain_code,
                    section_type=section_type,
                    chunk_index=chunk_index,
                    start=start_line.start,
                    end=end_line.end,
                    line_start=start_line.line_no,
                    line_end=end_line.line_no,
                    file_path=file_path,
                )
            )

    return units


def _split_lines(content: str) -> list[_LineInfo]:
    result: list[_LineInfo] = []
    offset = 0
    split_lines = content.splitlines(keepends=True)
    if not split_lines and content:
        split_lines = [content]

    for index, line in enumerate(split_lines, start=1):
        start = offset
        end = start + len(line)
        result.append(_LineInfo(text=line.rstrip("\r\n"), start=start, end=end, line_no=index))
        offset = end

    return result


def _find_title_candidates(lines: list[_LineInfo]) -> list[_TitleCandidate]:
    candidates: list[_TitleCandidate] = []
    seen_line_indexes: set[int] = set()

    for index, line in enumerate(lines):
        text = line.text.strip()
        if not text:
            continue

        matched = _match_explicit_title(text)
        if matched and _has_us_context_after(lines, index):
            us_id, title = matched
            candidates.append(_TitleCandidate(us_id=us_id, title=title, line_index=index))
            seen_line_indexes.add(index)
            continue

        if index in seen_line_indexes:
            continue
        if _is_plain_title_before_gwt(lines, index):
            candidates.append(_TitleCandidate(us_id=None, title=text, line_index=index))

    return _dedupe_candidates(candidates)


def _find_gwt_fallback_candidates(lines: list[_LineInfo]) -> list[_TitleCandidate]:
    candidates: list[_TitleCandidate] = []
    for index, line in enumerate(lines):
        if not _starts_with_gwt_marker(line.text.strip()):
            continue

        previous_index = _previous_non_empty_line_index(lines, index - 1)
        if previous_index is None:
            candidates.append(_TitleCandidate(us_id=None, title="", line_index=index))
            continue

        title = lines[previous_index].text.strip()
        if _looks_like_non_title(title):
            candidates.append(_TitleCandidate(us_id=None, title="", line_index=index))
        else:
            candidates.append(
                _TitleCandidate(us_id=None, title=title, line_index=previous_index)
            )

    return _dedupe_candidates(candidates)


def _dedupe_candidates(candidates: list[_TitleCandidate]) -> list[_TitleCandidate]:
    deduped: list[_TitleCandidate] = []
    seen: set[int] = set()
    for candidate in sorted(candidates, key=lambda item: item.line_index):
        if candidate.line_index in seen:
            continue
        seen.add(candidate.line_index)
        deduped.append(candidate)
    return deduped


def _match_explicit_title(text: str) -> tuple[str, str] | None:
    text = _strip_markdown_heading(text)
    us_match = US_TITLE_RE.match(text)
    if us_match:
        return us_match.group(1), us_match.group(2).strip()

    numeric_match = NUMERIC_TITLE_RE.match(text)
    if not numeric_match:
        return None

    us_id = numeric_match.group(1)
    title = numeric_match.group(2).strip()
    if not title or _looks_like_non_title(title):
        return None
    return us_id, title


def _has_us_context_after(lines: list[_LineInfo], line_index: int) -> bool:
    checked = 0
    for index in range(line_index + 1, min(len(lines), line_index + 18)):
        text = lines[index].text.strip()
        if not text:
            continue
        if any(marker in text for marker in US_CONTEXT_MARKERS):
            return True
        if checked >= 10:
            break
        checked += 1
    return False


def _is_plain_title_before_gwt(lines: list[_LineInfo], line_index: int) -> bool:
    text = lines[line_index].text.strip()
    if not text or _looks_like_non_title(text):
        return False

    next_index = _next_non_empty_line_index(lines, line_index + 1)
    if next_index is None:
        return False
    return _starts_with_gwt_marker(lines[next_index].text.strip())


def _previous_non_empty_line_index(
    lines: list[_LineInfo], start_index: int
) -> int | None:
    for index in range(start_index, -1, -1):
        if lines[index].text.strip():
            return index
    return None


def _next_non_empty_line_index(lines: list[_LineInfo], start_index: int) -> int | None:
    for index in range(start_index, len(lines)):
        if lines[index].text.strip():
            return index
    return None


def _starts_with_gwt_marker(text: str) -> bool:
    return any(text.startswith(marker) for marker in GWT_MARKERS)


def _looks_like_non_title(text: str) -> bool:
    text = _strip_markdown_heading(text)
    if _starts_with_gwt_marker(text) or text.startswith("【业务规则】"):
        return True
    if "Primary Domain" in text or "Feature Catalog" in text:
        return True
    if BUSINESS_RULE_NUMBER_RE.match(text):
        return True
    if LOWER_SNAKE_RE.match(text):
        return True
    if "\t" in text and _field_header_score(text) >= 2:
        return True
    return False


def _strip_markdown_heading(text: str) -> str:
    match = MARKDOWN_HEADING_RE.match(text)
    if not match:
        return text.strip()
    return match.group(1).strip()


def _split_block_sections(
    block: UsBlock, lines: list[_LineInfo], content: str
) -> list[_SectionRange]:
    start_index = block.line_start - 1
    end_index = block.line_end - 1
    sections: list[_SectionRange] = []
    consumed: list[tuple[int, int]] = []

    gwt_range = _find_gwt_range(lines, start_index, end_index)
    if gwt_range:
        sections.append(
            _SectionRange(
                section_type="gwt",
                start_line_index=gwt_range[0],
                end_line_index=gwt_range[1],
            )
        )
        consumed.append(gwt_range)

    field_ranges = _find_field_table_ranges(lines, start_index, end_index)
    for range_start, range_end in field_ranges:
        sections.append(
            _SectionRange(
                section_type="field_table",
                start_line_index=range_start,
                end_line_index=range_end,
            )
        )
        consumed.append((range_start, range_end))

    for range_start, range_end in _complement_ranges(start_index, end_index, consumed):
        for section_start, section_end in _split_markdown_heading_ranges(
            lines, range_start, range_end
        ):
            trimmed = _trim_line_range(lines, section_start, section_end)
            if trimmed is None:
                continue
            segment_start, segment_end = trimmed
            segment_text = content[lines[segment_start].start : lines[segment_end].end]
            if _is_title_only_segment(segment_text, block):
                continue
            section_type = _classify_section(segment_text)
            sections.append(
                _SectionRange(
                    section_type=section_type,
                    start_line_index=segment_start,
                    end_line_index=segment_end,
                )
            )

    return sorted(sections, key=lambda section: section.start_line_index)


def _find_gwt_range(
    lines: list[_LineInfo], start_index: int, end_index: int
) -> tuple[int, int] | None:
    first = None
    last = None
    for index in range(start_index, end_index + 1):
        text = lines[index].text.strip()
        if _starts_with_gwt_marker(text):
            if first is None:
                first = index
            last = index
            continue
        if first is not None:
            break

    if first is None or last is None:
        return None
    return first, last


def _find_field_table_ranges(
    lines: list[_LineInfo], start_index: int, end_index: int
) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    index = start_index
    while index <= end_index:
        if not _is_field_table_header(lines[index].text):
            index += 1
            continue

        range_start = index
        previous_index = _previous_non_empty_line_index(lines, index - 1)
        if previous_index is not None and previous_index >= start_index:
            previous_text = lines[previous_index].text.strip()
            if _is_field_table_intro(previous_text):
                range_start = previous_index

        range_end = index
        scan = index + 1
        while scan <= end_index:
            text = lines[scan].text.strip()
            if _is_major_non_table_heading(text):
                break
            range_end = scan
            scan += 1

        trimmed = _trim_line_range(lines, range_start, range_end)
        if trimmed is not None:
            ranges.append(trimmed)
        index = max(scan, index + 1)

    return ranges


def _is_field_table_header(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    if _field_header_score(normalized) >= 3:
        return True
    return "\t" in normalized and _field_header_score(normalized) >= 2


def _field_header_score(text: str) -> int:
    lowered = text.lower()
    score = 0
    for term in FIELD_HEADER_TERMS:
        if term.lower() in lowered:
            score += 1
    return score


def _is_field_table_intro(text: str) -> bool:
    return any(term in text for term in ("数据模型", "查询条件", "字段", "Field"))


def _is_major_non_table_heading(text: str) -> bool:
    if not text:
        return False
    if MARKDOWN_HEADING_RE.match(text):
        return True
    if BUSINESS_RULE_NUMBER_RE.match(text):
        return False
    if not MAJOR_SECTION_RE.match(text):
        return False
    return not _is_field_table_intro(text)


def _complement_ranges(
    start_index: int, end_index: int, consumed: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    if start_index > end_index:
        return []

    sorted_ranges = sorted(consumed)
    result: list[tuple[int, int]] = []
    cursor = start_index
    for range_start, range_end in sorted_ranges:
        if cursor < range_start:
            result.append((cursor, range_start - 1))
        cursor = max(cursor, range_end + 1)
    if cursor <= end_index:
        result.append((cursor, end_index))
    return result


def _split_markdown_heading_ranges(
    lines: list[_LineInfo], start_index: int, end_index: int
) -> list[tuple[int, int]]:
    headings = [
        index
        for index in range(start_index, end_index + 1)
        if MARKDOWN_HEADING_RE.match(lines[index].text.strip())
    ]
    if not headings:
        return [(start_index, end_index)]

    result: list[tuple[int, int]] = []
    cursor = start_index
    for heading_index in headings:
        if cursor < heading_index:
            result.append((cursor, heading_index - 1))
        cursor = heading_index
    result.append((cursor, end_index))

    split_result: list[tuple[int, int]] = []
    for index, (range_start, _range_end) in enumerate(result):
        next_start = result[index + 1][0] if index + 1 < len(result) else end_index + 1
        split_result.append((range_start, next_start - 1))
    return split_result


def _trim_line_range(
    lines: list[_LineInfo], start_index: int, end_index: int
) -> tuple[int, int] | None:
    while start_index <= end_index and not lines[start_index].text.strip():
        start_index += 1
    while end_index >= start_index and not lines[end_index].text.strip():
        end_index -= 1
    if start_index > end_index:
        return None
    return start_index, end_index


def _is_title_only_segment(segment_text: str, block: UsBlock) -> bool:
    lines = [line.strip() for line in segment_text.splitlines() if line.strip()]
    if not lines:
        return True
    if len(lines) == 1:
        matched = _match_explicit_title(lines[0])
        if matched:
            return matched[0] == block.us_id
        return lines[0] == block.title
    return False


def _is_metadata_only_segment(segment_text: str, block: UsBlock) -> bool:
    lines = [line.strip() for line in segment_text.splitlines() if line.strip()]
    if not lines:
        return True

    for line in lines:
        stripped = _strip_markdown_heading(line)
        matched = _match_explicit_title(line)
        if matched and matched[0] == block.us_id:
            continue
        if stripped == block.title:
            continue
        if "Primary Domain" in stripped or "Feature Catalog" in stripped:
            continue
        if stripped in {"---", "***"}:
            continue
        return False
    return True


def _classify_section(text: str) -> str:
    if not text.strip():
        return "unknown"
    if _is_us_header_segment(text):
        return "us_header"
    if any(marker in text for marker in GWT_MARKERS):
        return "gwt"
    if _is_field_table_header(text) or _has_tabular_field_rows(text):
        return "field_table"
    if _contains_any(text, DFX_TERMS):
        return "dfx_rule"
    if _contains_any(text, ACCEPTANCE_TERMS):
        return "acceptance_criteria"
    if _contains_any(text, API_TERMS):
        return "api_desc"
    if _contains_any(text, TASK_TERMS):
        return "task_rule"
    if _contains_any(text, MIGRATION_TERMS):
        return "migration_rule"
    if _is_report_section(text):
        return "report_rule"
    if _contains_any(text, STATE_TERMS):
        return "state_rule"
    if _contains_any(text, MESSAGE_TERMS):
        return "message_rule"
    if _contains_any(text, UI_REFERENCE_TERMS):
        return "ui_reference"
    if "【业务规则】" in text or "业务规则" in text:
        return "business_rule"
    return "unknown"


def _is_us_header_segment(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    has_title = any(_match_explicit_title(line) for line in lines)
    has_primary_domain = any("Primary Domain" in line for line in lines)
    has_feature_catalog = any("Feature Catalog" in line for line in lines)
    return has_title and (has_primary_domain or has_feature_catalog)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _is_report_section(text: str) -> bool:
    if _contains_any(text, REPORT_PRIMARY_TERMS):
        return True
    lowered = text.lower()
    return sum(1 for term in REPORT_TERMS if term.lower() in lowered) >= 2


def _has_tabular_field_rows(text: str) -> bool:
    tabular_lines = 0
    for line in text.splitlines():
        if line.count("\t") >= 2:
            tabular_lines += 1
        if tabular_lines >= 2:
            return True
    return False


def _make_source_text_unit(
    content: str,
    document_id: str,
    us_id: str | None,
    feature_key: str | None,
    domain_code: str | None,
    section_type: str,
    chunk_index: int,
    start: int,
    end: int,
    line_start: int,
    line_end: int,
    file_path: str | None,
) -> SourceTextUnit:
    chunk_text = content[start:end]
    text_hash = hashlib.md5(chunk_text.encode("utf-8")).hexdigest()[:16]
    id_seed = "|".join(
        [
            document_id,
            us_id or "",
            section_type,
            str(chunk_index),
            chunk_text,
        ]
    )
    return SourceTextUnit(
        text_unit_id=stable_hash(id_seed, "TU"),
        document_id=document_id,
        us_id=us_id,
        feature_key=feature_key,
        domain_code=domain_code,
        section_type=section_type,
        chunk_index=chunk_index,
        chunk_text=chunk_text,
        source_span={
            "start": start,
            "end": end,
            "line_start": line_start,
            "line_end": line_end,
        },
        text_hash=text_hash,
        file_path=file_path,
    )


def _extract_dsl_mappings(
    dsl_result: DslCompiledResult | dict[str, Any] | None,
) -> dict[str, dict[str, dict[str, str | None]]]:
    raw = _dsl_raw(dsl_result)
    if not raw:
        return {"plan": {}, "feature": {}}

    plan_by_us: dict[str, dict[str, str | None]] = {}
    for item in _dict_list(raw.get("sourceVectorizationPlan")):
        source_us_id = _string_or_none(item.get("sourceUsId"))
        if not source_us_id or source_us_id in plan_by_us:
            continue
        plan_by_us[source_us_id] = {
            "feature_key": _string_or_none(item.get("featureKey")),
            "domain_code": _string_or_none(item.get("domainCode")),
            "section_type": _string_or_none(item.get("sectionType")),
        }

    feature_by_us: dict[str, dict[str, str | None]] = {}
    for item in _dict_list(raw.get("featureCatalogIndex")):
        feature_key = _string_or_none(item.get("featureKey"))
        domain_code = _string_or_none(item.get("primaryDomain"))
        source_us_ids = item.get("sourceUsIds")
        if not isinstance(source_us_ids, list):
            continue
        for source_us_id in source_us_ids:
            if isinstance(source_us_id, str) and source_us_id not in feature_by_us:
                feature_by_us[source_us_id] = {
                    "feature_key": feature_key,
                    "domain_code": domain_code,
                    "section_type": None,
                }

    return {"plan": plan_by_us, "feature": feature_by_us}


def _mapping_for_us(
    us_id: str | None,
    mappings: dict[str, dict[str, dict[str, str | None]]],
) -> tuple[str | None, str | None, str | None]:
    if not us_id:
        return None, None, None

    mapping = mappings["plan"].get(us_id) or mappings["feature"].get(us_id)
    if not mapping:
        return None, None, None

    return (
        mapping.get("feature_key"),
        mapping.get("domain_code"),
        mapping.get("section_type"),
    )


def _dsl_raw(dsl_result: DslCompiledResult | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(dsl_result, DslCompiledResult):
        return dsl_result.raw
    if isinstance(dsl_result, dict):
        return dsl_result
    return {}


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None
