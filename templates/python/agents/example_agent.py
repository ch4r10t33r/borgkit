"""
ExampleAgent — starter template.
Replace the capability implementations with your own logic.
"""

from interfaces import IAgent, AgentRequest, AgentResponse
from discovery.local_discovery import LocalDiscovery
from interfaces.iagent_discovery import DiscoveryEntry, NetworkInfo, HealthStatus
from datetime import datetime, timezone


class ExampleAgent(IAgent):
    # ── ERC-8004 Identity ─────────────────────────────────────────────────
    agent_id     = "sentrix://agent/example"
    owner        = "0xYourWalletAddress"
    metadata_uri = "ipfs://QmYourMetadataHashHere"
    metadata     = {
        "name":        "ExampleAgent",
        "version":     "0.1.0",
        "description": "A starter Sentrix agent",
        "tags":        ["example", "starter"],
    }

    # ── Capabilities ──────────────────────────────────────────────────────
    def get_capabilities(self):
        return ["echo", "ping"]

    # ── Request handling ──────────────────────────────────────────────────
    async def handle_request(self, req: AgentRequest) -> AgentResponse:
        if not await self.check_permission(req.from_id, req.capability):
            return AgentResponse.error(req.request_id, "Permission denied")

        match req.capability:
            case "echo":
                return AgentResponse.success(req.request_id, {"echo": req.payload})
            case "ping":
                return AgentResponse.success(req.request_id, {"pong": True, "agentId": self.agent_id})
            case _:
                return AgentResponse.error(req.request_id, f'Unknown capability: "{req.capability}"')

    # ── Discovery ─────────────────────────────────────────────────────────
    async def register_discovery(self) -> None:
        registry = LocalDiscovery.get_instance()
        await registry.register(DiscoveryEntry(
            agent_id=self.agent_id,
            name="ExampleAgent",
            owner=self.owner,
            capabilities=self.get_capabilities(),
            network=NetworkInfo(protocol="http", host="localhost", port=8080),
            health=HealthStatus(
                status="healthy",
                last_heartbeat=datetime.now(timezone.utc).isoformat()
            ),
            registered_at=datetime.now(timezone.utc).isoformat(),
        ))
        print("[ExampleAgent] registered with discovery layer")

    async def unregister_discovery(self) -> None:
        await LocalDiscovery.get_instance().unregister(self.agent_id)


# ── Entry point ───────────────────────────────────────────────────────────────
#
# Run directly:
#   python agents/example_agent.py
#   SENTRIX_PORT=9090 python agents/example_agent.py
#
# Or via sentrix-cli:
#   sentrix run ExampleAgent --port 8080
#
if __name__ == "__main__":
    import asyncio
    import os
    from server import serve

    port = int(os.environ.get("SENTRIX_PORT", "8080"))

    agent = ExampleAgent()
    asyncio.run(serve(agent, port=port))
