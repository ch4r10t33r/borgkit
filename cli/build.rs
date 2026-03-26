fn main() {
    // Embed the build date so `sentrix version` can print it.
    let date = chrono::Utc::now().format("%Y-%m-%d").to_string();
    println!("cargo:rustc-env=SENTRIX_BUILD_DATE={date}");
    // Re-run if any template file changes (dev workflow with debug-embed).
    println!("cargo:rerun-if-changed=../templates");
}
