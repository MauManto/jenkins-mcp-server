# Jenkins MCP Server

A Model Context Protocol (MCP) server for fetching and analyzing Jenkins build console logs.

## Features

- **Get Console Logs**: Fetch complete console output from Jenkins builds
- **Analyze Build Errors**: Extract error snippets with context from large logs
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
```env
JENKINS_URL=https://your-jenkins-instance.com
JENKINS_USER=your_username
JENKINS_API_TOKEN=your_api_token
```

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
uv run jenkins-mcp
```

Or run the Python file directly:
```bash
uv run python main.py
```

The server will start on `http://0.0.0.0:3000/mcp` (configurable via `SERVER_PORT` and `SERVER_PATH` environment variables)

### Available Tools

#### 1. `get_jenkins_console_log`
Fetch the complete console log for a Jenkins build.

**Parameters:**
- `job_name` (required): The Jenkins job name (e.g., "MyProject/job/my-application")
- `build_number` (optional): Build number or alias like "lastBuild", "lastFailedBuild" (default: "lastBuild")

**Example:**
```python
get_jenkins_console_log(
    job_name="MyProject/job/my-application",
    build_number="123"
)
```

#### 2. `analyze_jenkins_build_errors`
Analyze a build log and extract error snippets. For large logs, it automatically extracts relevant error sections with surrounding context.

**Parameters:**
- `job_name` (required): The Jenkins job name
- `build_number` (optional): Build number or alias (default: "lastBuild")
- `context_lines` (optional): Number of lines to include before/after errors (default: 15)

**Example:**
```python
analyze_jenkins_build_errors(
    job_name="MyProject/job/my-application",
    build_number="lastFailedBuild",
    context_lines=20
)
```

#### 3. `get_jenkins_build_info`
Get metadata about a Jenkins build (status, duration, timestamp, etc.).

**Parameters:**
- `job_name` (required): The Jenkins job name
- `build_number` (optional): Build number or alias (default: "lastBuild")

**Example:**
```python
get_jenkins_build_info(
    job_name="MyProject/job/my-application",
    build_number="123"
)
```

## Configuration Options

You can customize the behavior using environment variables:

- `JENKINS_URL`: Your Jenkins instance URL
- `JENKINS_USER`: Your Jenkins username
- `JENKINS_API_TOKEN`: Your Jenkins API token
- `JENKINS_VERIFY_SSL`: Enable/disable SSL certificate verification (default: `true`). Set to `false` for self-signed certificates
- `MAX_LOG_SIZE`: Maximum log size (in characters) before extracting snippets (default: 250000)
- `CONTEXT_WINDOW`: Number of lines to include around errors (default: 15)
- `HTTP_TIMEOUT`: Overall HTTP request timeout in seconds (default: 30)
- `HTTP_CONNECT_TIMEOUT`: HTTP connection timeout in seconds (default: 10)
- `HTTP_READ_TIMEOUT`: HTTP read timeout in seconds (default: 120)
- `HTTP_WRITE_TIMEOUT`: HTTP write timeout in seconds (default: 10)
- `SERVER_PORT`: Port the MCP server listens on (default: 3000)
- `SERVER_PATH`: Path for the MCP endpoint (default: /mcp)

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
