# Sentrix Interfaces

All Sentrix agents speak the same four-interface language, regardless of the underlying framework or language they are written in. This document describes each interface, its fields, and its intended usage.

---

## IAgent

The root contract. Every Sentrix agent — whether built from scratch, wrapped from LangGraph, or adapted from Google ADK — must satisfy this interface.

```typescript
interface IAgent {
  // Identity
  readonly agentId:     string;        // "sentrix://agent/<address>"
  readonly owner:       string;        // wallet or contract address
  readonly metadataUri?: string;       // IPFS / Arweave pointer
  readonly metadata?:   AgentMetadata; // name, version, tags, …

  // Capabilities
  getCapabilities(): string[];

  // Request handling
  handleRequest(request: AgentRequest): Promise<AgentResponse>;
  preProcess?(request: AgentRequest):   Promise<void>;   // optional hook
  postProcess?(response: AgentResponse): Promise<void>;  // optional hook

  // Discovery (optional)
  registerDiscovery?():   Promise<void>;
  unregisterDiscovery?(): Promise<void>;

  // Delegation (optional)
  checkPermission?(caller: string, capability: string): Promise<boolean>;

  // Signing (optional)
  signMessage?(message: string): Promise<string>;
}
```

### Key fields

| Field | Required | Description |
|---|---|---|
| `agentId` | ✅ | Unique URI identifying this agent on the mesh |
| `owner` | optional | Wallet address or arbitrary identifier. Defaults to `"anonymous"`. Required only for ERC-8004 on-chain registration. |
| `getCapabilities()` | ✅ | Returns the list of capability names callers can invoke |
| `handleRequest()` | ✅ | The main dispatch method — all calls arrive here |
| `preProcess()` | optional | Hook for auth, rate-limiting, logging before dispatch |
| `postProcess()` | optional | Hook for audit logging, billing after response |
| `registerDiscovery()` | optional | Announce this agent to the discovery layer |
| `checkPermission()` | optional | ERC-8004 delegation / RBAC check |
| `signMessage()` | optional | EIP-712 compatible signing for verifiable responses |

### AgentMetadata

```typescript
// TypeScript
interface AgentMetadata {
  name:        string;
  version:     string;
  description?: string;
  author?:      string;
  license?:     string;
  repository?:  string;
  tags?:        string[];
  resourceRequirements?: {
    minMemoryMb?:  number;
    minCpuCores?:  number;
    storageGb?:    number;
  };
}
```

```python
# Python
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

@dataclass
class ResourceRequirements:
    min_memory_mb:  Optional[int]   = None
    min_cpu_cores:  Optional[float] = None
    storage_gb:     Optional[float] = None
```

---

## AgentRequest

The standard envelope for every inbound call. A caller — whether another agent, a wallet, or a user — always sends an `AgentRequest`.

```typescript
interface AgentRequest {
  requestId:   string;                    // UUID v4
  from:        string;                    // caller agent ID or wallet
  capability:  string;                    // which capability to invoke
  payload:     Record<string, unknown>;   // capability-specific args
  signature?:  string;                    // EIP-712 over this envelope
  timestamp?:  number;                    // Unix ms (stale-request guard)
  sessionKey?: string;                    // delegated execution key
  payment?:    PaymentInfo;              // optional micro-payment
}
```

### PaymentInfo

```typescript
interface PaymentInfo {
  type:     'oneshot' | 'stream' | 'subscription';
  token:    string;    // "USDC", "ETH", …
  amount:   string;    // human-readable, e.g. "0.001"
  txHash?:  string;    // pre-authorisation transaction
}
```

### Request lifecycle

```
Caller                          Agent
  │                               │
  │─── AgentRequest ─────────────>│
  │                          preProcess()
  │                          checkPermission()
  │                          handleRequest()
  │                          postProcess()
  │<── AgentResponse ─────────────│
```

---

## AgentResponse

The standard envelope returned by every capability invocation.

```typescript
interface AgentResponse {
  requestId:            string;                    // echoed from AgentRequest
  status:               'success' | 'error' | 'payment_required';
  result?:              Record<string, unknown>;   // capability-specific output
  errorMessage?:        string;                    // when status === 'error' or 'payment_required'
  proof?:               string;                    // optional ZK proof / attestation
  signature?:           string;                    // agent's EIP-712 signature
  timestamp?:           number;                    // Unix ms
  // x402 fields — present only when status === 'payment_required'
  paymentRequirements?: PaymentRequirement[];
}
```

### Status values

| Value | Meaning |
|---|---|
| `success` | Capability ran successfully; `result` contains the output |
| `error` | Capability failed; `errorMessage` describes why |
| `payment_required` | Caller must attach an x402 payment proof and retry; `paymentRequirements` lists what is accepted |

### Constructing responses (Python convenience)

```python
# Success
return AgentResponse.success(req.request_id, {"temp": 22, "city": "London"})

# Error
return AgentResponse.error(req.request_id, "City not found")
```

### Constructing responses (Rust convenience)

```rust
AgentResponse::success(req.request_id, json!({ "temp": 22 }))
AgentResponse::error(req.request_id, "City not found".into())
```

---

## IAgentDiscovery

The discovery layer contract. Swap the implementation to change the backend without touching any agent code.

```typescript
interface IAgentDiscovery {
  register(entry: DiscoveryEntry):   Promise<void>;
  unregister(agentId: string):       Promise<void>;
  query(capability: string):         Promise<DiscoveryEntry[]>;
  listAll():                         Promise<DiscoveryEntry[]>;
  heartbeat(agentId: string):        Promise<void>;
}
```

### DiscoveryEntry

```typescript
interface DiscoveryEntry {
  agentId:       string;
  name:          string;
  owner:         string;
  capabilities:  string[];
  network: {
    protocol:    'http' | 'websocket' | 'grpc' | 'tcp' | 'libp2p';
    host:        string;
    port:        number;
    tls:         boolean;
  };
  health: {
    status:         'healthy' | 'degraded' | 'unhealthy';
    lastHeartbeat:  string;    // ISO 8601
    uptimeSeconds:  number;
  };
  registeredAt:  string;       // ISO 8601
  metadataUri?:  string;
}
```

### Available implementations

| Class | Backend | Default? |
|---|---|---|
| `LocalDiscovery` | In-process map | ✅ Yes |
| `HttpDiscovery` | REST registry | ❌ Opt-in |
| `GossipDiscovery` | P2P gossip | 🚧 Coming |
| `OnChainDiscovery` | ERC-8004 | 🚧 Coming |

Use `DiscoveryFactory.create(config)` to select the right backend automatically. See [discovery.md](./discovery.md) for full details.

---

## Interface compatibility across languages

Every language template implements the same four interfaces with idiomatic naming:

| Concept | TypeScript | Python | Rust | Zig |
|---|---|---|---|---|
| Agent contract | `IAgent` | `IAgent` (ABC) | `IAgent` (trait) | `IAgent` (comptime vtable) |
| Request | `AgentRequest` | `AgentRequest` (dataclass) | `AgentRequest` (struct) | `AgentRequest` (struct) |
| Response | `AgentResponse` | `AgentResponse` (dataclass) | `AgentResponse` (struct) | `AgentResponse` (struct) |
| Discovery | `IAgentDiscovery` | `IAgentDiscovery` (ABC) | `IAgentDiscovery` (trait) | `LocalDiscovery` (struct) |

The **wire format** (JSON over HTTP, or RLP for ANR) is identical regardless of which language generated or consumed the message.
