"""Utility functions for Jenkins MCP Server."""

import os
import re


class JenkinsConfig:
    """Configuration for a Jenkins instance."""

    def __init__(self, url: str, user: str, api_token: str):
        self.url = url.rstrip('/')  # Remove trailing slash for consistency
        self.user = user
        self.api_token = api_token

    def get_credentials(self) -> tuple[str, str]:
        """Return authentication tuple for httpx."""
        return (self.user, self.api_token)


def load_jenkins_configurations() -> dict[str, JenkinsConfig]:
    """
    Load all Jenkins configurations from environment variables.

    Supports two formats:
    1. Default instance: JENKINS_URL, JENKINS_USER, JENKINS_API_TOKEN
    2. Named instances: JENKINS_<NAME>_URL, JENKINS_<NAME>_USER, JENKINS_<NAME>_API_TOKEN

    Returns:
        Dict mapping Jenkins base URLs to JenkinsConfig objects
    """
    configs = {}

    # Load default configuration (backward compatibility)
    default_url = os.getenv("JENKINS_URL")
    default_user = os.getenv("JENKINS_USER")
    default_token = os.getenv("JENKINS_API_TOKEN")

    if default_url and default_user and default_token:
        configs[default_url.rstrip('/')] = JenkinsConfig(default_url, default_user, default_token)

    # Discover named configurations
    env_vars = os.environ
    instance_names = set()

    for key in env_vars:
        if key.startswith("JENKINS_") and key.endswith("_URL"):
            # Extract instance name (e.g., "LEGACY" from "JENKINS_LEGACY_URL")
            parts = key.split("_")
            if len(parts) >= 3:  # JENKINS_<NAME>_URL
                instance_name = "_".join(parts[1:-1])  # Handle multi-word names
                if instance_name and instance_name != "URL":  # Skip if it's just JENKINS_URL
                    instance_names.add(instance_name)

    # Load each named instance
    for instance_name in instance_names:
        jenkins_url = os.getenv(f"JENKINS_{instance_name}_URL")
        user = os.getenv(f"JENKINS_{instance_name}_USER")
        token = os.getenv(f"JENKINS_{instance_name}_API_TOKEN")

        # Debug: Print what we're looking for and what we found
        if os.getenv("DEBUG", "false").lower() in ("true", "1", "yes"):
            import sys
            print(f"[DEBUG] Checking instance '{instance_name}':", file=sys.stderr)
            print(f"  URL key: JENKINS_{instance_name}_URL = {jenkins_url}", file=sys.stderr)
            print(f"  USER key: JENKINS_{instance_name}_USER = {user}", file=sys.stderr)
            print(f"  TOKEN key: JENKINS_{instance_name}_API_TOKEN = {'***' if token else None}", file=sys.stderr)

        if jenkins_url and user and token:
            configs[jenkins_url.rstrip('/')] = JenkinsConfig(jenkins_url, user, token)

    return configs


def detect_jenkins_instance(job_url: str, configs: dict[str, JenkinsConfig]) -> tuple[str, JenkinsConfig]:
    """
    Detect which Jenkins instance to use based on the job URL.

    Args:
        job_url: Full Jenkins job URL (e.g., "https://jenkins.example.com/job/MyFolder/job/my-job/123")
        configs: Dictionary of Jenkins configurations

    Returns:
        Tuple of (jenkins_base_url, JenkinsConfig)

    Raises:
        ValueError: If no matching Jenkins instance found or invalid URL format
    """
    if not configs:
        raise ValueError("No Jenkins instances configured. Check environment variables.")

    if not job_url.startswith(("http://", "https://")):
        raise ValueError(
            f"Invalid job URL format. Expected full Jenkins URL starting with http:// or https://, "
            f"got: '{job_url}'\n\n"
            f"Example format: https://jenkins.example.com/job/MyFolder/job/my-job/lastBuild"
        )

    # Match against configured Jenkins instances
    for jenkins_url, config in configs.items():
        if job_url.startswith(jenkins_url):
            return jenkins_url, config

    raise ValueError(
        f"No Jenkins instance found matching URL '{job_url}'. "
        f"Available instances: {', '.join(configs.keys())}\n\n"
        f"Make sure the URL starts with one of the configured Jenkins instance URLs."
    )


def extract_job_path_and_build(job_url: str, jenkins_base_url: str) -> tuple[str, str]:
    """
    Extract job path and build number from Jenkins URL.

    Args:
        job_url: Full Jenkins job URL
        jenkins_base_url: Base URL of the Jenkins instance

    Returns:
        Tuple of (job_path, build_number)
        Example: ("MyFolder/job/my-job", "123")

    Raises:
        ValueError: If URL format is invalid
    """
    # Remove the Jenkins base URL
    path = job_url[len(jenkins_base_url):].lstrip('/')

    # Extract job path and build number
    # URLs can be:
    # - /job/MyFolder/job/my-job/123/
    # - /job/MyFolder/job/my-job/lastBuild
    # - /job/MyFolder/job/my-job/lastBuild/consoleText
    parts = path.split('/')

    job_parts = []
    build_number = "lastBuild"
    i = 0

    while i < len(parts):
        if parts[i] == "job" and i + 1 < len(parts):
            job_parts.append(parts[i + 1])
            i += 2
        elif parts[i] and parts[i] not in ("consoleText", "api", ""):
            # This might be a build number or build alias
            if parts[i].isdigit() or parts[i] in ("lastBuild", "lastSuccessfulBuild", "lastFailedBuild", "lastCompletedBuild"):
                build_number = parts[i]
            i += 1
        else:
            i += 1

    if not job_parts:
        raise ValueError(
            f"Could not extract job name from URL: {job_url}\n\n"
            f"Expected format: {jenkins_base_url}/job/JobName/... or "
            f"{jenkins_base_url}/job/Folder/job/JobName/..."
        )

    job_path = "/job/".join(job_parts)
    return job_path, build_number


