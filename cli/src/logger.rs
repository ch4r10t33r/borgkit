use owo_colors::OwoColorize;

pub fn info(msg: &str) {
    println!("{} {}", "ℹ".cyan(), msg);
}

pub fn success(msg: &str) {
    println!("{} {}", "✔".green(), msg.green().to_string());
}

pub fn warn(msg: &str) {
    println!("{} {}", "⚠".yellow(), msg.yellow().to_string());
}

pub fn error(msg: &str) {
    eprintln!("{} {}", "✖".red(), msg.red().to_string());
}

pub fn title(msg: &str) {
    println!("\n{}", msg.bold().to_string());
}

pub fn dim(msg: &str) {
    println!("{}", msg.dimmed().to_string());
}

/// Print a tree entry, e.g. `  ├── src/agent.ts`
pub fn tree(prefix: &str, name: &str) {
    println!("  {} {}", prefix.bright_black(), name.cyan());
}

/// Print a key/value pair with aligned columns.
pub fn kv(key: &str, val: &str) {
    println!("  {:20} {}", key.bright_black(), val);
}
