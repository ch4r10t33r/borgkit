"""
OnChainDiscovery — ERC-8004 on-chain agent registry.

Stores and queries agent records via a deployed ERC-8004 contract.
Requires web3.py >= 6.0 and a funded wallet for write operations.

Usage:
    from discovery.onchain_discovery import OnChainDiscovery, OnChainDiscoveryConfig

    cfg = OnChainDiscoveryConfig(
        rpc_url          = "https://mainnet.base.org",
        contract_address = "0xYourDeployedRegistry",
        private_key      = os.environ["AGENT_PRIVATE_KEY"],  # hex, with or without 0x
    )
    registry = OnChainDiscovery(cfg)
    await registry.register(entry)
    results  = await registry.query("translate_text")
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

try:
    from web3 import AsyncWeb3
    from web3.providers import AsyncHTTPProvider
    from web3.exceptions import ContractLogicError
    from eth_account import Account
    _WEB3_OK = True
except ImportError:
    _WEB3_OK = False

from interfaces.iagent_discovery import IAgentDiscovery, DiscoveryEntry, NetworkInfo, HealthStatus


# ── ERC-8004 contract ABI (minimal subset) ────────────────────────────────────

_ERC8004_ABI = [
    {
        "name": "registerAgent",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "agentId",      "type": "string"},
            {"name": "name",         "type": "string"},
            {"name": "owner",        "type": "string"},
            {"name": "capabilities", "type": "string[]"},
            {"name": "protocol",     "type": "string"},
            {"name": "host",         "type": "string"},
            {"name": "port",         "type": "uint256"},
            {"name": "tls",          "type": "bool"},
            {"name": "metadataUri",  "type": "string"},
        ],
        "outputs": [],
    },
    {
        "name": "unregisterAgent",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "agentId", "type": "string"}],
        "outputs": [],
    },
    {
        "name": "heartbeat",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "agentId", "type": "string"}],
        "outputs": [],
    },
    {
        "name": "getAgent",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "agentId", "type": "string"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple",
                "components": [
                    {"name": "agentId",       "type": "string"},
                    {"name": "name",          "type": "string"},
                    {"name": "owner",         "type": "string"},
                    {"name": "capabilities",  "type": "string[]"},
                    {"name": "protocol",      "type": "string"},
                    {"name": "host",          "type": "string"},
                    {"name": "port",          "type": "uint256"},
                    {"name": "tls",           "type": "bool"},
                    {"name": "registeredAt",  "type": "uint256"},
                    {"name": "lastHeartbeat", "type": "uint256"},
                    {"name": "metadataUri",   "type": "string"},
                    {"name": "active",        "type": "bool"},
                ],
            }
        ],
    },
    {
        "name": "queryByCapability",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "capability", "type": "string"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple[]",
                "components": [
                    {"name": "agentId",       "type": "string"},
                    {"name": "name",          "type": "string"},
                    {"name": "owner",         "type": "string"},
                    {"name": "capabilities",  "type": "string[]"},
                    {"name": "protocol",      "type": "string"},
                    {"name": "host",          "type": "string"},
                    {"name": "port",          "type": "uint256"},
                    {"name": "tls",           "type": "bool"},
                    {"name": "registeredAt",  "type": "uint256"},
                    {"name": "lastHeartbeat", "type": "uint256"},
                    {"name": "metadataUri",   "type": "string"},
                    {"name": "active",        "type": "bool"},
                ],
            }
        ],
    },
    {
        "name": "listAll",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [
            {
                "name": "",
                "type": "tuple[]",
                "components": [
                    {"name": "agentId",       "type": "string"},
                    {"name": "name",          "type": "string"},
                    {"name": "owner",         "type": "string"},
                    {"name": "capabilities",  "type": "string[]"},
                    {"name": "protocol",      "type": "string"},
                    {"name": "host",          "type": "string"},
                    {"name": "port",          "type": "uint256"},
                    {"name": "tls",           "type": "bool"},
                    {"name": "registeredAt",  "type": "uint256"},
                    {"name": "lastHeartbeat", "type": "uint256"},
                    {"name": "metadataUri",   "type": "string"},
                    {"name": "active",        "type": "bool"},
                ],
            }
        ],
    },
    # Events
    {
        "name": "AgentRegistered",
        "type": "event",
        "inputs": [
            {"name": "agentId",      "type": "string",   "indexed": True},
            {"name": "name",         "type": "string",   "indexed": False},
            {"name": "owner",        "type": "address",  "indexed": True},
            {"name": "capabilities", "type": "string[]", "indexed": False},
        ],
    },
    {
        "name": "AgentUnregistered",
        "type": "event",
        "inputs": [
            {"name": "agentId", "type": "string", "indexed": True},
        ],
    },
    {
        "name": "AgentHeartbeat",
        "type": "event",
        "inputs": [
            {"name": "agentId",   "type": "string",  "indexed": True},
            {"name": "timestamp", "type": "uint256", "indexed": False},
        ],
    },
]


# ── Config dataclass ───────────────────────────────────────────────────────────

@dataclass
class OnChainDiscoveryConfig:
    rpc_url: str
    contract_address: str
    private_key: str = ""       # hex private key; empty = read-only
    chain_id: int = 8453        # Base mainnet default
    gas_limit: int = 300_000

    # ERC-8004 contract ABI (minimal subset)
    abi: list = field(default_factory=lambda: _ERC8004_ABI)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _health_from_heartbeat(last_heartbeat_ts: int) -> str:
    """Derive health status string from a Unix-seconds heartbeat timestamp."""
    if last_heartbeat_ts == 0:
        return "unhealthy"
    now = datetime.now(tz=timezone.utc).timestamp()
    age_seconds = now - last_heartbeat_ts
    if age_seconds <= 900:       # 15 minutes
        return "healthy"
    if age_seconds <= 1800:      # 30 minutes
        return "degraded"
    return "unhealthy"


def _ts_to_iso(ts: int) -> str:
    """Convert a Unix-seconds timestamp to an ISO 8601 UTC string."""
    if ts == 0:
        return ""
    return datetime.utcfromtimestamp(ts).isoformat() + "Z"


def _from_record(r) -> DiscoveryEntry:
    """
    Convert an ERC-8004 AgentRecord tuple (or named tuple from web3.py) into
    a DiscoveryEntry.

    Expected field order (matches ABI above):
      0  agentId
      1  name
      2  owner
      3  capabilities  (string[])
      4  protocol
      5  host
      6  port          (uint256)
      7  tls           (bool)
      8  registeredAt  (uint256, Unix seconds)
      9  lastHeartbeat (uint256, Unix seconds)
      10 metadataUri
      11 active        (bool)
    """
    # web3.py may return named tuples; index access works for both
    agent_id       = r[0]
    name           = r[1]
    owner          = r[2]
    capabilities   = list(r[3])
    protocol       = r[4]
    host           = r[5]
    port           = int(r[6])
    tls            = bool(r[7])
    registered_at  = _ts_to_iso(int(r[8]))
    last_heartbeat = int(r[9])
    metadata_uri   = r[10] if r[10] else None

    health_status  = _health_from_heartbeat(last_heartbeat)
    last_hb_iso    = _ts_to_iso(last_heartbeat)

    return DiscoveryEntry(
        agent_id=agent_id,
        name=name,
        owner=owner,
        capabilities=capabilities,
        network=NetworkInfo(
            protocol=protocol,
            host=host,
            port=port,
            tls=tls,
        ),
        health=HealthStatus(
            status=health_status,
            last_heartbeat=last_hb_iso,
        ),
        registered_at=registered_at,
        metadata_uri=metadata_uri,
    )


# ── OnChainDiscovery ──────────────────────────────────────────────────────────

class OnChainDiscovery(IAgentDiscovery):
    """ERC-8004 on-chain agent registry adapter."""

    def __init__(self, config: OnChainDiscoveryConfig) -> None:
        if not _WEB3_OK:
            raise RuntimeError(
                "web3 not installed — pip install web3"
            )
        self._cfg = config
        self._w3 = AsyncWeb3(AsyncHTTPProvider(config.rpc_url))
        self._contract = self._w3.eth.contract(
            address=AsyncWeb3.to_checksum_address(config.contract_address),
            abi=config.abi,
        )
        # Normalise private key once; store as None when absent
        pk = config.private_key.strip()
        if pk and not pk.startswith("0x"):
            pk = "0x" + pk
        self._private_key: Optional[str] = pk or None

    # ── write helpers ─────────────────────────────────────────────────────────

    def _require_key(self) -> str:
        if not self._private_key:
            raise PermissionError(
                "OnChainDiscovery: private_key required for write operations"
            )
        return self._private_key

    async def _send(self, fn) -> str:
        """Build, sign, and broadcast a contract transaction. Returns tx hash."""
        pk = self._require_key()
        account = Account.from_key(pk)
        nonce = await self._w3.eth.get_transaction_count(account.address)
        tx = await fn.build_transaction({
            "from":     account.address,
            "nonce":    nonce,
            "gas":      self._cfg.gas_limit,
            "chainId":  self._cfg.chain_id,
        })
        signed = Account.sign_transaction(tx, pk)
        tx_hash = await self._w3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash.hex()

    # ── IAgentDiscovery impl ──────────────────────────────────────────────────

    async def register(self, entry: DiscoveryEntry) -> None:
        fn = self._contract.functions.registerAgent(
            entry.agent_id,
            entry.name,
            entry.owner,
            entry.capabilities,
            entry.network.protocol,
            entry.network.host,
            entry.network.port,
            entry.network.tls,
            entry.metadata_uri or "",
        )
        try:
            tx_hash = await self._send(fn)
        except ContractLogicError as exc:
            raise RuntimeError(
                f"OnChainDiscovery: registerAgent reverted — {exc}"
            ) from exc
        print(f"[OnChainDiscovery] Registered {entry.agent_id} (tx={tx_hash})")

    async def unregister(self, agent_id: str) -> None:
        fn = self._contract.functions.unregisterAgent(agent_id)
        try:
            tx_hash = await self._send(fn)
        except ContractLogicError as exc:
            raise RuntimeError(
                f"OnChainDiscovery: unregisterAgent reverted — {exc}"
            ) from exc
        print(f"[OnChainDiscovery] Unregistered {agent_id} (tx={tx_hash})")

    async def query(self, capability: str) -> List[DiscoveryEntry]:
        try:
            records = await self._contract.functions.queryByCapability(
                capability
            ).call()
        except ContractLogicError as exc:
            raise RuntimeError(
                f"OnChainDiscovery: queryByCapability reverted — {exc}"
            ) from exc
        return [_from_record(r) for r in records]

    async def list_all(self) -> List[DiscoveryEntry]:
        try:
            records = await self._contract.functions.listAll().call()
        except ContractLogicError as exc:
            raise RuntimeError(
                f"OnChainDiscovery: listAll reverted — {exc}"
            ) from exc
        return [_from_record(r) for r in records]

    async def heartbeat(self, agent_id: str) -> None:
        fn = self._contract.functions.heartbeat(agent_id)
        try:
            tx_hash = await self._send(fn)
        except ContractLogicError as exc:
            raise RuntimeError(
                f"OnChainDiscovery: heartbeat reverted — {exc}"
            ) from exc
        print(f"[OnChainDiscovery] Heartbeat {agent_id} (tx={tx_hash})")

    # find() is intentionally inherited from IAgentDiscovery (default impl)
