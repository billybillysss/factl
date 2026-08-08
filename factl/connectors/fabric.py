from __future__ import annotations

import base64
import json
import logging
import time
from http.client import HTTPMessage
from pathlib import Path
from urllib import error, request
from typing import Any

from azure.core.credentials import TokenCredential

from factl.constants import FABRIC_API_ROOT_URL


DEFAULT_SCHEDULE_JOB_TYPE = "Execute"

logger = logging.getLogger(__name__)


class _FabricHttpEndpoint:
    _SCOPE = "https://api.fabric.microsoft.com/.default"

    def __init__(self, token_credential: TokenCredential) -> None:
        self._credential = token_credential

    def invoke(
        self,
        method: str,
        url: str,
        body: dict | None = None,
        poll_long_running: bool = True,
        max_duration: int = 600,
    ) -> dict[str, Any]:
        started_at = time.time()
        response = self._send(method=method, url=url, body=body)
        if not poll_long_running:
            return response

        while self._should_poll(response):
            if time.time() - started_at >= max_duration:
                raise TimeoutError(
                    f"Fabric request polling timed out after {max_duration}s for {url}."
                )

            retry_after = self._retry_after_seconds(response["header"])
            time.sleep(retry_after)
            poll_url = self._polling_url(response)
            if not poll_url:
                break
            response = self._send(method="GET", url=poll_url, body=None)

        return response

    def _send(self, method: str, url: str, body: dict | None) -> dict[str, Any]:
        token = self._credential.get_token(self._SCOPE)
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "Authorization": f"Bearer {token.token}",
            "Accept": "application/json",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"

        request_obj = request.Request(
            url=url,
            method=method.upper(),
            data=payload,
            headers=headers,
        )
        try:
            with request.urlopen(request_obj) as response_obj:
                status_code = int(response_obj.status)
                header = self._headers_to_dict(response_obj.headers)
                raw_body = response_obj.read().decode("utf-8")
                response_body = self._parse_body(raw_body)
                return {
                    "status_code": status_code,
                    "header": header,
                    "body": response_body,
                }
        except error.HTTPError as exc:
            status_code = int(exc.code)
            header = self._headers_to_dict(exc.headers)
            raw_body = exc.read().decode("utf-8") if exc.fp is not None else ""
            response_body = self._parse_body(raw_body)
            raise RuntimeError(
                f"Fabric API request failed. method={method.upper()} url={url} "
                f"status={status_code} body={response_body}"
            ) from exc

    @staticmethod
    def _parse_body(raw_body: str) -> dict[str, Any]:
        if not raw_body.strip():
            return {}
        try:
            parsed = json.loads(raw_body)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        return {"raw": raw_body}

    @staticmethod
    def _headers_to_dict(headers: HTTPMessage | None) -> dict[str, str]:
        if headers is None:
            return {}
        return {key: value for key, value in headers.items()}

    @staticmethod
    def _retry_after_seconds(headers: dict[str, str]) -> int:
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
        if not retry_after:
            return 2
        try:
            parsed = int(retry_after)
        except ValueError:
            return 2
        return max(1, parsed)

    @staticmethod
    def _polling_url(response: dict[str, Any]) -> str | None:
        headers = response.get("header") or {}
        return (
            headers.get("Location")
            or headers.get("location")
            or headers.get("Operation-Location")
            or headers.get("operation-location")
        )

    def _should_poll(self, response: dict[str, Any]) -> bool:
        status_code = int(response.get("status_code") or 0)
        if status_code in {202, 201} and self._polling_url(response):
            return True

        body = response.get("body") or {}
        status = str(body.get("status") or "").lower()
        if status in {"running", "inprogress", "notstarted"}:
            return True
        if status in {"failed", "cancelled"}:
            raise RuntimeError(f"Fabric long-running operation failed: {body}")
        return False


