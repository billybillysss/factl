from __future__ import annotations

from pathlib import Path

import click

from factl.logger import configure_logging
from factl.template_resources import read_config_template

LOCAL_CONFIG_DIR = Path(".config") / ".factl"
REPO_PROJECT_FILE = "project.yaml"
REPO_TARGET_FILE = "targets.yaml"
REPO_VARIABLES_FILE = "variables.yaml"


def _save_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write(content.rstrip() + "\n")


def register_config_commands(cli: click.Group) -> None:
    @cli.group("config")
    def config_group() -> None:
        """Manage repo-level factl config files."""

    @config_group.command("init")
    @click.option(
        "--path",
        "path",
        default=Path("."),
        type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
        help="Repo root directory where .config/.factl templates are created. Defaults to the current working directory.",
    )
    @click.option(
        "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
    )
    def config_init(path: Path, log_level: str | None) -> None:
        """Create .config/.factl project/targets/variables templates if missing."""
        configure_logging(log_level)
        repo_root = path.resolve()
        if repo_root.exists() and not repo_root.is_dir():
            raise ValueError(f"Invalid --path directory: {repo_root}")
        repo_root.mkdir(parents=True, exist_ok=True)

        config_dir = repo_root / LOCAL_CONFIG_DIR
        project_path = config_dir / REPO_PROJECT_FILE
        targets_path = config_dir / REPO_TARGET_FILE
        variables_path = config_dir / REPO_VARIABLES_FILE

        config_dir.mkdir(parents=True, exist_ok=True)

        if project_path.exists() or targets_path.exists() or variables_path.exists():
            existing = [
                str(p)
                for p in (project_path, targets_path, variables_path)
                if p.exists()
            ]
            raise ValueError(
                "Refusing to initialize config because file(s) already exist: "
                + ", ".join(existing)
            )

        _save_text(project_path, read_config_template(REPO_PROJECT_FILE))
        _save_text(targets_path, read_config_template(REPO_TARGET_FILE))
        _save_text(variables_path, read_config_template(REPO_VARIABLES_FILE))
        click.echo(f"Created {project_path}")
        click.echo(f"Created {targets_path}")
        click.echo(f"Created {variables_path}")
