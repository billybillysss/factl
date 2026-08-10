# factl

A CLI tool for deploying and orchestrating data pipelines in Microsoft Fabric using a declarative, Git-backed workflow model. Define pipelines as YAML, validate them locally, and deploy consistently to any environment — no UI clicking required.

## What is this?

factl is a **declarative data orchestration framework** for Microsoft Fabric. Instead of building pipelines by clicking through the Fabric UI, you define processors and workflows in YAML, version them in Git, and factl handles compilation, deployment, and scheduling. Orchestration runs in a common workspace; medallion Lakehouses and Warehouses live in separate data workspaces, connected through parameterized references.

### Core model: processors and workflows

factl separates your data platform into two layers:

**Processors** are reusable building blocks — Notebooks, DataPipelines, or any Fabric item type. You deploy each processor once, then reference it by name in any number of workflows. Per-workflow parameters control what it does with no processor code changes.

**Workflows** are YAML files that declare which processors run, in what order, on what schedule, and with what parameters. factl compiles the YAML into Fabric-native DataPipeline definitions and deploys them.

```
Processor items        Workflow YAML
(Notebooks,            (references processors
 DataPipelines,         by name with params
 custom types)          + schedule)

      │                      │
      │         ┌────────────▼──────────┐
      │         │   Framework Compiler  │
      │         └────────────┬──────────┘
      │                      │
      ▼                      ▼
┌──────────────────────────────────────┐
│          Common Workspace            │
│  (processors, workflows,            │
│   control Lakehouse,                 │
│   common items)                      │
│  ┌─────────────┐ ┌────────────────┐  │
│  │ processors  │ │   workflows    │  │
│  └─────────────┘ └────────────────┘  │
└────────────┬─────────────────────────┘
             │  workspace_id / lakehouse_id
             │  via params + parameter files
             ▼
┌──────────────────────────────────────┐
│          Data Workspace(s)            │
│  (medallion Lakehouses, Warehouses,   │
│   SQL databases — actual data)        │
│  ┌──────┐ ┌──────┐ ┌──────┐          │
│  │ LH_DP│ │ LH_DP│ │ LH_DP│          │
│  │ .brz │ │ .slv │ │ .gld │          │
│  └──────┘ └──────┘ └──────┘          │
└──────────────────────────────────────┘
```

**The problem it solves:** Fabric pipelines built through the UI have no single source of truth, drift between environments, and can't be reviewed or versioned. factl moves the orchestration layer — processors, workflows, control assets, common items, and metadata — into Git, where it can be versioned, reviewed, and deployed consistently. The data itself (Lakehouses, Warehouses, SQL databases) lives in separate data workspaces, accessed by processors through parameterized workspace and Lakehouse IDs.

**Where it fits:** factl sits between your Git repository and your Fabric workspaces. You write YAML, commit to Git, and factl handles the rest — compilation, parameterization, deployment, and schedule management. factl deploys orchestration (processors, workflows, common items) to a **common workspace**, while your data Lakehouses and Warehouses live in separate **data workspaces** — referenced by processors through configurable workspace and Lakehouse IDs.

**Who it's for:** Data engineers and platform teams building ELT/ETL pipelines in Microsoft Fabric who want repeatable, reviewable, and automated deployments.

## Why use it?

* **No framework to build from scratch.** factl provides a complete deployment and orchestration system — workflow compilation, parameter management, environment promotion, and schedule control are all built in.
* **Reusable processors with declarative parameters.** Processors (Notebooks, DataPipelines, or any Fabric item type with a custom template) are deployed once and composed into workflows by name. Each workflow configures the processor through `params` — the same processor behaves differently per workflow with no code changes.
* **Write once, deploy anywhere.** Environment differences (workspace IDs, Lakehouse IDs, connection strings) live in configuration files, not in pipeline code. The same workflow YAML deploys to dev, test, and prod.
* **Standardized pipeline development.** Every workflow follows the same declarative format. New team members can understand a pipeline by reading its YAML file.
* **Personal workspace isolation.** Each developer tests changes in their own Fabric workspace using `factl self` commands. Shared environments are never touched during development.
* **Data workspaces separate from orchestration.** Medallion Lakehouses, Warehouses, and SQL databases live in dedicated data workspaces — isolated from the common workspace where processors and workflows run. Processors reach data workspaces through parameterized workspace and Lakehouse IDs.
* **Fail early, fix locally.** Workflow YAML is validated at parse time — dependency cycles, missing references, and config errors are caught before anything touches Fabric.
* **Schedules managed declaratively.** Enable or disable schedules per environment. Schedule definitions live in the same YAML file as the workflow.

