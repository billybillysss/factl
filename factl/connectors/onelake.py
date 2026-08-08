from __future__ import annotations

from typing import Any

import fsspec
from azure.core.credentials import TokenCredential
from azure.core.credentials_async import AsyncTokenCredential
from fsspec.spec import AbstractFileSystem


class OnelakeFileSystem(AbstractFileSystem):
    protocol = ("onelake",)
    _DFS_HOST = "onelake.dfs.fabric.microsoft.com"
    _SUPPORTED_ROOTS = {"files": "Files", "tables": "Tables"}
    _DELETE_STATUS_OK_MESSAGE = "Operation returned an invalid status 'OK'"

    def __init__(
        self,
        workspace_id: str,
        lakehouse_id: str,
        credential: TokenCredential | AsyncTokenCredential | None = None,
        root: str = "Files",
        account_name: str = "onelake",
        account_host: str = "onelake.blob.fabric.microsoft.com",
        batch_size: int | None = None,
        max_concurrency: int = 8,
        **kwargs,
    ):
        super().__init__(asynchronous=False)

        if credential is None:
            raise ValueError("OnelakeFileSystem credential is required.")

        self.workspace_id = str(workspace_id)
        self.lakehouse_id = str(lakehouse_id)
        self.root = self._normalize_root(root)
        self.batch_size = batch_size
        self.max_concurrency = int(max_concurrency)
        self._base_url = f"abfss://{self.workspace_id}@{self._DFS_HOST}/{self.lakehouse_id}/{self.root}"

        fs_kwargs = dict(kwargs)
        fs_kwargs.setdefault("anon", False)
        fs_kwargs.setdefault("account_name", account_name)
        fs_kwargs.setdefault("account_host", account_host)
        fs_kwargs.setdefault("credential", credential)
        fs_kwargs.setdefault("asynchronous", False)
        fs_kwargs.setdefault("max_concurrency", self.max_concurrency)

        self._fs = fsspec.filesystem("abfs", **fs_kwargs)

    def close(self):
        close_fn = getattr(self._fs, "close", None)
        if callable(close_fn):
            close_fn()

    @staticmethod
    def _normalize_logical(path: str) -> str:
        value = str(path or "").strip().replace("\\", "/")
        while value.startswith("./"):
            value = value[2:]
        value = value.strip("/")
        if value in {"", "."}:
            return ""
        return value

    @staticmethod
    def _is_abfs_path(path: str) -> bool:
        value = str(path or "").strip().lower()
        return value.startswith("abfss://") or value.startswith("abfs://")

    @classmethod
    def _normalize_root(cls, value: str) -> str:
        key = str(value or "").strip().strip("/").lower()
        root = cls._SUPPORTED_ROOTS.get(key)
        if root is None:
            allowed = ", ".join(sorted(cls._SUPPORTED_ROOTS.values()))
            raise ValueError(f"Unsupported root '{value}'. Allowed values: {allowed}")
        return root

    @classmethod
    def _strip_protocol(cls, path):
        value = str(path or "").strip().replace("\\", "/")
        if value.startswith("fablake://"):
            value = value[len("fablake://") :]
        elif value.startswith("onelake://"):
            value = value[len("onelake://") :]
        return value

    def _to_logical_path(self, path: str) -> str:
        value = self._strip_protocol(path)
        value = value.strip("/")

        if self._is_abfs_path(value):
            prefix = f"abfss://{self.workspace_id}@{self._DFS_HOST}/"
            if value.startswith(prefix):
                value = value[len(prefix) :]

        workspace_prefix = f"{self.workspace_id}/"
        if value.startswith(workspace_prefix):
            value = value[len(workspace_prefix) :]

        lakehouse_prefix = f"{self.lakehouse_id}/"
        if value.startswith(lakehouse_prefix):
            value = value[len(lakehouse_prefix) :]

        root = value.split("/", 1)[0].lower()
        if root in self._SUPPORTED_ROOTS:
            if "/" not in value:
                return ""
            value = value.split("/", 1)[1]

        if value == self.root:
            return ""
        if value.startswith(f"{self.root}/"):
            value = value[len(self.root) + 1 :]

        return self._normalize_logical(value)

    def _to_url(self, path: str) -> str:
        value = str(path or "").strip()
        if self._is_abfs_path(value):
            return value

        logical = self._to_logical_path(value)
        if not logical:
            return self._base_url
        return f"{self._base_url}/{logical}"

    def _to_url_path_arg(self, path):
        if isinstance(path, list):
            return [self._to_url(str(item)) for item in path]
        return self._to_url(str(path))

    @staticmethod
    def _relative_to(base: str, value: str) -> str:
        if value == base:
            return ""
        prefix = f"{base}/"
        if value.startswith(prefix):
            return value[len(prefix) :]
        return value

    @staticmethod
    def _join_logical(base: str, suffix: str) -> str:
        left = str(base or "").strip("/")
        right = str(suffix or "").strip("/")
        if left and right:
            return f"{left}/{right}"
        return left or right

    @staticmethod
    def _normalize_entry_type(value: str | None) -> str:
        kind = str(value or "").lower()
        if kind in {"directory", "dir"}:
            return "directory"
        if kind == "file":
            return "file"
        return kind or "file"

    def exists(self, path: str, **kwargs) -> bool:
        return bool(self._fs.exists(self._to_url(path), **kwargs))

    def isdir(self, path: str) -> bool:
        fn = getattr(self._fs, "isdir", None)
        if callable(fn):
            return bool(fn(self._to_url(path)))
        info = self.info(path)
        return str(info.get("type") or "").lower() == "directory"

    def isfile(self, path: str) -> bool:
        fn = getattr(self._fs, "isfile", None)
        if callable(fn):
            return bool(fn(self._to_url(path)))
        info = self.info(path)
        return str(info.get("type") or "").lower() == "file"

    def info(self, path: str, **kwargs) -> dict[str, Any]:
        url = self._to_url(path)
        info = self._fs.info(url, **kwargs)
        if not isinstance(info, dict):
            return {
                "name": self._to_logical_path(path),
                "size": None,
                "type": "file",
            }

        out = dict(info)
        out["name"] = self._to_logical_path(str(out.get("name") or url))
        out["type"] = self._normalize_entry_type(out.get("type"))
        return out

    def ls(self, path: str, detail: bool = True, **kwargs):
        entries = self._fs.ls(self._to_url(path), detail=detail, **kwargs)
        if detail:
            out: list[dict[str, Any]] = []
            for entry in entries or []:
                item = dict(entry or {})
                item["name"] = self._to_logical_path(str(item.get("name") or ""))
                item["type"] = self._normalize_entry_type(item.get("type"))
                out.append(item)
            return out

        return [self._to_logical_path(str(entry)) for entry in (entries or [])]

    def find(
        self,
        path: str,
        maxdepth=None,
        withdirs: bool = False,
        detail: bool = False,
        **kwargs,
    ):
        entries = self._fs.find(
            self._to_url(path),
            maxdepth=maxdepth,
            withdirs=withdirs,
            detail=detail,
            **kwargs,
        )

        if detail:
            if isinstance(entries, dict):
                out: dict[str, dict[str, Any]] = {}
                for name, metadata in entries.items():
                    logical_name = self._to_logical_path(str(name))
                    item = dict(metadata or {})
                    item["name"] = self._to_logical_path(
                        str(item.get("name") or name),
                    )
                    item["type"] = self._normalize_entry_type(item.get("type"))
                    out[logical_name] = item
                return out

            out: dict[str, dict[str, Any]] = {}
            for name in entries or []:
                logical_name = self._to_logical_path(str(name))
                out[logical_name] = {"name": logical_name, "type": "file"}
            return out

        return [self._to_logical_path(str(name)) for name in (entries or [])]

    def glob(self, path: str, **kwargs):
        entries = self._fs.glob(self._to_url(path), **kwargs)
        return [self._to_logical_path(str(entry)) for entry in (entries or [])]

    def _collect_tree_entries(self, source: str):
        raw_entries = self._fs.find(
            self._to_url(source),
            withdirs=True,
            detail=True,
        )

        if isinstance(raw_entries, dict):
            pairs = [(str(name), dict(metadata or {})) for name, metadata in raw_entries.items()]
        else:
            pairs = [(str(name), {}) for name in (raw_entries or [])]

        source_logical = self._to_logical_path(source)
        files: list[str] = []
        dirs: list[str] = []

        for name, metadata in pairs:
            logical_name = self._to_logical_path(name)
            if not logical_name or logical_name == source_logical:
                continue
            entry_type = str(metadata.get("type") or "").lower()
            if entry_type in {"directory", "dir"}:
                dirs.append(logical_name)
            elif entry_type == "file":
                files.append(logical_name)
            elif logical_name.endswith("/"):
                dirs.append(logical_name.rstrip("/"))
            else:
                files.append(logical_name)

        return source_logical, sorted(set(files)), sorted(
            set(dirs),
            key=lambda item: item.count("/"),
        )

    def _copy_tree(self, source: str, destination: str, *, on_error: str, **kwargs):
        source_logical, files, dirs = self._collect_tree_entries(source)
        destination_logical = self._to_logical_path(destination)

        self.makedirs(destination_logical, exist_ok=True)
        for directory in dirs:
            relative = self._relative_to(source_logical, directory)
            if not relative:
                continue
            self.makedirs(
                self._join_logical(destination_logical, relative),
                exist_ok=True,
            )

        for file_path in files:
            relative = self._relative_to(source_logical, file_path)
            target_file = self._join_logical(destination_logical, relative)
            parent = target_file.rsplit("/", 1)[0] if "/" in target_file else ""
            if parent:
                self.makedirs(parent, exist_ok=True)
            try:
                self._fs.copy(
                    self._to_url(file_path),
                    self._to_url(target_file),
                    recursive=False,
                    on_error="raise",
                    maxdepth=None,
                    **kwargs,
                )
            except Exception:
                if on_error == "ignore":
                    continue
                raise
        return None

    def _move_tree(self, source: str, destination: str, **kwargs):
        source_logical, files, dirs = self._collect_tree_entries(source)
        destination_logical = self._to_logical_path(destination)

        self.makedirs(destination_logical, exist_ok=True)
        for directory in dirs:
            relative = self._relative_to(source_logical, directory)
            if not relative:
                continue
            self.makedirs(
                self._join_logical(destination_logical, relative),
                exist_ok=True,
            )

        for file_path in files:
            relative = self._relative_to(source_logical, file_path)
            target_file = self._join_logical(destination_logical, relative)
            parent = target_file.rsplit("/", 1)[0] if "/" in target_file else ""
            if parent:
                self.makedirs(parent, exist_ok=True)
            self._fs.mv(
                self._to_url(file_path),
                self._to_url(target_file),
                recursive=False,
                maxdepth=None,
                **kwargs,
            )

        for directory in sorted(dirs, key=lambda item: item.count("/"), reverse=True):
            if self.exists(directory):
                self.rm(directory, recursive=False)
        if self.exists(source_logical):
            self.rm(source_logical, recursive=False)
        return None

    def cat_file(self, path: str, start=None, end=None, **kwargs) -> bytes:
        return self._fs.cat_file(
            self._to_url(path),
            start=start,
            end=end,
            **kwargs,
        )

    def open(self, path: str, mode: str = "rb", **kwargs):
        return self._fs.open(self._to_url(path), mode=mode, **kwargs)

    def mkdir(self, path: str, create_parents: bool = True, **kwargs):
        if create_parents:
            return self.makedirs(path, exist_ok=kwargs.get("exist_ok", False))
        return self._fs.mkdir(self._to_url(path), **kwargs)

    def makedirs(self, path: str, exist_ok: bool = False):
        return self._fs.makedirs(self._to_url(path), exist_ok=exist_ok)

    def put(self, lpath, rpath, **kwargs):
        return self._fs.put(lpath, self._to_url_path_arg(rpath), **kwargs)

    def rm(self, path, recursive: bool = False, batch_size=None, **kwargs):
        try:
            return self._fs.rm(
                self._to_url_path_arg(path),
                recursive=recursive,
                **kwargs,
            )
        except RuntimeError as exc:
            if self._DELETE_STATUS_OK_MESSAGE in str(exc):
                return None
            raise

    def copy(
        self,
        path1,
        path2,
        recursive: bool = False,
        on_error=None,
        maxdepth=None,
        batch_size=None,
        **kwargs,
    ):
        if on_error is None and recursive:
            on_error = "ignore"
        elif on_error is None:
            on_error = "raise"

        if recursive and not isinstance(path1, list) and not isinstance(path2, list):
            source = str(path1)
            destination = str(path2)
            if self._to_logical_path(source) == self._to_logical_path(destination):
                return None
            if self.isdir(source):
                return self._copy_tree(
                    source,
                    destination,
                    on_error=on_error,
                    **kwargs,
                )

        return self._fs.copy(
            self._to_url_path_arg(path1),
            self._to_url_path_arg(path2),
            recursive=recursive,
            on_error=on_error,
            maxdepth=maxdepth,
            **kwargs,
        )

    cp = copy

    def mv(
        self,
        path1,
        path2,
        recursive: bool = False,
        maxdepth=None,
        batch_size=None,
        **kwargs,
    ):
        if recursive and not isinstance(path1, list) and not isinstance(path2, list):
            source = str(path1)
            destination = str(path2)
            if self._to_logical_path(source) == self._to_logical_path(destination):
                return None
            if self.isdir(source):
                return self._move_tree(
                    source,
                    destination,
                    **kwargs,
                )

        return self._fs.mv(
            self._to_url_path_arg(path1),
            self._to_url_path_arg(path2),
            recursive=recursive,
            maxdepth=maxdepth,
            **kwargs,
        )
