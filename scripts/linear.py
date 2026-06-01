#!/usr/bin/env python3
"""
scripts/linear.py

General-purpose Linear API CLI for agents and developers when the Linear MCP is
unavailable. It uses the official Linear GraphQL API, discovers workspace IDs at
runtime, and never stores API keys. Credentials are read from env first, with an
optional OpenMates Vault fallback through the local `api` Docker container.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx


API_URL = "https://api.linear.app/graphql"
DEFAULT_TEAM_KEY = "OPE"
DEFAULT_LIMIT = 25
REQUEST_TIMEOUT_SECONDS = 20
CREDENTIAL_SOURCES = ("auto", "env", "openmates-vault")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
LINEAR_VAULT_KEYS = (
    "api_key",
    "linear_api_key",
    "access_token",
    "token",
)
credential_source = "auto"
PRIORITY_NAMES = {
    0: "No priority",
    1: "Urgent",
    2: "High",
    3: "Medium",
    4: "Low",
}


class LinearError(RuntimeError):
    """Raised when Linear returns an error or the request cannot be completed."""


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@lru_cache(maxsize=None)
def get_openmates_vault_provider(provider: str) -> dict[str, str]:
    code = f"""
import asyncio, json
from backend.core.api.app.utils.secrets_manager import SecretsManager

async def main():
    manager = SecretsManager()
    await manager.initialize()
    secrets = await manager.get_secrets_from_path('kv/data/providers/{provider}')
    print(json.dumps(secrets or {{}}))

