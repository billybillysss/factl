from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
from fabric_cicd import FeatureFlag
import yaml

from factl.config.auth import normalize_auth_mode
from factl.logger import configure_logging

LOCAL_CONFIG_DIR = ".factl"
USER_CONFIG_FILE = "profiles.yaml"


@dataclass(frozen=True)
class DeveloperProfile:
    profile_id: str
    com_workspace_id: str
    force_disable_schedules: bool
    display_name: str
    aliases: tuple[str, ...]
    git_connection_id: str | None = None
    git_connection_type: str | None = None
    auth_mode: str | None = None
    meta_database_host: str | None = None
    meta_database_name: str | None = None
    fabric_cicd_enabled_features: tuple[str, ...] | None = None


def _normalize_token(value: str | None) -> str:
    return (value or "").strip().lower()


def _normalize_code(value: str) -> str:
    return value.strip().lower()


def _derive_initials(name: str) -> str:
    tokens = [token for token in name.replace("-", " ").split() if token]
    return "".join(token[0] for token in tokens).lower()


def _is_valid_code(value: str) -> bool:
    token = value.strip().lower()
    if not token:
        return False
    return token.replace("_", "").isalnum()


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    token = str(value).strip().lower()
    if token in {"1", "true", "yes", "y", "on"}:
        return True
    if token in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _user_config_path() -> Path:
    configured_dir = os.getenv("FACTL_PROFILE_DIR", "").strip()
    if configured_dir:
        return Path(configured_dir).expanduser() / USER_CONFIG_FILE
    return Path.home() / LOCAL_CONFIG_DIR / USER_CONFIG_FILE


