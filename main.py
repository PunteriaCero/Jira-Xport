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

FIELDS = [
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

CSV_HEADERS = [
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


def get_issues_from_filter(client: JIRA, filter_id: str) -> list:
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
                fields=",".join(FIELDS),
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


def _extract(value) -> str:
    """Convert a Jira field value to a plain string."""
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(str(getattr(item, "name", item)) for item in value)
    return str(getattr(value, "name", value))


def issue_to_row(issue) -> list:
    f = issue.fields
    return [
        issue.key,
        getattr(f, "summary", "") or "",
        _extract(f.status),
        _extract(f.issuetype),
        _extract(f.priority),
        _extract(f.assignee),
        _extract(f.reporter),
        (f.created or "")[:10],
        (f.updated or "")[:10],
        _extract(f.labels),
        _extract(f.components),
        _extract(f.fixVersions),
        (getattr(f, "description", "") or "").replace("\n", " ").replace("\r", ""),
    ]


def export_to_csv(issues: list, output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADERS)
        for issue in issues:
            writer.writerow(issue_to_row(issue))

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
    issues = get_issues_from_filter(client, args.filter_id)

    if not issues:
        print("[WARN] No issues found for the given filter.")
        sys.exit(0)

    output_path = build_output_path(args.filter_id, args.output)
    export_to_csv(issues, output_path)


if __name__ == "__main__":
    main()