class FabricWorkspaceClient:
    def __init__(
        self,
        workspace_id: str,
        credential: TokenCredential,
        repository_directory: Path | None = None,
    ) -> None:
        self.workspace_id = workspace_id
        self.repository_directory = repository_directory or Path.cwd()
        self.endpoint = _FabricHttpEndpoint(token_credential=credential)
        self.base_api_url = f"{FABRIC_API_ROOT_URL}/v1/workspaces/{workspace_id}"

    def _list_paginated(self, request_url: str) -> list[dict]:
        results: list[dict] = []

        while request_url:
            response = self.endpoint.invoke(method="GET", url=request_url)
            results.extend(response["body"].get("value", []))
            request_url = response["body"].get("continuationUri") or response[
                "header"
            ].get("continuationUri")

        return results

    def list_folders(self) -> list[dict]:
        request_url = f"{self.base_api_url}/folders"
        return self._list_paginated(request_url)

    def list_items(self, item_type: str | None = None) -> list[dict]:
        request_url = f"{self.base_api_url}/items"
        if item_type:
            request_url = f"{request_url}?type={item_type}"
        return self._list_paginated(request_url)

    def list_data_pipelines(self) -> list[dict]:
        return self.list_items(item_type="DataPipeline")

    def get_workspace(self) -> dict:
        response = self._invoke("GET", self.base_api_url)
        return response.get("body") or {}

    def list_item_schedules(
        self,
        item_id: str,
        job_type: str = DEFAULT_SCHEDULE_JOB_TYPE,
    ) -> list[dict]:
        request_url = f"{self.base_api_url}/items/{item_id}/jobs/{job_type}/schedules"
        logger.debug(
            "Listing schedules for item %s with job type '%s'",
            item_id,
            job_type,
        )
        return self._list_paginated(request_url)

    def create_folder(
        self,
        display_name: str,
        parent_folder_id: str | None = None,
    ) -> dict:
        request_url = f"{self.base_api_url}/folders"
        payload: dict[str, Any] = {"displayName": display_name}
        if parent_folder_id:
            payload["parentFolderId"] = parent_folder_id
        response = self._invoke("POST", request_url, body=payload)
        return response.get("body") or {}

    def create_item(
        self,
        display_name: str,
        item_type: str,
        folder_id: str | None = None,
        creation_payload: dict[str, Any] | None = None,
    ) -> dict:
        request_url = f"{self.base_api_url}/items"
        payload: dict[str, Any] = {
            "displayName": display_name,
            "type": item_type,
        }
        if folder_id:
            payload["folderId"] = folder_id
        if creation_payload:
            payload["creationPayload"] = creation_payload
        response = self._invoke("POST", request_url, body=payload)
        return response.get("body") or {}

    def _invoke(
        self,
        method: str,
        url: str,
        body: dict | None = None,
        poll_long_running: bool = True,
        max_duration: int = 600,
    ) -> dict:
        payload: Any = body or {}
        return self.endpoint.invoke(
            method=method,
            url=url,
            body=payload,
            poll_long_running=poll_long_running,
            max_duration=max_duration,
        )

    def get_item_definition(self, item_id: str) -> dict:
        """Fetch the full definition of a workspace item via the REST API.

        Returns the parsed definition with parts list, where each part has
        'path', 'payload' (decoded from base64), and 'payloadType'.
        """
        request_url = f"{self.base_api_url}/items/{item_id}/getDefinition"
        response = self._invoke("POST", request_url)
        definition = (response.get("body") or {}).get("definition", {})
        parts = definition.get("parts", [])
        decoded_parts = []
        for part in parts:
            decoded_part = dict(part)
            if part.get("payloadType") == "InlineBase64" and part.get("payload"):
                decoded_part["payload"] = base64.b64decode(part["payload"]).decode(
                    "utf-8"
                )
            decoded_parts.append(decoded_part)
        definition["parts"] = decoded_parts
        return definition

    def get_item_logical_id(self, item_id: str) -> str | None:
        """Fetch the logicalId from an item's .platform definition part."""
        try:
            definition = self.get_item_definition(item_id)
        except Exception:
            logger.warning(
                "Failed to fetch definition for item %s, skipping logicalId sync",
                item_id,
                exc_info=True,
            )
            return None
        for part in definition.get("parts", []):
            if part.get("path") == ".platform":
                try:
                    platform = json.loads(part["payload"])
                    return platform.get("config", {}).get("logicalId")
                except (json.JSONDecodeError, KeyError):
                    return None
        return None

    def get_git_connection(self) -> dict:
        request_url = f"{self.base_api_url}/git/connection"
        response = self._invoke("GET", request_url)
        return response.get("body") or {}

    def disconnect_git(self) -> None:
        request_url = f"{self.base_api_url}/git/disconnect"
        self._invoke("POST", request_url)

    def connect_git(
        self,
        git_provider_details: dict,
        my_git_credentials: dict | None = None,
    ) -> None:
        request_url = f"{self.base_api_url}/git/connect"
        payload: dict = {"gitProviderDetails": git_provider_details}
        if my_git_credentials:
            payload["myGitCredentials"] = my_git_credentials
        self._invoke("POST", request_url, body=payload)

    def initialize_git_connection(
        self,
        initialization_strategy: str = "PreferRemote",
    ) -> dict:
        request_url = f"{self.base_api_url}/git/initializeConnection"
        payload = {"initializationStrategy": initialization_strategy}
        response = self._invoke("POST", request_url, body=payload)
        return response.get("body") or {}

    def get_git_status(self) -> dict:
        request_url = f"{self.base_api_url}/git/status"
        response = self._invoke("GET", request_url)
        return response.get("body") or {}

    def update_from_git(
        self,
        remote_commit_hash: str,
        workspace_head: str | None,
        allow_override_items: bool = True,
    ) -> None:
        request_url = f"{self.base_api_url}/git/updateFromGit"
        payload: dict = {
            "remoteCommitHash": remote_commit_hash,
            "options": {
                "allowOverrideItems": allow_override_items,
            },
            "conflictResolution": {
                "conflictResolutionType": "Workspace",
                "conflictResolutionPolicy": "PreferRemote",
            },
        }
        if workspace_head:
            payload["workspaceHead"] = workspace_head

        self._invoke(
            "POST",
            request_url,
            body=payload,
            poll_long_running=True,
            max_duration=1800,
        )

    def commit_to_git(
        self,
        mode: str = "All",
        workspace_head: str | None = None,
        comment: str | None = None,
        items: list[dict[str, str]] | None = None,
    ) -> None:
        request_url = f"{self.base_api_url}/git/commitToGit"
        payload: dict[str, Any] = {
            "mode": mode,
        }
        if workspace_head:
            payload["workspaceHead"] = workspace_head
        if comment:
            payload["comment"] = comment
        if items:
            payload["items"] = items

        self._invoke(
            "POST",
            request_url,
            body=payload,
            poll_long_running=True,
            max_duration=1800,
        )


def list_workspace_folders(
    workspace_id: str,
    credential: TokenCredential,
    repository_directory: Path | None = None,
) -> list[dict]:
    workspace = FabricWorkspaceClient(
        workspace_id=workspace_id,
        credential=credential,
        repository_directory=repository_directory,
    )
    return workspace.list_folders()


def list_data_pipelines(
    workspace_id: str,
    credential: TokenCredential,
    repository_directory: Path | None = None,
) -> list[dict]:
    workspace = FabricWorkspaceClient(
        workspace_id=workspace_id,
        credential=credential,
        repository_directory=repository_directory,
    )
    return workspace.list_data_pipelines()


def list_pipeline_schedules(
    workspace_id: str,
    item_id: str,
    credential: TokenCredential,
    repository_directory: Path | None = None,
    job_type: str = DEFAULT_SCHEDULE_JOB_TYPE,
) -> list[dict]:
    workspace = FabricWorkspaceClient(
        workspace_id=workspace_id,
        credential=credential,
        repository_directory=repository_directory,
    )
    return workspace.list_item_schedules(item_id=item_id, job_type=job_type)
