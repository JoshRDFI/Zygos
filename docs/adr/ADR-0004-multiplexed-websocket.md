# ADR-0004: One Multiplexed WebSocket per Session

**Status:** Accepted
**Date:** 2026-07-03

## Context

Voice interaction — STT input and TTS output — must be present before Zygos 2.0 ships. That requirement means the transport layer must handle both text and audio from day one; retrofitting audio onto a text-only transport would require renegotiating the API surface at a disruptive stage of development.

Two alternatives were evaluated, as recorded in [RFC-0001](../rfcs/RFC-0001-Service-Architecture.md):

- **Separate sockets per concern** (one for chat, one for audio): avoids multiplexing complexity in the framing layer but creates two separate auth handshakes, cross-socket ordering problems when tool events and audio events must be correlated, and painful barge-in coordination (cancelling in-flight TTS requires signalling across sockets).
- **WebRTC for audio**: offers the best achievable latency for audio and is the appropriate choice for real-time media at scale. For a self-hosted deployment targeting a single developer on a droplet-class VM, the STUN/TURN infrastructure, SDP negotiation, and browser API surface are disproportionate complexity. WebRTC remains the appropriate escalation path if WebSocket latency proves inadequate on high-RTT links.

## Decision

Each session uses a single WebSocket connection at `/ws/session/{id}` that multiplexes typed frames: JSON frames carrying `{channel, type, payload}` on channels `chat`, `tools`, `trace`, and `control`; and binary frames with a 1-byte channel tag prefix for `audio.in` and `audio.out` (PCM or Opus, negotiated in the `control` handshake). Barge-in — cancelling in-flight TTS synthesis — is a `control` frame on the same connection, which makes it trivially implementable.

## Consequences

One connection means one auth handshake, no cross-socket ordering problems, and trivial barge-in. The framing protocol must handle binary channel-tagged frames from day one, which adds implementation complexity compared to a JSON-only socket. The `audio.*` channels are designed to be movable to a dedicated transport (or WebRTC) behind the same `VoiceService` interface if WebSocket latency proves inadequate on high-RTT links; that migration path is kept open and should be revisited in the dedicated voice RFC.
