# Compatibility and Stability

This page says what you can rely on when building on Zygos — which interfaces are
safe to depend on, how version numbers signal intent, and what guarantees apply to
skills, plugins, configs, and traces across releases.

## API stability levels

**Stable** — Breaking changes only at a major version, after a deprecation cycle
of one minor version. Deprecated symbols are annotated and logged; they
are removed in the next major.

**Beta** — Breaking changes are allowed at minor versions; migration notes are
provided in the changelog. Suitable for integrations you can update on a
minor-version cadence.

**Experimental** — May change or vanish in any release without notice. Do not
build production dependencies on Experimental interfaces.

**Internal** — Underscore-prefixed names or unexported symbols. Never rely on
these; they carry no compatibility promise of any kind.

**Current state:** Everything in `zygos.*` is Experimental until 2.0. The v1
TypeScript runtime (`src/`) is **Frozen**: bugfixes only, no interface changes.

Stability levels are declared in module docstrings. See
[STYLE_GUIDE.md](./STYLE_GUIDE.md) for the docstring convention.

## Version philosophy

- **Major** — Architecture change. A new major version may break any interface
  that has not been promoted to Stable or above.
- **Minor** — New capabilities. Minor versions add features and may break Beta
  interfaces (with migration notes); Stable interfaces are never broken at a
  minor.
- **Patch** — Bugfixes only. No interface changes, no new features.

**2.0 is the complete migration from v1, including voice interaction**
([ROADMAP.md](./ROADMAP.md)). Voice is not a stretch goal — it is a hard
requirement before the 2.0 tag is applied.

2.x minors beyond 2.0 will add capabilities that have no v1 equivalent: new
memory backends, new workflow types, and community-ecosystem features.

Pre-2.0, the package version is a `2.0.0aN` pre-release (currently `2.0.0a0`).
The `2.0.0aN` scheme signals that no interface in the package is yet Stable.

## Compatibility promises

The table below shows what you can count on for each artifact type before 2.0
ships and at the 2.0 release.

| Artifact | Pre-2.0 | At 2.0 |
|---|---|---|
| **Skills** | No guarantee — breaking changes allowed, noted in commit history | Beta (format may evolve with migration notes) |
| **Plugins** | No guarantee — breaking changes allowed, noted in commit history | Stable (constructor contract `cls(settings, client)` and Protocol conformance) |
| **Configs** | No guarantee — breaking changes allowed, noted in commit history | Stable (schema versioned, one-minor deprecation cycle) |
| **Traces** | No guarantee — breaking changes allowed, noted in commit history | Beta (schema may evolve with migration notes) |
