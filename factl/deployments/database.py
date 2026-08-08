from __future__ import annotations

from pathlib import Path

from factl.connectors import DatabaseConnection
from factl.deployments.base import BaseDeployment
from factl.deployments.includes import resolve_include_matches
from factl.logger import get_logger

logger = get_logger("deploy.database")

_META_DB_PORT = 1433


class DatabaseDeployment(BaseDeployment):
    def __init__(
        self,
        *,
        target_env: str,
        base_dir: Path,
        database_local_path: str,
        database_includes: list[str],
        metadata_database_host: str,
        metadata_database_name: str,
        auth_mode: str = "default",
    ) -> None:
        super().__init__(target_env=target_env, base_dir=base_dir, auth_mode=auth_mode)
        self.database_local_path = database_local_path
        self.database_includes = database_includes
        self.metadata_database_host = metadata_database_host
        self.metadata_database_name = metadata_database_name
        self._database_connection: DatabaseConnection | None = None

    @property
    def _database(self) -> DatabaseConnection:
        if self._database_connection is None:
            self._database_connection = DatabaseConnection(
                hostname=self.metadata_database_host,
                database=self.metadata_database_name,
                port=_META_DB_PORT,
                auth_mode=self.context.auth_mode,
            )
        return self._database_connection

    def deploy(self) -> None:
        sql_root = self.base_dir / self.database_local_path
        if not sql_root.exists() or not sql_root.is_dir():
            raise ValueError(
                f"Database local_path does not exist or is not a directory: {sql_root}"
            )

        sql_files: list[Path] = []
        sql_file_index: dict[Path, int] = {}
        unmatched_includes: list[str] = []
        skipped_non_sql_files: list[str] = []
        for include_order, include in enumerate(self.database_includes):
            include_matches = resolve_include_matches(sql_root, include)
            if not include_matches:
                unmatched_includes.append(include)
                continue

            for include_match in include_matches:
                include_path = include_match.full_path
                if include_match.is_dir:
                    for path in include_path.rglob("*.sql"):
                        if not path.is_file() or path in sql_file_index:
                            continue
                        sql_file_index[path] = include_order
                        sql_files.append(path)
                    continue

                if include_path.suffix.lower() != ".sql":
                    skipped_non_sql_files.append(include_match.relative_path)
                    continue
                if include_path not in sql_file_index:
                    sql_file_index[include_path] = include_order
                    sql_files.append(include_path)

        if unmatched_includes:
            logger.warning(
                "Skipping unmatched database include path(s) under %s: %s",
                sql_root,
                ",".join(unmatched_includes),
            )

        if skipped_non_sql_files:
            logger.warning(
                "Skipping non-SQL database include file(s) under %s: %s",
                sql_root,
                ",".join(skipped_non_sql_files),
            )

        sql_files = sorted(
            sql_files,
            key=lambda path: self._sql_sort_key(
                path,
                sql_root=sql_root,
                include_index=sql_file_index,
            ),
        )

        if not sql_files:
            logger.info(
                "No SQL files found for database deployment. local_path=%s includes=%s",
                sql_root,
                ",".join(self.database_includes),
            )
            return

        logger.info(
            "Deploying database SQL scripts. root=%s includes=%s files=%s",
            sql_root,
            ",".join(self.database_includes),
            len(sql_files),
        )
        for sql_file in sql_files:
            self._execute_sql_file(sql_file)

        logger.info("Database deployment completed.")

    def _sql_sort_key(
        self,
        path: Path,
        *,
        sql_root: Path,
        include_index: dict[Path, int],
    ) -> tuple[int, int, str]:
        relative_parts = [part.lower() for part in path.relative_to(sql_root).parts]
        include_order = include_index.get(path, len(include_index))

        object_order = 99
        for part in relative_parts:
            if part == "tables":
                object_order = 0
                break
            if part == "views":
                object_order = 1
                break
            if part == "functions":
                object_order = 2
                break
            if part == "storedprocedures":
                object_order = 3
                break

        return include_order, object_order, str(path).lower()

    def _execute_sql_file(self, sql_file: Path) -> None:
        logger.info("Executing database SQL script: %s", sql_file)
        script = sql_file.read_text(encoding="utf-8")
        batches = self._split_sql_batches(script)
        for batch in batches:
            self._database.execute_sql(batch)

    def _split_sql_batches(self, script: str) -> list[str]:
        batches: list[str] = []
        current: list[str] = []
        for line in script.splitlines():
            if line.strip().upper() == "GO":
                batch = "\n".join(current).strip()
                if batch:
                    batches.append(batch)
                current = []
                continue
            current.append(line)

        final_batch = "\n".join(current).strip()
        if final_batch:
            batches.append(final_batch)
        return batches