## Quick Start

### Prerequisites

* Python 3.10 or later
* A Microsoft Fabric capacity with at least one workspace
* Azure CLI authenticated with Fabric access (`az login`)

### 1. Install factl

```bash
git clone https://github.com/<your-org>/factl.git
cd factl
pip install -e .
```

### 2. Initialize repo configuration

```bash
factl config init
```

This creates three files under `.config/.factl/`:

* `project.yaml` — repository structure, deployment paths, item types
* `targets.yaml` — shared environment **common workspace** IDs (dev, test, prd)
* `variables.yaml` — per-environment variables available in workflow YAML

Edit these files to match your Fabric setup:

**`.config/.factl/targets.yaml`** — add your shared common workspace IDs:

```yaml
version: 1
personal_parameter_env: dev
targets:
  dev:
    com_workspace_id: <your-dev-workspace-guid>
    force_disable_schedules: false
    meta_database:
      host: <your-sql-endpoint>
      name: DB_META
  test:
    com_workspace_id: <your-test-workspace-guid>
    force_disable_schedules: true
  prd:
    com_workspace_id: <your-prod-workspace-guid>
    force_disable_schedules: false
```

**`.config/.factl/project.yaml`** — update at minimum:

* `project.repo_url` — your Git repository URL
* `deployment.common.parameter_path` — path to your fabric-cicd parameter file
* `deployment.common.control.lakehouse.name` — your control Lakehouse name

### 3. Create your developer profile

A profile links you to a personal common workspace for development and testing:

```bash
factl profile set bs \
  --com-workspace-id <your-personal-workspace-guid> \
  --display-name "Your Name"
```

This creates `~/.factl/profiles.yaml` and sets your profile as active.

### 4. Deploy control assets to your personal workspace

Control assets (dbt models, configuration files) are uploaded to the control Lakehouse in your workspace:

```bash
factl self deploy ctl --auto-create
```

Use `--auto-create` when the control Lakehouse does not exist yet.

### 5. Deploy common items and orchestration

Deploy common items:

```bash
factl self deploy com
```

This publishes all items from the directory configured by `deployment.common.local_path` in `project.yaml` to your personal workspace. Workspace and Lakehouse IDs are replaced via the parameter file configured by `deployment.common.parameter_path` in `project.yaml`.

Orchestration compiles your workflow YAML into Fabric DataPipelines and deploys them:

```bash
factl self deploy orc
```

### 6. Verify in Fabric

Open your personal workspace in the Fabric portal. You should see:

* Fabric items deployed to the workspace (from the directory configured by `deployment.common.local_path` in `project.yaml`)
* Control assets uploaded to the control Lakehouse (configured by `deployment.common.control.lakehouse.name` in `project.yaml`)
* Compiled DataPipelines under the folder configured by `deployment.orchestration.workflow.workspace_folder` in `project.yaml`
* Data Lakehouses referenced by processors may live in a separate data workspace, wired via parameter files

### Example workflow

Here's a complete workflow YAML (authored under the directory configured by `deployment.orchestration.workflow.control_folder` in `project.yaml`, relative to `deployment.control.local_path`):

