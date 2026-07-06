"""Suite loading + validation. Pure; fails fast. Stability: Experimental."""

from collections import Counter
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from zygos.eval.types import Category, Split, Task


class SuiteError(Exception):
    """Raised on malformed or invalid suite files."""


class Suite(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    tasks: tuple[Task, ...]

    def filter(
        self, split: Split | None = None, category: Category | None = None
    ) -> tuple[Task, ...]:
        return tuple(
            t for t in self.tasks
            if (split is None or t.split == split)
            and (category is None or t.category == category)
        )


def load_suite(path: str | Path) -> Suite:
    try:
        text = Path(path).read_text()
    except OSError as exc:
        raise SuiteError(f"cannot read suite file {path}: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SuiteError(f"malformed YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict) or "suite" not in raw or "tasks" not in raw:
        raise SuiteError(f"{path} must be a mapping with 'suite' and 'tasks' keys")
    try:
        tasks = tuple(Task(**item) for item in raw["tasks"])
    except (ValidationError, TypeError) as exc:
        raise SuiteError(f"invalid task in {path}: {exc}") from exc
    ids = [t.id for t in tasks]
    dupes = sorted(i for i, c in Counter(ids).items() if c > 1)
    if dupes:
        raise SuiteError(f"duplicate task ids in {path}: {dupes}")
    return Suite(name=str(raw["suite"]), tasks=tasks)
