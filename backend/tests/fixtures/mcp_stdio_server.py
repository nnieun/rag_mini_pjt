"""stdio MCP server backed by the fake pipeline, for the subprocess test.

Runs the same `build_server(...).run("stdio")` path as `python -m mcp_server`,
without Qdrant or an LLM.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp_server.server import build_server  # noqa: E402
from tests.test_agentic_features import AgenticFakePipeline  # noqa: E402
from tests.test_mcp_server import FakeAnswerer  # noqa: E402

if __name__ == "__main__":
    build_server(AgenticFakePipeline, FakeAnswerer).run("stdio")
