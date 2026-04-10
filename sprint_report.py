#!/usr/bin/env python3
"""
Generate a sprint productivity report from a Jira filter.

For each sprint, aggregates delivered (Done) issues and calculates:
  - Story points delivered
  - Hours spent
  - Productivity = SP / hours × 100

Outputs a CSV and a PNG chart.
"""

import argparse
import csv
import os
import sys
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # non-interactive backend — must be set before importing pyplot
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from dotenv import load_dotenv
from jira import JIRA
from jira.exceptions import JIRAError

load_dotenv()

JIRA_URL = os.getenv("JIRA_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")

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
        sys.exit(1)
    try:
        client = JIRA(server=JIRA_URL, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))
        client.myself()
        print(f"[OK] Connected to {JIRA_URL}")
        return client
    except JIRAError as e:
        print(f"[ERROR] Could not connect to Jira: {e.text}")
        sys.exit(1)


def get_field_map(client: JIRA) -> dict:
    url = f"{client._options['server']}/rest/api/3/field"
    try:
        r = client._session.get(url, headers={"Accept": "application/json"})
        if r.status_code == 200:
            return {f["id"]: f for f in r.json()}
    except Exception as e:
        print(f"[WARN] Could not fetch field metadata: {e}")
    return {}


def detect_sprint_field(field_map: dict) -> str | None:
    for fid, f in field_map.items():
        if "sprint" in f.get("schema", {}).get("custom", "").lower():
            print(f"[INFO] Sprint field: {fid} ({f.get('name')})")
            return fid
    return None


def detect_story_points_field(field_map: dict) -> str | None:
    # 1. Exact name match "story points" — most reliable, catches cf_10004 and cf_10016
    for fid, f in field_map.items():
        if f.get("name", "").lower() == "story points":
            print(f"[INFO] Story points field: {fid} ({f.get('name')})")
            return fid
    # 2. Schema custom type contains story_points / storypoints (underscore variants)
    for fid, f in field_map.items():
        custom = f.get("schema", {}).get("custom", "").lower()
        if any(kw in custom for kw in ("story_points", "storypoints")):
            print(f"[INFO] Story points field (by schema): {fid} ({f.get('name')})")
            return fid
    # 3. Schema custom contains story-points (hyphen, e.g. jsw-story-points)
    for fid, f in field_map.items():
        custom = f.get("schema", {}).get("custom", "").lower()
        if "story-points" in custom:
            print(f"[INFO] Story points field (by schema): {fid} ({f.get('name')})")
            return fid
    # 4. Name contains both "story" and "point"
    for fid, f in field_map.items():
        name = f.get("name", "").lower()
        if "story" in name and "point" in name:
            print(f"[INFO] Story points field (by name): {fid} ({f.get('name')})")
            return fid
    return None


