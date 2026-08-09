# CLI Commands

Complete reference for all factl CLI commands.

## Top-level commands

```
factl [command] [options]
```

| Command | Description |
|---|---|
| `config` | Manage repo-level configuration |
| `profile` | Manage user-level deployment profiles |
| `deploy` | Deploy resources to a shared environment |
| `self` | Commands for your personal workspace |
| `generate` | Generate artifacts for a shared environment |

## config

### `factl config init`

Create `.config/.factl/project.yaml`, `targets.yaml`, and `variables.yaml` from templates.

```bash
factl config init [--path <dir>] [--log-level <level>]
```

| Option | Description |
|---|---|
| `--path` | Repo root directory (default: current directory) |
| `--log-level` | Override FACTL_LOG_LEVEL |

Fails if any of the three files already exist.

## profile

### `factl profile set`

Create or update a developer profile.

```bash
factl profile set <id> \
  --com-workspace-id <guid> \
  [--display-name <name>] \
  [--force-disable-schedules | --allow-schedules] \
  [--auth-mode default|interactive|cli] \
  [--meta-database-host <host>] \
  [--meta-database-name <name>] \
  [--git-connection-id <guid>] \
  [--git-connection-type ado|github] \
  [--enabled-feature <feature>] \
  [--alias <alias>] \
  [--activate | --no-activate]
```

| Option | Description |
|---|---|
| `--com-workspace-id` | Personal workspace GUID (required) |
| `--display-name` | Human-readable name |
| `--force-disable-schedules` | Disable schedules in this workspace |
| `--allow-schedules` | Allow schedules as defined |
| `--auth-mode` | Auth mode override |
| `--meta-database-host` | SQL host for self deploy database |
| `--meta-database-name` | Database name for self deploy database |
| `--git-connection-id` | Git connection GUID |
| `--git-connection-type` | `ado` or `github` |
| `--enabled-feature` | fabric-cicd feature flag (repeatable) |
| `--alias` | Additional profile alias (repeatable) |
| `--activate` / `--no-activate` | Set as active profile |

### `factl profile list`

List all configured profiles. Active profile is marked with `*`.

```bash
factl profile list [--log-level <level>]
```

### `factl profile current`

Show the active profile.

```bash
factl profile current [--log-level <level>]
```

### `factl profile use`

Switch the active profile.

```bash
factl profile use <id> [--log-level <level>]
```

### `factl profile delete`

Remove a profile.

```bash
factl profile delete <id> [--yes] [--log-level <level>]
```

| Option | Description |
|---|---|
| `--yes` | Skip confirmation prompt |

## deploy (shared)

Deploy resources to a shared environment defined in `targets.yaml`.

### `factl <env> deploy com`

Deploy common items to a shared environment.

```bash
factl <env> deploy com \
  [--base-dir <dir>] \
  [--log-level <level>] \
  [--include-item-type <type>] \
  [--exclude-item-type <type>] \
  [--item-type <type>] \
  [--auth default|interactive|cli]
```

| Option | Description |
|---|---|
| `--include-item-type` | Include only these item types (repeatable) |
| `--exclude-item-type` | Exclude item types (repeatable) |
| `--item-type` | Legacy alias for `--include-item-type` |
| `--auth` | Auth mode override |

### `factl <env> deploy orc`

Deploy orchestration (workflows + processors) to a shared environment.

```bash
factl <env> deploy orc \
  [--base-dir <dir>] \
  [--log-level <level>] \
  [--force-disable-schedules | --allow-schedules] \
  [--unpublish-path <path>] \
  [--commit] \
  [--comment <text>] \
  [--auth default|interactive|cli]
```

| Option | Description |
|---|---|
| `--force-disable-schedules` | Force all schedules disabled |
| `--allow-schedules` | Use schedule settings from workflow YAML |
| `--unpublish-path` | Target path for orphan unpublish (repeatable) |
| `--commit` | Commit workflow changes to connected Git branch |
| `--comment` | Commit comment (max 300 chars) |

### `factl <env> deploy ctl`

Deploy control assets to a shared environment.

```bash
factl <env> deploy ctl \
  [--base-dir <dir>] \
  [--log-level <level>] \
  [--dry-run] \
  [--folder <path>] \
  [--auto-create] \
  [--auth default|interactive|cli]
```

| Option | Description |
|---|---|
| `--dry-run` | Show planned changes without writing |
| `--folder` | Control folder filter (repeatable) |
| `--auto-create` | Auto-create controls folder and Lakehouse |

