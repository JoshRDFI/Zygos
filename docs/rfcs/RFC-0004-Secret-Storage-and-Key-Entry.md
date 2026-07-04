# RFC-0004: Secret Storage and Key Entry

- **Status:** Draft
- **Author:** Zygos maintainers
- **Created:** 2026-07-04
- **Governs:** how provider API keys (and future runtime secrets) are stored,
  entered, and resolved into the runtime
- **Depends on:** [RFC-0001](RFC-0001-Service-Architecture.md) — **amends its §8
  credential resolution**; builds on [ADR-0003](../adr/ADR-0003-config-declared-plugins.md)
  (config-declared plugins) and reinforces
  [RFC-0003](RFC-0003-Capability-Registry-Runtime-Manifest-and-Inspection.md)'s
  "manifest contains no secret material"
- **Implementation status:** tracked in [ROADMAP.md](../../ROADMAP.md); a
  standalone increment, orthogonal to Milestone 3 (not a gate); may ride with the
  CLI adapter

## Summary

Introduce a `SecretStore` service — a Protocol with pluggable, config-declared
backends (`keyring` for desktops, `encrypted_file` for droplets, `env`/secret-ref
for CI and external managers) — so provider keys are stored outside committed
config and resolved at bootstrap without the composition root knowing the backend.
Add a `zygos keys` CLI for entry, deprecate plaintext keys in config behind a loud
warning, and state an honest threat boundary: this protects against accidental
exposure, not against an attacker who already controls the machine.

## Motivation

Zygos deploys to **both** a user's own machine and a droplet-class VM (per
[VISION.md](../../VISION.md)). Provider keys must be usable by the runtime in both,
and — the maintainer's explicit second requirement — a user must have an *easy way
to enter them*. Today neither holds well:

- The only ways to supply a key are plaintext in the config YAML, a `${ENV_VAR}`
  placeholder, or a `<PROVIDER>_API_KEY` environment variable
  (`backend/zygos/config/loader.py`). The plaintext path invites committing a key
  to git; there is no entry UX at all.
- No single mechanism serves both deployments: an OS keychain is ideal on a
  desktop but impractical on a headless droplet; an encrypted file fits the
  droplet but is not where a desktop user expects secrets to live.

The design must also honor existing constraints: config-declared plugins mean
reading config tells you what code runs ([ADR-0003](../adr/ADR-0003-config-declared-plugins.md)),
so a secret mechanism must not become hidden; and the composition root should
resolve `ProviderSettings.api_key` *without knowing storage details*.

## Problem Statement

1. **Plaintext-in-config is the path of least resistance.** `ProviderCredential.api_key`
   (`config/schema.py`) accepts a raw key; the most obvious way to configure a
   provider is also the least safe, and it is one `git add` away from leaking.
2. **No key-entry UX.** A user cannot enter a key without hand-editing YAML or
   exporting environment variables — unacceptable for the self-hosted,
   voice-and-web-UI product v2 is becoming.
3. **No storage abstraction, but two deployments that need different storage.**
   Resolution logic is hardwired into `config/loader.py` around env vars and
   config fields; there is no seam at which a desktop keychain or a droplet
   encrypted file could be substituted, and RFC-0001 §8 pins the resolution to
   those two sources.
4. **Secrets risk leaking into observability.** With RFC-0002's event bus and
   RFC-0003's manifest, a key held as a plain string can surface in a log, event,
   or manifest unless secrecy is designed in.

## Proposed Design

### 1. `SecretStore` service (standalone, config-declared backend)

A runtime service, resolved at bootstrap exactly like a provider plugin
(ADR-0003) — **not** an RFC-0003 capability (there is one active store per
deployment, chosen by config, with no "who provides secrets?" renegotiation):

```python
@runtime_checkable
class SecretStore(Protocol):
    name: str
    def get(self, handle: str) -> str | None: ...
    def set(self, handle: str, value: str) -> None: ...
    def delete(self, handle: str) -> None: ...
```

Secrets are addressed by a **logical handle**, `provider:<name>` (e.g.
`provider:anthropic`). Config references the handle; it never contains the value.
Enumeration is deliberately absent from the Protocol — backends like `keyring`
cannot portably list entries — so `zygos keys list` reports **presence** for the
providers config already knows about, via `get(...) is not None`. No backend
enumeration, no value exposure.

### 2. Backends (all three ship in the first increment)

Declared like any plugin kind, and only the selected backend is imported:

```yaml
plugins:
  secrets:
    keyring:        "zygos.secrets.keyring:KeyringStore"
    encrypted_file: "zygos.secrets.file:EncryptedFileStore"
    env:            "zygos.secrets.env:EnvStore"
secrets:
  backend: keyring          # optional; auto-selected if omitted (see below)
  encrypted_file:
    path: ~/.config/zygos/secrets.enc
```

