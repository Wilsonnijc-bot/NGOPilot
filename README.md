# NGOPilot

NGOPilot is a local AI agent tailored for NGO operations. It combines the
rebranded agent harness with NGOPilot MCP tools for CareFlow and roster
workflows.

## Repository Layout

- `harness bone/`: NGOPilot agent runtime, CLI, and desktop application
- `MCPcode/`: NGOPilot MCP server and four stateful NGO workflow tools
- `algo-dependencies/CareFlow/`: CareFlow algorithm dependency source
- `algo-dependencies/RosterCopiilot/`: roster algorithm dependency source

The product exposes one user-facing agent: NGOPilot. The MCP server runs as a
first-party stdio extension and retains ownership of workflow validation,
durable jobs, review state, and delivered artifacts.

See [Agent-MCP Architecture Design Plan.md](Agent-MCP%20Architecture%20Design%20Plan.md)
for the product architecture and
[MCP-pre-build algorithm design plan.md](MCP-pre-build%20algorithm%20design%20plan.md)
for the MCP and algorithm boundaries.
