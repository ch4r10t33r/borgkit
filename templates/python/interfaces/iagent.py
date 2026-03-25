"""
Sentrix agent interface.
Every Sentrix agent must implement this abstract base class.

Identity note
─────────────
``agent_id`` is required; ``owner`` is optional.
ERC-8004 on-chain registration is not required — a local secp256k1 key is
sufficient for signing ANR records and P2P discovery.
See identity.provider.LocalKeystoreIdentity for the default no-wallet option.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional
from .agent_request import AgentRequest
from .agent_response import AgentResponse


@dataclass
class ResourceRequirements:
    min_memory_mb:  Optional[int]   = None
    min_cpu_cores:  Optional[float] = None
    storage_gb:     Optional[float] = None


@dataclass
class AgentMetadata:
    name:                  str
    version:               str
    description:           Optional[str]                  = None
    author:                Optional[str]                  = None
    license:               Optional[str]                  = None
    repository:            Optional[str]                  = None
    tags:                  List[str]                      = field(default_factory=list)
    resource_requirements: Optional[ResourceRequirements] = None


class IAgent(ABC):
    # ── Identity ───────────────────────────────────────────────────────────
    agent_id: str                            # e.g. "sentrix://agent/0xABC..."
    owner: str              = "anonymous"    # Wallet address or arbitrary identifier.
                                             # Required for ERC-8004; optional otherwise.
    metadata_uri: Optional[str]          = None
    metadata:     Optional[AgentMetadata] = None

    # ── Capabilities ───────────────────────────────────────────────────────
    @abstractmethod
    def get_capabilities(self) -> List[str]:
        """Return list of capability names this agent exposes."""
        ...

    # ── Request handling ───────────────────────────────────────────────────
    @abstractmethod
    async def handle_request(self, request: AgentRequest) -> AgentResponse:
        """Primary dispatch — all inbound calls arrive here."""
        ...

    async def pre_process(self, request: AgentRequest) -> None:
        """Optional hook: auth, rate-limit, logging. Override as needed."""
        pass

    async def post_process(self, response: AgentResponse) -> None:
        """Optional hook: audit log, billing. Override as needed."""
        pass

    # ── Discovery (optional) ───────────────────────────────────────────────
    async def register_discovery(self) -> None:
        """Announce this agent to the discovery layer."""
        pass

    async def unregister_discovery(self) -> None:
        """Gracefully withdraw from the discovery layer."""
        pass

    # ── Delegation / permissions (optional) ────────────────────────────────
    async def check_permission(self, caller: str, capability: str) -> bool:
        """Return True if `caller` is permitted to invoke `capability`."""
        return True  # open by default; override for production

    # ── Signing (optional) ─────────────────────────────────────────────────
    async def sign_message(self, message: str) -> str:
        """EIP-712 compatible message signing. Override with your key."""
        raise NotImplementedError("sign_message not implemented")