- **`keyring`** (desktop default) — OS keychain via the `keyring` library (macOS
  Keychain, Windows DPAPI, Linux Secret Service) under service name `zygos`.
- **`encrypted_file`** (droplet/headless default) — an AEAD-encrypted JSON blob
  (`handle → value`) at `secrets.enc`, encrypted with a 32-byte data key held in a
  sibling **`0600`, machine-local** key file (`secrets.key`). `set` decrypts,
  updates, re-encrypts; AEAD authentication makes tampering a detected failure,
  not a silent corruption.
- **`env` / secret-ref** (CI, 12-factor, and the home for external managers) —
  reads `<PROVIDER>_API_KEY` or an operator-managed reference. This is where a
  Vault/KMS/docker-secrets integration lives for anyone who wants a stronger
  threat model, added behind the same Protocol.

**Default selection.** If `secrets.backend` is omitted, the runtime auto-selects
(`keyring` when an OS keychain is available, else `encrypted_file`) and **reports
the chosen backend in `zygos doctor` and the manifest** — auto for convenience,
never hidden.

`keyring` and `cryptography` are **optional dependencies** (extras); because the
plugin resolver imports only the declared backend, a minimal install pulls
neither.

### 3. Threat model — stated honestly

The design defends against **accidental exposure**: keys committed to git,
world-readable files, and leakage into logs, events, traces, or the manifest. The
`encrypted_file` backend's data key lives on the same disk, so encryption-at-rest
here stops casual disk reads and image sharing but **does not** defend against an
attacker who already has root or the running process — that attacker owns the
runtime regardless. The RFC says this plainly; the `env`/secret-ref backend is the
supported path for anyone whose threat model needs an externally-held key
(passphrase-at-startup or KMS), offered additively rather than imposed on the
unattended-droplet baseline.

### 4. Resolution at bootstrap (amends RFC-0001 §8)

Precedence, highest first:

1. `SecretStore.get("provider:<name>")` — the active backend.
2. `<PROVIDER>_API_KEY` environment variable (never committed; 12-factor-safe).
3. plaintext `providers.credentials.<name>.api_key` in config — **still works, but
   emits a loud security-deprecation warning** naming `zygos keys set <name>` as
   the fix.

The composition root asks the `SecretStore` Protocol and **never learns the
backend**, satisfying the stated constraint. `ProviderSettings.api_key` is
populated from the resolved value. RFC-0001 §8's fail-fast on the primary route is
**preserved**; its error message gains a `zygos keys set <provider>` hint. This
supersedes RFC-0001 §8's two-source (config/env) resolution with the three-tier
order above.

### 5. Entry UX

- **CLI now:** `zygos keys set <provider>` (no-echo prompt, writes through the
  active backend), `zygos keys list` (provider names + presence, **never values**),
  `zygos keys rm <provider>`.
- **`zygos doctor`** reports the active backend and per-provider key **presence**
  (boolean), reusing RFC-0003's passive default.
- **Web settings page:** the same `SecretStore` API backs a settings page built
  with the React UI at M8; the interface is shaped for it now, implemented later
  ("the architecture evolves before the implementation").

### 6. Secrecy in depth (reinforces RFC-0003)

- `api_key` fields on `ProviderCredential` and `ProviderSettings` migrate to
  Pydantic `SecretStr`, so a stray `repr()`/log line renders `**********`, not the
  key.
- Keys never enter events, traces, or the manifest; RFC-0003's "manifest contains
  no secret material" acceptance criterion is extended to the whole observability
  surface, which reports key **presence** only.

### 7. Inspectability preserved (ADR-0003)

Config still declares *which backend code runs* (a plugin module path), so the
storage mechanism is readable from config; what config no longer contains is the
secret *values* (only handles). Inspectable mechanism, opaque secrets.

## Alternatives Considered

| Decision | Rejected alternative | Why rejected |
|---|---|---|
| Shape | Single storage mechanism now, abstraction later | Both deployments are already known targets; a single mechanism gets retrofitted into an interface anyway — against "the architecture evolves before the implementation." |
| Shape | Env/secret-refs only, Zygos never stores | Fails the explicit "easy way for users to input them" goal; a desktop user would hand-manage env/secret managers with no `zygos keys` or settings page. |
| Threat model | Defend against disk/image theft as baseline | Requires a startup passphrase (breaks unattended droplet restart) or external KMS; too heavy for a single-tenant self-hosted runtime. Offered as the `env`/secret-ref backend instead. |
| Threat model | Full external secret manager (Vault/KMS) as core | Heavy dependency, poor local-first/desktop story, over-engineered for one user. Belongs as an additive backend. |
| Resolution | KeyStore-only; drop plaintext + env | Breaks existing config/env flows and CI/12-factor; forces immediate migration against "backward compatibility is preferred when practical." |
| Resolution | Add KeyStore as an equal, unranked source | Leaves plaintext first-class and unwarned; the security objective goes unmet. |
| Placement | Register `secret_storage` as an RFC-0003 capability | Capabilities are for multiple satisfiers with health-based renegotiation; a single config-chosen store has neither, so it would borrow machinery it cannot use. |
| Enumeration | `list()` on the Protocol | `keyring` cannot portably enumerate; deriving presence from known providers avoids a fragile method and never exposes values. |

