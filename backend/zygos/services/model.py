"""ModelService — the RFC-0001 §2 model contract over the provider router.

classify_task is a heuristic classifier; select_model consumes it via task_routes (M3).

Stability: Experimental.
"""

import re
from typing import AsyncIterator, Literal, Mapping, Protocol

from zygos.providers.types import GenerationChunk, GenerationRequest, GenerationResult
from zygos.runtime.context import ExecutionContext
from zygos.services.router import ProviderRouter, RouteChoice

TaskClassification = Literal["simple", "standard", "complex_reasoning", "code"]

_CODE_MARKERS = ("```", "def ", "import ", "function ")
_REASONING = re.compile(r"\b(why|analyze|prove|design|architecture|compare|trade-?off)\b", re.IGNORECASE)


def classify_task(prompt: str) -> TaskClassification:
    if any(marker in prompt for marker in _CODE_MARKERS):
        return "code"
    if len(prompt) > 800 or _REASONING.search(prompt):
        return "complex_reasoning"
    if len(prompt) < 80:
        return "simple"
    return "standard"


class ModelService(Protocol):
    def classify_task(self, prompt: str) -> TaskClassification: ...

    def select_model(self, classification: TaskClassification | None = None) -> RouteChoice: ...

    async def generate(self, ctx: ExecutionContext, request: GenerationRequest) -> GenerationResult: ...

    def stream(self, ctx: ExecutionContext, request: GenerationRequest) -> AsyncIterator[GenerationChunk]: ...


class DefaultModelService:
    def __init__(self, router: ProviderRouter, task_routes: Mapping[str, RouteChoice] | None = None) -> None:
        self._router = router
        self._task_routes = dict(task_routes) if task_routes else {}

    def classify_task(self, prompt: str) -> TaskClassification:
        return classify_task(prompt)

    def select_model(self, classification: TaskClassification | None = None) -> RouteChoice:
        if classification is not None and classification in self._task_routes:
            return self._task_routes[classification]
        return self._router.first_eligible()

    async def generate(self, ctx: ExecutionContext, request: GenerationRequest) -> GenerationResult:
        return await self._router.generate(ctx, request)

    def stream(self, ctx: ExecutionContext, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        return self._router.stream(ctx, request)
