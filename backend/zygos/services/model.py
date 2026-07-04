"""ModelService — the RFC-0001 §2 model contract over the provider router.

classify_task is a deliberate heuristic stub in M2; the RDT milestone (M3)
deepens it and makes routing consume it.

Stability: Experimental.
"""

import re
from typing import AsyncIterator, Literal, Protocol

from zygos.providers.types import GenerationChunk, GenerationRequest, GenerationResult
from zygos.services.router import ProviderRouter, RouteChoice

TaskClassification = Literal["simple", "standard", "complex_reasoning", "code"]

_CODE_MARKERS = ("```", "def ", "import ", "function ")
_REASONING = re.compile(r"\b(why|analyze|prove|design|architecture|compare|trade-?off)\b", re.IGNORECASE)


def classify_task(prompt: str) -> TaskClassification:
    if any(marker in prompt for marker in _CODE_MARKERS):
        return "code"
    if len(prompt) > 800 or _REASONING.search(prompt):
        return "complex_reasoning"
    if len(prompt) < 70:
        return "simple"
    return "standard"


class ModelService(Protocol):
    def classify_task(self, prompt: str) -> TaskClassification: ...

    def select_model(self, classification: TaskClassification | None = None) -> RouteChoice: ...

    async def generate(self, request: GenerationRequest) -> GenerationResult: ...

    def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]: ...


class DefaultModelService:
    def __init__(self, router: ProviderRouter) -> None:
        self._router = router

    def classify_task(self, prompt: str) -> TaskClassification:
        return classify_task(prompt)

    def select_model(self, classification: TaskClassification | None = None) -> RouteChoice:
        # M2: classification does not alter routing yet (M3 hook).
        return self._router.first_eligible()

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return await self._router.generate(request)

    def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        return self._router.stream(request)
