from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


BUSINESS_HARDCODE_TERMS = (
    "FX",
    "FXDeal",
    "AC",
    "ACDeal",
    "AT",
    "ATDeal",
    "LC",
    "LCAB",
    "Acceptable Bank",
    "可接受银行",
    "Bank Default Confirmation",
    "Swift Code",
    "Bank Internal Code",
    "Deal Number",
    "Agent Bank",
    "Pricing Type",
    "eflowNum",
    "Suggested Rating",
)

TEST_FIXTURE_ONLY = "TEST_FIXTURE_ONLY"
CONFIG_OR_EXAMPLE = "CONFIG_OR_EXAMPLE"
RULE_REGISTRY_ALLOWED = "RULE_REGISTRY_ALLOWED"
PRODUCTION_LOGIC_HARDCODE = "PRODUCTION_LOGIC_HARDCODE"
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class GeneralizationAuditFinding:
    path: str
    line_number: int
    term: str
    category: str
    line_preview: str


@dataclass
class GeneralizationAuditReport:
    total_findings: int
    production_hardcode_count: int
    test_fixture_hardcode_count: int
    config_example_count: int
    rule_registry_allowed_count: int
    unknown_count: int
    findings: list[GeneralizationAuditFinding] = field(default_factory=list)
    pass_status: str = "PASS"
    recommendations: list[str] = field(default_factory=list)


def run_generalization_audit(
    root_dir: str | Path = "lightrag_ext/us_dsl",
    *,
    allowed_test_hardcodes: bool = True,
) -> GeneralizationAuditReport:
    root = Path(root_dir)
    findings: list[GeneralizationAuditFinding] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if _skip_file(path):
            continue
        category = _category_for_path(path, root, allowed_test_hardcodes)
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for term in _terms_in_line(line):
                findings.append(
                    GeneralizationAuditFinding(
                        path=str(path.relative_to(root)),
                        line_number=line_number,
                        term=term,
                        category=category,
                        line_preview=line.strip()[:180],
                    )
                )
    production_count = sum(
        1 for finding in findings if finding.category == PRODUCTION_LOGIC_HARDCODE
    )
    test_count = sum(1 for finding in findings if finding.category == TEST_FIXTURE_ONLY)
    config_count = sum(1 for finding in findings if finding.category == CONFIG_OR_EXAMPLE)
    registry_count = sum(
        1 for finding in findings if finding.category == RULE_REGISTRY_ALLOWED
    )
    unknown_count = sum(1 for finding in findings if finding.category == UNKNOWN)
    pass_status = "FAIL" if production_count else ("WARN" if unknown_count else "PASS")
    recommendations = _recommendations(production_count, unknown_count, config_count)
    return GeneralizationAuditReport(
        total_findings=len(findings),
        production_hardcode_count=production_count,
        test_fixture_hardcode_count=test_count,
        config_example_count=config_count,
        rule_registry_allowed_count=registry_count,
        unknown_count=unknown_count,
        findings=findings,
        pass_status=pass_status,
        recommendations=recommendations,
    )


def serialize_generalization_audit_report(
    report: GeneralizationAuditReport,
) -> dict:
    return {
        **asdict(report),
        "findings": [asdict(finding) for finding in report.findings],
    }


def _terms_in_line(line: str) -> list[str]:
    terms: list[str] = []
    for term in BUSINESS_HARDCODE_TERMS:
        if _term_pattern(term).search(line):
            terms.append(term)
    return terms


def _term_pattern(term: str) -> re.Pattern[str]:
    if term in {"FX", "AC", "AT", "LC"}:
        return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])")
    return re.compile(re.escape(term))


def _category_for_path(
    path: Path,
    root: Path,
    allowed_test_hardcodes: bool,
) -> str:
    relative = path.relative_to(root)
    parts = set(relative.parts)
    name = path.name
    if "__pycache__" in parts:
        return UNKNOWN
    if "tests" in parts or "fixtures" in parts:
        return TEST_FIXTURE_ONLY if allowed_test_hardcodes else PRODUCTION_LOGIC_HARDCODE
    if name in {"config_registry.py", "generalization_audit.py"}:
        return RULE_REGISTRY_ALLOWED
    if any(part in {"scripts", "examples"} for part in parts):
        return CONFIG_OR_EXAMPLE
    if any(token in name for token in ("prompt", "eval", "smoke", "dry_run")):
        return CONFIG_OR_EXAMPLE
    return PRODUCTION_LOGIC_HARDCODE


def _skip_file(path: Path) -> bool:
    if path.suffix not in {".py", ".md", ".txt", ".json"}:
        return True
    return "__pycache__" in path.parts


def _recommendations(
    production_count: int,
    unknown_count: int,
    config_count: int,
) -> list[str]:
    recommendations = [
        "Keep module-specific names in fixtures, examples, or registry config.",
        "Do not branch production logic by module names such as FX, LC, AC, or AT.",
    ]
    if production_count:
        recommendations.append("Move production hardcodes into ConfigRegistry rules or fixtures.")
    if unknown_count:
        recommendations.append("Review UNKNOWN findings before pilot.")
    if config_count:
        recommendations.append("Ensure prompt/examples do not affect generic selector behavior.")
    return recommendations


__all__ = [
    "CONFIG_OR_EXAMPLE",
    "GeneralizationAuditFinding",
    "GeneralizationAuditReport",
    "PRODUCTION_LOGIC_HARDCODE",
    "RULE_REGISTRY_ALLOWED",
    "TEST_FIXTURE_ONLY",
    "UNKNOWN",
    "run_generalization_audit",
    "serialize_generalization_audit_report",
]
