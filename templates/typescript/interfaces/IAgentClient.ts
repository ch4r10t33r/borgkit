/**
 * IAgentClient — standard interface for discovering and calling Sentrix agents.
 *
 * Combines lookup (find by capability / agent ID) with invocation
 * (send AgentRequest, receive AgentResponse) in a single coherent API.
 *
 * Quick start
 * -----------
 * import { AgentClient }     from './IAgentClient';
 * import { DiscoveryFactory } from '../discovery/DiscoveryFactory';
 *
 * const discovery = DiscoveryFactory.create({ type: 'local' });
 * const client    = new AgentClient(discovery);
 *
 * // Discover-and-call in one step:
 * const resp = await client.callCapability('weather_forecast', { city: 'NYC' });
 *
 * // With x402 auto-payment:
 * import { MockWalletProvider } from '../addons/x402/client';
 * const client = new AgentClient(discovery, { x402Wallet: new MockWalletProvider(), autoPay: true });
 * const resp = await client.callCapability('premium_analysis', { query: '...' });
 */

import type { AgentResponse }  from './IAgentResponse';
import type { DiscoveryEntry } from './IAgentDiscovery';
import type { IAgentDiscovery } from './IAgentDiscovery';
import { AgentRequest }        from './IAgentRequest';  // will use for construction
import * as crypto             from 'crypto';

// ── interface ─────────────────────────────────────────────────────────────────

export interface IAgentClient {

  // ── Lookup ─────────────────────────────────────────────────────────────────

  /**
   * Find the best healthy agent that exposes `capability`.
   * Returns null if no agent is registered for this capability.
   */
  find(capability: string): Promise<DiscoveryEntry | null>;

  /** Return all healthy agents that expose `capability`. */
  findAll(capability: string): Promise<DiscoveryEntry[]>;

  /**
   * Look up a specific agent by agent ID.
   * Returns null if not found in the discovery layer.
   */
  findById(agentId: string): Promise<DiscoveryEntry | null>;

  // ── Interaction ────────────────────────────────────────────────────────────

  /**
   * Call a specific agent by its agentId.
   *
   * Looks up the agent's endpoint via discovery, builds an AgentRequest,
   * and dispatches it over HTTP transport to `{protocol}://{host}:{port}/invoke`.
   */
  call(
    agentId:    string,
    capability: string,
    payload:    Record<string, unknown>,
    options?:   CallOptions,
  ): Promise<AgentResponse>;

  /**
   * Discover the best agent for `capability` then call it in one step.
   * Returns an error AgentResponse if no healthy agent is found.
   */
  callCapability(
    capability: string,
    payload:    Record<string, unknown>,
    options?:   CallOptions,
  ): Promise<AgentResponse>;

  /**
   * Call an agent using a DiscoveryEntry you already have (skips lookup).
   */
  callEntry(
    entry:      DiscoveryEntry,
    capability: string,
    payload:    Record<string, unknown>,
    options?:   CallOptions,
  ): Promise<AgentResponse>;
}

export interface CallOptions {
  /** Identity of the calling agent (default: "anonymous"). */
  callerId?:   string;
  /** Request timeout in milliseconds (default: 30 000). */
  timeoutMs?:  number;
}

// ── AgentClient — HTTP transport implementation ───────────────────────────────

export interface AgentClientOptions {
  /** Default caller identity injected into every AgentRequest. */
  callerId?:   string;
  /** Default HTTP timeout in milliseconds. */
  timeoutMs?:  number;
  /**
   * WalletProvider for automatic x402 payment handling.
   * If omitted, payment_required responses are returned as-is.
   */
  x402Wallet?: import('../addons/x402/client').WalletProvider;
  /** If true, pays x402 challenges without calling onPaymentRequired(). */
  autoPay?:    boolean;
}

export class AgentClient implements IAgentClient {
  private readonly discovery:  IAgentDiscovery;
  private readonly callerId:   string;
  private readonly timeoutMs:  number;
  private readonly x402Wallet: import('../addons/x402/client').WalletProvider | undefined;
  private readonly autoPay:    boolean;

  constructor(discovery: IAgentDiscovery, options: AgentClientOptions = {}) {
    this.discovery  = discovery;
    this.callerId   = options.callerId  ?? 'anonymous';
    this.timeoutMs  = options.timeoutMs ?? 30_000;
    this.x402Wallet = options.x402Wallet;
    this.autoPay    = options.autoPay ?? false;
  }

  // ── lookup ──────────────────────────────────────────────────────────────────

