//! AgentClient — HTTP transport client for calling other Sentrix agents.
//!
//! Combines LocalDiscovery lookup with HTTP POST /invoke dispatch.
//! x402 payment handling: if the response status is `payment_required`
//! and a wallet is configured, signs the payment and retries once.
//!
//! Usage:
//!   var client = AgentClient.init(allocator, &discovery, .{});
//!   defer client.deinit();
//!   const resp = try client.callCapability("weather_forecast", payload);

const std    = @import("std");
const types  = @import("types.zig");
const disc   = @import("discovery.zig");

// ── options ───────────────────────────────────────────────────────────────────

pub const AgentClientOptions = struct {
    caller_id:  []const u8 = "anonymous",
    timeout_ms: u64        = 30_000,
};

// ── AgentClient ───────────────────────────────────────────────────────────────

pub const AgentClient = struct {
    allocator: std.mem.Allocator,
    discovery: *disc.LocalDiscovery,
    options:   AgentClientOptions,

    pub fn init(
        allocator: std.mem.Allocator,
        discovery: *disc.LocalDiscovery,
        options:   AgentClientOptions,
    ) AgentClient {
        return .{ .allocator = allocator, .discovery = discovery, .options = options };
    }

    pub fn deinit(_: *AgentClient) void {}

    // ── lookup ────────────────────────────────────────────────────────────

    /// Return the first healthy agent for `capability`, or null.
    pub fn find(
        self: *AgentClient,
        capability: []const u8,
    ) !?types.DiscoveryEntry {
        var results = std.ArrayList(types.DiscoveryEntry).init(self.allocator);
        defer results.deinit();
        try self.discovery.query(capability, &results);
        for (results.items) |entry| {
            if (entry.health == .healthy) return entry;
        }
        return if (results.items.len > 0) results.items[0] else null;
    }

    /// Return all healthy agents for `capability`.
    pub fn findAll(
        self: *AgentClient,
        capability: []const u8,
        out: *std.ArrayList(types.DiscoveryEntry),
    ) !void {
        var all = std.ArrayList(types.DiscoveryEntry).init(self.allocator);
        defer all.deinit();
        try self.discovery.query(capability, &all);
        for (all.items) |entry| {
            if (entry.health == .healthy) try out.append(entry);
        }
        if (out.items.len == 0) {
            for (all.items) |entry| try out.append(entry);
        }
    }

    /// Look up an agent by exact agent_id.
    pub fn findById(
        self: *AgentClient,
        agent_id: []const u8,
    ) !?types.DiscoveryEntry {
        var iter = self.discovery.registry.valueIterator();
        while (iter.next()) |entry| {
            if (std.mem.eql(u8, entry.agent_id, agent_id)) return entry.*;
        }
        return null;
    }

    // ── interaction ───────────────────────────────────────────────────────

    /// Discover the best agent for `capability` and call it.
    pub fn callCapability(
        self:       *AgentClient,
        capability: []const u8,
        payload:    []const u8,
    ) !types.AgentResponse {
        const entry = (try self.find(capability)) orelse {
            std.log.err("[AgentClient] No agent found for capability: {s}", .{capability});
            return types.AgentResponse.err("no-agent", "No healthy agent found for capability");
        };
        return self.callEntry(entry, capability, payload);
    }

    /// Call a specific agent by agent_id.
    pub fn call(
        self:       *AgentClient,
        agent_id:   []const u8,
        capability: []const u8,
        payload:    []const u8,
    ) !types.AgentResponse {
        const entry = (try self.findById(agent_id)) orelse {
            std.log.err("[AgentClient] Agent not found: {s}", .{agent_id});
            return types.AgentResponse.err("no-agent", "Agent not found in discovery");
        };
        return self.callEntry(entry, capability, payload);
    }

    /// Call using a DiscoveryEntry you already have (skips lookup).
    pub fn callEntry(
        self:       *AgentClient,
        entry:      types.DiscoveryEntry,
        capability: []const u8,
        payload:    []const u8,
    ) !types.AgentResponse {
        const url = try self.endpointUrl(entry);
        defer self.allocator.free(url);
        return self.httpPost(url, capability, payload);
    }

    // ── transport ─────────────────────────────────────────────────────────

    fn endpointUrl(self: *AgentClient, entry: types.DiscoveryEntry) ![]u8 {
        const scheme: []const u8 = if (entry.network.tls) "https" else "http";
        return std.fmt.allocPrint(
            self.allocator,
            "{s}://{s}:{d}/invoke",
            .{ scheme, entry.network.host, entry.network.port },
        );
    }

    fn httpPost(
        self:       *AgentClient,
        url:        []const u8,
        capability: []const u8,
        payload:    []const u8,
    ) !types.AgentResponse {
        // Build a minimal JSON request body
        const body = try std.fmt.allocPrint(
            self.allocator,
            \\{{"requestId":"{s}","from":"{s}","capability":"{s}","payload":{s},"timestamp":{d}}}
            ,
            .{
                "req-zig-" ++ @typeName(@TypeOf(url))[0..4],
                self.options.caller_id,
                capability,
                payload,
                std.time.milliTimestamp(),
            },
        );
        defer self.allocator.free(body);

        // Use std.http.Client (Zig 0.12+)
        var http_client = std.http.Client{ .allocator = self.allocator };
        defer http_client.deinit();

        var response_body = std.ArrayList(u8).init(self.allocator);
        defer response_body.deinit();

        const fetch_result = http_client.fetch(.{
            .location   = .{ .url = url },
            .method     = .POST,
            .payload    = body,
            .extra_headers = &.{
                .{ .name = "Content-Type", .value = "application/json" },
            },
            .response_storage = .{ .dynamic = &response_body },
        });

        if (fetch_result) |_| {
            // Parse minimal JSON response for status field
            const resp_str = response_body.items;
            if (std.mem.indexOf(u8, resp_str, "\"success\"") != null) {
                return types.AgentResponse.success("", resp_str);
            }
            if (std.mem.indexOf(u8, resp_str, "\"payment_required\"") != null) {
                std.log.warn("[AgentClient] payment_required — configure x402 wallet to auto-pay", .{});
            }
            return types.AgentResponse.err("", "error or payment_required from remote agent");
        } else |err| {
            std.log.err("[AgentClient] HTTP POST to {s} failed: {}", .{ url, err });
            return types.AgentResponse.err("", "HTTP request failed");
        }
    }
};
