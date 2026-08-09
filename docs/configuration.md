# Configuration

Reference for all factl configuration files, settings, and precedence rules.

## Configuration files

| File | Location | Scope | Created by |
|---|---|---|---|
| `profiles.yaml` | `~/.factl/` | Per-user (developer machine) | `factl profile set` |
| `project.yaml` | `.config/.factl/` | Per-repository | `factl config init` |
| `targets.yaml` | `.config/.factl/` | Per-repository | `factl config init` |
| `variables.yaml` | `.config/.factl/` | Per-repository | `factl config init` |
| Parameter files | `fabric/parameters/` | Per-repository | Manual |
| Workflow definitions | `{control.local_path}/{workflow.control_folder}/` (default: `controls/workflows/`) | Per-repository | Manual |

## profiles.yaml (`~/.factl/`)

Per-developer settings for personal workspace workflows. Created and managed with `factl profile set`.

```yaml
profiles:
  - id: bs
    com_workspace_id: 12345678-1234-1234-1234-123456789abc
    force_disable_schedules: false
    display_name: "Bruno Star"
    auth:
      mode: default
    git_connection:
      id: <git-connection-guid>
      type: github
    meta_database:
      host: <sql-host>
      name: <meta-database-name>
    fabric_cicd:
      enabled_features: []
    aliases: []
active: bs
```

| Field | Required | Description |
|---|---|---|
| `id` | Yes | Short profile identifier (letters, numbers, underscore) |
| `com_workspace_id` | Yes | Personal common workspace GUID |
| `display_name` | No | Human-readable name (defaults to id) |
| `force_disable_schedules` | No | Force-disable schedules in this personal workspace (default: false) |
| `auth.mode` | No | Auth override: `default`, `interactive`, or `cli` |
| `git_connection.id` | No | Git connection GUID (required for GitHub repos) |
| `git_connection.type` | No | `ado` or `github` |
| `meta_database.host` | No | SQL endpoint for self deploy database |
| `meta_database.name` | No | Database name for self deploy database |
| `fabric_cicd.enabled_features` | No | fabric-cicd feature flags for this profile |
| `aliases` | No | Additional identifiers for `factl profile use` |

`factl profile use <selector>` matches against a set of aliases derived automatically from each profile — the profile id, the workspace GUID, the display name (with and without spaces), and the display name's initials — plus any explicit `aliases` entries. A selector that matches more than one profile is rejected as ambiguous.

Commands:
* `factl profile set <id> ...` — create or update a profile
* `factl profile list` — list all profiles
* `factl profile current` — show active profile
* `factl profile use <id>` — switch active profile
* `factl profile delete <id>` — remove a profile

## project.yaml (`.config/.factl/`)

Repository-level deployment structure. Created by `factl config init`.

### Top-level fields

```yaml
version: 1
project:
  repo_url: https://github.com/org/repo
auth:
  mode: default
deployment:
  # ...
```

| Field | Description |
|---|---|
| `version` | Config format version (must be `1`) |
| `project.repo_url` | Git repository URL (supports Azure DevOps and GitHub) |
| `auth.mode` | Default auth mode: `default`, `interactive`, or `cli` |

### deployment.control

```yaml
deployment:
  control:
    local_path: controls
    includes:
      - dbt/models
      - dbt/dbt_project.yml
```

| Field | Description |
|---|---|
| `local_path` | Repo-relative root for control assets deployed to Lakehouse |
| `includes` | Default paths to deploy when no `--folder` filter is passed. Each entry may be a folder, file path, or glob pattern, relative to `local_path` |

### deployment.database (optional)

```yaml
deployment:
  database:
    local_path: controls/database
    includes:
      - prc
```

| Field | Description |
|---|---|
| `local_path` | Repo-relative root for SQL scripts |
| `includes` | Default paths when no `--include` filter is passed. Each entry may be a folder, `.sql` file path, or glob pattern, relative to `local_path` |

### deployment.common

```yaml
deployment:
  common:
    local_path: fabric/com
    parameter_path: fabric/parameters/parameter.yml
    control:
      lakehouse:
        name: LH_CTL
        enable_schemas: true
    item_types:
      - Notebook
      - DataPipeline
      - Environment
      - Lakehouse
      - SparkJobDefinition
      # ... other supported Fabric item types (see below)
```

| Field | Description |
|---|---|
| `local_path` | Repo-relative folder containing Fabric items |
| `parameter_path` | Repo-relative parameter file for fabric-cicd |
| `control.lakehouse.name` | Control Lakehouse display name (in the common workspace) |
| `control.lakehouse.enable_schemas` | Whether to enable schema support |
| `item_types` | Default Fabric item types included in common deploy |

The full set of supported common item types is:

`ApacheAirflowJob`, `CopyJob`, `DataAgent`, `DataPipeline`, `Dataflow`, `Environment`, `Eventhouse`, `Eventstream`, `GraphQLApi`, `KQLDashboard`, `KQLDatabase`, `KQLQueryset`, `Lakehouse`, `MirroredDatabase`, `MLExperiment`, `MountedDataFactory`, `Notebook`, `Reflex`, `Report`, `SemanticModel`, `SparkJobDefinition`, `SQLDatabase`, `UserDataFunction`, `VariableLibrary`