def paginate_jql(client: JIRA, jql: str, fields: list[str]) -> list:
    issues = []
    next_page_token = None
    url = f"{client._options['server']}/rest/api/3/search/jql"
    while True:
        payload: dict = {"jql": jql, "maxResults": PAGE_SIZE, "fields": fields}
        if next_page_token:
            payload["nextPageToken"] = next_page_token
        try:
            r = client._session.post(
                url,
                json=payload,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
            r.raise_for_status()
        except Exception as e:
            print(f"[ERROR] Jira request failed: {e}")
            sys.exit(1)
        data = r.json()
        batch = data.get("issues", [])
        if not batch:
            break
        issues.extend(batch)
        if data.get("isLast", True) or not data.get("nextPageToken"):
            break
        next_page_token = data["nextPageToken"]
    return issues


def get_last_sprint(sprint_value) -> tuple[int, str] | None:
    """Return (sprint_id, sprint_name) using the last sprint in the field array."""
    if not sprint_value:
        return None
    sprint = sprint_value[-1] if isinstance(sprint_value, list) else sprint_value
    if isinstance(sprint, dict):
        sid = sprint.get("id", 0)
        name = sprint.get("name", f"Sprint {sid}")
        return int(sid), name
    return None


def aggregate_by_sprint(
    issues: list, sprint_field: str, sp_field: str
) -> dict[int, dict]:
    """
    Group done issues by their last sprint.
    Returns {sprint_id: {"name": str, "sp": float, "hours": float}}
    """
    data: dict[int, dict] = {}
    for issue in issues:
        fields = issue.get("fields", {})

        # Only count delivered issues
        status_key = (
            fields.get("status", {}).get("statusCategory", {}).get("key", "")
        )
        if status_key != "done":
            continue

        sprint_info = get_last_sprint(fields.get(sprint_field))
        if not sprint_info:
            continue
        sid, sname = sprint_info

        sp = 0.0
        try:
            sp = float(fields.get(sp_field) or 0)
        except (TypeError, ValueError):
            pass

        # Use aggregate time (includes time logged on subtasks)
        hours = (fields.get("aggregatetimespent") or fields.get("timespent") or 0) / 3600

        if sid not in data:
            data[sid] = {"name": sname, "sp": 0.0, "hours": 0.0}
        data[sid]["sp"] += sp
        data[sid]["hours"] += hours

    return data


def write_csv(rows: list[dict], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fieldnames = ["Sprint", "Story Points", "Hours Spent", "Productivity (SP/h×100)"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[OK] CSV   → {path}")


def write_chart(rows: list[dict], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    labels = [r["Sprint"] for r in rows]
    sp = [r["Story Points"] for r in rows]
    hours = [r["Hours Spent"] for r in rows]
    productivity = [r["Productivity (SP/h×100)"] for r in rows]
    x = list(range(len(labels)))

    fig, ax1 = plt.subplots(figsize=(max(10, len(labels) * 1.4), 6))

    # Secondary Y axis — Hours (bars, drawn first so lines render on top)
    ax2 = ax1.twinx()
    ax2.bar(x, hours, width=0.55, alpha=0.40, color="steelblue", zorder=2)
    ax2.set_ylabel("Hours Spent", color="steelblue", fontsize=11)
    ax2.tick_params(axis="y", labelcolor="steelblue")
    ax2.set_ylim(bottom=0)

    # Primary Y axis — SP line + Productivity line (drawn on top)
    ax1.set_zorder(ax2.get_zorder() + 1)
    ax1.patch.set_visible(False)  # transparent background so bars show through

    line_sp, = ax1.plot(
        x, sp, "o-", color="seagreen", linewidth=2.5, markersize=7,
        label="Story Points Delivered", zorder=3,
    )
    line_prod, = ax1.plot(
        x, productivity, "s--", color="tomato", linewidth=2, markersize=6,
        label="Productivity (SP/h×100)", zorder=3,
    )
    ax1.set_ylabel("Story Points / Productivity", fontsize=11)
    ax1.set_xlabel("Sprint", fontsize=11)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
    ax1.set_ylim(bottom=0)

    # Combined legend
    bar_handle = Patch(facecolor="steelblue", alpha=0.55, label="Hours Spent")
    ax1.legend(handles=[bar_handle, line_sp, line_prod], loc="upper left", fontsize=9)

    plt.title("Sprint Productivity Report", fontsize=13, pad=12)
    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[OK] Chart → {path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a sprint productivity report (CSV + chart) from a Jira filter."
    )
    parser.add_argument("filter_id", help="Jira filter ID (numeric)")
    parser.add_argument(
        "--sprint-field", default=None, metavar="FIELD_ID",
        help="Sprint custom field ID (auto-detected if omitted)",
    )
    parser.add_argument(
        "--sp-field", default=None, metavar="FIELD_ID",
        help="Story points custom field ID (auto-detected if omitted)",
    )
    parser.add_argument(
        "-o", "--output", default=None, metavar="DIR",
        help="Output directory (default: output/)",
    )
    args = parser.parse_args()

    if not args.filter_id.isdigit():
        print(f"[ERROR] filter_id must be numeric, got: {args.filter_id!r}")
        sys.exit(1)

    client = connect_jira()
    field_map = get_field_map(client)

    sprint_field = args.sprint_field or detect_sprint_field(field_map)
    if not sprint_field:
        print("[ERROR] Sprint field not detected. Use --sprint-field FIELD_ID to specify it.")
        sys.exit(1)

    sp_field = args.sp_field or detect_story_points_field(field_map)
    if not sp_field:
        print("[ERROR] Story points field not detected. Use --sp-field FIELD_ID to specify it.")
        sys.exit(1)

    print(f"[INFO] Fetching issues for filter {args.filter_id}...")
    issues = paginate_jql(
        client,
        f"filter={args.filter_id}",
        [sprint_field, sp_field, "timespent", "aggregatetimespent", "status"],
    )
    print(f"[INFO] Retrieved {len(issues)} issue(s).")

    if not issues:
        print("[WARN] No issues found.")
        sys.exit(0)

    sprint_data = aggregate_by_sprint(issues, sprint_field, sp_field)

    if not sprint_data:
        print("[WARN] No delivered issues with sprint data found.")
        sys.exit(0)

    # Sort by sprint ID (chronological order)
    rows = []
    for _, d in sorted(sprint_data.items()):
        sp_val = round(d["sp"], 1)
        hours_val = round(d["hours"], 2)
        prod = round(sp_val / hours_val * 100, 2) if hours_val > 0 else 0.0
        rows.append({
            "Sprint": d["name"],
            "Story Points": sp_val,
            "Hours Spent": hours_val,
            "Productivity (SP/h×100)": prod,
        })

    output_dir = args.output or os.getenv("OUTPUT_DIR", "output")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"sprint_report_{args.filter_id}_{ts}"
    csv_path = os.path.join(output_dir, f"{base}.csv")
    chart_path = os.path.join(output_dir, f"{base}.png")

    write_csv(rows, csv_path)
    write_chart(rows, chart_path)

    # Write GitHub Actions outputs if running in a workflow
    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.write(f"csv_path={csv_path}\n")
            fh.write(f"chart_path={chart_path}\n")


if __name__ == "__main__":
    main()
