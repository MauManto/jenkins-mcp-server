import os
import sys
from datetime import datetime

import httpx
from dotenv import load_dotenv
from fastmcp.server import FastMCP

# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
JENKINS_URL = os.getenv("JENKINS_URL", "https://jenkins.example.com")
JENKINS_USER = os.getenv("JENKINS_USER")
JENKINS_API_TOKEN = os.getenv("JENKINS_API_TOKEN")
JENKINS_VERIFY_SSL = os.getenv("JENKINS_VERIFY_SSL", "true").lower() in ("true", "1", "yes")
MAX_LOG_SIZE = int(os.getenv("MAX_LOG_SIZE", "250000"))
CONTEXT_WINDOW = int(os.getenv("CONTEXT_WINDOW", "15"))
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "30"))
HTTP_CONNECT_TIMEOUT = float(os.getenv("HTTP_CONNECT_TIMEOUT", "10"))
HTTP_READ_TIMEOUT = float(os.getenv("HTTP_READ_TIMEOUT", "120"))
HTTP_WRITE_TIMEOUT = float(os.getenv("HTTP_WRITE_TIMEOUT", "10"))
SERVER_PORT = int(os.getenv("SERVER_PORT", "3000"))
SERVER_PATH = os.getenv("SERVER_PATH", "/mcp")
DEBUG = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")


def debug_log(message: str, **kwargs):
    """Log debug messages when DEBUG mode is enabled."""
    if DEBUG:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"[DEBUG {timestamp}] {message}", file=sys.stderr)
        if kwargs:
            for key, value in kwargs.items():
                print(f"  {key}: {value}", file=sys.stderr)


# Debug output
if DEBUG:
    print(f"🔧 Configuration loaded (DEBUG MODE ENABLED):")
    print(f"   JENKINS_URL: {JENKINS_URL}")
    print(f"   JENKINS_USER: {JENKINS_USER}")
    print(f"   JENKINS_VERIFY_SSL: {JENKINS_VERIFY_SSL} (raw value: '{os.getenv('JENKINS_VERIFY_SSL', 'true')}')")
    print(f"   MAX_LOG_SIZE: {MAX_LOG_SIZE}")
    print(f"   CONTEXT_WINDOW: {CONTEXT_WINDOW}")
    print(f"   HTTP_TIMEOUT: {HTTP_TIMEOUT}s")
    print(f"   HTTP_CONNECT_TIMEOUT: {HTTP_CONNECT_TIMEOUT}s")
    print(f"   HTTP_READ_TIMEOUT: {HTTP_READ_TIMEOUT}s")
    print(f"   HTTP_WRITE_TIMEOUT: {HTTP_WRITE_TIMEOUT}s")
    print(f"   SERVER_PORT: {SERVER_PORT}")
    print(f"   SERVER_PATH: {SERVER_PATH}")
else:
    print(f"🚀 Jenkins MCP Server starting on port {SERVER_PORT} (set DEBUG=true for verbose logging)")


def get_jenkins_credentials() -> tuple[str, str] | None:
    """Validate and return Jenkins credentials."""
    if not all([JENKINS_URL, JENKINS_USER, JENKINS_API_TOKEN]):
        return None
    # At this point, we know these are not None due to the check above
    assert JENKINS_USER is not None
    assert JENKINS_API_TOKEN is not None
    return (JENKINS_USER, JENKINS_API_TOKEN)


def analyze_log_for_errors(console_log: str, context_window: int = 15) -> list[str]:
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
    import re

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

    current_repo = None

    for i, line in enumerate(lines):
        # Look for repository URLs
        for pattern in patterns:
            matches = re.finditer(pattern, line, re.IGNORECASE)
            for match in matches:
                url = match.group(1)

                # Normalize URL
                if not url.startswith(('http://', 'https://', 'git@')):
                    # Try to reconstruct full URL if we caught a partial match
                    if '/' in url and not url.startswith('/'):
                        # Check if there's a domain before this in the line
                        full_match = re.search(r'((?:git@|https?://)[^\s]+?' + re.escape(url) + r')', line)
                        if full_match:
                            url = full_match.group(1)

                # Skip if we've already seen this URL
                if url in seen_urls:
                    continue

                seen_urls.add(url)

                repo_info = {'url': url, 'branch': None, 'commit': None}

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
                current_repo = repo_info

    return repositories


