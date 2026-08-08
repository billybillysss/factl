from __future__ import annotations

import struct
from typing import Any, Literal

import mssql_python
import pandas as pd

from factl.config.auth import normalize_auth_mode

SQL_ACCESS_TOKEN_ATTRIBUTE = 1256
SQL_SCOPE = "https://database.windows.net/.default"


def _quote_identifier(value: str) -> str:
    if not value or "\x00" in value:
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return "[" + value.replace("]", "]]" ) + "]"


def _escape_connection_value(value: str) -> str:
    return "{" + value.replace("}", "}}") + "}"


class DatabaseConnection:
    def __init__(
        self,
        hostname: str,
        database: str,
        port: int,
        auth_mode: str = "default",
        client_id: str | None = None,
        client_secret: str | None = None,
    ):
        self.host = hostname
        self.db = database
        self.port = port
        self.auth_mode = normalize_auth_mode(auth_mode)
        self.client_id = client_id
        self.client_secret = client_secret

    def _base_connection_string(self) -> str:
        return (
            f"Server={self.host},{self.port};"
            f"Database={_escape_connection_value(self.db)};"
            "Encrypt=yes;"
            "TrustServerCertificate=no;"
        )

    def connect(self):
        if self.client_id and self.client_secret:
            connection_string = (
                self._base_connection_string()
                + "Authentication=ActiveDirectoryServicePrincipal;"
                + f"UID={_escape_connection_value(self.client_id)};"
                + f"PWD={_escape_connection_value(self.client_secret)};"
            )
            return mssql_python.connect(
                connection_string,
                timeout=120,
            )
        if self.auth_mode == "default":
            return mssql_python.connect(
                self._base_connection_string() + "Authentication=ActiveDirectoryDefault;",
                timeout=120,
            )
        if self.auth_mode == "interactive":
            return mssql_python.connect(
                self._base_connection_string()
                + "Authentication=ActiveDirectoryInteractive;",
                timeout=120,
            )
        if self.auth_mode == "cli":
            return self._create_cli_token_connection()
        raise ValueError(
            "DatabaseConnection requires a supported auth_mode or client_id/client_secret."
        )

    def _create_cli_token_connection(self) -> Any:
        from azure.identity import AzureCliCredential

        credential = AzureCliCredential(process_timeout=30)
        token = credential.get_token(SQL_SCOPE).token.encode("utf-16-le")
        token_struct = struct.pack(f"<I{len(token)}s", len(token), token)
        return mssql_python.connect(
            self._base_connection_string(),
            timeout=120,
            attrs_before={SQL_ACCESS_TOKEN_ATTRIBUTE: token_struct},
        )

    def execute_sql(self, sql: str, params: dict | None = None) -> None:
        conn = self.connect()
        try:
            cursor = conn.cursor()
            try:
                cursor.execute(sql, params or {})
            finally:
                cursor.close()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def pandas_read(self, sql: str, params: dict | None = None) -> pd.DataFrame:
        conn = self.connect()
        try:
            cursor = conn.cursor()
            try:
                cursor.execute(sql, params or {})
                columns = [column[0] for column in cursor.description] if cursor.description else []
                rows = [tuple(row) for row in cursor.fetchall()]
            finally:
                cursor.close()
        finally:
            conn.close()
        return pd.DataFrame(rows, columns=columns)

    def read_pandas(self, sql: str, params: dict | None = None) -> pd.DataFrame:
        return self.pandas_read(sql, params=params)

    def pandas_write(
        self,
        df: pd.DataFrame,
        table_name: str,
        if_exists: Literal["fail", "replace", "append"] = "append",
        index: bool = False,
    ) -> None:
        if index:
            df = df.reset_index()

        conn = self.connect()
        try:
            cursor = conn.cursor()
            try:
                if if_exists == "replace":
                    cursor.execute(f"TRUNCATE TABLE {table_name}")
                elif if_exists == "fail":
                    cursor.execute(f"SELECT TOP 1 1 FROM {table_name}")
                    if cursor.fetchone() is not None:
                        raise ValueError(
                            f"Table {table_name} already contains data and if_exists='fail'."
                        )

                if df.empty:
                    conn.commit()
                    return

                columns = list(df.columns)
                placeholders = ", ".join(["?" for _ in columns])
                column_names = ", ".join(_quote_identifier(str(column)) for column in columns)
                sql_insert = (
                    f"INSERT INTO {table_name} ({column_names}) VALUES ({placeholders})"
                )
                rows = [
                    tuple(None if pd.isna(value) else value for value in row)
                    for row in df.itertuples(index=False, name=None)
                ]
                cursor.executemany(sql_insert, rows)
            finally:
                cursor.close()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
