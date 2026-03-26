//! Runnable template: in-memory **gossip fan-out** discovery between linked peers.
//!
//! ```text
//! cargo run --example gossip_fanout_discovery
//! ```

use std::sync::Arc;
use std::time::Duration;

use {{PROJECT_LIB}}::discovery::IAgentDiscovery;
use {{PROJECT_LIB}}::gossip_fanout_example::{demo_entry, GossipFanoutDiscovery};

#[tokio::main]
async fn main() {
    let a = GossipFanoutDiscovery::new("agent-a", 3);
    let b = GossipFanoutDiscovery::new("agent-b", 3);
    GossipFanoutDiscovery::link_peers(&a, &b).await;

    let entry = demo_entry("agent-a", "echo");
    if let Err(e) = a.register(entry).await {
        eprintln!("register: {e}");
        return;
    }

    tokio::time::sleep(Duration::from_millis(50)).await;

    match b.query("echo").await {
        Ok(found) => println!("agent-b sees {} echo-capable agent(s)", found.len()),
        Err(e) => eprintln!("query: {e}"),
    }
}