```yaml
workflows:
  - name: "WF_NycTaxiWeatherDaily"
    description: "NYC taxi + NOAA weather medallion processing."
    schedules:
      - enabled: false
        cron_expression: "0 6 * * *"
    processors:
      - name: "NB_IngestTlcTripsToBronze"
        alias: "ingest_tlc"
        depends_on: []
        params:
          dataset_months:
            value: '["2024-01","2024-02"]'
            type: "string"
      - name: "NB_IngestNoaaWeatherToBronze"
        alias: "ingest_weather"
        depends_on: []
        params:
          env:
            value: "{{ env_name }}"
            type: "string"
      - name: "NB_RunDbtTaxiWeather"
        alias: "run_dbt"
        depends_on:
          - "ingest_tlc"
          - "ingest_weather"
        params:
          dbt_project_subpath:
            value: "controls/dbt"
            type: "string"
```

The workflow declares three processors (two ingests that run in parallel, followed by a dbt run), a daily schedule, and Jinja2 templating for environment-specific values.

The processors themselves (`NB_IngestTlcTripsToBronze`, `NB_IngestNoaaWeatherToBronze`, `NB_RunDbtTaxiWeather`) are Fabric items deployed once to the workspace folder configured by `deployment.orchestration.processor.workspace_folder` in `project.yaml`. They can be referenced by name in any workflow. For example, `NB_IngestNoaaWeatherToBronze` could appear in a different workflow with different `start_date` and `end_date` params — same processor, different behavior.

## How it works

```
┌──────────────┐     ┌──────────────┐     ┌───────────────────┐
│ Workflow YAML │ ──▶ │  Framework   │ ──▶ │ Fabric DataPipeline│
│ (under your   │     │  Compiler    │     │ JSON definitions   │
│  control dir) │     └──────────────┘     └───────────────────┘
└──────────────┘                                   │
                    ┌──────────────┐               │
                    │ fabric-cicd  │ ◀─────────────┘
                    │ publish      │
                    └──────────────┘
                           │
                    ┌──────▼──────┐     ┌──────────────────┐
                    │   Common    │     │  Data Workspace  │
                    │  Workspace  │ ──▶ │ (Lakehouses,     │
                    │ (processors,│     │  Warehouses,     │
                    │  workflows, │     │  SQL databases)  │
                    │  control LH)│     │                  │
                    └─────────────┘     └──────────────────┘
```

1. **Deploy processors.** Fabric items (Notebooks, DataPipelines, or items backed by custom templates) are deployed to the workspace folder configured by `deployment.orchestration.processor.workspace_folder` in `project.yaml`. Each processor is a reusable building block — deployed once, used by many workflows.
2. **Author workflows.** You write a workflow YAML file under the directory configured by `deployment.orchestration.workflow.control_folder` in `project.yaml` (relative to `deployment.control.local_path`) that references processors by name with per-workflow parameters, dependencies, and schedules. The same processor can appear in multiple workflows with different params.
3. **Compile.** `factl self deploy orc` loads the YAML, validates it with Pydantic, renders Jinja2 template variables, and compiles the workflow into Fabric DataPipeline JSON using built-in activity templates.
4. **Publish.** The compiled JSON is published to the common workspace via the fabric-cicd SDK. Parameters are environment-aware — your workspace gets the right workspace and Lakehouse IDs (for both the common and data workspaces) without changing the workflow definition.
5. **Schedule.** Schedule definitions from the YAML are converted to Fabric schedule JSON and deployed alongside the pipeline.

Four deployment types are supported:

| Command | What it deploys |
|---|---|
| `deploy com` / `deploy common` | Fabric items (Notebooks, Environments, Lakehouses, etc.) to common workspace |
| `deploy orc` / `deploy orchestration` | Compiled workflows + processor items to common workspace |
| `deploy ctl` / `deploy control` | Control assets (dbt models, configs) to the control Lakehouse in the common workspace |
| `deploy db` / `deploy database` | SQL scripts to metadata database |

## Documentation

* [Getting Started](docs/getting-started.md) — full setup walkthrough
* [Architecture](docs/architecture.md) — how the framework works
* [Configuration](docs/configuration.md) — all config files and settings
* [Workflows](docs/workflows.md) — authoring workflow YAML
* [Deployment](docs/deployment.md) — deploying to environments and CI/CD
* [CLI Commands](docs/cli-commands.md) — complete command reference
