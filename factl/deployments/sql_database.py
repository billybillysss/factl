from __future__ import annotations

import logging
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

SQL_DATABASE_ITEM_TYPE = "SQLDatabase"
SQL_DATABASE_SUFFIX = ".SQLDatabase"

SQLPACKAGE_DOWNLOAD_URLS = {
    "windows": "https://aka.ms/sqlpackage-windows",
    "linux": "https://aka.ms/sqlpackage-linux",
    "darwin": "https://aka.ms/sqlpackage-macos",
}


class SQLDatabaseDeploymentHandler:
    def __init__(
        self,
        *,
        repo_dir: Path,
        credential,
        logger: logging.Logger,
    ) -> None:
        self.repo_dir = repo_dir
        self.credential = credential
        self.logger = logger
        self.sqlproj_backend = SQLProjSqlPackageBackend(
            credential=credential,
            logger=logger,
        )

    def deploy(self, target_workspace, deploy_item_types: list[str]) -> None:
        if SQL_DATABASE_ITEM_TYPE not in deploy_item_types:
            return

        sql_sources = self._discover_sql_database_sources()
        if not sql_sources:
            self.logger.info(
                "No SQLDatabase item sources found under %s",
                self.repo_dir,
            )
            return

        target_workspace._refresh_deployed_items()
        deployed_sql_items = target_workspace.workspace_items.get(
            SQL_DATABASE_ITEM_TYPE,
            {},
        )

        for item_name, source_dir in sorted(sql_sources.items()):
            deployed_item = deployed_sql_items.get(item_name)
            if not deployed_item:
                self.logger.warning(
                    (
                        "Skipping SQL schema deployment for item=%s because it is not "
                        "deployed in workspace."
                    ),
                    item_name,
                )
                continue

            item_id = str(deployed_item.get("id") or "").strip()
            if not item_id:
                self.logger.warning(
                    (
                        "Skipping SQL schema deployment for item=%s due to missing "
                        "deployed item id."
                    ),
                    item_name,
                )
                continue

            sql_endpoint = str(deployed_item.get("sqlendpoint") or "")
            database_host = self._parse_sql_database_host(sql_endpoint)
            if not database_host:
                self.logger.warning(
                    (
                        "Skipping SQL schema deployment for item=%s due to missing "
                        "SQL endpoint."
                    ),
                    item_name,
                )
                continue

            database_name = f"{item_name}-{item_id}"
            sqlproj_path = self._find_sqlproj_path(source_dir)
            if not sqlproj_path:
                raise FileNotFoundError(
                    "SQLDatabase deployment requires a .sqlproj source. "
                    f"None found under {source_dir}."
                )

            self.sqlproj_backend.deploy_sqlproj(
                sqlproj_path=sqlproj_path,
                database_host=database_host,
                database_name=database_name,
            )

    def _discover_sql_database_sources(self) -> dict[str, Path]:
        sql_sources: dict[str, Path] = {}
        for directory in self.repo_dir.rglob(f"*{SQL_DATABASE_SUFFIX}"):
            if not directory.is_dir():
                continue
            item_name = directory.name.removesuffix(SQL_DATABASE_SUFFIX)
            if not item_name:
                continue
            sql_sources[item_name] = directory
        return sql_sources

    def _find_sqlproj_path(self, sql_root: Path) -> Path | None:
        projects = sorted(sql_root.glob("*.sqlproj"))
        if not projects:
            return None
        if len(projects) > 1:
            self.logger.warning(
                "Multiple sqlproj files found under %s; using %s",
                sql_root,
                projects[0],
            )
        return projects[0]

    def _parse_sql_database_host(self, sql_endpoint: str) -> str:
        raw_value = sql_endpoint.strip()
        if not raw_value:
            return ""

        candidate = raw_value
        if "://" in candidate:
            parsed = urlparse(candidate)
            if parsed.hostname:
                candidate = parsed.hostname
            else:
                candidate = parsed.netloc or parsed.path

        if ":" in candidate:
            candidate = candidate.split(":", 1)[0]

        return candidate.strip().rstrip("/")


