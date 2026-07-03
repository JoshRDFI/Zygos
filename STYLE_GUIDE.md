# Zygos Style Guide

This guide codifies the conventions the Zygos codebase already uses. It exists to
make the right choice obvious and to give reviewers a shared reference. When in
doubt about a convention not covered here, look at existing code in the same module
and match it.

## Python (v2)

**Language version.** The backend requires Python 3.12 or later. Use the features
available in 3.12 — union types with `|`, `match` statements, `tomllib`, and so on
— without wrapping them in compatibility shims.

**PEP 8 as baseline.** The standard PEP 8 rules apply: 4-space indentation, 88-
character line limit (Black's default), and `snake_case` for functions and variables.
Where this guide says something more specific, the more specific rule wins.

**Service interfaces use `typing.Protocol`.** Every service boundary is expressed as
a `Protocol`. Protocols define what a service can do without naming a particular
implementation. Implementations are assembled in the composition root
(`runtime/bootstrap.py`) and nowhere else. Never import a concrete implementation
class from a module that should be unaware of it.

**Frozen dataclasses for assemblies and state snapshots.** Any value that represents
a completed assembly (like `RuntimeAssembly`) or a point-in-time snapshot must use
`@dataclass(frozen=True)`. Mutability in assemblies and snapshots is a review-
blocking smell.

**Pydantic models with `extra="forbid"`.** All configuration classes extend
`pydantic.BaseModel` and set `model_config = ConfigDict(extra="forbid")`. Unknown
fields in config should be a hard error, not a silent ignore. This applies to every
model that reads user-supplied data.

**Errors subclass `ZygosError` with a stable code.** All exceptions raised by the
runtime extend `ZygosError` and declare a class-level `code` attribute whose value
is a stable, machine-readable string. Once a `code` is published it must not change
— downstream code may match on it. Example:

```python
class PluginError(ZygosError):
    code = "plugin_resolution_failed"
```

**Module docstrings cite the governing RFC section.** Every module starts with a
docstring that states its purpose and, where applicable, the RFC section that
governs its design. This makes the relationship between documentation and
implementation traceable. Example:

```python
"""Composition root (RFC-0001 §3)."""
```

### Public vs internal

Public API consists of names exported through package `__init__.py` `__all__` lists
and all `typing.Protocol` classes. Internal API includes underscore-prefixed modules
(e.g., `zygos.services._breaker`) and any unexported names. Every module docstring
must cite its governing RFC section and declare its stability level from
[COMPATIBILITY.md](./COMPATIBILITY.md). Example for Experimental stability:
`"""Provider routing (RFC-0001 §4). Stability: Experimental."""` Applied prospectively
— no retroactive renames.

**Imports at module level.** All import statements belong at the top of the file,
after the module docstring. Local imports inside functions or classes are not
permitted except in the rare case where they are required to break a circular import
— and that case is itself a signal that the module boundary needs re-examination.

## Tests

**Framework.** All v2 tests use [pytest](https://docs.pytest.org). No `unittest.TestCase`
subclasses. No custom test runners.

**Test-driven development.** Write the failing test first. The pull request must
include evidence that the test failed before the implementation was added (the RED
step) and passes after (the GREEN step). Reviewers will ask for this evidence if it
is absent.

**Test names describe behavior.** A test name should read like a sentence describing
what the system does under a specific condition. Prefer long, specific names over
short, generic ones.

- Good: `test_primary_route_missing_required_key_fails_fast`
- Good: `test_registry_rejects_unknown_plugin`
- Avoid: `test_loader_2`, `test_error`, `test_case_3`

**Use `monkeypatch` for environment variables and `tmp_path` for files.** These are
pytest's built-in fixtures for the two most common external dependencies in unit
tests. Avoid writing to real filesystem paths or modifying `os.environ` directly.

**Prefer real objects over mocks.** When a test can use a real implementation — a
real stdlib class, a real config object, a real registry — it should. The plugin
tests, for example, resolve actual `collections.OrderedDict` rather than mocking
the resolver. Mocks are appropriate when the real dependency involves I/O that
cannot reasonably be performed in a unit test; they are not a default.

## TypeScript (v1)

v1 (`src/`) is **frozen**. It accepts bugfixes only.

When fixing a bug in v1:

- Match the surrounding file's style exactly. Do not introduce new formatting
  conventions, rename identifiers, or reorganize imports.
- Do not add new dependencies. If a fix seems to require a new package, the fix is
  out of scope for v1.
- Do not restructure modules or move code between files. The change should be as
  narrow as possible.

If a fix cannot be made narrowly without restructuring, bring it to the maintainers
as an issue before proceeding.

## Documentation

**One source of truth per topic.** If two documents cover the same topic, one of
them should link to the other rather than repeating the content. Duplication means
that one copy will eventually become stale.

**Relative links between project docs.** All links between project documentation
files use relative paths (e.g., `[CONSTITUTION.md](CONSTITUTION.md)`, not an
absolute URL to the repository host). Relative links work in any fork and any
local checkout.

**RFCs are immutable once accepted.** An accepted RFC is a historical record of a
decision. Do not amend it. If the decision needs to change, write a new RFC that
supersedes it and reference the original.

**Keep README's quick start runnable.** The quick-start commands in README.md must
work on a clean checkout without any prior setup. Before changing the setup
instructions, verify the new commands on a machine that does not already have the
project installed.