## Migration Plan

v1 stays frozen; TDD per RFC-0001 §9. Existing env/plaintext keep working through a
grace period, so the change is behavior-preserving except that it *adds* safer
paths and a warning.

1. **`SecretStore` Protocol + three backends**, each with a shared contract test
   run against a temp/fake store (no OS keychain, no network).
2. **Resolution precedence** wired into `config/loader.py`, superseding RFC-0001
   §8's two-source order; plaintext path emits the deprecation warning.
3. **`SecretStr` migration** for `api_key` fields.
4. **`zygos keys` CLI** + `zygos doctor` backend/presence reporting, landing with
   the CLI adapter.
5. **Docs**: quick-start switches to `zygos keys set`; `.env.example` and config
   samples stop showing raw keys.
6. **Web settings page** deferred to the React UI (M8) over the same API.

## Risks

- **`keyring` unavailable/locked on a target.** Mitigation: auto-selection falls
  back to `encrypted_file`; the active backend is reported by `doctor`, so the
  fallback is visible, not silent.
- **`encrypted_file` key-file mishandling.** A `0600` key file beside the
  ciphertext is only as safe as the filesystem. Mitigation: the honest threat
  boundary is documented; permissions are asserted on write; `env`/secret-ref is
  the path for stronger needs.
- **Optional-dependency drift.** Backends need extras (`keyring`, `cryptography`).
  Mitigation: the resolver imports only the declared backend; a missing extra
  produces a clear `PluginError`, not an import crash at startup for unrelated
  backends.
- **Deprecation-warning fatigue.** Mitigation: warn once per process per provider,
  with the exact `zygos keys set` remedy.

## Acceptance Criteria

1. `SecretStore` has `keyring`, `encrypted_file`, and `env` backends, each passing
   one shared contract test against a temp/fake store — **no OS keychain, no
   network** — test-proven.
2. Resolution precedence is KeyStore → env → plaintext; the plaintext path emits a
   security-deprecation warning naming `zygos keys set` — test-proven.
3. RFC-0001 §8 fail-fast on the primary route is preserved; the error message
   includes a `zygos keys set <provider>` hint — test-proven.
4. `encrypted_file` writes a `0600` key file, AEAD-encrypts the store, and reports
   a detected authentication failure on tampering — test-proven.
5. `zygos keys set` writes via the active backend without echoing input;
   `zygos keys list` shows provider presence, never values; `zygos keys rm`
   deletes — test-proven.
6. No secret appears in logs, events, traces, or the manifest; `api_key` is a
   `SecretStr`; `doctor`/manifest report presence only — test-proven (extends
   RFC-0003 criterion 5).
7. The backend is config-declared and reported by `doctor`/manifest, and only the
   declared backend module is imported — test-proven.
8. The full suite proving 1–7 runs with no OS keychain, no network, and no real
   keys (RFC-0001 §9).

## Architectural Impact

- **Coupling:** *controlled.* The composition root and every consumer depend on
  the `SecretStore` Protocol, not a backend; resolution is one seam, not logic
  scattered across the loader.
- **Hidden state:** secret *values* are deliberately not in snapshots, events, or
  the manifest — but their *presence* is inspectable, and the *backend* is
  config-declared and reported by `doctor`. This is a justified, stated exception
  to "hidden state is discouraged" for secret material; no hidden *control flow*
  is introduced.
- **Bypasses a prior boundary:** no. It **amends** RFC-0001 §8 through the RFC
  process built for changing a published contract, reinforces RFC-0003's no-secret
  manifest rule, and reuses ADR-0003 plugin resolution.
- **Constitution:** aligns with "local-first is preferred" (keyring/file, no
  mandatory cloud), "simplicity over cleverness" (honest threat model, no theater),
  "every component must be replaceable" (backends behind a Protocol), and "the
  runtime should degrade gracefully" (backend fallback, plaintext grace period).
- **Independently testable:** yes — a fake in-memory backend and a temp-dir
  `encrypted_file` cover everything with no OS keychain or network.
- **New service or existing:** a new standalone runtime service alongside
  `ConfigService`/`PluginService`; `zygos keys` is CLI-adapter surface.
- **Removable later:** yes. Remove the service and resolution reverts to env +
  config; the Protocol seam keeps the runtime core unaffected.