  async find(capability: string): Promise<DiscoveryEntry | null> {
    const entries = await this.discovery.query(capability);
    const healthy = entries.filter(e => e.health.status === 'healthy');
    return healthy[0] ?? entries[0] ?? null;
  }

  async findAll(capability: string): Promise<DiscoveryEntry[]> {
    const entries = await this.discovery.query(capability);
    const healthy = entries.filter(e => e.health.status === 'healthy');
    return healthy.length > 0 ? healthy : entries;
  }

  async findById(agentId: string): Promise<DiscoveryEntry | null> {
    const all = await this.discovery.listAll();
    return all.find(e => e.agentId === agentId) ?? null;
  }

  // ── interaction ─────────────────────────────────────────────────────────────

  async call(
    agentId: string,
    capability: string,
    payload: Record<string, unknown>,
    options: CallOptions = {},
  ): Promise<AgentResponse> {
    const entry = await this.findById(agentId);
    if (!entry) {
      return errorResponse(`Agent not found in discovery: ${agentId}`);
    }
    return this.callEntry(entry, capability, payload, options);
  }

  async callCapability(
    capability: string,
    payload: Record<string, unknown>,
    options: CallOptions = {},
  ): Promise<AgentResponse> {
    const entry = await this.find(capability);
    if (!entry) {
      return errorResponse(`No healthy agent found for capability: '${capability}'`);
    }
    return this.callEntry(entry, capability, payload, options);
  }

  async callEntry(
    entry: DiscoveryEntry,
    capability: string,
    payload: Record<string, unknown>,
    options: CallOptions = {},
  ): Promise<AgentResponse> {
    const req = buildRequest(
      options.callerId ?? this.callerId,
      capability,
      payload,
    );
    return this.dispatch(entry, req, options.timeoutMs ?? this.timeoutMs);
  }

  // ── transport ────────────────────────────────────────────────────────────────

  private async dispatch(
    entry: DiscoveryEntry,
    req: Record<string, unknown>,
    timeoutMs: number,
  ): Promise<AgentResponse> {
    const url = endpointUrl(entry);
    let resp = await httpPost(url, req, timeoutMs);

    // x402 auto-payment
    if (resp.status === 'payment_required' && this.x402Wallet) {
      const reqs: unknown[] = (resp as any).paymentRequirements ?? [];
      if (reqs.length > 0) {
        const { X402PaymentRequirements } = await import('../addons/x402/types');
        const requirements = X402PaymentRequirements.fromDict(reqs[0] as Record<string, unknown>);
        const payment = await this.x402Wallet.signPayment(requirements, req as any);
        const paidReq = { ...req, x402: payment };
        resp = await httpPost(url, paidReq, timeoutMs);
      }
    }

    return resp;
  }
}

// ── helpers ───────────────────────────────────────────────────────────────────

function endpointUrl(entry: DiscoveryEntry): string {
  const scheme = entry.network.tls
    ? 'https'
    : ['http', 'https'].includes(entry.network.protocol) ? entry.network.protocol : 'http';
  return `${scheme}://${entry.network.host}:${entry.network.port}/invoke`;
}

function buildRequest(
  callerId: string,
  capability: string,
  payload: Record<string, unknown>,
): Record<string, unknown> {
  return {
    requestId:  crypto.randomUUID(),
    from:       callerId,
    capability,
    payload,
    timestamp:  Date.now(),
  };
}

async function httpPost(
  url: string,
  body: Record<string, unknown>,
  timeoutMs: number,
): Promise<AgentResponse> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
      signal:  controller.signal,
    });
    const data = await res.json() as Record<string, unknown>;
    return normaliseResponse(data);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return errorResponse(`HTTP request failed: ${msg}`);
  } finally {
    clearTimeout(timer);
  }
}

function normaliseResponse(d: Record<string, unknown>): AgentResponse {
  return {
    requestId:          (d.requestId ?? d.request_id ?? '') as string,
    status:             (d.status ?? 'error') as AgentResponse['status'],
    result:             d.result as Record<string, unknown> | undefined,
    errorMessage:       (d.errorMessage ?? d.error_message) as string | undefined,
    proof:              d.proof as string | undefined,
    signature:          d.signature as string | undefined,
    timestamp:          (d.timestamp ?? Date.now()) as number,
    paymentRequirements: d.paymentRequirements as unknown[] | undefined,
  } as AgentResponse;
}

function errorResponse(message: string): AgentResponse {
  return {
    requestId:    crypto.randomUUID(),
    status:       'error',
    errorMessage: message,
    timestamp:    Date.now(),
  } as AgentResponse;
}
