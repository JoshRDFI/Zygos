# ADR-0003: Config-Declared Plugins

**Status:** Accepted
**Date:** 2026-07-03

## Context

The v2 architecture treats providers, voice engines, and other swappable components as plugins resolved at startup. Before settling on a plugin-loading mechanism, two alternatives were evaluated, as recorded in [RFC-0001](../rfcs/RFC-0001-Service-Architecture.md):

- **Entry-point auto-discovery** (setuptools `entry_points`): installed packages advertise themselves; the runtime activates everything it finds. This is convenient for a mature ecosystem but weakens inspectability — code runs because a package is installed, not because a human wrote a config line. It is also premature before any community plugins exist.
- **Drop-in plugins directory**: the runtime scans a filesystem path and loads whatever it finds. This creates filesystem-implicit behavior and is awkward for image-based or droplet-class deployments where the filesystem is not a natural configuration surface.

## Decision

Plugins are declared explicitly in configuration using the mapping `kind → name → "module.path:ClassName"` — for example, `providers.ollama: "zygos_plugins.providers.ollama:OllamaProvider"`. The composition root (`runtime/bootstrap.py`) reads this map and imports exactly the classes listed. Reading the configuration file tells you exactly what code the runtime will load.

## Consequences

Every active plugin requires an explicit entry in the configuration file. This is an accepted cost: it is the price of full inspectability. Pip-installable community plugins with entry-point discovery are explicitly deferred to the Phase 8 ecosystem RFC, at which point auto-discovery can be layered on top of the config-declared mechanism without replacing it. Drop-in directory support is not planned. Image-based deployments benefit immediately because the plugin set is fully described by the config, with no filesystem scanning required.
