//! Runnable template: derive **`did:key:z…`** from a 32-byte secp256k1 secret.
//!
//! ```text
//! cargo run --example did_key_identity
//! ```

fn main() {
    // Demo scalar only — use a real secret from your keystore in production.
    let secret = [7u8; 32];
    match {{PROJECT_LIB}}::did_key_example::did_key_from_secret_key_bytes(&secret) {
        Ok(did) => println!("{did}"),
        Err(e) => eprintln!("{e}"),
    }
}
