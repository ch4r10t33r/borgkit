/// Embeds every file under `templates/` at compile time.
///
/// In debug builds (`debug-embed` feature) files are read from disk, giving
/// fast iteration without a full recompile when template content changes.
/// In release builds every file is baked into the binary.
///
/// Access a file:
///   `Templates::get("typescript/interfaces/IAgent.ts")`
///
/// Iterate a language sub-tree:
///   `Templates::iter().filter(|k| k.starts_with("python/"))`
#[derive(rust_embed::Embed)]
#[folder = "../templates/"]
pub struct Templates;
