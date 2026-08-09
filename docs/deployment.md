# Deployment

How to deploy factl-managed assets to common workspaces. Data Lakehouses and Warehouses live in separate data workspaces and are not deployed by factl — they are referenced by processors through parameter files.

## Deployment model

factl supports two deployment modes:

| Mode | Command prefix | Target | Use case |
|---|---|---|---|
| **Self** | `factl self deploy` | Your personal workspace | Individual development and testing |
| **Shared** | `factl <env> deploy` | Shared environments (dev, test, prd) | Team deployment and promotion |

## Self deployment

Self deployment uses your active profile from `~/.factl/profiles.yaml`. All deployments go to your personal workspace.

### Before you start

Ensure you have:

1. An active profile: `factl profile current`
2. Repo configuration: `.config/.factl/project.yaml`, `targets.yaml`, `variables.yaml`
3. Fabric items in the directory configured by `deployment.common.local_path` in `project.yaml` (for common deploy)
4. Workflow YAML in the directory configured by `deployment.orchestration.workflow.control_folder` in `project.yaml` (relative to `deployment.control.local_path`)

### Deploy common items

```bash
factl self deploy com
```

Publishes all items from the directory configured by `deployment.common.local_path` in `project.yaml` to your personal workspace. Items are filtered by the `item_types` list in `project.yaml`.

Filter specific item types:

```bash
factl self deploy com --include-item-type Notebook --include-item-type Environment
```

Exclude item types:

```bash
factl self deploy com --exclude-item-type Report
```

### Deploy orchestration

```bash
factl self deploy orc
```

Compiles workflow YAML from the directory configured by `deployment.orchestration.workflow.control_folder` in `project.yaml` (relative to `deployment.control.local_path`) into Fabric DataPipelines and publishes them along with processor items.

Override schedule behavior:

```bash
# Force-disable all schedules regardless of workflow YAML
factl self deploy orc --force-disable-schedules

# Allow schedules as defined in workflow YAML
factl self deploy orc --allow-schedules
```

### Deploy control assets

```bash
factl self deploy ctl --auto-create
```

Uploads files from the directory configured by `deployment.control.local_path` in `project.yaml` to the control Lakehouse (configured by `deployment.common.control.lakehouse.name` in `project.yaml`) in your common workspace. The `--auto-create` flag creates the Lakehouse and controls folder when they do not exist.

Filter specific folders:

```bash
factl self deploy ctl --folder dbt/models
```

Preview changes without writing:

```bash
factl self deploy ctl --dry-run
```

### Deploy database

```bash
factl self deploy db
```

Executes SQL scripts from the directory configured by `deployment.database.local_path` in `project.yaml` against the metadata database configured in your profile (`meta_database.host` and `meta_database.name`).

Filter specific paths:

```bash
factl self deploy db --include prc
```

## Shared deployment

Shared deployment uses the targets defined in `.config/.factl/targets.yaml`.

### Deploy to an environment

```bash
factl dev deploy com
factl dev deploy orc
factl dev deploy ctl
factl dev deploy db
```

The environment name (`dev`, `test`, `prd`) must match a key under `targets` in `targets.yaml`.

### Full command forms

Shared deploy commands always use the environment-first form. Shorthand and full resource names are equivalent:

| Shorthand | Full resource name |
|---|---|
| `factl dev deploy com` | `factl dev deploy common` |
| `factl dev deploy orc` | `factl dev deploy orchestration` |
| `factl dev deploy ctl` | `factl dev deploy control` |
| `factl dev deploy db` | `factl dev deploy database` |

### Creating control Lakehouse in shared workspace

When deploying control assets to a shared common workspace for the first time:

```bash
factl dev deploy ctl --auto-create
```

This creates the controls folder and control Lakehouse (configured by `deployment.common.control.lakehouse.name` in `project.yaml`) in the shared common workspace.

## Git integration

### Pulling a branch to your personal workspace

```bash
factl self pull feature/my-changes
```

This connects your personal workspace to the Git repository and updates from the specified branch. Requires `project.repo_url` in `project.yaml` and, for GitHub repos, `git_connection_id` in your profile.

### Pushing changes from your personal workspace

```bash
factl self push feature/my-changes --comment "Updated ingest processors"
```

This commits all workspace changes to the specified branch. The workspace is connected to Git if not already connected.

### Force reconnect

If the workspace has an existing Git connection you want to replace:

```bash
factl self pull feature/my-changes --force-git-connect
factl self push feature/my-changes --force-git-connect
```

## Development workflow

A typical development cycle:

```bash
# 1. Start a feature branch
git checkout -b feature/my-changes

# 2. Pull the branch into your personal workspace
factl self pull feature/my-changes

# 3. Edit workflow YAML and Fabric items locally

# 4. Deploy changes to your personal workspace
factl self deploy ctl --auto-create
factl self deploy com
factl self deploy orc

# 5. Test in Fabric UI

# 6. Push changes back to Git
factl self push feature/my-changes --comment "Added new ingest workflow"

# 7. Create PR, merge, and deploy to shared environments
factl dev deploy ctl
factl dev deploy com
factl dev deploy orc
```

## Deployment promotion

After merging to the shared branch, promote through environments:

```bash
factl dev deploy com       # Deploy to dev
factl test deploy com      # Deploy to test
factl prd deploy com       # Deploy to prod
```

### Controlling schedules in production

Schedules are typically disabled in dev/test and enabled in production:

```yaml
# targets.yaml
targets:
  dev:
    force_disable_schedules: true
  test:
    force_disable_schedules: true
  prd:
    force_disable_schedules: false
```

This ensures workflows only run automatically in production while still allowing manual triggering in lower environments.

## Parameter staging

fabric-cicd parameter files replace environment-specific values (workspace IDs, Lakehouse IDs) at deploy time. This is how processors in the common workspace are bound to the correct data workspace Lakehouse and Warehouse GUIDs for each environment.

For personal workspace deploys, parameter files are **always** staged (applied). For shared deploys, parameter files are staged **unless** the target environment equals `personal_parameter_env` in `targets.yaml`.

This means if `personal_parameter_env` is set to `dev`, deploying to `dev` skips parameter staging (the parameter file values are already correct), while deploying to `test` or `prd` applies parameter replacements.

## Metadata generation

Generate metadata about deployed workflows and schedules:

```bash
# Shared environment
factl dev generate workflow
factl dev generate schedule

# Personal workspace
factl self generate workflow
factl self generate schedule
```

Output as CSV:

```bash
factl dev generate workflow --save framework.csv
```
