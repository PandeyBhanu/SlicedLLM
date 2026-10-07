import re
from typing import Any

_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


class TemplateError(ValueError):
    pass


def extract_variables(template: str) -> list[str]:
    """Unique `{{name}}` placeholders in order of first appearance."""
    seen: dict[str, None] = {}
    for name in _VAR.findall(template):
        seen.setdefault(name, None)
    return list(seen)


def render_template(template: str, variables: dict[str, Any]) -> str:
    """Substitute `{{name}}`. Unknown variables are an error, never a silent placeholder."""
    missing = [v for v in extract_variables(template) if v not in variables]
    if missing:
        raise TemplateError(f"Template uses undefined variable(s): {', '.join(missing)}")
    return _VAR.sub(lambda m: str(variables[m.group(1)]), template)
