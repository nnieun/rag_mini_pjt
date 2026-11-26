"""Static checks for the Claude Code plugin in plugin/ai-basic-act.

The skills and commands name MCP tools, resources and prompts; these tests keep
those names in sync with what mcp_server actually registers.
"""

import json
import re
import unittest
from pathlib import Path

from mcp.shared.memory import create_connected_server_and_client_session

from mcp_server.server import build_server
from tests.test_agentic_features import AgenticFakePipeline
from tests.test_mcp_server import FakeAnswerer

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / "plugin" / "ai-basic-act"


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        raise AssertionError(f"{path} has no frontmatter")
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


class PluginManifestTest(unittest.TestCase):
    def test_manifests_are_consistent(self):
        plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
        marketplace = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
        entry = next(item for item in marketplace["plugins"] if item["name"] == plugin["name"])
        self.assertEqual((REPO / entry["source"]).resolve(), PLUGIN.resolve())
        self.assertEqual(entry["version"], plugin["version"])

        servers = json.loads((PLUGIN / ".mcp.json").read_text())["mcpServers"]
        self.assertEqual(servers["ai-basic-act"]["type"], "http")
        self.assertTrue(servers["ai-basic-act"]["url"].endswith("/mcp}"))

    def test_skills_and_commands_have_frontmatter(self):
        for name in ("compliance-check", "law-citation"):
            fields = frontmatter(PLUGIN / "skills" / name / "SKILL.md")
            self.assertEqual(fields["name"], name)
            self.assertGreater(len(fields["description"]), 30)
        for name in ("law", "compliance"):
            fields = frontmatter(PLUGIN / "commands" / f"{name}.md")
            self.assertTrue(fields["description"])
            self.assertIn("$ARGUMENTS", (PLUGIN / "commands" / f"{name}.md").read_text())


class PluginNamesMatchServerTest(unittest.IsolatedAsyncioTestCase):
    async def test_referenced_names_exist_on_server(self):
        server = build_server(AgenticFakePipeline, FakeAnswerer)
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            tools = {tool.name for tool in (await client.list_tools()).tools}
            prompts = {prompt.name for prompt in (await client.list_prompts()).prompts}
            resources = {str(item.uri) for item in (await client.list_resources()).resources}

        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [*PLUGIN.glob("skills/*/SKILL.md"), *PLUGIN.glob("commands/*.md")]
        )
        referenced = set(re.findall(r"`([a-z_]+)`(?:\(|로|를|가|이)", text))
        self.assertTrue(referenced, "no tool names found in plugin text")
        for name in referenced:
            self.assertIn(name, tools | prompts, f"{name} is not registered by mcp_server")
        for uri in re.findall(r"law://[a-z\-/{}_0-9]+", text):
            self.assertIn(uri, resources)


if __name__ == "__main__":
    unittest.main()
