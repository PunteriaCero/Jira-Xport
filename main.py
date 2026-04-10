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
    url = f"{client._options['server']}/rest/api/3/filter/{filter_id}/columns"
    try:
        response = client._session.get(url, headers={"Accept": "application/json"})
        if response.status_code == 200:
            columns = response.json()
            if columns:
                print(f"[INFO] Filter has {len(columns)} custom column(s).")
                return columns
            print("[INFO] Filter has no custom column configuration.")
            return None
        print(f"[WARN] Could not retrieve filter columns ({response.status_code}): no column config found.")
        return None
    except Exception as e:
        print(f"[WARN] Could not retrieve filter columns: {e}")
        return None


def _extract(field_id: str, issue: dict) -> str:
    """Dynamically extract a field value from a raw Jira API issue dict."""
    if field_id == "issuekey":
        return issue.get("key", "")

    if field_id == "parent":
        parent = issue.get("fields", {}).get("parent")
        return parent.get("key", "-") if parent else "-"

    value = issue.get("fields", {}).get(field_id)
    if value is None:
        return ""

    # List fields (labels → list[str], components/fixVersions → list[dict])
    if isinstance(value, list):
        parts = [
            item.get("name", str(item)) if isinstance(item, dict) else str(item)
            for item in value
        ]
        return "; ".join(parts)

    # Date fields
    if field_id in DATE_FIELDS:
        return str(value)[:10]

    # Object fields (dict): prefer displayName, then name, then value
    if isinstance(value, dict):
        for attr in ("displayName", "name", "value"):
            if attr in value:
                return str(value[attr])
        return str(value)

    # Plain string / number fallback
    return str(value).replace("\n", " ").replace("\r", "")


def _paginate_jql(client: JIRA, jql: str, fields_to_request: list[str]) -> list:
    """Fetches all issues matching a JQL query using cursor-based pagination."""
    issues = []
    next_page_token = None
    url = f"{client._options['server']}/rest/api/3/search/jql"

    while True:
        payload: dict = {"jql": jql, "maxResults": PAGE_SIZE}
        if fields_to_request:
            payload["fields"] = fields_to_request
        if next_page_token:
            payload["nextPageToken"] = next_page_token
        try:
            response = client._session.post(
                url,
                json=payload,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
            response.raise_for_status()
        except Exception as e:
            print(f"[ERROR] Failed to fetch issues: {e}")
            sys.exit(1)

        data = response.json()
        batch = data.get("issues", [])
        is_last = data.get("isLast", True)
        next_page_token = data.get("nextPageToken")

        if not batch:
            break

        issues.extend(batch)

        if is_last or not next_page_token:
            break

    return issues


def get_issues_from_filter(client: JIRA, filter_id: str, fields: list[str]) -> list:
    fields_to_request = [f for f in fields if f != "issuekey"]
    if "parent" not in fields_to_request:
        fields_to_request.append("parent")

    print(f"[INFO] Fetching issues for filter ID {filter_id}...")
    issues = _paginate_jql(client, f"filter={filter_id}", fields_to_request)
    print(f"[INFO] Retrieved {len(issues)} issue(s).")
    return issues


def fetch_subtasks(client: JIRA, parent_keys: list[str], labels: list[str], fields: list[str]) -> list:
    if not parent_keys:
        return []

    fields_to_request = [f for f in fields if f != "issuekey"]
    if "parent" not in fields_to_request:
        fields_to_request.append("parent")

    label_desc = f" with labels [{', '.join(labels)}]" if labels else ""
    print(f"[INFO] Fetching subtasks{label_desc}...")

    all_subtasks = []
    chunk_size = 50  # keep JQL length manageable
    for i in range(0, len(parent_keys), chunk_size):
        chunk = parent_keys[i:i + chunk_size]
        keys_jql = ", ".join(chunk)
        jql = f"parent in ({keys_jql})"
        if labels:
            labels_jql = ", ".join(f'"{lbl}"' for lbl in labels)
            jql += f" AND labels in ({labels_jql})"
        all_subtasks.extend(_paginate_jql(client, jql, fields_to_request))

    print(f"[INFO] Retrieved {len(all_subtasks)} subtask(s).")
    return all_subtasks


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
    parser.add_argument(
        "--subtasks",
        nargs="?",
        const="",
        default=None,
        metavar="LABELS",
        help=(
            "Include subtasks of each issue. Optionally provide a comma-separated list "
            "of labels to filter subtasks (e.g. --subtasks label1,label2). "
            "If no labels are given, all subtasks are included."
        ),
    )
    args = parser.parse_args()

    if not args.filter_id.isdigit():
        print(f"[ERROR] filter_id must be a numeric value, got: {args.filter_id!r}")
        sys.exit(1)

    client = connect_jira()

    # Resolve columns: use filter's custom config, or warn and export KEY only
    columns = get_filter_columns(client, args.filter_id)
    if columns:
        field_ids = [col["value"] for col in columns]
        headers = [col["label"] for col in columns]
    else:
        print(
            "[WARN] The filter has no column configuration. "
            "Only the 'Key' field will be written to the CSV."
        )
        field_ids = ["issuekey"]
        headers = ["Key"]

    # Parent Key column is always the first column regardless of filter configuration
    if "parent" in field_ids:
        idx = field_ids.index("parent")
        field_ids.insert(0, field_ids.pop(idx))
        headers.insert(0, headers.pop(idx))
    else:
        field_ids.insert(0, "parent")
        headers.insert(0, "Parent Key")

    issues = get_issues_from_filter(client, args.filter_id, field_ids)

    if args.subtasks is not None:
        labels = [lbl.strip() for lbl in args.subtasks.split(",") if lbl.strip()]
        parent_keys = [issue["key"] for issue in issues]
        subtasks = fetch_subtasks(client, parent_keys, labels, field_ids)
        existing_keys = {issue["key"] for issue in issues}
        issues.extend(s for s in subtasks if s["key"] not in existing_keys)

    if not issues:
        print("[WARN] No issues found for the given filter.")
        sys.exit(0)

    output_path = build_output_path(args.filter_id, args.output)
    export_to_csv(issues, headers, field_ids, output_path)


if __name__ == "__main__":
    main()
