//! Example: **gossip fan-out** discovery — same idea as `templates/typescript/discovery/GossipDiscovery.ts`.
//!
//! Each node keeps a local registry. On `register`, an **announce** message is **fanned out**
//! to every linked peer with TTL decay; duplicates are dropped via a seen set. When TTL hits
//! zero, forwarding stops. Hops run **sequentially** so the async graph stays `Send`-safe;
//! production code can use bounded workers or per-peer tasks instead.
//!
//! Link nodes with [`GossipFanoutDiscovery::link_peers`], then use
//! `IAgentDiscovery` on the shared [`std::sync::Arc`] returned from [`GossipFanoutDiscovery::new`].
//!
//! Run: `cargo run --example gossip_fanout_discovery`

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Weak};
use tokio::sync::Mutex;

use crate::discovery::{DiscoveryEntry, HealthStatus, IAgentDiscovery, NetworkInfo};

/// Gossip payload mirrored loosely on the TypeScript `GossipMessage` shape.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GossipMessage {
    pub kind: String,
    pub sender_id: String,
    pub timestamp_millis: i64,
    pub ttl: u32,
    pub seen_by: Vec<String>,
    pub nonce: u64,
    pub entry: Option<DiscoveryEntry>,
}

pub struct GossipFanoutDiscovery {
    agent_id: String,
    default_ttl: u32,
    registry: Mutex<HashMap<String, DiscoveryEntry>>,
    seen: Mutex<HashSet<String>>,
    peers: Mutex<Vec<Weak<GossipFanoutDiscovery>>>,
}

impl GossipFanoutDiscovery {
    pub fn new(agent_id: impl Into<String>, default_ttl: u32) -> Arc<Self> {
        Arc::new(Self {
            agent_id: agent_id.into(),
            default_ttl,
            registry: Mutex::new(HashMap::new()),
            seen: Mutex::new(HashSet::new()),
            peers: Mutex::new(Vec::new()),
        })
    }

    /// Bidirectional link (weak pointers avoid reference cycles).
    pub async fn link_peers(a: &Arc<Self>, b: &Arc<Self>) {
        a.peers.lock().await.push(Arc::downgrade(b));
        b.peers.lock().await.push(Arc::downgrade(a));
    }

    fn dedup_key(msg: &GossipMessage) -> String {
        format!("{}:{}:{}", msg.sender_id, msg.timestamp_millis, msg.nonce)
    }

    /// Apply an incoming gossip message and optionally forward with `ttl - 1`.
    pub async fn deliver_incoming(self: Arc<Self>, mut msg: GossipMessage) {
        let key = Self::dedup_key(&msg);
        {
            let mut seen = self.seen.lock().await;
            if seen.contains(&key) {
                return;
            }
            seen.insert(key);
        }

        match msg.kind.as_str() {
            "announce" => {
                if let Some(ref e) = msg.entry {
                    self.registry.lock().await.insert(e.agent_id.clone(), e.clone());
                }
            }
            "revoke" => {
                if let Some(ref e) = msg.entry {
                    self.registry.lock().await.remove(&e.agent_id);
                }
            }
            "heartbeat" => {
                if let Some(e) = self.registry.lock().await.get_mut(&msg.sender_id) {
                    e.health = HealthStatus {
                        status: "healthy".into(),
                        last_heartbeat: chrono::Utc::now().to_rfc3339(),
                        uptime_seconds: 0,
                    };
                }
            }
            _ => {}
        }

        if msg.ttl == 0 {
            return;
        }

        msg.ttl -= 1;
        msg.seen_by.push(self.agent_id.clone());

        // Collect targets with the peer lock dropped before awaiting (Send-safe, template-friendly).
        let mut next_hops: Vec<(Arc<Self>, GossipMessage)> = Vec::new();
        {
            let peers = self.peers.lock().await;
            for w in peers.iter() {
                if let Some(peer) = w.upgrade() {
                    if msg.seen_by.contains(&peer.agent_id) {
                        continue;
                    }
                    let mut forwarded = msg.clone();
                    forwarded.seen_by = msg.seen_by.clone();
                    next_hops.push((peer, forwarded));
                }
            }
        }
        for (peer, forwarded) in next_hops {
            peer.deliver_incoming(forwarded).await;
        }
    }

