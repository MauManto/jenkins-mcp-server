import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from main import analyze_log_for_errors, create_server, get_jenkins_credentials


class TestGetJenkinsCredentials:
    """Test the credentials validation function."""

    def test_valid_credentials(self):
        """Test that valid credentials are returned correctly."""
        with patch.dict(os.environ, {
            "JENKINS_URL": "https://jenkins.test.com",
            "JENKINS_USER": "testuser",
            "JENKINS_API_TOKEN": "testtoken123"
        }):
            # Need to reload the module to pick up env changes
            import importlib
            import main
            importlib.reload(main)

            credentials = main.get_jenkins_credentials()
            assert credentials is not None
            assert credentials == ("testuser", "testtoken123")

    def test_missing_credentials(self):
        """Test that None is returned when credentials are missing."""
        with patch.dict(os.environ, {
            "JENKINS_URL": "",
            "JENKINS_USER": "",
            "JENKINS_API_TOKEN": ""
        }):
            import importlib
            import main
            importlib.reload(main)

            credentials = main.get_jenkins_credentials()
            assert credentials is None


class TestAnalyzeLogForErrors:
    """Test the log analysis function."""

    def test_simple_error_detection(self):
        """Test detecting a simple error in logs."""
        log = """Line 1
Line 2
Line 3
ERROR: Something went wrong
Line 5
Line 6"""

        snippets = analyze_log_for_errors(log, context_window=2)
        assert len(snippets) == 1
        assert "ERROR: Something went wrong" in snippets[0]
        assert "Line 2" in snippets[0]
        assert "Line 6" in snippets[0]

    def test_multiple_errors(self):
        """Test detecting multiple errors in logs."""
        log = """Line 1
ERROR: First error
Line 3
Line 4
Line 5
Line 6
Line 7
Line 8
Line 9
Line 10
EXCEPTION: Second error
Line 12"""

        snippets = analyze_log_for_errors(log, context_window=2)
        assert len(snippets) == 2
        assert "ERROR: First error" in snippets[0]
        assert "EXCEPTION: Second error" in snippets[1]

    def test_overlapping_errors(self):
        """Test that overlapping error contexts are handled correctly."""
        log = """Line 1
ERROR: First error
Line 3
FAILED: Second error
Line 5"""

        snippets = analyze_log_for_errors(log, context_window=5)
        # Should merge into one snippet since they overlap
        assert len(snippets) == 1
        assert "ERROR: First error" in snippets[0]
        assert "FAILED: Second error" in snippets[0]

    def test_no_errors(self):
        """Test log with no errors."""
        log = """Line 1
Line 2
Line 3
All good here
Line 5"""

        snippets = analyze_log_for_errors(log, context_window=2)
        assert len(snippets) == 0

    def test_case_insensitive_detection(self):
        """Test that error detection is case-insensitive."""
        log = """Line 1
Error: lowercase error
Line 3
EXCEPTION: uppercase exception
Line 5
FaIlUrE: mixed case failure"""

        snippets = analyze_log_for_errors(log, context_window=1)
        assert len(snippets) == 3

    def test_traceback_detection(self):
        """Test detecting Python-style tracebacks."""
        log = """Running tests...
Traceback (most recent call last):
  File "test.py", line 10, in <module>
    raise ValueError("Test error")
ValueError: Test error
Test completed"""

        snippets = analyze_log_for_errors(log, context_window=2)
        # May detect multiple snippets due to "traceback" and "error" keywords
        assert len(snippets) >= 1
        # Check that at least one snippet contains the traceback
        combined = " ".join(snippets)
        assert "Traceback" in combined
        assert "ValueError" in combined

    def test_empty_log(self):
        """Test empty log."""
        snippets = analyze_log_for_errors("", context_window=2)
        assert len(snippets) == 0


class TestJenkinsTools:
    """Test the MCP tools with mocked HTTP responses."""

    @pytest.fixture
    def mock_credentials(self):
        """Fixture to mock Jenkins credentials."""
        with patch("main.get_jenkins_credentials") as mock:
            mock.return_value = ("testuser", "testtoken")
            yield mock

    @pytest.fixture
    def server(self):
        """Fixture to create the MCP server."""
        return create_server()

    def test_server_creation(self, server):
        """Test that server can be created successfully."""
        assert server is not None
        assert hasattr(server, "run")
