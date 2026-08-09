# Workflows

How to author workflow definitions in YAML.

## Workflow file structure

Workflow definitions live under the path configured by `deployment.control.local_path` and `deployment.orchestration.workflow.control_folder` in `project.yaml` (e.g. `controls/workflows`). Each file can contain one or more workflows under the top-level `workflows` key:

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

## Fields

### Workflow

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Display name in Fabric (shown in workspace) |
| `description` | No | Description shown in Fabric |
| `schedules` | No | List of schedule definitions |
| `processors` | Yes | List of processor references |
| `params` | No | Workflow-level parameters (become top-level DataPipeline parameters) |

### Schedule

Schedules are defined with a 5-field cron expression. The framework auto-converts it to the appropriate Fabric-native schedule at deploy time.

| Field | Required | Description |
|---|---|---|
| `enabled` | Yes | Whether the schedule is active (`true`/`false`) |
| `cron_expression` | Yes | 5-field cron expression (`minute hour day month dow`) |
| `start_datetime` | No | ISO 8601 start datetime (default: `2025-01-01T00:00:00Z`) |
| `end_datetime` | No | ISO 8601 end datetime (default: `2099-12-31T00:00:00Z`) |
| `local_time_zone_id` | No | Timezone ID (default: `Eastern Standard Time`) |

`start_datetime` must be earlier than `end_datetime`. Multi-entry cron expansions (e.g. monthly on the 1st and 15th) result in multiple schedule entries automatically.

Schedules are converted to Fabric-compatible schedule JSON during orchestration deployment. The `force_disable_schedules` setting in profiles or targets can override the `enabled` field.

### Cron expressions

All schedules use a standard 5-field cron expression via `cron_expression`. The framework auto-converts it to the appropriate Fabric-native schedule type at deploy time:

```yaml
schedules:
  - enabled: true
    cron_expression: "0 6 * * 1,3,5"     # Mon, Wed, Fri at 06:00
```

Supported conversions:

| Cron example | Fabric type |
|---|---|
| `*/15 * * * *` | `Cron` interval 15 minutes |
| `0 * * * *` | `Cron` interval 60 minutes (hourly) |
| `0 */2 * * *` | `Cron` interval 120 minutes (every 2 hours) |
| `0 6,18 * * *` | `Daily` at 06:00 and 18:00 |
| `0 9 * * 1-5` | `Weekly` Mon–Fri at 09:00 |
| `0 9 * * MON,FRI` | `Weekly` Monday and Friday |
| `0 10 15 * *` | `Monthly` day 15 at 10:00 |
| `0 10 1,15 * *` | `Monthly` days 1 and 15 (two schedule entries) |
| `0 10 15 */2 *` | `Monthly` day 15 every 2 months |
| `0 9 * * 1#1` | `Monthly` first Monday at 09:00 |
| `@daily` | `Daily` at midnight |
| `@hourly` | `Cron` interval 60 minutes |

Cron expressions that cannot be mapped to a Fabric schedule produce a clear error: expressions that are not exactly 5 fields, `L`/`W` markers, month-restricted patterns, day-of-month + day-of-week OR semantics, and arbitrary month selections (Fabric can only express "every N months" starting from month one).

### Processor

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Name of the Fabric item (Notebook or DataPipeline) |
| `alias` | Yes | Unique alias within this workflow, used for dependency references |
| `depends_on` | No | List of processor aliases this processor depends on |
| `params` | No | Key-value parameters passed to the processor |

### Params

Each param has a `value` and optional `type`:

```yaml
params:
  env:
    value: "{{ env_name }}"
    type: "string"
  max_retries:
    value: 3
    type: "int"
  source_table:
    value: "dbo.orders"
    type: "string"
```

| Field | Required | Description |
|---|---|---|
| `value` | Yes | Parameter value (can use Jinja2 expressions) |
| `type` | No | Parameter type: `string`, `int`, `float`, `bool`, `array`, `object`, `SecureString`, or `Expression` |

