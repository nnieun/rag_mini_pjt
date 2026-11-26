"""Run the MCP server over stdio: `uv run python -m mcp_server`."""

from mcp_server.server import build_server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
