"""Shared provider contract-test helpers (RFC-0001 acceptance criterion 2)."""

from typing import Awaitable, Callable

import httpx
import pytest

from zygos.errors import ProviderAuthFailed, ProviderRateLimited, ProviderTimeout, ProviderUnavailable
from zygos.providers.base import Provider
from zygos.providers.types import GenerationRequest, Message


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def contract_request() -> GenerationRequest:
    return GenerationRequest(model="test-model", messages=(Message(role="user", content="ping"),))


async def run_error_contract(make_provider: Callable[[httpx.AsyncClient], Provider]) -> None:
    """Every real provider must map HTTP failures to the same error family."""
    for status, expected in ((401, ProviderAuthFailed), (429, ProviderRateLimited), (500, ProviderUnavailable)):
        client = make_client(lambda req, status=status: httpx.Response(status, json={"error": "x"}))
        provider = make_provider(client)
        with pytest.raises(expected):
            await provider.generate(contract_request())

    def raise_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    provider = make_provider(make_client(raise_timeout))
    with pytest.raises(ProviderTimeout):
        await provider.generate(contract_request())
