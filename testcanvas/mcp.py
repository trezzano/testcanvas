from pathlib import Path

from mcp_server import MCPToolset
from testcanvas.models import ApplicationMap

# Directory holding the Markdown instruction files served to MCP clients.
_LLM_PROMPTS_DIR = Path(__file__).resolve().parent / "llm_prompts"

class ProductTools(MCPToolset):

    def get_server_instructions(self) -> str:
        """Return the top-level usage protocol for this MCP server.

        Loads the server-level instructions from the ``llm_prompts`` directory
        so an LLM client learns the mandatory two-step workflow: first call
        ``get_tool_instructions`` for the target tool, understand the returned
        rules, and only then invoke that tool with a compliant payload.

        Returns:
            The Markdown instructions describing the interaction protocol.

        Raises:
            ValueError: If the server instructions file is missing.
        """
        # The server-level instructions live in a dedicated Markdown file so
        # they can be edited without touching the Python source.
        instructions_file = _LLM_PROMPTS_DIR / "get_server_instructions.txt"
        if not instructions_file.exists():
            raise ValueError("No server instructions file found.")
        return instructions_file.read_text(encoding="utf-8")

    def get_tool_instructions(self, tool_name: str) -> str:
        """Return the usage instructions for a single MCP tool.

        Loads a tool-specific Markdown guide from the ``llm_prompts`` directory
        so a client (LLM agent) can learn exactly how to call a given tool
        before invoking it. Call this tool first for the target tool, then use
        the returned schema and rules to build the request.

        Args:
            tool_name: Name of the tool whose instructions are requested
                (e.g. ``"insert_flow_in_testcanvas"``).

        Returns:
            The Markdown instructions for the requested tool.

        Raises:
            ValueError: If no instructions file exists for ``tool_name``.
        """
        # Instruction files follow the ``<tool_name>_instructions.txt`` naming
        # convention inside the shared prompts directory.
        instructions_file = _LLM_PROMPTS_DIR / f"{tool_name}_instructions.txt"
        if not instructions_file.exists():
            raise ValueError(
                f"No instructions found for tool '{tool_name}'."
            )
        return instructions_file.read_text(encoding="utf-8")

    def insert_flow_in_testcanvas(self,
                          flow: dict,
                          name: str,
                          description: str = "",
                          ) -> dict:
        """Insert or update an application flow in the TestCanvas app.

        IMPORTANT: Before calling this tool, first call
        ``get_tool_instructions("insert_flow_in_testcanvas")`` to obtain the
        exact input schema and rules, then build the ``flow`` payload
        accordingly.

        Creates a new ``ApplicationMap`` or updates the existing one that
        matches ``name``, storing the provided Cytoscape.js graph in
        ``graph_data``. Saving the map keeps the relational ``FlowNode`` rows
        in sync with the graph nodes (handled by ``ApplicationMap.save``).

        Args:
            flow: Cytoscape.js graph data (``elements.nodes`` / ``elements.edges``)
                to store in the map's ``graph_data`` field.
            name: Unique name used to look up or create the ``ApplicationMap``.
            description: Optional human-readable description of the flow.

        Returns:
            A dict with ``ok`` set to ``True`` and ``flow_id`` (the map primary
            key) on success, or ``ok`` set to ``False`` and ``message`` with the
            error detail on failure.
        """
        try:
            application_map, created = ApplicationMap.objects.update_or_create(
                name=name,
                defaults={
                    "graph_data": flow,
                    "description": description,
                },
            )
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
        return {
            "ok": True,
            "flow_id": application_map.pk,
        }

