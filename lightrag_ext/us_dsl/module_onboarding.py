from __future__ import annotations


def render_module_onboarding_checklist(
    *,
    module_name: str | None = None,
    module_fixture_found: bool = True,
    additional_module_fixture_note: str | None = None,
) -> str:
    name = module_name or "New module"
    fixture_status = "found" if module_fixture_found else "not found"
    lines = [
        f"# Module Onboarding Checklist - {name}",
        "",
        "## Scope",
        "- Add a representative User Story fixture for the module.",
        "- Add or reuse a module registry only for terminology and ontology aliases.",
        "- Keep production logic module-agnostic.",
        "- Reuse the same report-only pilot validation flow.",
        "",
        "## Required Inputs",
        f"- Module fixture: {fixture_status}",
        "- DSL compiler output or minimal validated DSL mapping.",
        "- Source US IDs and source text units.",
        "- Evidence metadata: sourceUsId, textUnitId, sourceSpan, textHash, evidenceText.",
        "",
        "## Guardrails",
        "- Do not write graph.",
        "- Do not write GES or formal store.",
        "- Do not mark candidates as Confirmed.",
        "- Do not auto-promote candidates.",
        "- Do not add module-name branches to production logic.",
        "",
        "## Validation",
        "- Run hardcode audit.",
        "- Run candidate extraction dry-run.",
        "- Run candidate review report.",
        "- Generate Pilot Report Pack.",
        "- Confirm review burden is acceptable.",
    ]
    if additional_module_fixture_note:
        lines.extend(["", "## Fixture Coverage Note", f"- {additional_module_fixture_note}"])
    return "\n".join(lines)


__all__ = ["render_module_onboarding_checklist"]