def analyze_log_for_errors(console_log: str, context_window: int = 2) -> list[str]:
    """
    Analyze console log and extract error snippets with context.

    Args:
        console_log: The Jenkins console log text
        context_window: Number of lines to include before and after an error

    Returns:
        List of error snippet strings
    """
    error_keywords = ["error", "exception", "failed", "failure", "traceback", "fatal"]
    snippets = []
    lines = console_log.splitlines()
    found_indices = set()  # To avoid capturing overlapping contexts

    for i, line in enumerate(lines):
        if i in found_indices:
            continue

        # Check if any keyword is in the current line (case-insensitive)
        if any(keyword in line.lower() for keyword in error_keywords):
            # Define the start and end of the context window
            start_index = max(0, i - context_window)
            end_index = min(len(lines), i + context_window + 1)

            # Extract the context snippet
            context = "\n".join(lines[start_index:end_index])
            snippets.append(context)

            # Mark these lines as found so we don't re-process them
            for j in range(start_index, end_index):
                found_indices.add(j)

    return snippets


def extract_git_repositories(console_log: str) -> list[dict[str, str]]:
    """
    Extract git repository information from console log.

    Args:
        console_log: The Jenkins console log text

    Returns:
        List of dictionaries containing repository info (url, branch, commit)
    """
    repositories = []
    seen_urls = set()  # Track unique repository URLs
    lines = console_log.splitlines()

    # Common patterns for git operations in Jenkins logs
    patterns = [
        # Git clone/fetch URLs (various formats)
        r'(?:Cloning|Fetching|Checking out)\s+(?:remote )?repository\s+["\']?([^"\'>\s]+\.git)["\']?',
        r'git clone\s+(?:-[^\s]+\s+)*["\']?([^"\'>\s]+\.git)["\']?',
        r'git fetch\s+(?:-[^\s]+\s+)*["\']?([^"\'>\s]+\.git)["\']?',
        r'(?:url|URL):\s*([^"\'>\s]+\.git)',
        r'Repository:\s*([^"\'>\s]+\.git)',
        # Git URLs without .git extension
        r'(?:git@|https?://)[^\s]+?(?:github\.com|gitlab\.com|bitbucket\.org)[:/]([^\s"\'<>]+?)(?:\s|$|\.git)',
    ]

    # Pattern for branch information
    branch_pattern = r'(?:branch|Branch|ref)[:=]?\s*["\']?([^"\'>\s]+)["\']?'

    # Pattern for commit hash
    commit_pattern = r'(?:commit|Commit|revision|Revision)\s+([0-9a-f]{7,40})'

    for i, line in enumerate(lines):
        # Look for repository URLs
        for pattern in patterns:
            matches = re.finditer(pattern, line, re.IGNORECASE)
            for match in matches:
                repo_url = match.group(1)

                # Normalize URL
                if not repo_url.startswith(('http://', 'https://', 'git@')):
                    # Try to reconstruct full URL if we caught a partial match
                    if '/' in repo_url and not repo_url.startswith('/'):
                        # Check if there's a domain before this in the line
                        full_match = re.search(r'((?:git@|https?://)[^\s]+?' + re.escape(repo_url) + r')', line)
                        if full_match:
                            repo_url = full_match.group(1)

                # Skip if we've already seen this URL
                if repo_url in seen_urls:
                    continue

                seen_urls.add(repo_url)

                repo_info = {'url': repo_url, 'branch': None, 'commit': None}

                # Look for branch and commit in nearby lines (±5 lines)
                context_start = max(0, i - 5)
                context_end = min(len(lines), i + 6)

                for context_line in lines[context_start:context_end]:
                    # Look for branch
                    if repo_info['branch'] is None:
                        branch_match = re.search(branch_pattern, context_line, re.IGNORECASE)
                        if branch_match:
                            branch = branch_match.group(1)
                            # Filter out common false positives
                            if branch not in ('true', 'false', 'master', 'main') or 'branch' in context_line.lower():
                                repo_info['branch'] = branch

                    # Look for commit hash
                    if repo_info['commit'] is None:
                        commit_match = re.search(commit_pattern, context_line, re.IGNORECASE)
                        if commit_match:
                            repo_info['commit'] = commit_match.group(1)

                repositories.append(repo_info)

    return repositories
