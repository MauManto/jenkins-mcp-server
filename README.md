# Jenkins MCP Server

A Model Context Protocol (MCP) server for fetching and analyzing Jenkins build console logs. Supports multiple Jenkins instances (named configurations) and automatic instance detection from job URLs.


## Features

- **Get Console Logs**: Fetch complete console output from Jenkins builds
- **Analyze Build Errors**: Extract error snippets with context from large logs
- **Extract Git Repositories**: Identify git repositories, branches, and commits used in builds
- **Get Build Information**: Retrieve build metadata (status, duration, triggers, etc.)

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd jenkins-mcp-server
```

2. Install dependencies:
```bash
uv sync
```

## Configuration

1. Create a `.env` file in the root directory (use `.env.example` as a template):
```bash
cp .env.example .env
```

2. Configure your Jenkins credentials:

### Single Jenkins Instance
For a single Jenkins server:
```env
JENKINS_URL=https://your-jenkins-instance.com
JENKINS_USER=your_username
JENKINS_API_TOKEN=your_api_token
```

### Multiple Jenkins Instances
If you have multiple Jenkins servers (e.g., legacy and current), you can configure them using named instances:

```env
# Default instance (backward compatible)
JENKINS_URL=https://jenkins.example.com
JENKINS_USER=default_user
JENKINS_API_TOKEN=default_token

# Legacy Jenkins
JENKINS_LEGACY_URL=https://jenkins-legacy.example.com
JENKINS_LEGACY_USER=legacy_user
JENKINS_LEGACY_API_TOKEN=legacy_token

# Current/Production Jenkins
JENKINS_CURRENT_URL=https://jenkins.production.example.com
JENKINS_CURRENT_USER=current_user
JENKINS_CURRENT_API_TOKEN=current_token
```

When using multiple instances, provide the **full Jenkins job URL** and the server will automatically use the correct instance:
- Example: `"https://jenkins-legacy.example.com/job/MyFolder/job/MyJob/lastBuild"`

The server matches the URL against configured instances and uses the appropriate credentials.

### Getting a Jenkins API Token

1. Log in to your Jenkins instance
2. Click on your username in the top-right corner
3. Click "Configure"
4. Under "API Token", click "Add new Token"
5. Give it a name and click "Generate"
6. Copy the token and add it to your `.env` file

## Usage

### Running the Server

```bash
uv run jenkins-mcp-server
```

Or run the Python file directly:
```bash
uv run python main.py
```

The server will start on `http://0.0.0.0:3000/mcp` (configurable via `SERVER_PORT` and `SERVER_PATH` environment variables)

### Available Tools

All tools require a **full Jenkins job URL** including the build number or alias.

**URL Format:**
```
https://jenkins.example.com/job/JobName/job/SubJob/lastBuild
```

**Build Aliases:**
- `lastBuild` - Most recent build
- `lastSuccessfulBuild` - Most recent successful build
- `lastFailedBuild` - Most recent failed build
- `lastCompletedBuild` - Most recent completed build

#### 1. `get_jenkins_console_log`
Fetch the complete console log for a Jenkins build.

**Parameters:**
- `job_url` (required): Full Jenkins job URL

**Example:**
```python
get_jenkins_console_log(
    job_url="https://jenkins.example.com/job/MyProject/job/my-application/123"
)
```

#### 2. `analyze_jenkins_build_errors`
Analyze a build log and extract error snippets. For large logs, it automatically extracts relevant error sections with surrounding context.

**Parameters:**
- `job_url` (required): Full Jenkins job URL

**Example:**
```python
analyze_jenkins_build_errors(
    job_url="https://jenkins.example.com/job/MyProject/job/my-application/lastFailedBuild"
)
```

#### 3. `get_jenkins_git_repositories`
Extract git repository information from a build's console log. Returns deduplicated list of repositories with URLs, branches, and commit hashes.

**Parameters:**
- `job_url` (required): Full Jenkins job URL

**Example:**
```python
get_jenkins_git_repositories(
    job_url="https://jenkins.example.com/job/MyProject/job/my-application/lastBuild"
)
```

#### 4. `get_jenkins_build_info`
Get metadata about a Jenkins build (status, duration, timestamp, etc.).

**Parameters:**
- `job_url` (required): Full Jenkins job URL

**Example:**
```python
get_jenkins_build_info(
    job_url="https://jenkins.example.com/job/MyProject/job/my-application/123"
)
```

## Configuration Options

You can customize the behavior using environment variables:

- `JENKINS_URL`: Your Jenkins instance URL
- `JENKINS_USER`: Your Jenkins username
- `JENKINS_API_TOKEN`: Your Jenkins API token
- `JENKINS_VERIFY_SSL`: Enable/disable SSL certificate verification (default: `true`). Set to `false` for self-signed certificates
- `MAX_LOG_SIZE`: Maximum log size (in characters) before extracting snippets (default: 250000)
- `CONTEXT_WINDOW`: Number of lines to include around errors (default: 2)
- `HTTP_TIMEOUT`: Overall HTTP request timeout in seconds (default: 30)
- `HTTP_CONNECT_TIMEOUT`: HTTP connection timeout in seconds (default: 10)
- `HTTP_READ_TIMEOUT`: HTTP read timeout in seconds (default: 120)
- `HTTP_WRITE_TIMEOUT`: HTTP write timeout in seconds (default: 10)
- `SERVER_PORT`: Port the MCP server listens on (default: 3000)
- `SERVER_PATH`: Path for the MCP endpoint (default: /mcp)
- `DEBUG`: Enable verbose debug logging (default: `false`). Set to `true` to see detailed logs including instance detection, API calls, and response sizes

### Debug Mode

Enable verbose logging to see detailed information about instance detection, API calls, and responses:

```env
DEBUG=true
```

When enabled, you'll see output like:
```
🔧 Configuration loaded (DEBUG MODE ENABLED):
   Jenkins instances configured: 2
     - https://jenkins.example.com (user: your_user)
     - https://jenkins-legacy.example.com (user: legacy_user)
   ...
```

### SSL Certificate Issues

If you're connecting to a Jenkins instance with a self-signed certificate and encounter SSL errors, you can disable SSL verification:

```env
JENKINS_VERIFY_SSL=false
```

**Note:** Disabling SSL verification should only be used in development/staging environments. For production, use proper SSL certificates.

## Development

### Running Tests
```bash
uv run pytest
```

### Linting
```bash
uv run ruff check .
```

### Type Checking
```bash
uv run pyright
```

## License

MIT