### deployment.orchestration

```yaml
deployment:
  orchestration:
    parameter_path: fabric/parameters/datapipeline.yml
    processor:
      item_types:
        - DataPipeline
        - Notebook
      workspace_folder: processors
    workflow:
      control_folder: workflows
      workspace_folder: workflows
```

| Field | Description |
|---|---|
| `parameter_path` | Repo-relative parameter file for orchestration deploy |
| `processor.item_types` | Fabric item types treated as processor assets |
| `processor.workspace_folder` | Workspace folder for deployed processor items |
| `workflow.control_folder` | Subfolder under controls for workflow YAML definitions |
| `workflow.workspace_folder` | Workspace folder for published workflow items |
| `workflow.template.path` | Optional custom template directory path |

> **Note:** the legacy key `deployment.orchestration.workflow.template.variables` is rejected with an explicit error. Workflow template variables must be defined in `.config/.factl/variables.yaml` instead.

## targets.yaml (`.config/.factl/`)

Shared environment common workspace IDs and settings. These are the workspaces factl deploys orchestration (processors, workflows, common items, control Lakehouse) to. Data workspaces (where medallion Lakehouses and Warehouses live) are not configured here — they are referenced by processors through parameter files (`fabric/parameters/`).

```yaml
version: 1
personal_parameter_env: dev
targets:
  dev:
    com_workspace_id: <workspace-guid>
    force_disable_schedules: false
    auth:
      mode: default
    meta_database:
      host: <sql-endpoint>
      name: <meta-database-name>
    fabric_cicd:
      enabled_features: []
  test:
    com_workspace_id: <workspace-guid>
    force_disable_schedules: true
  prd:
    com_workspace_id: <workspace-guid>
    force_disable_schedules: false
```

| Field | Required | Description |
|---|---|---|
| `personal_parameter_env` | Yes | Which target's variables/parameters to use for `self` deploys |
| `targets.<env>.com_workspace_id` | Yes | Common workspace GUID (where factl deploys orchestration) |
| `targets.<env>.force_disable_schedules` | No | Force-disable schedules for this env |
| `targets.<env>.auth.mode` | No | Auth override for this target |
| `targets.<env>.meta_database.host` | No | SQL endpoint for shared database deploy |
| `targets.<env>.meta_database.name` | No | Database name for shared database deploy |
| `targets.<env>.fabric_cicd.enabled_features` | No | fabric-cicd feature flags for this env |

Supported `fabric_cicd.enabled_features` values:

`enable_lakehouse_unpublish`, `enable_warehouse_unpublish`, `enable_sqldatabase_unpublish`, `enable_eventhouse_unpublish`, `enable_kqldatabase_unpublish`, `enable_shortcut_publish`, `disable_workspace_folder_publish`, `continue_on_shortcut_failure`, `enable_environment_variable_replacement`, `enable_experimental_features`, `enable_items_to_include`, `enable_exclude_folder`, `enable_include_folder`, `enable_shortcut_exclude`, `enable_response_collection`, `enable_hard_delete`, `enable_bulk_publish`

## variables.yaml (`.config/.factl/`)

Per-environment template variables available in workflow YAML as Jinja2 expressions.

```yaml
version: 1
targets:
  dev:
    env_name: dev
  prd:
    env_name: prd
    retry_count: 5
```

Any variable can be any type (string, number, list, object). Use in workflow YAML:

```yaml
params:
  env:
    value: "{{ env_name }}"
    type: "string"
```

### Reserved variable names

These are provided automatically and cannot be redefined in `variables.yaml`:

`workspace_id`, `item_id`, `item_name`, `item_type`, `processor_name`, `processor_alias`, `workflow_name`, `item`, `processor`, `workflow`, `deployment`

## Parameter files 

fabric-cicd parameter files for environment-specific value replacement. The file paths are configured in `project.yaml`:

* `deployment.common.parameter_path` — used by `deploy com` (e.g., `fabric/parameters/parameter.yml`)
* `deployment.orchestration.parameter_path` — used by `deploy orc` (e.g., `fabric/parameters/datapipeline.yml`)

Follow the [fabric-cicd parameter file format](https://microsoft.github.io/fabric-cicd).

Used automatically during `deploy com` and `deploy orc`. When deploying to a personal workspace (`self` commands), parameter files are always staged. When deploying to a shared environment, parameter files are skipped if the target environment equals `personal_parameter_env`.

Parameter files replace both **workspace IDs** and **Lakehouse IDs** per environment using `find_replace` and `key_value_replace` entries. This is the mechanism that lets processors in the common workspace reference Lakehouses and Warehouses that live in separate data workspaces. The same processor definition uses placeholder IDs; the parameter file binds them to the correct workspace and Lakehouse GUIDs for each environment.

## Precedence rules

| Setting | Precedence (highest first) |
|---|---|
| Auth mode | CLI `--auth` → profile → target → project → `default` |
| fabric-cicd features | profile → target → `()` (none) |
| Schedule disabling | `--force-disable-schedules` → profile/target `force_disable_schedules` → `false` |
| Template variables | Self deploys use `<personal_parameter_env>`; shared deploys use matching target |
| Parameter staging | Always staged for self deploys; staged for shared deploys unless env equals `personal_parameter_env` |
