import { IAgent, AgentMetadata } from '../interfaces/IAgent';
import { AgentRequest }           from '../interfaces/IAgentRequest';
import { AgentResponse }          from '../interfaces/IAgentResponse';
import { DiscoveryEntry }         from '../interfaces/IAgentDiscovery';

/**
 * ExampleAgent — starter template.
 * Replace the capability implementations with your own logic.
 */
export class ExampleAgent implements IAgent {
  // ─── ERC-8004 Identity ────────────────────────────────────────────────────
  readonly agentId     = 'sentrix://agent/example';
  readonly owner       = '0xYourWalletAddress';
  readonly metadataUri = 'ipfs://QmYourMetadataHashHere';
  readonly metadata: AgentMetadata = {
    name:        'ExampleAgent',
    version:     '0.1.0',
    description: 'A starter Sentrix agent',
    tags:        ['example', 'starter'],
  };

  // ─── Capabilities ─────────────────────────────────────────────────────────
  getCapabilities(): string[] {
    return ['echo', 'ping'];
  }

  // ─── Request handling ─────────────────────────────────────────────────────
  async handleRequest(req: AgentRequest): Promise<AgentResponse> {
    // Optional: enforce permissions
    if (this.checkPermission) {
      const allowed = await this.checkPermission(req.from, req.capability);
      if (!allowed) {
        return { requestId: req.requestId, status: 'error', errorMessage: 'Permission denied' };
      }
    }

    switch (req.capability) {
      case 'echo':
        return {
          requestId: req.requestId,
          status:    'success',
          result:    { echo: req.payload },
          timestamp: Date.now(),
        };

      case 'ping':
        return {
          requestId: req.requestId,
          status:    'success',
          result:    { pong: true, agentId: this.agentId },
          timestamp: Date.now(),
        };

      default:
        return {
          requestId:    req.requestId,
          status:       'error',
          errorMessage: `Unknown capability: "${req.capability}"`,
        };
    }
  }

  // ─── Discovery ────────────────────────────────────────────────────────────
  async registerDiscovery(): Promise<void> {
    // TODO: swap LocalDiscovery for GossipDiscovery or OnChainDiscovery
    const { LocalDiscovery } = await import('../discovery/LocalDiscovery');
    const registry = LocalDiscovery.getInstance();
    await registry.register({
      agentId:      this.agentId,
      name:         this.metadata.name,
      owner:        this.owner,
      capabilities: this.getCapabilities(),
      network:      { protocol: 'http', host: 'localhost', port: 8080, tls: false },
      health:       { status: 'healthy', lastHeartbeat: new Date().toISOString(), uptimeSeconds: 0 },
      registeredAt: new Date().toISOString(),
    });
    console.log(`[ExampleAgent] registered with discovery layer`);
  }

  async unregisterDiscovery(): Promise<void> {
    const { LocalDiscovery } = await import('../discovery/LocalDiscovery');
    await LocalDiscovery.getInstance().unregister(this.agentId);
  }

  // ─── ANR / Identity exposure ──────────────────────────────────────────────
  getAnr(): DiscoveryEntry {
    return {
      agentId:      this.agentId,
      name:         this.metadata.name,
      owner:        this.owner,
      capabilities: this.getCapabilities(),
      network:      { protocol: 'http', host: 'localhost', port: 8080, tls: false },
      health:       { status: 'healthy', lastHeartbeat: new Date().toISOString(), uptimeSeconds: 0 },
      registeredAt: new Date().toISOString(),
      metadataUri:  this.metadataUri,
    };
  }

  async getPeerId(): Promise<string | null> {
    // ExampleAgent has no signing key — swap for LocalKeystoreIdentity to get a real PeerId.
    return null;
  }

  // ─── Permissions ──────────────────────────────────────────────────────────
  async checkPermission(_caller: string, _capability: string): Promise<boolean> {
    // TODO: implement ERC-8004 delegation checks
    return true; // open by default for development
  }
}

// ── Entry point ───────────────────────────────────────────────────────────────
//
// Run directly:
//   npx ts-node agents/ExampleAgent.ts
//   SENTRIX_PORT=9090 npx ts-node agents/ExampleAgent.ts
//
// Or via sentrix-cli:
//   sentrix run ExampleAgent --port 8080
//
if (require.main === module) {
  (async () => {
    const { serve } = await import('../server');
    const port = parseInt(process.env.SENTRIX_PORT ?? '8080', 10);
    const agent = new ExampleAgent();
    await serve(agent, { port });
  })();
}
