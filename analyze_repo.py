"""
analyze_repo.py

Analyzes a public GitHub repository's health using the GitHub API and
generates a simple 0-100 health score with a breakdown.

Usage:
    python analyze_repo.py owner/repo-name

Requires a GitHub personal access token set as an environment variable
to avoid API rate limits:
    export GITHUB_TOKEN=your_token_here
"""

import argparse
import os
import sys
from datetime import datetime, timezone

import requests

GITHUB_API = "https://api.github.com"


def get_headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_json(url: str) -> dict | list:
    response = requests.get(url, headers=get_headers())
    if response.status_code == 404:
        print(f"Error: repository not found ({url})")
        sys.exit(1)
    if response.status_code == 403:
        print("Error: rate limit exceeded. Set GITHUB_TOKEN to increase your limit.")
        sys.exit(1)
    response.raise_for_status()
    return response.json()


def days_since(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).days


def check_commit_activity(owner: str, repo: str) -> tuple[int, str]:
    commits = fetch_json(f"{GITHUB_API}/repos/{owner}/{repo}/commits?per_page=1")
    if not commits:
        return 0, "No commits found."

    latest_commit_date = commits[0]["commit"]["committer"]["date"]
    days = days_since(latest_commit_date)

    if days <= 30:
        return 25, f"Active — last commit {days} days ago."
    elif days <= 180:
        return 15, f"Moderately active — last commit {days} days ago."
    else:
        return 5, f"Inactive — last commit {days} days ago."


def check_readme(owner: str, repo: str) -> tuple[int, str]:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/readme"
    response = requests.get(url, headers=get_headers())
    if response.status_code != 200:
        return 0, "No README found."

    size = response.json().get("size", 0)
    if size > 1000:
        return 20, f"README present and substantial ({size} bytes)."
    elif size > 200:
        return 12, f"README present but brief ({size} bytes)."
    else:
        return 5, f"README present but very minimal ({size} bytes)."


def check_issue_age(owner: str, repo: str) -> tuple[int, str]:
    issues = fetch_json(
        f"{GITHUB_API}/repos/{owner}/{repo}/issues?state=open&per_page=20&sort=created&direction=asc"
    )
    issues = [i for i in issues if "pull_request" not in i]

    if not issues:
        return 20, "No open issues — clean backlog."

    oldest_days = days_since(issues[0]["created_at"])
    if oldest_days <= 30:
        return 18, f"Oldest open issue is {oldest_days} days old."
    elif oldest_days <= 180:
        return 10, f"Oldest open issue is {oldest_days} days old."
    else:
        return 4, f"Oldest open issue is {oldest_days} days old — backlog needs attention."


def check_license(owner: str, repo: str) -> tuple[int, str]:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/license"
    response = requests.get(url, headers=get_headers())
    if response.status_code == 200:
        license_name = response.json().get("license", {}).get("name", "Unknown")
        return 15, f"License present: {license_name}."
    return 0, "No license found."


def check_dependency_files(owner: str, repo: str) -> tuple[int, str]:
    for filename in ["requirements.txt", "package.json", "pyproject.toml"]:
        url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{filename}"
        response = requests.get(url, headers=get_headers())
        if response.status_code == 200:
            return 20, f"Dependency file found: {filename}."
    return 5, "No recognized dependency file found."


def analyze(owner: str, repo: str) -> None:
    checks = [
        ("Commit Activity", check_commit_activity),
        ("README Quality", check_readme),
        ("Issue Age", check_issue_age),
        ("License", check_license),
        ("Dependency File", check_dependency_files),
    ]

    total_score = 0
    print(f"\nHealth Report for {owner}/{repo}\n{'-' * 40}")

    for label, check_fn in checks:
        score, message = check_fn(owner, repo)
        total_score += score
        print(f"{label:<18} [{score:>3} pts]  {message}")

    print(f"{'-' * 40}\nOverall Health Score: {total_score} / 100\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze a GitHub repository's health.")
    parser.add_argument("repo", help="Repository in the form owner/repo-name")
    args = parser.parse_args()

    if "/" not in args.repo:
        print("Error: repo must be in the form owner/repo-name")
        sys.exit(1)

    owner, repo_name = args.repo.split("/", 1)
    analyze(owner, repo_name)