asyncio.run(main())
"""
    try:
        result = subprocess.run(
            ["docker", "exec", "api", "python", "-c", code],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise LinearError("OpenMates Vault fallback requires Docker to be installed and available.") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or "docker exec api failed"
        raise LinearError(f"OpenMates Vault fallback failed for provider '{provider}': {detail}") from exc
    return json.loads(result.stdout or "{}")


def get_api_key() -> str:
    api_key = None if credential_source == "openmates-vault" else os.environ.get("LINEAR_API_KEY")
    if api_key:
        return api_key

    if credential_source != "env":
        linear_secrets = get_openmates_vault_provider("linear")
        for key in LINEAR_VAULT_KEYS:
            api_key = linear_secrets.get(key)
            if api_key:
                return api_key

    if credential_source == "auto":
        keys = ", ".join(LINEAR_VAULT_KEYS)
        raise LinearError(f"Missing LINEAR_API_KEY; OpenMates Vault provider 'linear' also did not provide one of: {keys}.")
    if credential_source == "openmates-vault":
        keys = ", ".join(LINEAR_VAULT_KEYS)
        raise LinearError(f"OpenMates Vault provider 'linear' did not provide one of: {keys}.")
    raise LinearError("Missing LINEAR_API_KEY. Export it before running this script.")


def graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        response = httpx.post(
            API_URL,
            json={"query": query, "variables": variables or {}},
            headers={"Authorization": get_api_key(), "Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LinearError(f"Linear API HTTP {exc.response.status_code}: {exc.response.text}") from exc
    except httpx.HTTPError as exc:
        raise LinearError(f"Linear API request failed: {exc}") from exc

    payload = response.json()
    if payload.get("errors"):
        message = payload["errors"][0].get("message", payload["errors"])
        raise LinearError(f"Linear API error: {message}")
    return payload.get("data") or {}


def read_text_arg(value: str | None, file_path: str | None) -> str | None:
    if value is not None and file_path is not None:
        raise LinearError("Use either inline text or a file, not both.")
    if file_path is None:
        return value
    return Path(file_path).read_text(encoding="utf-8")


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))


def print_issue(issue: dict[str, Any], include_description: bool = True) -> None:
    print(f"{issue['identifier']} - {issue['title']}")
    print(f"State: {issue.get('state', {}).get('name', 'Unknown')}")
    print(f"Priority: {PRIORITY_NAMES.get(issue.get('priority') or 0, issue.get('priority'))}")
    assignee = issue.get("assignee")
    print(f"Assignee: {assignee.get('displayName') if assignee else 'Unassigned'}")
    labels = [label["name"] for label in issue.get("labels", {}).get("nodes", [])]
    print(f"Labels: {', '.join(labels) if labels else '-'}")
    project = issue.get("project")
    if project:
        print(f"Project: {project.get('name')}")
    print(f"URL: {issue.get('url', '')}")
    if include_description and issue.get("description"):
        print("\nDescription:\n")
        print(issue["description"])


def print_issue_table(issues: list[dict[str, Any]]) -> None:
    for issue in issues:
        state = issue.get("state", {}).get("name", "Unknown")
        priority = PRIORITY_NAMES.get(issue.get("priority") or 0, issue.get("priority"))
        print(f"{issue['identifier']:<9} {state:<14} {priority:<11} {issue['title']}")


def team_fields() -> str:
    return "id key name"


def issue_fields(with_comments: bool = False) -> str:
    comments = """
        comments(last: 20) {
          nodes { id body createdAt user { displayName email } }
        }
    """ if with_comments else ""
    return f"""
        id
        identifier
        number
        title
        description
        url
        priority
        createdAt
        updatedAt
        state {{ id name type }}
        team {{ id key name }}
        assignee {{ id name displayName email }}
        creator {{ id name displayName email }}
        project {{ id name }}
        labels {{ nodes {{ id name color }} }}
        {comments}
    """


def find_team(team_key_or_id: str) -> dict[str, Any]:
    query = f"""
    query Teams {{
      teams(first: 100) {{ nodes {{ {team_fields()} }} }}
    }}
    """
    teams = graphql(query).get("teams", {}).get("nodes", [])
    for team in teams:
        if team["id"] == team_key_or_id or team["key"].lower() == team_key_or_id.lower():
            return team
    known = ", ".join(f"{team['key']} ({team['name']})" for team in teams)
    raise LinearError(f"Team '{team_key_or_id}' not found. Known teams: {known or 'none'}")


def list_teams() -> list[dict[str, Any]]:
    query = f"""
    query Teams {{
      teams(first: 100) {{ nodes {{ {team_fields()} }} }}
    }}
    """
    return graphql(query).get("teams", {}).get("nodes", [])


def list_states(team_id: str) -> list[dict[str, Any]]:
    query = """
    query States($teamId: ID!) {
      workflowStates(filter: { team: { id: { eq: $teamId } } }, first: 100) {
        nodes { id name type position }
      }
    }
    """
    return graphql(query, {"teamId": team_id}).get("workflowStates", {}).get("nodes", [])


def find_state(team_id: str, state_name_or_id: str | None) -> str | None:
    if not state_name_or_id:
        return None
    for state in list_states(team_id):
        if state["id"] == state_name_or_id or state["name"].lower() == state_name_or_id.lower():
            return state["id"]
    raise LinearError(f"State '{state_name_or_id}' not found for this team.")


def list_labels(team_id: str | None = None) -> list[dict[str, Any]]:
    if team_id:
        query = """
        query Labels($teamId: ID!) {
          issueLabels(filter: { team: { id: { eq: $teamId } } }, first: 200) {
            nodes { id name color team { key name } }
          }
        }
        """
        variables = {"teamId": team_id}
    else:
        query = """
        query Labels {
          issueLabels(first: 200) {
            nodes { id name color team { key name } }
          }
        }
        """
        variables = {}
    return graphql(query, variables).get("issueLabels", {}).get("nodes", [])


def resolve_label_ids(team_id: str, labels: list[str]) -> list[str]:
    if not labels:
        return []
    known_labels = list_labels(team_id)
    resolved: list[str] = []
    for wanted in labels:
        match = next(
            (
                label for label in known_labels
                if label["id"] == wanted or label["name"].lower() == wanted.lower()
            ),
            None,
        )
        if not match:
            raise LinearError(f"Label '{wanted}' not found for this team.")
        resolved.append(match["id"])
    return resolved


def get_issue(identifier: str, with_comments: bool = False) -> dict[str, Any]:
    query = f"""
    query Issue($id: String!) {{
      issue(id: $id) {{ {issue_fields(with_comments)} }}
    }}
    """
    issue = graphql(query, {"id": identifier}).get("issue")
    if not issue:
        raise LinearError(f"Issue '{identifier}' not found.")
    return issue


def list_issues(args: argparse.Namespace) -> list[dict[str, Any]]:
    team = find_team(args.team)
    filters: dict[str, Any] = {"team": {"id": {"eq": team["id"]}}}
    if args.state:
        filters["state"] = {"name": {"in": args.state}}
    elif not args.all:
        filters["state"] = {"type": {"nin": ["canceled", "completed"]}}
    if args.label:
        filters["labels"] = {"name": {"in": args.label}}
    if args.assignee:
        filters["assignee"] = {"email": {"eq": args.assignee}}
    if args.query:
        filters["or"] = [
            {"title": {"containsIgnoreCase": args.query}},
            {"description": {"containsIgnoreCase": args.query}},
        ]

    query = f"""
    query Issues($filter: IssueFilter, $first: Int!) {{
      issues(filter: $filter, first: $first, orderBy: updatedAt) {{
        nodes {{ {issue_fields(False)} }}
      }}
    }}
    """
    return graphql(query, {"filter": filters, "first": args.limit}).get("issues", {}).get("nodes", [])


def create_issue(args: argparse.Namespace) -> dict[str, Any]:
    team = find_team(args.team)
    description = read_text_arg(args.description, args.description_file)
    label_ids = resolve_label_ids(team["id"], args.label or [])
    input_data: dict[str, Any] = {
        "teamId": team["id"],
        "title": args.title,
        "description": description,
        "priority": args.priority,
    }
    state_id = find_state(team["id"], args.state)
    if state_id:
        input_data["stateId"] = state_id
    if label_ids:
        input_data["labelIds"] = label_ids

    query = f"""
    mutation CreateIssue($input: IssueCreateInput!) {{
      issueCreate(input: $input) {{ success issue {{ {issue_fields(False)} }} }}
    }}
    """
    result = graphql(query, {"input": input_data}).get("issueCreate", {})
    if not result.get("success"):
        raise LinearError("Issue creation failed.")
    return result["issue"]


def update_issue(args: argparse.Namespace) -> dict[str, Any]:
    issue = get_issue(args.issue)
    team_id = issue["team"]["id"]
    input_data: dict[str, Any] = {}

    if args.title is not None:
        input_data["title"] = args.title
    description = read_text_arg(args.description, args.description_file)
    if description is not None:
        input_data["description"] = description
    if args.state is not None:
        input_data["stateId"] = find_state(team_id, args.state)
    if args.priority is not None:
        input_data["priority"] = args.priority
    if args.project_id is not None:
        input_data["projectId"] = args.project_id or None

    current_label_ids = [label["id"] for label in issue.get("labels", {}).get("nodes", [])]
    if args.label is not None:
        input_data["labelIds"] = resolve_label_ids(team_id, args.label)
    elif args.add_label or args.remove_label:
        add_ids = resolve_label_ids(team_id, args.add_label or [])
        remove_ids = set(resolve_label_ids(team_id, args.remove_label or []))
        input_data["labelIds"] = sorted((set(current_label_ids) | set(add_ids)) - remove_ids)

    if not input_data:
        raise LinearError("No update fields provided.")

    query = f"""
    mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {{
      issueUpdate(id: $id, input: $input) {{ success issue {{ {issue_fields(False)} }} }}
    }}
    """
    result = graphql(query, {"id": issue["id"], "input": input_data}).get("issueUpdate", {})
    if not result.get("success"):
        raise LinearError("Issue update failed.")
    return result["issue"]


def comment_issue(args: argparse.Namespace) -> bool:
    issue = get_issue(args.issue)
    body = read_text_arg(args.body, args.body_file)
    if not body:
        raise LinearError("Comment body is empty.")

    query = """
    mutation Comment($input: CommentCreateInput!) {
      commentCreate(input: $input) { success }
    }
    """
    result = graphql(query, {"input": {"issueId": issue["id"], "body": body}}).get("commentCreate", {})
    return bool(result.get("success"))


def delete_issue(args: argparse.Namespace) -> bool:
    issue = get_issue(args.issue)
    if not args.yes:
        raise LinearError(f"Refusing to delete {issue['identifier']} without --yes.")

    query = """
    mutation DeleteIssue($id: String!) {
      issueDelete(id: $id) { success }
    }
    """
    result = graphql(query, {"id": issue["id"]}).get("issueDelete", {})
    return bool(result.get("success"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Linear issues through the Linear GraphQL API.")
    parser.add_argument("--json", action="store_true", help="Print raw JSON output.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_credential_source_arg(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument(
            "--credential-source",
            choices=CREDENTIAL_SOURCES,
            default="auto",
            help="Read credentials from env, OpenMates Vault, or env with Vault fallback.",
        )

    me = subparsers.add_parser("me", help="Show the authenticated Linear user.")
    add_credential_source_arg(me)

    teams = subparsers.add_parser("teams", help="List workspace teams.")
    add_credential_source_arg(teams)

    states = subparsers.add_parser("states", help="List workflow states for a team.")
    add_credential_source_arg(states)
    states.add_argument("--team", default=DEFAULT_TEAM_KEY)

    labels = subparsers.add_parser("labels", help="List issue labels.")
    add_credential_source_arg(labels)
    labels.add_argument("--team", default=DEFAULT_TEAM_KEY)
    labels.add_argument("--all-teams", action="store_true", help="List labels for all teams.")

    for command_name, help_text in (
        ("list", "List issues."),
        ("search", "Search issues by title or description."),
    ):
        list_parser = subparsers.add_parser(command_name, help=help_text)
        add_credential_source_arg(list_parser)
        list_parser.add_argument("query_arg", nargs="?", help="Search text. Same as --query.")
        list_parser.add_argument("--team", default=DEFAULT_TEAM_KEY)
        list_parser.add_argument("--state", action="append", help="Workflow state name. May be repeated.")
        list_parser.add_argument("--label", action="append", help="Label name. May be repeated.")
        list_parser.add_argument("--assignee", help="Assignee email address.")
        list_parser.add_argument("--query", help="Case-insensitive title/description search.")
        list_parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
        list_parser.add_argument("--all", action="store_true", help="Include completed and canceled issues.")

    get_parser = subparsers.add_parser("get", help="Get one issue by OPE-123 or UUID.")
    add_credential_source_arg(get_parser)
    get_parser.add_argument("issue")
    get_parser.add_argument("--comments", action="store_true", help="Include the latest comments.")

    create = subparsers.add_parser("create", help="Create an issue.")
    add_credential_source_arg(create)
    create.add_argument("--team", default=DEFAULT_TEAM_KEY)
    create.add_argument("--title", required=True)
    create.add_argument("--description")
    create.add_argument("--description-file")
    create.add_argument("--state")
    create.add_argument("--priority", type=int, choices=range(0, 5), default=0)
    create.add_argument("--label", action="append")

    update = subparsers.add_parser("update", help="Update an issue.")
    add_credential_source_arg(update)
    update.add_argument("issue")
    update.add_argument("--title")
    update.add_argument("--description")
    update.add_argument("--description-file")
    update.add_argument("--state")
    update.add_argument("--priority", type=int, choices=range(0, 5))
    update.add_argument("--label", action="append", help="Replace all labels with these label names.")
    update.add_argument("--add-label", action="append", help="Add a label by name.")
    update.add_argument("--remove-label", action="append", help="Remove a label by name.")
    update.add_argument("--project-id", help="Set a Linear project UUID. Use an empty string to clear it.")

    comment = subparsers.add_parser("comment", help="Add a comment to an issue.")
    add_credential_source_arg(comment)
    comment.add_argument("issue")
    comment.add_argument("--body")
    comment.add_argument("--body-file")

    delete = subparsers.add_parser("delete", help="Soft-delete an issue. Recoverable in Linear for 30 days.")
    add_credential_source_arg(delete)
    delete.add_argument("issue")
    delete.add_argument("--yes", action="store_true", help="Required confirmation flag.")

    return parser


def main() -> int:
    load_env_file(PROJECT_ROOT / ".env")
    parser = build_parser()
    args = parser.parse_args()
    global credential_source
    credential_source = args.credential_source

    try:
        if args.command == "me":
            data = graphql("query Viewer { viewer { id name displayName email } }")["viewer"]
            print_json(data) if args.json else print(f"{data.get('displayName') or data.get('name')} <{data.get('email')}>")
        elif args.command == "teams":
            data = list_teams()
            print_json(data) if args.json else [print(f"{team['key']:<8} {team['name']}  {team['id']}") for team in data]
        elif args.command == "states":
            team = find_team(args.team)
            data = list_states(team["id"])
            print_json(data) if args.json else [print(f"{state['name']:<16} {state['type']:<10} {state['id']}") for state in data]
        elif args.command == "labels":
            team_id = None if args.all_teams else find_team(args.team)["id"]
            data = list_labels(team_id)
            print_json(data) if args.json else [print(f"{label['name']:<28} {label['id']}") for label in data]
        elif args.command in {"list", "search"}:
            if args.query_arg and args.query:
                raise LinearError("Use either positional query text or --query, not both.")
            if args.query_arg:
                args.query = args.query_arg
            data = list_issues(args)
            print_json(data) if args.json else print_issue_table(data)
        elif args.command == "get":
            data = get_issue(args.issue, args.comments)
            print_json(data) if args.json else print_issue(data)
        elif args.command == "create":
            data = create_issue(args)
            print_json(data) if args.json else print_issue(data, include_description=False)
        elif args.command == "update":
            data = update_issue(args)
            print_json(data) if args.json else print_issue(data, include_description=False)
        elif args.command == "comment":
            print("Comment added." if comment_issue(args) else "Comment failed.")
        elif args.command == "delete":
            print("Issue deleted." if delete_issue(args) else "Delete failed.")
        else:
            parser.error(f"Unhandled command: {args.command}")
    except LinearError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
