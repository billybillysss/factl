from __future__ import annotations

import asyncio
import inspect

from azure.core.credentials import AccessTokenInfo, TokenRequestOptions
from azure.core.credentials import TokenCredential
from azure.core.credentials_async import AsyncTokenCredential
from azure.identity import (
    AzureCliCredential,
    ChainedTokenCredential,
    DefaultAzureCredential,
    InteractiveBrowserCredential,
)
from azure.identity.aio import (
    AzureCliCredential as AsyncAzureCliCredential,
    ChainedTokenCredential as AsyncChainedTokenCredential,
    DefaultAzureCredential as AsyncDefaultAzureCredential,
)

_AZURE_CLI_PROCESS_TIMEOUT = 30
_VALID_AUTH_MODES = ("default", "interactive", "cli")

_SYNC_CREDENTIALS: dict[str, TokenCredential] = {}
_ASYNC_CREDENTIALS: dict[str, AsyncTokenCredential] = {}


class _AsyncInteractiveBrowserCredential(AsyncTokenCredential):
    """Async adapter for sync InteractiveBrowserCredential.

    azure.identity.aio in this environment does not provide an async
    InteractiveBrowserCredential. This shim preserves `interactive` mode
    behavior (Azure CLI -> browser fallback) for async credential chains.
    """

    def __init__(self):
        self._sync_credential = InteractiveBrowserCredential()
        self._interactive_lock = asyncio.Lock()

    async def get_token(self, *scopes: str, **kwargs):
        async with self._interactive_lock:
            return await asyncio.to_thread(
                self._sync_credential.get_token,
                *scopes,
                **kwargs,
            )

    async def get_token_info(
        self,
        *scopes: str,
        options: TokenRequestOptions | None = None,
    ) -> AccessTokenInfo:
        request_options = options or {}
        kwargs = {}
        for key in ("claims", "tenant_id", "enable_cae"):
            if key in request_options and request_options[key] is not None:
                kwargs[key] = request_options[key]

        token = await self.get_token(*scopes, **kwargs)
        return AccessTokenInfo(token=token.token, expires_on=token.expires_on)

    async def close(self) -> None:
        closer = getattr(self._sync_credential, "close", None)
        if callable(closer):
            result = closer()
            if inspect.isawaitable(result):
                await result


def normalize_auth_mode(value: str | None, *, default: str = "default") -> str:
    mode = (value or default).strip().lower()
    if mode not in _VALID_AUTH_MODES:
        raise ValueError(
            f"Invalid auth mode '{value}'. Supported values: {', '.join(_VALID_AUTH_MODES)}"
        )
    return mode


def build_default_credential(*, auth_mode: str = "default") -> TokenCredential:
    mode = normalize_auth_mode(auth_mode)
    cached = _SYNC_CREDENTIALS.get(mode)
    if cached is not None:
        return cached

    if mode == "default":
        credential = DefaultAzureCredential(
            process_timeout=_AZURE_CLI_PROCESS_TIMEOUT,
            exclude_interactive_browser_credential=True,
        )
    elif mode == "cli":
        credential = AzureCliCredential(process_timeout=_AZURE_CLI_PROCESS_TIMEOUT)
    else:
        credential = ChainedTokenCredential(
            AzureCliCredential(process_timeout=_AZURE_CLI_PROCESS_TIMEOUT),
            InteractiveBrowserCredential(),
        )

    _SYNC_CREDENTIALS[mode] = credential
    return credential


def build_default_async_credential(
    *, auth_mode: str = "default"
) -> AsyncTokenCredential:
    mode = normalize_auth_mode(auth_mode)
    cached = _ASYNC_CREDENTIALS.get(mode)
    if cached is not None:
        return cached

    if mode == "default":
        credential = AsyncDefaultAzureCredential(
            process_timeout=_AZURE_CLI_PROCESS_TIMEOUT,
            exclude_interactive_browser_credential=True,
        )
    elif mode == "cli":
        credential = AsyncAzureCliCredential(process_timeout=_AZURE_CLI_PROCESS_TIMEOUT)
    else:
        credential = AsyncChainedTokenCredential(
            AsyncAzureCliCredential(process_timeout=_AZURE_CLI_PROCESS_TIMEOUT),
            _AsyncInteractiveBrowserCredential(),
        )

    _ASYNC_CREDENTIALS[mode] = credential
    return credential


AUTH_TROUBLESHOOTING_GUIDE = (
    "Authentication failed. factl auth mode controls credential behavior: "
    "default=DefaultAzureCredential (non-interactive), "
    "interactive=AzureCliCredential then InteractiveBrowserCredential, "
    "cli=AzureCliCredential only.\n"
    "Check auth.mode in .config/.factl/project.yaml, .config/.factl/targets.yaml, or ~/.factl/profiles.yaml profile settings.\n"
    "Try one of the following:\n"
    "1) For mode=default, configure workload identity or environment credentials.\n"
    "2) For mode=interactive or mode=cli, run `az login`.\n"
    "3) Verify access to target Fabric workspace and related resources."
)
