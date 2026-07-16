"""Test-only worker for the aclose() grandchild-reaping integration test.

Connects back to the runtime's listener like a real sidecar, then forks a
grandchild that sleeps (simulating e.g. a model-loading subprocess), reports
the grandchild's pid over IPC, and immediately exits itself — leaving the
grandchild as an orphan still in the leader's original process group (fork()
does not create a new session; only the original start_new_session=True exec
did that). This lets a test assert that SidecarHandle.aclose() reaps
grandchildren via killpg even after the direct child has already died.

Run as: python -m tests.voice._fork_worker <address>
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

from zygos.voice.ipc import connect


async def _run(address: str) -> None:
    conn = await connect(address)
    pid = os.fork()
    if pid == 0:
        # grandchild: just sleep so it's alive long enough for the test to
        # observe it, then exit if somehow never killed.
        time.sleep(30)
        os._exit(0)
    else:
        await conn.send_control({"type": "forked", "child_pid": pid})
        await conn.close()
        # leader exits immediately; grandchild lives on in the same pgid.
        os._exit(0)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m tests.voice._fork_worker <address>")
    asyncio.run(_run(sys.argv[1]))


if __name__ == "__main__":
    main()
