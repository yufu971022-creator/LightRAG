from __future__ import annotations

from .graph_answer_types import GraphAnswerContext


def build_graph_answer_prompt(context: GraphAnswerContext) -> str:
    return "\n".join(
        [
            "你是企业产品功能知识库问答助手。",
            "请只根据提供的文本证据和图谱路径回答问题。",
            "不得使用外部知识或常识补充业务规则。",
            "每个关键结论必须标注 evidence_id。",
            "如果某结论只由图谱路径支持，也必须标注路径中节点/边对应的 evidence_id。",
            "如果证据不足，请明确说明“当前证据不足”。",
            "不要把 Candidate 当 Confirmed。",
            "不要把 InfoOnly 当事实。",
            "不要生成 source evidence 中不存在的接口、字段、台账、状态、待办、报表。",
            "",
            f"用户问题：{context.query_text}",
            "",
            "文本证据：",
            _evidence_block(context, from_graph=False),
            "",
            "图谱节点：",
            _graph_hit_block(context.node_hits),
            "",
            "图谱关系：",
            _graph_hit_block(context.edge_hits),
            "",
            "图谱路径：",
            _graph_path_block(context),
            "",
            "输出要求：",
            "1. 先给出结论。",
            "2. 再列出证据。",
            "3. 若涉及影响路径，列出路径。",
            "4. 不得输出无证据结论。",
            "5. 不得把 Candidate 写成已确认事实。",
        ]
    )


def build_text_only_answer_prompt(context: GraphAnswerContext) -> str:
    return "\n".join(
        [
            "你是企业产品功能知识库问答助手。",
            "请只根据提供的文本证据回答问题。",
            "不得使用图谱关系、外部知识或常识补充业务规则。",
            "每个关键结论必须标注 evidence_id。",
            "",
            f"用户问题：{context.query_text}",
            "",
            "文本证据：",
            _evidence_block(context, from_graph=False),
            "",
            "输出要求：简洁中文回答；证据不足时说明当前证据不足。",
        ]
    )


def _evidence_block(context: GraphAnswerContext, *, from_graph: bool) -> str:
    lines = [
        (
            f"- {item.evidence_id}: {item.evidence_text} "
            f"(sourceUsId={item.source_us_id}, textUnitId={item.text_unit_id}, "
            f"textHash={item.text_hash})"
        )
        for item in context.evidence_items
        if item.from_graph is from_graph
    ]
    return "\n".join(lines) if lines else "- 无"


def _graph_hit_block(hits: list) -> str:
    lines = [
        (
            f"- {getattr(hit, 'entity_name', None) or ''} "
            f"{getattr(hit, 'relation_type', None) or ''} "
            f"(source_id={getattr(hit, 'source_id', None)})"
        ).strip()
        for hit in hits
    ]
    return "\n".join(lines) if lines else "- 无"


def _graph_path_block(context: GraphAnswerContext) -> str:
    lines = [
        (
            f"- {path.path_id}: {' -> '.join(path.nodes)}; "
            f"relations={', '.join(path.relation_sequence)}"
        )
        for path in context.graph_paths
    ]
    return "\n".join(lines) if lines else "- 无"


__all__ = ["build_graph_answer_prompt", "build_text_only_answer_prompt"]
