import os
import sys
from datetime import datetime

import httpx
from dotenv import load_dotenv
from fastmcp.server import FastMCP

from utils import (
    load_jenkins_configurations,
    detect_jenkins_instance,
    extract_job_path_and_build,
    analyze_log_for_errors,
    extract_git_repositories,
)

# Load environment variables from .env file
load_dotenv()

# --- Load Configurations ---
JENKINS_CONFIGS = load_jenkins_configurations()

# --- Other Configuration ---
JENKINS_VERIFY_SSL = os.getenv("JENKINS_VERIFY_SSL", "true").lower() in ("true", "1", "yes")
MAX_LOG_SIZE = int(os.getenv("MAX_LOG_SIZE", "250000"))
CONTEXT_WINDOW = int(os.getenv("CONTEXT_WINDOW", "2"))
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
    print("🔧 Configuration loaded (DEBUG MODE ENABLED):")
    print(f"   Jenkins instances configured: {len(JENKINS_CONFIGS)}")
    for url, config in JENKINS_CONFIGS.items():
        print(f"     - {url} (user: {config.user})")
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
    print(f"🚀 Jenkins MCP Server starting with {len(JENKINS_CONFIGS)} Jenkins instance(s) on port {SERVER_PORT} (set DEBUG=true for verbose logging)")


def create_server():
    mcp = FastMCP(
        name="Jenkins MCP Server",
        instructions=(
            "Fetch and analyze Jenkins build console logs using full Jenkins URLs. "
            "All tools require a complete Jenkins job URL in this format: "
            "https://jenkins.example.com/job/JobName/job/SubJob/lastBuild (or build number like /123). "
            "URL Format Examples:"
            "- https://jenkins.example.com/job/my-job/123"
            "- https://jenkins.example.com/job/MyFolder/job/my-job/lastBuild"
            "- https://jenkins-legacy.example.com/job/ProjectName/job/build-job/lastFailedBuild"
            "Build aliases: lastBuild, lastSuccessfulBuild, lastFailedBuild, lastCompletedBuild"
            "When analyzing build failures, consider calling get_jenkins_git_repositories "
            "to identify which repositories are involved, as this context can help diagnose issues. "
            "IMPORTANT: Always ask the user for the full Jenkins job URL if not provided."
        )
    )

    @mcp.tool()
    async def get_jenkins_console_log(
        job_url: str
    ) -> str:
        """
        Fetch the console log for a specific Jenkins build.

        Args:
            job_url: Full Jenkins job URL including build number or alias.
        """
        debug_log("get_jenkins_console_log called", job_url=job_url)

        # Detect which Jenkins instance to use
        jenkins_url, jenkins_config = detect_jenkins_instance(job_url, JENKINS_CONFIGS)
        credentials = jenkins_config.get_credentials()

        # Extract job path and build number from URL
        job_path, build_number = extract_job_path_and_build(job_url, jenkins_url)
        debug_log("Extracted job info", job_path=job_path, build_number=build_number)

        api_url = f"{jenkins_url}/job/{job_path}/{build_number}/consoleText"
        debug_log("API URL constructed", url=api_url)

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

        debug_log("Console log fetched successfully", size=len(console_log))
        # Return the full log with size info
        result = f"Console log for {job_url} ({len(console_log)} characters):\n\n{console_log}"
        debug_log("Returning response to LLM", response_length=len(result))
        return result

    @mcp.tool()
    async def analyze_jenkins_build_errors(
        job_url: str
    ) -> str:
        """
        Fetch and analyze a Jenkins build log to extract error snippets.
        If the log is small enough, returns the full log. Otherwise, extracts
        relevant error snippets with surrounding context.

        Args:
            job_url: Full Jenkins job URL including build number or alias.
        """
        debug_log("analyze_jenkins_build_errors called", job_url=job_url, context_window=CONTEXT_WINDOW)

        # Detect which Jenkins instance to use
        jenkins_url, jenkins_config = detect_jenkins_instance(job_url, JENKINS_CONFIGS)
        credentials = jenkins_config.get_credentials()

        # Extract job path and build number from URL
        job_path, build_number = extract_job_path_and_build(job_url, jenkins_url)
        debug_log("Extracted job info", job_path=job_path, build_number=build_number)

        api_url = f"{jenkins_url}/job/{job_path}/{build_number}/consoleText"
        debug_log("API URL constructed", url=api_url)

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
                f"Build log for {job_url} ({len(console_log)} characters):\n"
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
        debug_log("Error analysis complete", snippet_count=len(snippets))

        if not snippets:
            debug_log("No error snippets found")
            result = (
                f"Build log for {job_url} ({len(console_log)} characters):\n"
                f"The log was too large to analyze fully, and no specific error keywords "
                f"(like 'error' or 'exception') were found. Manual review may be needed."
            )
            debug_log("Returning response to LLM", response_length=len(result))
            return result

        # Combine snippets into a single context block
        combined_snippets = "\n\n--- SNIPPET DELIMITER ---\n\n".join(snippets)

        result = (
            f"Build log analysis for {job_url} ({len(console_log)} characters):\n"
            f"Found {len(snippets)} error snippets. Here are the relevant sections:\n\n"
            f"--- ERROR CONTEXT SNIPPETS ---\n"
            f"{combined_snippets}"
        )
        debug_log("Returning response to LLM", response_length=len(result),
                  original_log_size=len(console_log), compression_ratio=f"{len(result)/len(console_log)*100:.1f}%")
        return result

    @mcp.tool()
    async def get_jenkins_git_repositories(
        job_url: str
    ) -> str:
        """
        Extract information about git repositories used in a Jenkins build.
        Returns a deduplicated list of repositories with their URLs, branches, and commits.

        Args:
            job_url: Full Jenkins job URL including build number or alias.
        """
        debug_log("get_jenkins_git_repositories called", job_url=job_url)

        # Detect which Jenkins instance to use
        jenkins_url, jenkins_config = detect_jenkins_instance(job_url, JENKINS_CONFIGS)
        credentials = jenkins_config.get_credentials()

        # Extract job path and build number from URL
        job_path, build_number = extract_job_path_and_build(job_url, jenkins_url)
        debug_log("Extracted job info", job_path=job_path, build_number=build_number)

        api_url = f"{jenkins_url}/job/{job_path}/{build_number}/consoleText"
        debug_log("API URL constructed", url=api_url)

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
                f"Git repository analysis for {job_url}:\n"
                f"No git repositories were detected in the console log. "
                f"This build may not involve git operations or the log format may be different than expected."
            )
            debug_log("No repositories found")
            return result

        # Format the results
        result_lines = [
            f"Git repository analysis for {job_url}:",
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
        job_url: str
    ) -> str:
        """
        Get information about a specific Jenkins build (status, duration, timestamp, etc.).

        Args:
            job_url: Full Jenkins job URL including build number or alias.
        """
        debug_log("get_jenkins_build_info called", job_url=job_url)

        # Detect which Jenkins instance to use
        jenkins_url, jenkins_config = detect_jenkins_instance(job_url, JENKINS_CONFIGS)
        credentials = jenkins_config.get_credentials()

        # Extract job path and build number from URL
        job_path, build_number = extract_job_path_and_build(job_url, jenkins_url)
        debug_log("Extracted job info", job_path=job_path, build_number=build_number)

        api_url = f"{jenkins_url}/job/{job_path}/{build_number}/api/json"
        debug_log("API URL constructed", url=api_url)

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
            f"Build Information for {job_url} (#{build_info.get('number', build_number)}):",
            "",
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
                result_lines.append("\nTriggered by:")
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
