import os

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

# Debug output
print(f"🔧 Configuration loaded:")
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


def create_server():
    mcp = FastMCP(
        name="Jenkins MCP Server",
        instructions="Fetch and analyze Jenkins build console logs."
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
        credentials = get_jenkins_credentials()
        if not credentials:
            raise ValueError("Jenkins credentials not configured. Check JENKINS_URL, JENKINS_USER, and JENKINS_API_TOKEN environment variables.")

        # Ensure job_name has proper /job/ separators for nested folders
        if "/job/" not in job_name and "/" in job_name:
            job_name = job_name.replace("/", "/job/")

        api_url = f"{JENKINS_URL}/job/{job_name}/{build_number}/consoleText"

        async def fetch_log():
            async with httpx.AsyncClient(timeout=30.0, verify=JENKINS_VERIFY_SSL) as client:
                try:
                    response = await client.get(api_url, auth=credentials)
                    response.raise_for_status()
                    return response.text
                except httpx.HTTPStatusError as err:
                    if err.response.status_code == 401:
                        raise ValueError("Authentication failed. Please check your username and API token.")
                    elif err.response.status_code == 404:
                        raise ValueError(f"Job or build not found. Please check the job name and build number.")
                    else:
                        raise ValueError(f"HTTP Error: {err}")
                except httpx.RequestError as err:
                    raise ValueError(f"Network or connection error: {err}")

        console_log = await fetch_log()

        if not console_log:
            return "Console log is empty."

        # Return the full log with size info
        return f"Console log for {job_name} build {build_number} ({len(console_log)} characters):\n\n{console_log}"

    @mcp.tool()
    async def analyze_jenkins_build_errors(
        job_name: str,
        build_number: str = "lastBuild",
        context_lines: int = 15
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
            context_lines: Number of lines to include before and after each error (default: 15)
        """
        credentials = get_jenkins_credentials()
        if not credentials:
            raise ValueError("Jenkins credentials not configured. Check JENKINS_URL, JENKINS_USER, and JENKINS_API_TOKEN environment variables.")

        # Ensure job_name has proper /job/ separators for nested folders
        if "/job/" not in job_name and "/" in job_name:
            job_name = job_name.replace("/", "/job/")

        api_url = f"{JENKINS_URL}/job/{job_name}/{build_number}/consoleText"

        async def fetch_log():
            timeout_config = httpx.Timeout(
                timeout=HTTP_TIMEOUT,
                connect=HTTP_CONNECT_TIMEOUT,
                read=HTTP_READ_TIMEOUT,
                write=HTTP_WRITE_TIMEOUT
            )
            async with httpx.AsyncClient(timeout=timeout_config, verify=JENKINS_VERIFY_SSL) as client:
                try:
                    response = await client.get(api_url, auth=credentials)
                    response.raise_for_status()
                    return response.text
                except httpx.HTTPStatusError as err:
                    if err.response.status_code == 401:
                        raise ValueError("Authentication failed. Please check your username and API token.")
                    elif err.response.status_code == 404:
                        raise ValueError(f"Job or build not found. Please check the job name and build number.")
                    else:
                        raise ValueError(f"HTTP Error: {err}")
                except httpx.RequestError as err:
                    raise ValueError(f"Network or connection error: {err}")

        console_log = await fetch_log()

        if not console_log:
            return "Console log is empty or could not be fetched."

        # If log is small enough, return it in its entirety
        if len(console_log) < MAX_LOG_SIZE:
            return (
                f"Build log for {job_name} build {build_number} ({len(console_log)} characters):\n"
                f"The log is small enough to analyze in its entirety.\n\n"
                f"--- FULL CONSOLE LOG ---\n"
                f"{console_log}"
            )

        # Log is too large, extract error snippets
        snippets = analyze_log_for_errors(console_log, context_lines)

        if not snippets:
            return (
                f"Build log for {job_name} build {build_number} ({len(console_log)} characters):\n"
                f"The log was too large to analyze fully, and no specific error keywords "
                f"(like 'error' or 'exception') were found. Manual review may be needed."
            )

        # Combine snippets into a single context block
        combined_snippets = "\n\n--- SNIPPET DELIMITER ---\n\n".join(snippets)

        return (
            f"Build log analysis for {job_name} build {build_number} ({len(console_log)} characters):\n"
            f"Found {len(snippets)} error snippets. Here are the relevant sections:\n\n"
            f"--- ERROR CONTEXT SNIPPETS ---\n"
            f"{combined_snippets}"
        )

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
        credentials = get_jenkins_credentials()
        if not credentials:
            raise ValueError("Jenkins credentials not configured. Check JENKINS_URL, JENKINS_USER, and JENKINS_API_TOKEN environment variables.")

        # Ensure job_name has proper /job/ separators for nested folders
        if "/job/" not in job_name and "/" in job_name:
            job_name = job_name.replace("/", "/job/")

        api_url = f"{JENKINS_URL}/job/{job_name}/{build_number}/api/json"

        async def fetch_info():
            timeout_config = httpx.Timeout(
                timeout=HTTP_TIMEOUT,
                connect=HTTP_CONNECT_TIMEOUT,
                read=HTTP_READ_TIMEOUT,
                write=HTTP_WRITE_TIMEOUT
            )
            async with httpx.AsyncClient(timeout=timeout_config, verify=JENKINS_VERIFY_SSL) as client:
                try:
                    response = await client.get(api_url, auth=credentials)
                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPStatusError as err:
                    if err.response.status_code == 401:
                        raise ValueError("Authentication failed. Please check your username and API token.")
                    elif err.response.status_code == 404:
                        raise ValueError(f"Job or build not found. Please check the job name and build number.")
                    else:
                        raise ValueError(f"HTTP Error: {err}")
                except httpx.RequestError as err:
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

        return "\n".join(result_lines)

    return mcp


def main():
    """Entry point for the server."""
    create_server().run(transport="http", host="0.0.0.0", port=SERVER_PORT, path=SERVER_PATH)


if __name__ == "__main__":
    main()
