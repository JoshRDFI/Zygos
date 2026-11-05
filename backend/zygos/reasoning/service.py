"""ReasoningService — adaptive prelude -> recurrent -> coda orchestration.

Consumes ModelService; emits request.*/model.selected; exposes a snapshotable
ReasoningState. Always runs the full loop (the disabled bypass is external).
Stability: Experimental.
"""

import time
from collections.abc import Callable
from typing import Protocol

from zygos.config.schema import ReasoningConfig
from zygos.providers.types import GenerationRequest, Message
from zygos.reasoning import adaptive, confidence, prompts
from zygos.reasoning.profiles import resolve_profile
from zygos.reasoning.types import (
    AdaptiveDecision, IterationRecord, ReasoningInput,
    ReasoningResult, ReasoningState,
)
from zygos.runtime.context import ExecutionContext
from zygos.runtime.events import ModelSelected, RequestFinished, RequestStarted
from zygos.services.model import CONFIG_ORDER, ModelService, TurnRoute
from zygos.services.router import RouteChoice
from zygos.thinking.capture import Step, ThinkingRecorder


class ReasoningService(Protocol):
    async def run(self, ctx: ExecutionContext, input: ReasoningInput, *,
                  thinking: ThinkingRecorder | None = None,
                  route: TurnRoute | None = None,
                  on_route: Callable[[RouteChoice], None] | None = None,
                  on_loading: Callable[[RouteChoice], None] | None = None) -> ReasoningResult: ...

    def snapshot(self) -> ReasoningState: ...


