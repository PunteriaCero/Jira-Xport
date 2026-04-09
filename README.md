# jira-xport

Export all tickets from a Jira filter to a CSV file.

Columns are taken directly from the filter's configured columns in Jira. A **Parent Key** column is always included as the first column. Optionally, subtasks of each issue can be fetched and appended to the output, with optional label filtering.

---

## Requirements

- Docker
- A Jira Cloud account with an [API token](https://id.atlassian.com/manage-profile/security/api-tokens)

---

## Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```env
JIRA_URL=https://yourorg.atlassian.net
JIRA_EMAIL=your@email.com
JIRA_API_TOKEN=your_api_token
```

---

## Usage

### Docker

```bash
# Build
docker build -t jira-xport .

# Export filter 12345
docker run --rm --env-file .env -v $(pwd)/output:/app/output jira-xport 12345

# Include all subtasks
docker run --rm --env-file .env -v $(pwd)/output:/app/output jira-xport 12345 --subtasks

# Include only subtasks that have at least one of the given labels
docker run --rm --env-file .env -v $(pwd)/output:/app/output jira-xport 12345 --subtasks "backend,urgent"

# Custom output filename
docker run --rm --env-file .env -v $(pwd)/output:/app/output jira-xport 12345 -o /app/output/my_export.csv
```

### Docker Compose

```bash
docker compose run --rm jira-xport 12345
```

---

## Parameters

| Parameter | Description | Required | Default |
|---|---|---|---|
| `filter_id` | Jira filter ID (numeric, positional) | Yes | — |
| `-o / --output` | Output CSV file path | No | `output/jira_filter_<id>_<timestamp>.csv` |
| `--subtasks [LABELS]` | Include subtasks. Optionally provide comma-separated labels to restrict which subtasks are included. | No | — |

---

## GitHub Actions

Add `jira-xport` to any workflow to export a Jira filter and upload the CSV as an artifact.

### Basic example

```yaml
jobs:
  export:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Export Jira filter
        uses: your-org/jira-xport@v1
        with:
          filter_id: '12345'
          jira_url: ${{ secrets.JIRA_URL }}
          jira_email: ${{ secrets.JIRA_EMAIL }}
          jira_api_token: ${{ secrets.JIRA_API_TOKEN }}

      - name: Upload CSV
        uses: actions/upload-artifact@v4
        with:
          name: jira-export
          path: output/
```

### With subtasks

```yaml
      - name: Export Jira filter with subtasks
        uses: your-org/jira-xport@v1
        with:
          filter_id: '12345'
          jira_url: ${{ secrets.JIRA_URL }}
          jira_email: ${{ secrets.JIRA_EMAIL }}
          jira_api_token: ${{ secrets.JIRA_API_TOKEN }}
          include_subtasks: 'true'
          subtasks_labels: 'backend,urgent'   # omit to include all subtasks
```

### Action inputs

| Input | Description | Required | Default |
|---|---|---|---|
| `filter_id` | Jira filter ID (numeric) | Yes | — |
| `jira_url` | Jira instance URL | Yes | — |
| `jira_email` | Jira user email | Yes | — |
| `jira_api_token` | Jira API token | Yes | — |
| `output` | Output CSV filename (placed in `output/`) | No | auto-generated |
| `include_subtasks` | `"true"` to include subtasks | No | `"false"` |
| `subtasks_labels` | Comma-separated labels to filter subtasks | No | _(all subtasks)_ |

### Action outputs

| Output | Description |
|---|---|
| `output_dir` | Path to the directory containing the generated CSV file |

---

## Output

The CSV is written to the `output/` folder. The filename defaults to `jira_filter_<filter_id>_<timestamp>.csv`.

When a filter has no custom column configuration, only the **Key** field is exported and a warning is printed to the console.
