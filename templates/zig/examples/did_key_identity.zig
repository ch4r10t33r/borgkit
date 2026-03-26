//! Example: build a **`did:key`** string from a **compressed secp256k1 public key** (33 bytes).
//!
//! Matches the multicodec prefix **`secp256k1-pub`** (`0xe7 0x01`) + compressed SEC1 point, then
//! **base58-btc** (multibase `z`), same as the TypeScript `IdentityProvider` template.
//!
//! Supply the compressed pubkey from your secp256k1 library (e.g. after scalar multiplication).
//! This demo uses the secp256k1 generator point as a fixed test vector.
//!
//! Build: `zig build examples`  (or `zig build install` then run `example-did-key`)

const std = @import("std");

/// Multicodec `secp256k1-pub` (compressed) per https://github.com/multiformats/multicodec
const multicodec_secp256k1_pub = [2]u8{ 0xe7, 0x01 };

const b58_alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

/// Base58-btc encode (no checksum) for multibase `z`.
fn base58BtcEncode(allocator: std.mem.Allocator, input: []const u8) ![]u8 {
    if (input.len == 0) return try allocator.dupe(u8, "1");

    var leading: usize = 0;
    for (input) |b| {
        if (b == 0) leading += 1 else break;
    }

    var buf = try allocator.alloc(u8, input.len);
    defer allocator.free(buf);
    @memcpy(buf, input);

    var out = std.ArrayList(u8).init(allocator);
    errdefer out.deinit();

    while (true) {
        var all_zero = true;
        for (leading..buf.len) |i| {
            if (buf[i] != 0) {
                all_zero = false;
                break;
            }
        }
        if (all_zero) break;

        var rem: u32 = 0;
        for (leading..buf.len) |i| {
            rem = rem * 256 + @as(u32, buf[i]);
            buf[i] = @truncate(rem / 58);
            rem %= 58;
        }
        try out.append(b58_alphabet[@intCast(rem)]);
    }

    for (0..leading) |_| try out.append('1');

    std.mem.reverse(u8, out.items);
    return try out.toOwnedSlice();
}

/// `did:key:z` + base58(multicodec || compressed_pubkey).
pub fn didKeyFromCompressedSecp256k1Pubkey(allocator: std.mem.Allocator, compressed: *const [33]u8) ![]u8 {
    var payload: [2 + 33]u8 = undefined;
    payload[0..2].* = multicodec_secp256k1_pub;
    @memcpy(payload[2..][0..33], compressed);

    const enc = try base58BtcEncode(allocator, &payload);
    defer allocator.free(enc);

    const prefix = "did:key:z";
    const out = try allocator.alloc(u8, prefix.len + enc.len);
    @memcpy(out[0..prefix.len], prefix);
    @memcpy(out[prefix.len..], enc);
    return out;
}

pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa.deinit();
    const allocator = gpa.allocator();

    // secp256k1 generator, compressed (standard test vector).
    const pk_hex = "0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798";
    var comp: [33]u8 = undefined;
    _ = try std.fmt.hexToBytes(&comp, pk_hex);

    const did = try didKeyFromCompressedSecp256k1Pubkey(allocator, &comp);
    defer allocator.free(did);

    const stdout = std.io.getStdOut().writer();
    try stdout.print("{s}\n", .{did});
}