class DefaultReasoningService:
    def __init__(self, model_service: ModelService, config: ReasoningConfig) -> None:
        self._model = model_service
        self._config = config
        self._running = False
        self._reset()

    def _reset(self) -> None:
        self._stage: str = "idle"
        self._decomposition: tuple[str, ...] = ()
        self._iterations: list[IterationRecord] = []
        self._best: int | None = None
        self._final: str | None = None
        self._halted_early = False
        self._cancelled = False
        self._selected_model: str | None = None
        self._routing: dict = {}

    def snapshot(self) -> ReasoningState:
        return ReasoningState(
            stage=self._stage,  # type: ignore[arg-type]
            decomposition=self._decomposition,
            iterations=tuple(self._iterations),
            best_iteration=self._best,
            final_answer=self._final,
            halted_early=self._halted_early,
            cancelled=self._cancelled,
            selected_model=self._selected_model,
        )

    async def _call(self, ctx: ExecutionContext, prompt: str, *, model: str, temperature: float,
                    max_tokens: int | None = None, system: tuple[str, ...] = (),
                    think: bool | None = None, step: Step = "direct", index: int = 0,
                    recorder: ThinkingRecorder | None = None) -> str:
        messages = (*(Message(role="system", content=t) for t in system),
                    Message(role="user", content=prompt))
        request = GenerationRequest(
            model=model, messages=messages,
            temperature=temperature, max_tokens=max_tokens, think=think,
        )
        t0 = time.monotonic()
        result = await self._model.generate(ctx, request, **self._routing)
        if recorder is not None:
            await recorder.record(ctx, step=step, index=index, text=result.thinking,
                                  elapsed_ms=int((time.monotonic() - t0) * 1000))
        return result.text

    async def run(self, ctx: ExecutionContext, input: ReasoningInput, *,
                  thinking: ThinkingRecorder | None = None,
                  route: TurnRoute | None = None,
                  on_route: Callable[[RouteChoice], None] | None = None,
                  on_loading: Callable[[RouteChoice], None] | None = None) -> ReasoningResult:
        """``route`` is the turn's pinned route (RFC-0013 §5): every call uses it and
        model.selected reports it. CONFIG_ORDER: select_model without the saved default,
        then the router's configured order. None: the old per-call lookup."""
        if self._running:
            raise RuntimeError(
                "ReasoningService.run is not re-entrant; a run is already in progress on this instance"
            )
        self._running = True
        try:
            self._reset()
            self._routing = {"route": route, "on_route": on_route, "on_loading": on_loading}
            profile = resolve_profile(self._config.profile)
            await ctx.emit(RequestStarted(prompt_chars=len(input.prompt)), source="reasoning")

            classification = self._model.classify_task(input.prompt)
            pick = classification if profile.escalate else None
            if isinstance(route, RouteChoice):
                selected = route
            elif route is CONFIG_ORDER:
                selected = self._model.select_model(pick, route=CONFIG_ORDER)
            else:
                selected = self._model.select_model(pick)
            route = selected
            self._selected_model = route.model
            await ctx.emit(
                # classification is the task classification, not necessarily the escalation reason (escalate may be off)
                ModelSelected(provider=route.provider, model=route.model, classification=classification),
                source="reasoning",
            )

            # Prelude (skipped if already cancelled — the router raises rather than
            # admitting a request once ctx.cancelled is set, so we must not call it).
            self._stage = "prelude"
            if ctx.cancelled:
                self._cancelled = True
                summary = "(cancelled before prelude completed)"
            else:
                prelude_text = await self._call(
                    ctx.child("prelude"), prompts.build_prelude(input.prompt, input.context),
                    model=route.model, temperature=profile.temperature, system=input.system,
                    think=input.think, step="prelude", index=0, recorder=thinking,
                )
                summary, self._decomposition = prompts.parse_prelude(prelude_text)

            # Recurrent loop
            self._stage = "recurrent"
            prior_summary = summary
            prior_aggregate: float | None = None
            threshold = profile.early_exit
            best_summary = summary
            best_confidence = 0.0
            revisions = 0

            for iteration in range(1, profile.max_iters + 1):
                if ctx.cancelled:
                    self._cancelled = True
                    break
                stalled = prior_aggregate is not None and prior_aggregate < profile.floor
                temperature = adaptive.temperature_for(profile, stalled)
                text = await self._call(
                    ctx.child(f"recurrent-{iteration}"),
                    prompts.build_recurrent(input.prompt, self._decomposition, prior_summary, iteration),
                    model=route.model, temperature=temperature,
                    think=input.think, step="recurrent", index=iteration, recorder=thinking,
                )
                current = prompts.parse_summary(text)
                breakdown = confidence.score(
                    current, prior_summary, self._decomposition, prior_aggregate, threshold, profile
                )

                heuristic_exit = breakdown.aggregate >= breakdown.threshold
                judge_exit: bool | None = None
                judge_used = False
                if confidence.in_fence_band(breakdown.aggregate, breakdown.threshold, profile.fence_band):
                    judge_used = True
                    judged = prompts.parse_judge(
                        await self._call(
                            # ADR-0006: no token cap — a starved thinking judge returns empty
                            # content and parse_judge would silently read 0.0.
                            ctx.child(f"judge-{iteration}"), prompts.build_judge(input.prompt, current),
                            model=route.model, temperature=0.0,
                            think=input.think, step="judge", index=iteration, recorder=thinking,
                        )
                    )
                    judge_exit = judged >= breakdown.threshold

                regressed = prior_aggregate is not None and (prior_aggregate - breakdown.aggregate) >= 0.12
                at_max = iteration >= profile.max_iters
                before_min = iteration < profile.min_iters
                action = adaptive.decide_action(
                    iteration, profile,
                    heuristic_exit=heuristic_exit and not before_min,
                    judge_exit=None if before_min else judge_exit,
                    regressed=regressed and revisions < profile.max_revision_depth,
                    at_max=at_max,
                )

                revised_from: int | None = None
                if action == "backtrack":
                    revisions += 1
                    revised_from = self._best
                    current = best_summary  # revert working summary to best

                self._iterations.append(IterationRecord(
                    index=iteration, summary=current, confidence=breakdown, judge_used=judge_used,
                    decision=AdaptiveDecision(
                        temperature=temperature, max_tokens=None, model=route.model, action=action,
                    ),
                    revised_from=revised_from,
                ))

                if breakdown.aggregate > best_confidence:
                    best_confidence = breakdown.aggregate
                    best_summary = current
                    self._best = iteration

                prior_summary = current
                prior_aggregate = breakdown.aggregate
                threshold = breakdown.threshold

                if action == "early_exit":
                    self._halted_early = True
                    break
                if action == "max_iters":
                    break

            # Coda (skipped on cancellation — return best-so-far without a further call)
            if self._cancelled:
                final = best_summary
            else:
                self._stage = "coda"
                final = await self._call(
                    ctx.child("coda"), prompts.build_coda(input.prompt, best_summary),
                    model=route.model, temperature=profile.temperature, system=input.system,
                    think=input.think, step="coda", index=0, recorder=thinking,
                )
            self._final = final
            self._stage = "cancelled" if self._cancelled else "done"
            await ctx.emit(
                RequestFinished(ok=not self._cancelled, loops_used=len(self._iterations)),
                source="reasoning",
            )
            return ReasoningResult(
                text=final, loops_used=len(self._iterations), final_confidence=best_confidence,
                halted_early=self._halted_early, model=route.model,
            )
        finally:
            self._running = False