    async fn broadcast(self: &Arc<Self>, msg: GossipMessage) {
        self.clone().deliver_incoming(msg).await;
    }
}

#[async_trait]
impl IAgentDiscovery for Arc<GossipFanoutDiscovery> {
    async fn register(&self, entry: DiscoveryEntry) -> Result<(), Box<dyn std::error::Error>> {
        self.registry.lock().await.insert(entry.agent_id.clone(), entry.clone());
        let msg = GossipMessage {
            kind: "announce".into(),
            sender_id: self.agent_id.clone(),
            timestamp_millis: chrono::Utc::now().timestamp_millis(),
            ttl: self.default_ttl,
            seen_by: vec![],
            nonce: rand_u64(),
            entry: Some(entry),
        };
        self.broadcast(msg).await;
        Ok(())
    }

    async fn unregister(&self, agent_id: &str) -> Result<(), Box<dyn std::error::Error>> {
        let entry = self.registry.lock().await.remove(agent_id);
        if let Some(entry) = entry {
            let msg = GossipMessage {
                kind: "revoke".into(),
                sender_id: self.agent_id.clone(),
                timestamp_millis: chrono::Utc::now().timestamp_millis(),
                ttl: self.default_ttl,
                seen_by: vec![],
                nonce: rand_u64(),
                entry: Some(entry),
            };
            self.broadcast(msg).await;
        }
        Ok(())
    }

    async fn query(&self, capability: &str) -> Result<Vec<DiscoveryEntry>, Box<dyn std::error::Error>> {
        let reg = self.registry.lock().await;
        let out = reg
            .values()
            .filter(|e| e.capabilities.contains(&capability.to_string()) && e.health.status != "unhealthy")
            .cloned()
            .collect();
        Ok(out)
    }

    async fn list_all(&self) -> Result<Vec<DiscoveryEntry>, Box<dyn std::error::Error>> {
        Ok(self.registry.lock().await.values().cloned().collect())
    }

    async fn heartbeat(&self, agent_id: &str) -> Result<(), Box<dyn std::error::Error>> {
        if let Some(e) = self.registry.lock().await.get_mut(agent_id) {
            e.health = HealthStatus {
                status: "healthy".into(),
                last_heartbeat: chrono::Utc::now().to_rfc3339(),
                uptime_seconds: 0,
            };
        }
        let msg = GossipMessage {
            kind: "heartbeat".into(),
            sender_id: agent_id.to_string(),
            timestamp_millis: chrono::Utc::now().timestamp_millis(),
            ttl: 1,
            seen_by: vec![],
            nonce: rand_u64(),
            entry: None,
        };
        self.broadcast(msg).await;
        Ok(())
    }
}

fn rand_u64() -> u64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0)
}

/// Build a tiny [`DiscoveryEntry`] for demos.
pub fn demo_entry(agent_id: &str, capability: &str) -> DiscoveryEntry {
    DiscoveryEntry {
        agent_id: agent_id.into(),
        name: "demo".into(),
        owner: "demo-owner".into(),
        capabilities: vec![capability.into()],
        network: NetworkInfo {
            protocol: "http".into(),
            host: "127.0.0.1".into(),
            port: 6174,
            tls: false,
            peer_id: String::new(),
            multiaddr: String::new(),
        },
        health: HealthStatus {
            status: "healthy".into(),
            last_heartbeat: chrono::Utc::now().to_rfc3339(),
            uptime_seconds: 0,
        },
        registered_at: chrono::Utc::now().to_rfc3339(),
        metadata_uri: None,
    }
}
