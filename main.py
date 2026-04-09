import argparse
import csv
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from jira import JIRA
from jira.exceptions import JIRAError

load_dotenv()

JIRA_URL = os.getenv("JIRA_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")

# Used when the filter has no custom column configuration
DEFAULT_FIELD_IDS = [
    "issuekey",
    "summary",
    "status",
    "issuetype",
    "priority",
    "assignee",
    "reporter",
    "created",
    "updated",
    "labels",
    "components",
    "fixVersions",
    "description",
]

DEFAULT_HEADERS = [
    "Key",
    "Summary",
    "Status",
    "Type",
    "Priority",
    "Assignee",
    "Reporter",
    "Created",
    "Updated",
    "Labels",
    "Components",
    "Fix Versions",
    "Description",
]

# Fields treated as plain date strings (truncate to YYYY-MM-DD)
DATE_FIELDS = {"created", "updated", "duedate", "resolutiondate"}

PAGE_SIZE = 100


def connect_jira() -> JIRA:
    missing = [
        name
        for name, val in [
            ("JIRA_URL", JIRA_URL),
            ("JIRA_EMAIL", JIRA_EMAIL),
            ("JIRA_API_TOKEN", JIRA_API_TOKEN),
        ]
        if not val
    ]
    if missing:
        print(f"[ERROR] Missing environment variables: {', '.join(missing)}")
        print("        Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)

    try:
        client = JIRA(server=JIRA_URL, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))
        client.myself()  # validate credentials
        print(f"[OK] Connected to {JIRA_URL}")
        return client
    except JIRAError as e:
        print(f"[ERROR] Could not connect to Jira: {e.text}")
        sys.exit(1)


def get_filter_columns(client: JIRA, filter_id: str) -> list[dict] | None:
    """
    Calls GET /rest/api/3/filter/{id}/columns and returns the column list.
    Each item: {"label": str, "value": str}  (value = Jira field ID).
    Returns None when the filter has no custom column configuration.
    """
    try:
        columns = client._get_json(f"filter/{filter_id}/columns")
        if columns:
            print(f"[INFO] Filter has {len(columns)} custom column(s).")
            return columns
        print("[INFO] Filter has no custom column configuration — using defaults.")
        return None
    except JIRAError as e:
        print(f"[WARN] Could not retrieve filter columns ({e.status_code}): using defaults.")
        return None


def _extract(field_id: str, issue) -> str:
    """Dynamically extract a field value from a Jira issue by field ID."""
    if field_id == "issuekey":
        return issue.key

    value = getattr(issue.fields, field_id, None)
    if value is None:
        return ""

    # List fields (labels → list[str], components/fixVersions → list[obj])
    if isinstance(value, list):
        return "; ".join(str(getattr(item, "name", item)) for item in value)

    # Date fields
    if field_id in DATE_FIELDS:
        return str(value)[:10]

    # Object fields: prefer displayName, then name, then value
    for attr in ("displayName", "name", "value"):
        candidate = getattr(value, attr, None)
        if candidate is not None:
            return str(candidate)

    # Plain string / fallback
    return str(value).replace("\n", " ").replace("\r", "")


def get_issues_from_filter(client: JIRA, filter_id: str, fields: list[str]) -> list:
    jql = f"filter={filter_id}"
    issues = []
    start = 0

    print(f"[INFO] Fetching issues for filter ID {filter_id}...")

    while True:
        try:
            batch = client.search_issues(
                jql,
                startAt=start,
                maxResults=PAGE_SIZE,
                fields=",".join(fields),
            )
        except JIRAError as e:
            print(f"[ERROR] Failed to fetch issues: {e.text}")
            sys.exit(1)

        if not batch:
            break

        issues.extend(batch)
        total = batch.total
        print(f"[INFO] Retrieved {len(issues)} / {total} issues...")

        if len(batch) < PAGE_SIZE:
            break

        start += PAGE_SIZE

    return issues


def export_to_csv(
    issues: list,
    headers: list[str],
    field_ids: list[str],
    output_path: str,
) -> None:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        for issue in issues:
            writer.writerow([_extract(fid, issue) for fid in field_ids])

    print(f"[OK] Exported {len(issues)} issues → {output_path}")


def build_output_path(filter_id: str, output_arg: str | None) -> str:
    if output_arg:
        return output_arg
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.getenv("OUTPUT_DIR", "output")
    return os.path.join(output_dir, f"jira_filter_{filter_id}_{timestamp}.csv")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export all tickets from a Jira filter to CSV."
    )
    parser.add_argument("filter_id", help="Jira filter ID (numeric)")
    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        default=None,
        help="Output CSV file path (default: output/jira_filter_<id>_<timestamp>.csv)",
    )
    args = parser.parse_args()

    if not args.filter_id.isdigit():
        print(f"[ERROR] filter_id must be a numeric value, got: {args.filter_id!r}")
        sys.exit(1)

    client = connect_jira()

    # Resolve columns: use filter's custom config, or fall back to defaults
    columns = get_filter_columns(client, args.filter_id)
    if columns:
        field_ids = [col["value"] for col in columns]
        headers = [col["label"] for col in columns]
    else:
        field_ids = DEFAULT_FIELD_IDS
        headers = DEFAULT_HEADERS

    # "issuekey" is always returned by the API; don't request it as a field
    fields_to_fetch = [fid for fid in field_ids if fid != "issuekey"]

    issues = get_issues_from_filter(client, args.filter_id, fields_to_fetch)

    if not issues:
        print("[WARN] No issues found for the given filter.")
        sys.exit(0)

    output_path = build_output_path(args.filter_id, args.output)
    export_to_csv(issues, headers, field_ids, output_path)


if __name__ == "__main__":
    main()