class SQLProjSqlPackageBackend:
    def __init__(self, *, credential, logger: logging.Logger) -> None:
        self.credential = credential
        self.logger = logger

    def deploy_sqlproj(
        self,
        *,
        sqlproj_path: Path,
        database_host: str,
        database_name: str,
    ) -> None:
        sqlpackage_path = self._resolve_sqlpackage_path()
        dacpac_path = self._resolve_or_build_dacpac(sqlproj_path)
        access_token = self._get_database_access_token()

        target_connection_string = (
            f"Server=tcp:{database_host},1433;"
            f"Initial Catalog={database_name};"
            "Encrypt=True;"
            "TrustServerCertificate=False;"
            "Connection Timeout=30;"
        )

        command = [
            str(sqlpackage_path),
            "/Action:Publish",
            f"/SourceFile:{dacpac_path}",
            f"/TargetConnectionString:{target_connection_string}",
            f"/AccessToken:{access_token}",
            "/p:BlockOnPossibleDataLoss=True",
            "/p:DropObjectsNotInSource=False",
            "/p:VerifyDeployment=True",
            "/p:AllowIncompatiblePlatform=False",
        ]

        self.logger.info(
            "Publishing dacpac via SqlPackage. project=%s dacpac=%s target=%s",
            sqlproj_path,
            dacpac_path,
            database_name,
        )

        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            raise RuntimeError(
                "SqlPackage publish failed for "
                f"{sqlproj_path}. stdout={stdout} stderr={stderr}"
            )

        if result.stdout:
            self.logger.info(result.stdout.strip())

    def _resolve_or_build_dacpac(self, sqlproj_path: Path) -> Path:
        existing_dacpac = self._find_dacpac(sqlproj_path)
        if existing_dacpac and not self._should_build_dacpac():
            return existing_dacpac

        dotnet_path = shutil.which("dotnet")
        if dotnet_path:
            self.logger.info("Building sqlproj via dotnet: %s", sqlproj_path)
            subprocess.run(
                [dotnet_path, "build", str(sqlproj_path), "-c", "Release"],
                cwd=str(sqlproj_path.parent),
                check=True,
            )
            built_dacpac = self._find_dacpac(sqlproj_path)
            if built_dacpac:
                return built_dacpac
            raise FileNotFoundError(f"Dacpac not found after build for {sqlproj_path}.")

        if existing_dacpac:
            self.logger.warning(
                "dotnet not found; using existing dacpac=%s",
                existing_dacpac,
            )
            return existing_dacpac

        raise RuntimeError(
            "dotnet is required to build sqlproj to dacpac, but it is not available. "
            "Install dotnet or provide a prebuilt dacpac under the project bin folder."
        )

    def _find_dacpac(self, sqlproj_path: Path) -> Path | None:
        project_dir = sqlproj_path.parent
        preferred = project_dir / "bin" / "Release" / f"{sqlproj_path.stem}.dacpac"
        if preferred.exists():
            return preferred

        candidates = sorted(project_dir.glob("bin/**/*.dacpac"))
        if not candidates:
            return None
        return candidates[-1]

    def _should_build_dacpac(self) -> bool:
        raw = os.environ.get("factl_SQLPACKAGE_BUILD", "true").strip().lower()
        return raw not in {"0", "false", "no"}

    def _get_database_access_token(self) -> str:
        token = self.credential.get_token("https://database.windows.net/.default")
        return token.token

    def _resolve_sqlpackage_path(self) -> Path:
        configured_path = os.environ.get("factl_SQLPACKAGE_PATH", "").strip()
        if configured_path:
            path_obj = Path(configured_path).expanduser().resolve()
            if not path_obj.exists():
                raise FileNotFoundError(
                    f"factl_SQLPACKAGE_PATH does not exist: {path_obj}"
                )
            return path_obj

        for executable_name in self._candidate_executable_names():
            discovered = shutil.which(executable_name)
            if discovered:
                return Path(discovered)

        auto_download = os.environ.get("factl_SQLPACKAGE_AUTO_DOWNLOAD", "true")
        if auto_download.strip().lower() in {"0", "false", "no"}:
            raise FileNotFoundError(
                "SqlPackage executable not found in PATH and auto-download disabled."
            )

        return self._download_sqlpackage_binary()

    def _candidate_executable_names(self) -> tuple[str, ...]:
        if os.name == "nt":
            return ("SqlPackage.exe", "SqlPackage")
        return ("sqlpackage", "SqlPackage")

    def _download_sqlpackage_binary(self) -> Path:
        platform_key = self._platform_key()
        download_url = SQLPACKAGE_DOWNLOAD_URLS.get(platform_key)
        if not download_url:
            raise RuntimeError(
                f"SqlPackage auto-download is not supported for platform={platform_key}."
            )

        version = (
            os.environ.get("factl_SQLPACKAGE_VERSION", "latest").strip() or "latest"
        )
        cache_root = self._sqlpackage_cache_root() / f"{platform_key}-{version}"
        executable_path = self._find_sqlpackage_executable(cache_root)
        if executable_path:
            return executable_path

        cache_root.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="sqlpackage_download_") as temp_dir:
            archive_path = Path(temp_dir) / "sqlpackage.archive"
            self.logger.info("Downloading SqlPackage from %s", download_url)
            urllib.request.urlretrieve(download_url, archive_path)
            self._extract_archive(archive_path, cache_root)

        executable_path = self._find_sqlpackage_executable(cache_root)
        if not executable_path:
            raise FileNotFoundError(
                f"SqlPackage executable not found after extracting download from {download_url}."
            )

        self._ensure_executable(executable_path)
        self.logger.info("SqlPackage downloaded to %s", executable_path)
        return executable_path

    def _extract_archive(self, archive_path: Path, target_dir: Path) -> None:
        if zipfile.is_zipfile(archive_path):
            with zipfile.ZipFile(archive_path, "r") as archive:
                archive.extractall(target_dir)
            return

        if tarfile.is_tarfile(archive_path):
            with tarfile.open(archive_path, "r:*") as archive:
                archive.extractall(target_dir)
            return

        raise RuntimeError(f"Unsupported SqlPackage archive format: {archive_path}")

    def _find_sqlpackage_executable(self, directory: Path) -> Path | None:
        if not directory.exists():
            return None

        candidates = ["SqlPackage.exe", "sqlpackage", "SqlPackage"]
        for candidate in candidates:
            matches = sorted(directory.rglob(candidate))
            if matches:
                return matches[0]
        return None

    def _ensure_executable(self, executable_path: Path) -> None:
        if os.name == "nt":
            return
        current_mode = executable_path.stat().st_mode
        executable_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def _sqlpackage_cache_root(self) -> Path:
        if os.name == "nt":
            local_app_data = os.environ.get("LOCALAPPDATA")
            if local_app_data:
                return Path(local_app_data) / "factl" / "tools" / "sqlpackage"
            return Path.home() / "AppData" / "Local" / "factl" / "tools" / "sqlpackage"
        return Path.home() / ".cache" / "factl" / "tools" / "sqlpackage"

    def _platform_key(self) -> str:
        if os.name == "nt":
            return "windows"
        if platform.system().lower() == "darwin":
            return "darwin"
        return "linux"