### `factl <env> deploy db`

Deploy SQL database objects to a shared environment.

```bash
factl <env> deploy db \
  [--base-dir <dir>] \
  [--log-level <level>] \
  [--include <path>] \
  [--auth default|interactive|cli]
```

| Option | Description |
|---|---|
| `--include` | Database include folder (repeatable) |

## self

Commands for your personal workspace, using the active profile.

### `factl self pull`

Pull a remote Git branch into your personal workspace.

```bash
factl self pull <branch> \
  [--base-dir <dir>] \
  [--log-level <level>] \
  [--force-git-connect] \
  [--auth default|interactive|cli]
```

| Option | Description |
|---|---|
| `--force-git-connect` | Force reconnect before updateFromGit |

### `factl self push`

Commit personal workspace changes to a Git branch.

```bash
factl self push <branch> \
  [--base-dir <dir>] \
  [--log-level <level>] \
  [--force-git-connect] \
  [--comment <text>] \
  [--auth default|interactive|cli]
```

| Option | Description |
|---|---|
| `--force-git-connect` | Force disconnect/reconnect before commit |
| `--comment` | Commit comment (max 300 chars) |

### `factl self deploy com` / `factl self deploy common`

Deploy common items to your personal workspace.

```bash
factl self deploy com \
  [--base-dir <dir>] \
  [--log-level <level>] \
  [--include-item-type <type>] \
  [--exclude-item-type <type>] \
  [--item-type <type>] \
  [--auth default|interactive|cli]
```

### `factl self deploy orc` / `factl self deploy orchestration`

Deploy orchestration to your personal workspace.

```bash
factl self deploy orc \
  [--base-dir <dir>] \
  [--log-level <level>] \
  [--force-disable-schedules | --allow-schedules] \
  [--unpublish-path <path>] \
  [--commit] \
  [--comment <text>] \
  [--auth default|interactive|cli]
```

### `factl self deploy ctl` / `factl self deploy control`

Deploy control assets to your personal workspace.

```bash
factl self deploy ctl \
  [--base-dir <dir>] \
  [--log-level <level>] \
  [--dry-run] \
  [--folder <path>] \
  [--auto-create] \
  [--auth default|interactive|cli]
```

### `factl self deploy db` / `factl self deploy database`

Deploy SQL database objects for your workspace.

```bash
factl self deploy db \
  [--base-dir <dir>] \
  [--log-level <level>] \
  [--include <path>] \
  [--auth default|interactive|cli]
```

## generate (shared)

### `factl <env> generate workflow`

Generate workflow rows from controls and workspace items.

```bash
factl <env> generate workflow \
  [--base-dir <dir>] \
  [--log-level <level>] \
  [--save <path.csv>] \
  [--auth default|interactive|cli]
```

### `factl <env> generate schedule`

Generate schedule rows from workflows in workspace.

```bash
factl <env> generate schedule \
  [--base-dir <dir>] \
  [--log-level <level>] \
  [--save <path.csv>] \
  [--auth default|interactive|cli]
```

## self generate

### `factl self generate workflow`

Generate workflow rows for your personal workspace.

```bash
factl self generate workflow \
  [--base-dir <dir>] \
  [--log-level <level>] \
  [--save <path.csv>] \
  [--auth default|interactive|cli]
```

### `factl self generate schedule`

Generate schedule rows for your personal workspace.

```bash
factl self generate schedule \
  [--base-dir <dir>] \
  [--log-level <level>] \
  [--save <path.csv>] \
  [--auth default|interactive|cli]
```

## Global options

| Option | Description |
|---|---|
| `--base-dir` | Repository root directory (default: `"."`) |
| `--log-level` | Override FACTL_LOG_LEVEL (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) |
| `--auth` | Override auth mode (`default`, `interactive`, `cli`) |

## Environment variables

| Variable | Description |
|---|---|
| `FACTL_LOG_LEVEL` | Default log level |
| `FACTL_PROFILE_DIR` | Custom directory for `profiles.yaml` |

Azure authentication environment variables are handled by `azure-identity`:

| Variable | Description |
|---|---|
| `AZURE_CLIENT_ID` | Service principal client ID |
| `AZURE_CLIENT_SECRET` | Service principal client secret |
| `AZURE_TENANT_ID` | Azure tenant ID |
| `AZURE_USE_DEVICE_CODE` | Use device code authentication |
