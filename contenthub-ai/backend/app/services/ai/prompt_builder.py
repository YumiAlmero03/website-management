from __future__ import annotations

from typing import Any

from jinja2 import StrictUndefined, TemplateSyntaxError, UndefinedError, meta
from jinja2.sandbox import SandboxedEnvironment

from app.services.ai.defaults import ALLOWED_PROMPT_VARIABLES
from app.services.ai.exceptions import PromptSecurityError

_SAFE_ENV = SandboxedEnvironment(
    autoescape=False,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
# Clear dangerous default globals and permit only safe string/length filters
_SAFE_ENV.globals.clear()
_ALLOWED_FILTERS = {"default", "join", "length", "lower", "trim", "truncate", "upper"}
_SAFE_ENV.filters = {k: v for k, v in _SAFE_ENV.filters.items() if k in _ALLOWED_FILTERS}

_ALLOWED_VAR_SET = frozenset(ALLOWED_PROMPT_VARIABLES)


def validate_template_source(template_source: str, *, label: str = "prompt template") -> set[str]:
    """Validate Jinja2 syntax, reject dunder/attribute traversal, and restrict variable names."""
    if "__" in template_source:
        raise PromptSecurityError(
            f"Unsafe double-underscore expression rejected in {label}."
        )
    try:
        parsed_ast = _SAFE_ENV.parse(template_source)
    except TemplateSyntaxError as exc:
        raise PromptSecurityError(f"Invalid Jinja2 syntax in {label}: {exc.message}") from exc

    referenced = meta.find_undeclared_variables(parsed_ast)
    disallowed = sorted(v for v in referenced if v not in _ALLOWED_VAR_SET)
    if disallowed:
        raise PromptSecurityError(
            f"Unsupported template variable(s) in {label}: {', '.join(disallowed)}. "
            f"Allowed variables: {', '.join(ALLOWED_PROMPT_VARIABLES)}"
        )
    return referenced


def render_sandboxed_prompt(
    *,
    system_instructions: str,
    user_prompt_template: str,
    variables: dict[str, Any],
) -> tuple[str, str]:
    """Safely render system & user templates using an explicit whitelist of variables."""
    validate_template_source(system_instructions, label="system_instructions")
    validate_template_source(user_prompt_template, label="user_prompt_template")

    safe_context: dict[str, Any] = {key: "" for key in ALLOWED_PROMPT_VARIABLES}
    for key in ALLOWED_PROMPT_VARIABLES:
        if key in variables and variables[key] is not None:
            safe_context[key] = variables[key]

    try:
        rendered_system = _SAFE_ENV.from_string(system_instructions).render(**safe_context).strip()
        rendered_user = _SAFE_ENV.from_string(user_prompt_template).render(**safe_context).strip()
    except (UndefinedError, TemplateSyntaxError, SecurityError) as exc:
        raise PromptSecurityError(f"Template rendering error: {exc}") from exc

    return rendered_system, rendered_user


# Import SecurityError cleanly in case Jinja2 raises Sandbox SecurityError during evaluation
from jinja2.exceptions import SecurityError  # noqa: E402
