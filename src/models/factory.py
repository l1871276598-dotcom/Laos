from .codex import CodexReviewBackend
from .openai_compatible import OpenAICompatibleBackend
from .registry import ModelBackendRegistry
from .router import AdaptiveModelRouterBackend


def build_model_backend(config=None, registry=None):
    values = config or {"backend": "codex", "options": {}}
    if not isinstance(values, dict):
        raise ValueError("model backend config must be an object")
    if not set(values) <= {"backend", "options"}:
        raise ValueError("model backend config has unsupported fields")
    active = registry or ModelBackendRegistry()
    if registry is None:
        active.register("codex", CodexReviewBackend)
        active.register("openai_compatible", OpenAICompatibleBackend)
        active.register("adaptive_router", AdaptiveModelRouterBackend)
    return active.create(values.get("backend", "codex"), values.get("options", {}))