Type `Expression` is for ADF pipeline expressions like `@pipeline().TriggerTime`. Values starting with `@` are automatically treated as `Expression` type.

## Dependencies

Dependencies define the execution order of processors within a workflow. factl builds a directed acyclic graph (DAG) and validates it at parse time — cycles are caught as errors before deployment.

In this example, `ingest_tlc` and `ingest_weather` run in parallel (no dependencies on each other), and `run_dbt` runs after both complete:

```yaml
processors:
  - name: "NB_IngestTlcTripsToBronze"
    alias: "ingest_tlc"
    depends_on: []
  - name: "NB_IngestNoaaWeatherToBronze"
    alias: "ingest_weather"
    depends_on: []
  - name: "NB_RunDbtTaxiWeather"
    alias: "run_dbt"
    depends_on:
      - "ingest_tlc"
      - "ingest_weather"
```

## Jinja2 templating

Workflow YAML is rendered with Jinja2 before compilation. Variables from `.config/.factl/variables.yaml` are available as template variables.

```yaml
params:
  env:
    value: "{{ env_name }}"
    type: "string"
```

With `variables.yaml`:

```yaml
targets:
  dev:
    env_name: dev
```

The rendered value becomes `"dev"`.

Use the `tojson` filter for string values to ensure proper JSON escaping. For numeric values, use directly:

```yaml
params:
  retry_count:
    value: "{{ retry_count }}"
    type: "int"
```

## Processor reuse

A processor is a Fabric item (Notebook or DataPipeline) deployed once to the workspace folder configured by `deployment.orchestration.processor.workspace_folder` in `project.yaml` (e.g. `processors`). It can be referenced by name in any number of workflows with different aliases and parameters:

```yaml
# Workflow A
processors:
  - name: "NB_IngestToBronze"
    alias: "ingest_sales"
    params:
      table_name:
        value: "sales"
        type: "string"

# Workflow B
processors:
  - name: "NB_IngestToBronze"
    alias: "ingest_orders"
    params:
      table_name:
        value: "orders"
        type: "string"
```

The same processor handles different tables based on the workflow-level parameter. No notebook code changes needed.

## Schedule examples

### Every N minutes (Cron)

```yaml
schedules:
  - enabled: true
    cron_expression: "*/30 * * * *"          # Every 30 minutes
```

### Daily

```yaml
schedules:
  - enabled: true
    cron_expression: "0 6,18 * * *"         # 06:00 and 18:00 daily
```

### Weekly

```yaml
schedules:
  - enabled: true
    cron_expression: "0 8 * * 1,3,5"        # Mon, Wed, Fri at 08:00
```

### Monthly — day of month

```yaml
schedules:
  - enabled: true
    cron_expression: "0 2 15 * *"           # 15th of every month at 02:00
```

### Monthly — multiple days

Multi-day monthly cron expressions expand to multiple schedule entries automatically:

```yaml
schedules:
  - enabled: true
    cron_expression: "0 10 1,15 * *"        # 1st and 15th at 10:00
```

### Monthly — Nth weekday

```yaml
schedules:
  - enabled: true
    cron_expression: "0 9 * * 1#1"          # First Monday at 09:00
```

### Monthly — every N months

```yaml
schedules:
  - enabled: true
    cron_expression: "0 10 15 */3 *"        # 15th every 3 months at 10:00
```

## Validation

factl validates workflow YAML at parse time before any Fabric API calls:

* **DAG cycles:** Circular dependencies are rejected
* **Duplicate aliases:** Each alias must be unique within a workflow
* **Missing references:** All `depends_on` values must match a processor alias
* **Schema violations:** All fields are validated against Pydantic models
* **Reserved variable names:** User variables cannot use reserved names

## Deploying workflows

After authoring a workflow YAML file, deploy it with:

```bash
factl self deploy orc
```

This compiles the YAML into Fabric DataPipeline JSON and publishes it to your workspace. The workflow appears under the folder configured by `deployment.orchestration.workflow.workspace_folder` in `project.yaml` (e.g. `workflows`).

To deploy to a shared environment:

```bash
factl dev deploy orc
```
