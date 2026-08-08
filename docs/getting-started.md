# Getting Started

Step-by-step guide to installing and using factl.

## Prerequisites

* **Python 3.10** or later
* **Microsoft Fabric capacity** — you need at least two workspaces in a Fabric-enabled capacity: a **common workspace** (where factl deploys orchestration) and a **data workspace** (where Lakehouses, Warehouses, and SQL databases live). Personal dev workspaces are also needed per developer.
* **Azure authentication** — you must be authenticated to Azure. Choose one:
  * `az login` (recommended for local development)
  * Environment variables: `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID` (for CI/service principals)
* **Fabric workspace IDs** — you'll need the GUID for each workspace you want to deploy to. Find it in the Fabric portal URL: `https://app.fabric.microsoft.com/groups/<workspace-id>/`

## Installation

Install from PyPI:
```bash
pip install factl
```

Or clone the repository and install from source:

```bash
git clone <your-repo-url>
cd factl
pip install -e .
```

Verify the install:

```bash
factl --help
```

You should see the top-level command groups: `config`, `profile`, `deploy`, `self`, `generate`.

## Step 1: Initialize repo configuration

Run this in your repository root:

```bash
factl config init
```

This creates three template files under `.config/.factl/`:

```
.config/
  .factl/
    project.yaml     # repo structure and deployment settings
    targets.yaml     # shared environment workspace IDs
    variables.yaml   # per-environment template variables
```

### Configure project.yaml

Open `.config/.factl/project.yaml` and update:

| Field | What to set |
|---|---|
| `project.repo_url` | Your Git repository URL (Azure DevOps or GitHub) |
| `deployment.control.local_path` | Path to control assets (default: `controls`) |
| `deployment.common.local_path` | Path to Fabric items (default: `fabric/com`) |
| `deployment.common.parameter_path` | Path to the fabric-cicd parameter file |
| `deployment.common.control.lakehouse.name` | Name of your control Lakehouse (`LH_CTL`) in the common workspace |
| `deployment.orchestration.parameter_path` | Path to orchestration parameter file |

### Configure targets.yaml

Open `.config/.factl/targets.yaml` and add your shared environments:

```yaml
version: 1
personal_parameter_env: dev
targets:
  dev:
    com_workspace_id: <dev-workspace-guid>
    force_disable_schedules: false
    meta_database:
      host: <dev-sql-endpoint>
      name: <dev-meta-database>
  prd:
    com_workspace_id: <prd-workspace-guid>
    force_disable_schedules: false
    meta_database:
      host: <prd-sql-endpoint>
      name: <prd-meta-database>
```

`personal_parameter_env` tells factl which shared environment's variables and parameter files to use when deploying to your personal workspace.

The `com_workspace_id` values are your common workspace IDs — the workspaces factl deploys orchestration to. Data workspaces (where medallion Lakehouses and Warehouses live) are not listed here. They are referenced by processors through workspace and Lakehouse IDs in `fabric/parameters/*.yml` — the same processor code points at a different data workspace per environment through parameter replacement.

### Configure variables.yaml

Add per-environment variables used in workflow YAML:

```yaml
version: 1
targets:
  dev:
    env_name: dev
  prd:
    env_name: prd
```

Variables defined here become available as `{{ variable_name }}` in workflow YAML files.

## Step 2: Create your developer profile

A profile maps you to a personal common workspace where you test changes before promoting to shared environments. Run `factl profile set <id>` interactively and answer the prompts, or provide everything as command-line flags.

### Interactive setup

```bash
factl profile set bs
```

factl walks you through each setting:

| Prompt | What to enter |
|---|---|
| `Profile id` | Short identifier — letters, numbers, or underscore |
| `Display name` | Your full name (defaults to profile id) |
| `Personal common workspace id` | GUID of your personal workspace |
| `Disable schedules by default in this personal workspace?` | `y` (recommended — prevents accidental production triggers in dev) |
| `Git connection id` | Git connection GUID — optional for Azure DevOps, required for GitHub |
| `Git connection type: 1) Azure DevOps 2) GitHub` | `1` or `2` (only asked if a git connection id was entered) |
| `Configure metadata database for self deploy database?` | `y` if you deploy database assets (`self deploy database`) |
| `Metadata database host` | SQL endpoint (only asked if yes above) |
| `Metadata database name` | Database name (only asked if yes above) |
| `Configure fabric-cicd feature flags for this personal profile?` | `n` unless you need specific feature flags |
| `Enabled feature flags (comma-separated)` | Feature flag names (only asked if yes above) |
| `Set '<profile id>' as active profile?` | `y` |

### Full parameter example

Provide everything on the command line to skip the prompts:

```bash
factl profile set bs \
  --com-workspace-id 12345678-1234-1234-1234-123456789abc \
  --display-name "Bruno Star" \
  --force-disable-schedules \
  --activate \
  --auth-mode default \
  --git-connection-id 11111111-1111-1111-1111-111111111111 \
  --git-connection-type ado \
  --meta-database-host c4s53.example.database.fabric.microsoft.com \
  --meta-database-name DB_META \
  --enabled-feature enable_experimental_features,enable_bulk_publish
```

This creates `~/.factl/profiles.yaml` and sets the profile as active (if `--activate` is used). Verify:

```bash
factl profile current
```

## Step 3: Prepare your Fabric items

You have two ways to create Fabric items:

- **Create locally** — add Notebooks, Environments, Spark Job Definitions, etc. under `fabric/com/` in your repo, commit to Git, then deploy.
- **Create in the workspace** — build items in your common workspace via the Fabric UI, then sync back to Git:

  ```bash
  factl self push <branch> --comment "Created new notebook"
  ```

  This commits workspace items to your branch under `fabric/com/`.

Create parameter files for environment-specific replacement of IDs (workspace IDs, Lakehouse IDs, etc.). See the [fabric-cicd parameter file documentation](https://microsoft.github.io/fabric-cicd) for the format. Parameter file paths are configured via `deployment.common.parameter_path` and `deployment.orchestration.parameter_path` in `project.yaml`.

## Step 4: Deploy to your personal common workspace

Deploy common items first:

```bash
factl self deploy com
```

Deploy control assets (creates the control Lakehouse if needed):

```bash
factl self deploy ctl --auto-create
```

Deploy orchestration (compiles workflows and deploys processors):

```bash
factl self deploy orc
```

## Step 5: Verify in Fabric

Open your personal workspace in the [Fabric portal](https://app.fabric.microsoft.com).

You should see:

* Items from `fabric/com/` deployed in the workspace
* A `controls` folder in your control Lakehouse (`LH_CTL`) with control assets
* Compiled DataPipelines under the `workflows/` folder
* Processor items (Notebooks, DataPipelines) under the `processors/` folder
* Data Lakehouses (e.g., `LH_DP`) referenced by processors may live in a separate data workspace — they are wired to the common workspace through parameter files

## Step 6: Deploy to a shared common workspace

Once your changes work in your personal workspace, deploy to a shared environment:

```bash
factl dev deploy com
factl dev deploy orc
factl dev deploy ctl
```

This uses the workspace IDs and settings from `.config/.factl/targets.yaml`.

## Next steps

* [Architecture](architecture.md) — understand how the framework compiles and deploys workflows
* [Configuration](configuration.md) — detailed reference for all config files
* [Workflows](workflows.md) — learn the workflow YAML format
* [Deployment](deployment.md) — understand personal vs shared deploys and Git integration
