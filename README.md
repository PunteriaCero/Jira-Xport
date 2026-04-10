# jira-xport

Export all tickets from a Jira filter to a CSV file.

The first three columns are always **EpicKey**, **IssueKey**, and **Sub-Key**, which map the 3-level hierarchy (Epic → Issue → Sub-task). The remaining columns follow the filter's configured column layout in Jira. Time-tracking fields (e.g. time spent, original estimate) are automatically converted from seconds to hours.

---

## Run with GitHub Actions (this repo)

The easiest way to use this tool is through the included workflow. Go to **Actions → Export Jira Filter → Run workflow** and fill in the parameters:

| Input | Description | Required |
|---|---|---|
| `jira_url` | Jira instance URL (e.g. `https://yourorg.atlassian.net`) | Yes |
| `jira_email` | Jira user email address | Yes |
| `jira_api_token` | Jira [API token](https://id.atlassian.com/manage-profile/security/api-tokens) | Yes |
| `filter_id` | Jira filter ID (numeric) | Yes |
| `include_subtasks` | `true` to fetch and append subtasks | No |
| `subtasks_labels` | Comma-separated labels to restrict which subtasks are included | No |
| `output` | Custom output filename (leave empty for auto-generated) | No |

The CSV is uploaded as an artifact named `jira-export-<filter_id>` and kept for **1 day**. Only the latest run is retained — previous runs are deleted automatically on each execution.

---

## Sample output

```
EpicKey,IssueKey,Sub-Key,Type,Summary,Status,Assignee,Original Estimate,Time Spent
DEMO-100,DEMO-201,,Story,Build login page,In Progress,Alice Smith,8,3.5
DEMO-100,DEMO-202,,Story,Integrate payment gateway,Done,Bob Jones,5,5
DEMO-100,,DEMO-301,Sub-task,Write unit tests for login,Done,Alice Smith,2,1.5
DEMO-100,,DEMO-302,Sub-task,Fix redirect after login,In Review,Carol White,1,0.5
DEMO-105,DEMO-210,,Task,Update API documentation,To Do,,,
```

- **EpicKey** — key of the Epic the issue belongs to (empty if the issue is an Epic itself)
- **IssueKey** — key of the Story/Task/Bug (empty for Epics and Sub-tasks)
- **Sub-Key** — key of the Sub-task (empty for Epics and Stories)
- Time columns (e.g. `Σ Estimación original`, `Σ Tiempo empleado`) are in **hours**

---

## Use as a GitHub Action in another repo

```yaml
jobs:
  export:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - id: export
        uses: PunteriaCero/jira-xport@v1
        with:
          filter_id: '12345'
          jira_url: ${{ secrets.JIRA_URL }}
          jira_email: ${{ secrets.JIRA_EMAIL }}
          jira_api_token: ${{ secrets.JIRA_API_TOKEN }}
          include_subtasks: 'true'
          subtasks_labels: 'backend,urgent'   # omit to include all subtasks

      - uses: actions/upload-artifact@v4
        with:
          name: jira-export
          path: ${{ steps.export.outputs.csv_path }}
```

---

## Run locally with Docker

```bash
# Build
docker build -t jira-xport .

# Export filter 12345 (credentials in .env — copy from .env.example)
docker run --rm --env-file .env -v $(pwd)/output:/app/output jira-xport 12345

# Include all subtasks
docker run --rm --env-file .env -v $(pwd)/output:/app/output jira-xport 12345 --subtasks

# Include only subtasks with specific labels
docker run --rm --env-file .env -v $(pwd)/output:/app/output jira-xport 12345 --subtasks "backend,urgent"
```