def _load_yaml_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _save_yaml_dict(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        yaml.safe_dump(payload, file, sort_keys=False)


def _supported_feature_flags() -> set[str]:
    return {flag.value for flag in FeatureFlag}


def _normalize_enabled_features(
    values: list[str] | tuple[str, ...],
    *,
    source: str,
) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        feature = str(value).strip()
        if feature and feature not in result:
            result.append(feature)

    supported = _supported_feature_flags()
    invalid = sorted(feature for feature in result if feature not in supported)
    if invalid:
        supported_values = ", ".join(sorted(supported))
        invalid_values = ", ".join(invalid)
        raise ValueError(
            f"Unsupported fabric_cicd.enabled_features value(s) in {source}: {invalid_values}. "
            f"Supported values: {supported_values}"
        )
    return tuple(result)


def _load_profiles_from_new_schema(payload: dict[str, Any]) -> list[DeveloperProfile]:
    configured = payload.get("profiles") or []
    if not isinstance(configured, list):
        return []

    profiles: list[DeveloperProfile] = []
    for row in configured:
        if not isinstance(row, dict):
            continue
        profile_id = _normalize_code(str(row.get("id") or ""))
        com_workspace_id = str(row.get("com_workspace_id") or "").strip()
        force_disable_schedules = _as_bool(
            row.get("force_disable_schedules"), default=False
        )
        display_name = str(row.get("display_name") or "").strip() or profile_id
        git_connection = row.get("git_connection")
        git_connection_id = (
            str(git_connection.get("id") or "").strip()
            if isinstance(git_connection, dict)
            else ""
        )
        git_connection_id = git_connection_id or None
        git_connection_type = (
            str(git_connection.get("type") or "").strip().lower()
            if isinstance(git_connection, dict)
            else ""
        )
        if git_connection_type not in {"ado", "github"}:
            git_connection_type = None
        auth_mode = None
        auth = row.get("auth")
        if isinstance(auth, dict) and auth.get("mode") is not None:
            auth_mode = normalize_auth_mode(str(auth.get("mode")))

        metadata_database = row.get("meta_database")
        meta_database_host = (
            str(metadata_database.get("host") or "").strip()
            if isinstance(metadata_database, dict)
            else ""
        )
        meta_database_name = (
            str(metadata_database.get("name") or "").strip()
            if isinstance(metadata_database, dict)
            else ""
        )
        fabric_cicd = row.get("fabric_cicd")
        fabric_cicd_enabled_features: tuple[str, ...] | None = None
        if fabric_cicd is not None:
            if not isinstance(fabric_cicd, dict):
                raise ValueError(
                    f"Missing or invalid 'fabric_cicd' mapping in {_user_config_path()}"
                )
            raw_enabled_features = fabric_cicd.get("enabled_features")
            if raw_enabled_features is None:
                fabric_cicd_enabled_features = ()
            elif not isinstance(raw_enabled_features, list):
                raise ValueError(
                    f"Missing or invalid 'fabric_cicd.enabled_features' list in {_user_config_path()}"
                )
            else:
                fabric_cicd_enabled_features = _normalize_enabled_features(
                    tuple(str(value) for value in raw_enabled_features),
                    source=str(_user_config_path()),
                )
        if not _is_valid_code(profile_id) or not com_workspace_id:
            continue

        aliases: set[str] = {
            profile_id,
            _normalize_token(com_workspace_id),
            _normalize_token(display_name),
            _normalize_token(display_name.replace(" ", "")),
        }
        initials = _derive_initials(display_name)
        if initials:
            aliases.add(initials)

        raw_aliases = row.get("aliases") or []
        if isinstance(raw_aliases, list):
            aliases.update(
                _normalize_token(str(value)) for value in raw_aliases if value
            )

        profiles.append(
            DeveloperProfile(
                profile_id=profile_id,
                com_workspace_id=com_workspace_id,
                force_disable_schedules=force_disable_schedules,
                display_name=display_name,
                aliases=tuple(sorted(alias for alias in aliases if alias)),
                git_connection_id=git_connection_id,
                git_connection_type=git_connection_type,
                auth_mode=auth_mode,
                meta_database_host=meta_database_host or None,
                meta_database_name=meta_database_name or None,
                fabric_cicd_enabled_features=fabric_cicd_enabled_features,
            )
        )

    deduped: dict[str, DeveloperProfile] = {}
    for profile in profiles:
        deduped[profile.profile_id] = profile
    return sorted(deduped.values(), key=lambda profile: profile.profile_id)


def _get_active_profile_id(payload: dict[str, Any]) -> str | None:
    active = payload.get("active")
    if active:
        return _normalize_code(str(active))
    return None


def save_profiles(profiles: list[DeveloperProfile], active: str | None) -> None:
    payload: dict[str, Any] = {
        "profiles": [
            {
                "id": profile.profile_id,
                "com_workspace_id": profile.com_workspace_id,
                "force_disable_schedules": profile.force_disable_schedules,
                "display_name": profile.display_name,
                **(
                    {
                        "git_connection": {
                            "id": profile.git_connection_id,
                            "type": profile.git_connection_type,
                        }
                    }
                    if profile.git_connection_id
                    else {}
                ),
                **(
                    {"auth": {"mode": profile.auth_mode}}
                    if profile.auth_mode is not None
                    else {}
                ),
                **(
                    {
                        "meta_database": {
                            "host": profile.meta_database_host,
                            "name": profile.meta_database_name,
                        }
                    }
                    if profile.meta_database_host and profile.meta_database_name
                    else {}
                ),
                **(
                    {
                        "fabric_cicd": {
                            "enabled_features": list(
                                profile.fabric_cicd_enabled_features or ()
                            )
                        }
                    }
                    if profile.fabric_cicd_enabled_features is not None
                    else {}
                ),
                "aliases": [
                    alias
                    for alias in profile.aliases
                    if alias != profile.profile_id
                    and alias != _normalize_token(profile.com_workspace_id)
                ],
            }
            for profile in profiles
        ],
        "active": active,
    }
    _save_yaml_dict(_user_config_path(), payload)


def load_profiles() -> tuple[list[DeveloperProfile], str | None]:
    payload = _load_yaml_dict(_user_config_path())
    profiles = _load_profiles_from_new_schema(payload)
    active = _get_active_profile_id(payload)
    return profiles, active


def _prompt_text(
    message: str, default: str | None = None, show_default: bool = True
) -> str:
    try:
        if default is None:
            return str(click.prompt(message)).strip()
        return str(
            click.prompt(message, default=default, show_default=show_default)
        ).strip()
    except (click.Abort, EOFError) as exc:
        raise ValueError(
            "Interactive input cancelled. Use explicit flags for non-interactive usage."
        ) from exc


def _prompt_confirm(message: str, default: bool = False) -> bool:
    try:
        return bool(click.confirm(message, default=default))
    except (click.Abort, EOFError) as exc:
        raise ValueError(
            "Interactive input cancelled. Use explicit flags for non-interactive usage."
        ) from exc


def _validate_guid(value: str, label: str) -> str:
    stripped = value.strip()
    try:
        uuid.UUID(stripped)
    except ValueError:
        raise ValueError(f"{label} must be a valid GUID. Got: {stripped!r}")
    return stripped


def _prompt_git_connection_type(default: str | None = None) -> str:
    default_text = {"ado": "1", "github": "2"}.get(default or "", "")
    while True:
        raw = _prompt_text(
            "Git connection type: 1) Azure DevOps 2) GitHub",
            default=default_text,
            show_default=bool(default_text),
        )
        token = _normalize_code(raw)
        if token in {"1", "ado", "azuredevops", "azure devops"}:
            return "ado"
        if token in {"2", "github"}:
            return "github"
        click.echo("Invalid choice. Enter 1 for Azure DevOps or 2 for GitHub.")


def _git_connection_display(profile: DeveloperProfile) -> str:
    if not profile.git_connection_id:
        return "unset"
    if profile.git_connection_type:
        return f"set({profile.git_connection_type})"
    return "set"


def _find_profile(
    profiles: list[DeveloperProfile], selector: str
) -> DeveloperProfile | None:
    token = _normalize_token(selector)
    if not token:
        return None
    matches = [profile for profile in profiles if token in set(profile.aliases)]
    if not matches:
        return None
    if len(matches) > 1:
        matched_ids = ", ".join(sorted(profile.profile_id for profile in matches))
        raise ValueError(
            f"Profile selector '{selector}' is ambiguous. Matches: {matched_ids}"
        )
    return matches[0]


def _prompt_profile_selection(
    profiles: list[DeveloperProfile],
    message: str,
    allow_skip: bool = False,
) -> str | None:
    click.echo("Profiles:")
    for index, profile in enumerate(profiles, start=1):
        click.echo(
            f"  [{index}] {profile.profile_id:<8} {profile.display_name} "
            f"(com={profile.com_workspace_id}, auth={profile.auth_mode or 'inherit'}, git_connection_id={_git_connection_display(profile)}, force_disable_schedules={profile.force_disable_schedules}, meta_db={'set' if profile.meta_database_host and profile.meta_database_name else 'unset'}, fabric_cicd={'inherit' if profile.fabric_cicd_enabled_features is None else len(profile.fabric_cicd_enabled_features)})"
        )

    while True:
        suffix = " (press Enter to skip)" if allow_skip else ""
        raw = _prompt_text(f"{message}{suffix}", default="", show_default=False)
        if not raw:
            if allow_skip:
                return None
            continue

        if raw.isdigit():
            selected_index = int(raw)
            if 1 <= selected_index <= len(profiles):
                return profiles[selected_index - 1].profile_id

        matched = _find_profile(profiles, raw)
        if matched is not None:
            return matched.profile_id

        click.echo("Invalid selection. Choose a listed number or profile id.")


def active_profile_or_error() -> DeveloperProfile:
    profiles, active = load_profiles()
    if not profiles:
        raise ValueError(
            "No profiles configured. Run `factl profile set <id>` first. "
            'Example: factl profile set bs --com-workspace-id <id> --display-name "Bruno Star"'
        )
    if not active:
        raise ValueError(
            "No active profile configured. Run `factl profile use <id>` or `factl profile set <id> ...`."
        )

    profile = _find_profile(profiles, active)
    if profile is None:
        raise ValueError(
            f"Active profile '{active}' was not found. Run `factl profile list` then `factl profile use <id>`."
        )
    return profile


def register_profile_commands(cli: click.Group) -> None:
    @cli.group("profile")
    def profile_group() -> None:
        """Manage user-level deployment profiles."""

    @profile_group.command("list")
    @click.option(
        "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
    )
    def profile_list(log_level: str | None) -> None:
        configure_logging(log_level)
        profiles, active = load_profiles()
        active_profile = _find_profile(profiles, active) if active else None
        if not profiles:
            click.echo("No profiles configured. Use `factl profile set <id> ...`.")
            return

        click.echo("Profiles:")
        for profile in profiles:
            marker = (
                "*"
                if active_profile and active_profile.profile_id == profile.profile_id
                else " "
            )
            click.echo(
                f"{marker} {profile.profile_id:<8} {profile.display_name} "
                f"(com={profile.com_workspace_id}, git_connection_id={_git_connection_display(profile)}, force_disable_schedules={profile.force_disable_schedules}, meta_db={'set' if profile.meta_database_host and profile.meta_database_name else 'unset'}, fabric_cicd={'inherit' if profile.fabric_cicd_enabled_features is None else len(profile.fabric_cicd_enabled_features)})"
            )

    @profile_group.command("current")
    @click.option(
        "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
    )
    def profile_current(log_level: str | None) -> None:
        configure_logging(log_level)
        profile = active_profile_or_error()
        click.echo(
            f"Active profile: {profile.profile_id} "
            f"({profile.display_name}, com={profile.com_workspace_id}, git_connection_id={_git_connection_display(profile)}, force_disable_schedules={profile.force_disable_schedules}, meta_db={'set' if profile.meta_database_host and profile.meta_database_name else 'unset'}, fabric_cicd={'inherit' if profile.fabric_cicd_enabled_features is None else len(profile.fabric_cicd_enabled_features)})"
        )

    @profile_group.command("use")
    @click.argument("profile_id")
    @click.option(
        "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
    )
    def profile_use(profile_id: str, log_level: str | None) -> None:
        configure_logging(log_level)
        profiles, _ = load_profiles()
        if not profiles:
            raise ValueError(
                "No profiles configured. Use `factl profile set <id> ...` first."
            )

        profile = _find_profile(profiles, profile_id)
        if profile is None:
            raise ValueError(
                f"Unknown profile '{profile_id}'. Use `factl profile list` to see valid ids."
            )
        save_profiles(profiles, active=profile.profile_id)
        click.echo(f"Active profile set to '{profile.profile_id}'.")

    @profile_group.command("set")
    @click.argument("profile_id", required=False)
    @click.option(
        "--com-workspace-id", default=None, help="Personal common workspace id."
    )
    @click.option(
        "--force-disable-schedules/--allow-schedules",
        default=None,
        help="Force workflow schedules disabled for this personal workspace.",
    )
    @click.option("--display-name", default=None, help="Display name.")
    @click.option(
        "--alias", "aliases", multiple=True, help="Additional alias. Repeatable."
    )
    @click.option(
        "--activate/--no-activate",
        default=None,
        help="Set this profile as active. If omitted, interactive sessions ask when multiple profiles exist.",
    )
    @click.option(
        "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
    )
    @click.option(
        "--auth-mode",
        type=click.Choice(["default", "interactive", "cli"], case_sensitive=False),
        default=None,
        help="Profile auth mode override. If omitted, inherits from target/project settings.",
    )
    @click.option(
        "--meta-database-host",
        default=None,
        help="Metadata database host override for self deploy database.",
    )
    @click.option(
        "--meta-database-name",
        default=None,
        help="Metadata database name override for self deploy database.",
    )
    @click.option(
        "--enabled-feature",
        "enabled_features",
        multiple=True,
        help="fabric-cicd feature flag override for this profile. Repeatable.",
    )
    @click.option(
        "--git-connection-id",
        default=None,
        help="Git connection id (GUID).",
    )
    @click.option(
        "--git-connection-type",
        type=click.Choice(["ado", "github"], case_sensitive=False),
        default=None,
        help="Git connection type.",
    )
    def profile_set(
        profile_id: str | None,
        com_workspace_id: str | None,
        force_disable_schedules: bool | None,
        display_name: str | None,
        aliases: tuple[str, ...],
        activate: bool | None,
        log_level: str | None,
        auth_mode: str | None,
        meta_database_host: str | None,
        meta_database_name: str | None,
        enabled_features: tuple[str, ...],
        git_connection_id: str | None,
        git_connection_type: str | None,
    ) -> None:
        configure_logging(log_level)
        is_interactive = sys.stdin.isatty()

        if profile_id:
            normalized_id = _normalize_code(profile_id)
            if not _is_valid_code(normalized_id):
                raise ValueError(
                    "Invalid profile id. Use letters, numbers, or underscore."
                )
        else:
            if not is_interactive:
                raise ValueError(
                    "Usage: factl profile set <id> --com-workspace-id <id> "
                    "[--force-disable-schedules/--allow-schedules] --display-name <name>"
                )
            while True:
                candidate = _normalize_code(_prompt_text("Profile id"))
                if _is_valid_code(candidate):
                    normalized_id = candidate
                    break
                click.echo("Invalid profile id. Use letters, numbers, or underscore.")

        profiles, current_active = load_profiles()
        existing = _find_profile(profiles, normalized_id)

        display_default = existing.display_name if existing else normalized_id
        resolved_display_name = (
            display_name or display_default
        ).strip() or normalized_id
        if not display_name and is_interactive:
            resolved_display_name = (
                _prompt_text(
                    "Display name", default=resolved_display_name, show_default=True
                ).strip()
                or normalized_id
            )

        com_default = existing.com_workspace_id if existing else None
        resolved_com_workspace_id = (com_workspace_id or com_default or "").strip()
        if not resolved_com_workspace_id and is_interactive:
            resolved_com_workspace_id = _prompt_text("Personal common workspace id")

        if not resolved_com_workspace_id:
            raise ValueError(
                "com_workspace_id is required. Example: factl profile set bs --com-workspace-id <id> "
                "--display-name <name>"
            )
        resolved_com_workspace_id = _validate_guid(
            resolved_com_workspace_id, "com_workspace_id"
        )

        schedule_default = existing.force_disable_schedules if existing else False
        resolved_force_disable_schedules = (
            force_disable_schedules
            if force_disable_schedules is not None
            else schedule_default
        )
        if force_disable_schedules is None and is_interactive:
            resolved_force_disable_schedules = _prompt_confirm(
                "Disable schedules by default in this personal workspace?",
                default=False,
            )

        extra_aliases = set(_normalize_token(alias) for alias in aliases if alias)
        if existing:
            extra_aliases.update(existing.aliases)

        merged_aliases = tuple(
            sorted(
                {
                    normalized_id,
                    _normalize_token(resolved_com_workspace_id),
                    _normalize_token(resolved_display_name),
                    _normalize_token(resolved_display_name.replace(" ", "")),
                    _derive_initials(resolved_display_name),
                    *extra_aliases,
                }
                - {""}
            )
        )

        git_connection_id_default = existing.git_connection_id if existing else None
        git_connection_type_default = (
            existing.git_connection_type if existing else None
        )
        if git_connection_id is not None:
            resolved_git_connection_id = git_connection_id.strip() or None
        else:
            resolved_git_connection_id = git_connection_id_default
        if git_connection_type is not None:
            resolved_git_connection_type = git_connection_type.lower()
        else:
            resolved_git_connection_type = git_connection_type_default
        if is_interactive and git_connection_id is None:
            resolved_git_connection_id = (
                _prompt_text(
                    "Git connection id [optional for Azure DevOps, required for GitHub]",
                    default=git_connection_id_default or "",
                    show_default=bool(git_connection_id_default),
                ).strip()
                or None
            )
            if resolved_git_connection_id:
                resolved_git_connection_type = _prompt_git_connection_type(
                    resolved_git_connection_type
                )
            else:
                resolved_git_connection_type = None

        if resolved_git_connection_id:
            resolved_git_connection_id = _validate_guid(
                resolved_git_connection_id, "git_connection_id"
            )
        if resolved_git_connection_id and not resolved_git_connection_type:
            raise ValueError(
                f"git_connection_type is required when git_connection_id is set for profile "
                f"'{normalized_id}'. Rerun `factl profile set {normalized_id}` and choose "
                "the connection type (1) Azure DevOps 2) GitHub)."
            )
        if resolved_git_connection_type and not resolved_git_connection_id:
            raise ValueError(
                f"git_connection_type requires git_connection_id for profile "
                f"'{normalized_id}'. Provide a Git connection id or clear the type."
            )

        auth_mode_default = existing.auth_mode if existing else None
        resolved_auth_mode = (
            normalize_auth_mode(auth_mode) if auth_mode else auth_mode_default
        )

        meta_db_host_default = existing.meta_database_host if existing else None
        meta_db_name_default = existing.meta_database_name if existing else None
        resolved_meta_database_host = (
            meta_database_host
            if meta_database_host is not None
            else meta_db_host_default
        )
        resolved_meta_database_name = (
            meta_database_name
            if meta_database_name is not None
            else meta_db_name_default
        )
        resolved_meta_database_host = (
            resolved_meta_database_host or ""
        ).strip() or None
        resolved_meta_database_name = (
            resolved_meta_database_name or ""
        ).strip() or None
        if is_interactive and meta_database_host is None and meta_database_name is None:
            has_existing_meta_database = bool(
                resolved_meta_database_host and resolved_meta_database_name
            )
            configure_meta_database = _prompt_confirm(
                "Configure metadata database for self deploy database?",
                default=has_existing_meta_database,
            )
            if configure_meta_database:
                resolved_meta_database_host = (
                    _prompt_text(
                        "Metadata database host",
                        default=resolved_meta_database_host or "",
                        show_default=bool(resolved_meta_database_host),
                    ).strip()
                    or None
                )
                resolved_meta_database_name = (
                    _prompt_text(
                        "Metadata database name",
                        default=resolved_meta_database_name or "",
                        show_default=bool(resolved_meta_database_name),
                    ).strip()
                    or None
                )
            else:
                resolved_meta_database_host = None
                resolved_meta_database_name = None
        if (resolved_meta_database_host and not resolved_meta_database_name) or (
            resolved_meta_database_name and not resolved_meta_database_host
        ):
            raise ValueError(
                "Profile meta_database requires both --meta-database-host and --meta-database-name."
            )

        enabled_features_default = (
            existing.fabric_cicd_enabled_features if existing else None
        )
        resolved_enabled_features: tuple[str, ...] | None
        if enabled_features:
            resolved_enabled_features = _normalize_enabled_features(
                enabled_features,
                source="CLI",
            )
        else:
            resolved_enabled_features = enabled_features_default
            if is_interactive:
                configure_enabled_features = _prompt_confirm(
                    "Configure fabric-cicd feature flags for this personal profile?",
                    default=enabled_features_default is not None,
                )
                if configure_enabled_features:
                    default_value = ", ".join(enabled_features_default or ())
                    raw_enabled_features = _prompt_text(
                        "Enabled feature flags (comma-separated)",
                        default=default_value,
                        show_default=bool(default_value),
                    )
                    resolved_enabled_features = _normalize_enabled_features(
                        [
                            value
                            for value in (
                                item.strip()
                                for item in raw_enabled_features.split(",")
                            )
                            if value
                        ],
                        source="interactive profile input",
                    )
                else:
                    resolved_enabled_features = None

        updated = DeveloperProfile(
            profile_id=normalized_id,
            com_workspace_id=resolved_com_workspace_id,
            force_disable_schedules=resolved_force_disable_schedules,
            display_name=resolved_display_name,
            aliases=merged_aliases,
            git_connection_id=resolved_git_connection_id,
            git_connection_type=resolved_git_connection_type,
            auth_mode=resolved_auth_mode,
            meta_database_host=resolved_meta_database_host,
            meta_database_name=resolved_meta_database_name,
            fabric_cicd_enabled_features=resolved_enabled_features,
        )

        replaced = False
        next_profiles: list[DeveloperProfile] = []
        for profile in profiles:
            if profile.profile_id == normalized_id:
                next_profiles.append(updated)
                replaced = True
            else:
                next_profiles.append(profile)
        if not replaced:
            next_profiles.append(updated)
        next_profiles = sorted(next_profiles, key=lambda profile: profile.profile_id)

        should_activate = False
        if activate is not None:
            should_activate = activate
        elif existing and current_active == normalized_id:
            should_activate = True
        elif len(next_profiles) == 1 and not current_active:
            should_activate = True
        elif current_active and current_active != normalized_id:
            if is_interactive:
                should_activate = _prompt_confirm(
                    f"Set '{normalized_id}' as active profile?",
                    default=False,
                )
        elif is_interactive:
            should_activate = _prompt_confirm(
                f"Set '{normalized_id}' as active profile?", default=False
            )

        next_active = normalized_id if should_activate else current_active
        save_profiles(next_profiles, active=next_active)
        if should_activate:
            click.echo(f"Profile '{normalized_id}' saved and set active.")
        else:
            click.echo(f"Profile '{normalized_id}' saved.")

    @profile_group.command("delete")
    @click.argument("profile_id")
    @click.option("--yes", is_flag=True, help="Delete without confirmation prompt.")
    @click.option(
        "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
    )
    def profile_delete(profile_id: str, yes: bool, log_level: str | None) -> None:
        configure_logging(log_level)
        profiles, active = load_profiles()
        if not profiles:
            raise ValueError(
                "No profiles configured. Use `factl profile set <id> ...` first."
            )

        target = _find_profile(profiles, profile_id)
        if target is None:
            raise ValueError(
                f"Unknown profile '{profile_id}'. Use `factl profile list` to see valid ids."
            )

        is_interactive = sys.stdin.isatty()
        if not yes:
            if not is_interactive:
                raise ValueError("Non-interactive delete requires --yes.")
            confirmed = _prompt_confirm(
                f"Delete profile '{target.profile_id}' ({target.display_name})?",
                default=False,
            )
            if not confirmed:
                click.echo("Delete cancelled.")
                return

        remaining = [
            profile for profile in profiles if profile.profile_id != target.profile_id
        ]

        next_active = active
        if active == target.profile_id:
            next_active = None
            if remaining and is_interactive:
                if _prompt_confirm(
                    "Deleted profile was active. Select another active profile now?",
                    default=True,
                ):
                    selected = _prompt_profile_selection(
                        remaining,
                        "Choose new active profile (number or id)",
                        allow_skip=False,
                    )
                    next_active = selected

        save_profiles(remaining, active=next_active)
        click.echo(f"Profile '{target.profile_id}' deleted.")