def create_server():
    mcp = FastMCP(
        name="Jenkins MCP Server",
        instructions=(
            "Fetch and analyze Jenkins build console logs. "
            "When analyzing build failures, consider calling get_jenkins_git_repositories "
            "to identify which repositories are involved, as this context can help diagnose issues. "
            "IMPORTANT: To analyze a Jenkins job, you need the Jenkins job URL - ask the user for it "
            "to extract the job name (e.g., from 'https://jenkins.example.com/job/MyFolder/job/my-job/' "
            "extract 'MyFolder/my-job')."
        )
    )

    @mcp.tool()
    async def get_jenkins_console_log(
        job_name: str,
        build_number: str = "lastBuild"
    ) -> str:
        """
        Fetch the console log for a specific Jenkins build.

        Args:
            job_name: The Jenkins job path. For nested jobs, use slashes to separate folders
                     (e.g., "MyFolder/my-job" or "MyFolder/job/my-job"). The function will
                     automatically handle the proper /job/ separators needed by Jenkins API.
            build_number: The build number (e.g., "123") or alias like "lastBuild",
                         "lastSuccessfulBuild", "lastFailedBuild" (default: "lastBuild")
        """
        debug_log(f"get_jenkins_console_log called", job_name=job_name, build_number=build_number)

        credentials = get_jenkins_credentials()
        if not credentials:
            raise ValueError("Jenkins credentials not configured. Check JENKINS_URL, JENKINS_USER, and JENKINS_API_TOKEN environment variables.")

        # Ensure job_name has proper /job/ separators for nested folders
        original_job_name = job_name
        if "/job/" not in job_name and "/" in job_name:
            job_name = job_name.replace("/", "/job/")
            debug_log(f"Transformed job name", original=original_job_name, transformed=job_name)

        api_url = f"{JENKINS_URL}/job/{job_name}/{build_number}/consoleText"
        debug_log(f"API URL constructed", url=api_url)

        async def fetch_log():
            async with httpx.AsyncClient(timeout=30.0, verify=JENKINS_VERIFY_SSL) as client:
                try:
                    debug_log("Sending HTTP request to Jenkins")
                    response = await client.get(api_url, auth=credentials)
                    debug_log(f"Received response", status_code=response.status_code, content_length=len(response.text))
                    response.raise_for_status()
                    return response.text
                except httpx.HTTPStatusError as err:
                    debug_log(f"HTTP error occurred", status_code=err.response.status_code, error=str(err))
                    if err.response.status_code == 401:
                        raise ValueError("Authentication failed. Please check your username and API token.")
                    elif err.response.status_code == 404:
                        raise ValueError(f"Job or build not found. Please check the job name and build number.")
                    else:
                        raise ValueError(f"HTTP Error: {err}")
                except httpx.RequestError as err:
                    debug_log(f"Request error occurred", error=str(err))
                    raise ValueError(f"Network or connection error: {err}")

        console_log = await fetch_log()

        if not console_log:
            debug_log("Console log is empty")
            return "Console log is empty."

        debug_log(f"Console log fetched successfully", size=len(console_log))
        # Return the full log with size info
        result = f"Console log for {job_name} build {build_number} ({len(console_log)} characters):\n\n{console_log}"
        debug_log("Returning response to LLM", response_length=len(result))
        return result

    @mcp.tool()
    async def analyze_jenkins_build_errors(
        job_name: str,
        build_number: str = "lastBuild"
    ) -> str:
        """
        Fetch and analyze a Jenkins build log to extract error snippets.
        If the log is small enough, returns the full log. Otherwise, extracts
        relevant error snippets with surrounding context.

        Args:
            job_name: The Jenkins job path. For nested jobs, use slashes to separate folders
                     (e.g., "MyFolder/my-job" or "MyFolder/job/my-job"). The function will
                     automatically handle the proper /job/ separators needed by Jenkins API.
            build_number: The build number (e.g., "123") or alias like "lastBuild",
                         "lastSuccessfulBuild", "lastFailedBuild" (default: "lastBuild")
        """
        debug_log(f"analyze_jenkins_build_errors called",
                  job_name=job_name, build_number=build_number, context_window=CONTEXT_WINDOW)

        credentials = get_jenkins_credentials()
        if not credentials:
            raise ValueError("Jenkins credentials not configured. Check JENKINS_URL, JENKINS_USER, and JENKINS_API_TOKEN environment variables.")

        # Ensure job_name has proper /job/ separators for nested folders
        original_job_name = job_name
        if "/job/" not in job_name and "/" in job_name:
            job_name = job_name.replace("/", "/job/")
            debug_log(f"Transformed job name", original=original_job_name, transformed=job_name)

        api_url = f"{JENKINS_URL}/job/{job_name}/{build_number}/consoleText"
        debug_log(f"API URL constructed", url=api_url)

        async def fetch_log():
            timeout_config = httpx.Timeout(
                timeout=HTTP_TIMEOUT,
                connect=HTTP_CONNECT_TIMEOUT,
                read=HTTP_READ_TIMEOUT,
                write=HTTP_WRITE_TIMEOUT
            )
            debug_log("Timeout configuration", timeout=HTTP_TIMEOUT,
                     connect=HTTP_CONNECT_TIMEOUT, read=HTTP_READ_TIMEOUT, write=HTTP_WRITE_TIMEOUT)

            async with httpx.AsyncClient(timeout=timeout_config, verify=JENKINS_VERIFY_SSL) as client:
                try:
                    debug_log("Sending HTTP request to Jenkins")
                    response = await client.get(api_url, auth=credentials)
                    debug_log(f"Received response", status_code=response.status_code, content_length=len(response.text))
                    response.raise_for_status()
                    return response.text
                except httpx.HTTPStatusError as err:
                    debug_log(f"HTTP error occurred", status_code=err.response.status_code, error=str(err))
                    if err.response.status_code == 401:
                        raise ValueError("Authentication failed. Please check your username and API token.")
                    elif err.response.status_code == 404:
                        raise ValueError(f"Job or build not found. Please check the job name and build number.")
                    else:
                        raise ValueError(f"HTTP Error: {err}")
                except httpx.RequestError as err:
                    debug_log(f"Request error occurred", error=str(err))
                    raise ValueError(f"Network or connection error: {err}")

        console_log = await fetch_log()

        if not console_log:
            debug_log("Console log is empty")
            return "Console log is empty or could not be fetched."

        debug_log(f"Log fetched", size=len(console_log), threshold=MAX_LOG_SIZE)

        # If log is small enough, return it in its entirety
        if len(console_log) < MAX_LOG_SIZE:
            debug_log("Log is small enough to return in full")
            result = (
                f"Build log for {job_name} build {build_number} ({len(console_log)} characters):\n"
                f"The log is small enough to analyze in its entirety.\n\n"
                f"--- FULL CONSOLE LOG ---\n"
                f"{console_log}"
            )
            debug_log("Returning response to LLM", response_length=len(result))
            return result

        # Log is too large, extract error snippets
        debug_log("Log is too large, extracting error snippets",
                  log_size=len(console_log), max_size=MAX_LOG_SIZE, context_window=CONTEXT_WINDOW)
        snippets = analyze_log_for_errors(console_log, CONTEXT_WINDOW)
        debug_log(f"Error analysis complete", snippet_count=len(snippets))

        if not snippets:
            debug_log("No error snippets found")
            result = (
                f"Build log for {job_name} build {build_number} ({len(console_log)} characters):\n"
                f"The log was too large to analyze fully, and no specific error keywords "
                f"(like 'error' or 'exception') were found. Manual review may be needed."
            )
            debug_log("Returning response to LLM", response_length=len(result))
            return result

        # Combine snippets into a single context block
        combined_snippets = "\n\n--- SNIPPET DELIMITER ---\n\n".join(snippets)

        result = (
            f"Build log analysis for {job_name} build {build_number} ({len(console_log)} characters):\n"
            f"Found {len(snippets)} error snippets. Here are the relevant sections:\n\n"
            f"--- ERROR CONTEXT SNIPPETS ---\n"
            f"{combined_snippets}"
        )
        debug_log("Returning response to LLM", response_length=len(result),
                  original_log_size=len(console_log), compression_ratio=f"{len(result)/len(console_log)*100:.1f}%")
        return result

    @mcp.tool()
    async def get_jenkins_git_repositories(
        job_name: str,
        build_number: str = "lastBuild"
    ) -> str:
        """
        Extract information about git repositories used in a Jenkins build.
        Returns a deduplicated list of repositories with their URLs, branches, and commits.

        Args:
            job_name: The Jenkins job path. For nested jobs, use slashes to separate folders
                     (e.g., "MyFolder/my-job" or "MyFolder/job/my-job"). The function will
                     automatically handle the proper /job/ separators needed by Jenkins API.
            build_number: The build number (e.g., "123") or alias like "lastBuild",
                         "lastSuccessfulBuild", "lastFailedBuild" (default: "lastBuild")
        """
        debug_log(f"get_jenkins_git_repositories called", job_name=job_name, build_number=build_number)

        credentials = get_jenkins_credentials()
        if not credentials:
            raise ValueError("Jenkins credentials not configured. Check JENKINS_URL, JENKINS_USER, and JENKINS_API_TOKEN environment variables.")

        # Ensure job_name has proper /job/ separators for nested folders
        original_job_name = job_name
        if "/job/" not in job_name and "/" in job_name:
            job_name = job_name.replace("/", "/job/")
            debug_log(f"Transformed job name", original=original_job_name, transformed=job_name)

        api_url = f"{JENKINS_URL}/job/{job_name}/{build_number}/consoleText"
        debug_log(f"API URL constructed", url=api_url)

        async def fetch_log():
            timeout_config = httpx.Timeout(
                timeout=HTTP_TIMEOUT,
                connect=HTTP_CONNECT_TIMEOUT,
                read=HTTP_READ_TIMEOUT,
                write=HTTP_WRITE_TIMEOUT
            )
            async with httpx.AsyncClient(timeout=timeout_config, verify=JENKINS_VERIFY_SSL) as client:
                try:
                    debug_log("Sending HTTP request to Jenkins")
                    response = await client.get(api_url, auth=credentials)
                    debug_log(f"Received response", status_code=response.status_code, content_length=len(response.text))
                    response.raise_for_status()
                    return response.text
                except httpx.HTTPStatusError as err:
                    debug_log(f"HTTP error occurred", status_code=err.response.status_code, error=str(err))
                    if err.response.status_code == 401:
                        raise ValueError("Authentication failed. Please check your username and API token.")
                    elif err.response.status_code == 404:
                        raise ValueError(f"Job or build not found. Please check the job name and build number.")
                    else:
                        raise ValueError(f"HTTP Error: {err}")
                except httpx.RequestError as err:
                    debug_log(f"Request error occurred", error=str(err))
                    raise ValueError(f"Network or connection error: {err}")

        console_log = await fetch_log()

        if not console_log:
            debug_log("Console log is empty")
            return "Console log is empty or could not be fetched."

        debug_log(f"Log fetched, extracting git repositories", size=len(console_log))
        repositories = extract_git_repositories(console_log)
        debug_log(f"Git repository extraction complete", repo_count=len(repositories))

        if not repositories:
            result = (
                f"Git repository analysis for {job_name} build {build_number}:\n"
                f"No git repositories were detected in the console log. "
                f"This build may not involve git operations or the log format may be different than expected."
            )
            debug_log("No repositories found")
            return result

        # Format the results
        result_lines = [
            f"Git repository analysis for {job_name} build {build_number}:",
            f"Found {len(repositories)} unique repository/repositories:\n"
        ]

        for idx, repo in enumerate(repositories, 1):
            result_lines.append(f"{idx}. Repository URL: {repo['url']}")
            if repo['branch']:
                result_lines.append(f"   Branch: {repo['branch']}")
            if repo['commit']:
                result_lines.append(f"   Commit: {repo['commit']}")
            result_lines.append("")  # Empty line between repos

        result = "\n".join(result_lines)
        debug_log("Returning response to LLM", response_length=len(result), repo_count=len(repositories))
        return result

    @mcp.tool()
    async def get_jenkins_build_info(
        job_name: str,
        build_number: str = "lastBuild"
    ) -> str:
        """
        Get information about a specific Jenkins build (status, duration, timestamp, etc.).

        Args:
            job_name: The Jenkins job path. For nested jobs, use slashes to separate folders
                     (e.g., "MyFolder/my-job" or "MyFolder/job/my-job"). The function will
                     automatically handle the proper /job/ separators needed by Jenkins API.
            build_number: The build number (e.g., "123") or alias like "lastBuild",
                         "lastSuccessfulBuild", "lastFailedBuild" (default: "lastBuild")
        """
        debug_log(f"get_jenkins_build_info called", job_name=job_name, build_number=build_number)

        credentials = get_jenkins_credentials()
        if not credentials:
            raise ValueError("Jenkins credentials not configured. Check JENKINS_URL, JENKINS_USER, and JENKINS_API_TOKEN environment variables.")

        # Ensure job_name has proper /job/ separators for nested folders
        original_job_name = job_name
        if "/job/" not in job_name and "/" in job_name:
            job_name = job_name.replace("/", "/job/")
            debug_log(f"Transformed job name", original=original_job_name, transformed=job_name)

        api_url = f"{JENKINS_URL}/job/{job_name}/{build_number}/api/json"
        debug_log(f"API URL constructed", url=api_url)

        async def fetch_info():
            timeout_config = httpx.Timeout(
                timeout=HTTP_TIMEOUT,
                connect=HTTP_CONNECT_TIMEOUT,
                read=HTTP_READ_TIMEOUT,
                write=HTTP_WRITE_TIMEOUT
            )
            async with httpx.AsyncClient(timeout=timeout_config, verify=JENKINS_VERIFY_SSL) as client:
                try:
                    debug_log("Sending HTTP request to Jenkins")
                    response = await client.get(api_url, auth=credentials)
                    debug_log(f"Received response", status_code=response.status_code)
                    response.raise_for_status()
                    build_data = response.json()
                    debug_log(f"Build info parsed", build_number=build_data.get('number'),
                             result=build_data.get('result'), building=build_data.get('building'))
                    return build_data
                except httpx.HTTPStatusError as err:
                    debug_log(f"HTTP error occurred", status_code=err.response.status_code, error=str(err))
                    if err.response.status_code == 401:
                        raise ValueError("Authentication failed. Please check your username and API token.")
                    elif err.response.status_code == 404:
                        raise ValueError(f"Job or build not found. Please check the job name and build number.")
                    else:
                        raise ValueError(f"HTTP Error: {err}")
                except httpx.RequestError as err:
                    debug_log(f"Request error occurred", error=str(err))
                    raise ValueError(f"Network or connection error: {err}")

        build_info = await fetch_info()

        # Extract relevant information
        result_lines = [
            f"Build Information for {job_name} #{build_info.get('number', build_number)}:",
            f"",
            f"Status: {build_info.get('result', 'IN_PROGRESS')}",
            f"Duration: {build_info.get('duration', 0) / 1000:.2f} seconds",
            f"Timestamp: {build_info.get('timestamp', 'N/A')}",
            f"Building: {build_info.get('building', False)}",
            f"URL: {build_info.get('url', 'N/A')}",
        ]

        # Add causes if available
        actions = build_info.get('actions', [])
        for action in actions:
            if 'causes' in action:
                result_lines.append(f"\nTriggered by:")
                for cause in action['causes']:
                    cause_desc = cause.get('shortDescription', 'Unknown')
                    result_lines.append(f"  - {cause_desc}")
                break

        debug_log("Build info formatted successfully")
        result = "\n".join(result_lines)
        debug_log("Returning response to LLM", response_length=len(result))
        return result

    return mcp


def main():
    """Entry point for the server."""
    create_server().run(transport="http", host="0.0.0.0", port=SERVER_PORT, path=SERVER_PATH)


if __name__ == "__main__":
    main()
