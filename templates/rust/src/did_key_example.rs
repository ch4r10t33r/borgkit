//! Example: derive a W3C **`did:key`** identifier from a secp256k1 secret (same shape as the
//! TypeScript `IdentityProvider` template).
//!
//! Multicodec prefix for **secp256k1 public key (compressed)** is `0xe7 0x01` per the multicodec
//! table. The multibase **`z`** prefix means **base58-btc** encoding of the prefixed key bytes.
//!
//! Run the runnable demo: `cargo run --example did_key_identity`

use k256::elliptic_curve::sec1::ToEncodedPoint;
use k256::SecretKey;

/// Multicodec code `secp256k1-pub` (varint) — compressed pubkey form.
const MULTICODEC_SECP256K1_PUB: [u8; 2] = [0xe7, 0x01];

/// Build `did:key:z...` from 32-byte secp256k1 secret scalar.
pub fn did_key_from_secret_key_bytes(secret: &[u8; 32]) -> Result<String, Box<dyn std::error::Error>> {
    let sk = SecretKey::from_slice(secret)?;
    let pk = sk.public_key();
    let enc = pk.to_encoded_point(true);
    let comp = enc.as_bytes();
    let mut payload = Vec::with_capacity(2 + comp.len());
    payload.extend_from_slice(&MULTICODEC_SECP256K1_PUB);
    payload.extend_from_slice(comp);
    Ok(format!("did:key:z{}", bs58::encode(&payload).into_string()))
}
