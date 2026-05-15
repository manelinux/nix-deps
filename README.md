# nix-deps

A simple but powerful utility to inspect the real dependency cost of installing packages on NixOS.

```bash
nix-deps -k blender
nix-deps -k jamesdsp
nix-deps -k firefox
```

## Why?

On NixOS, installing a package can pull hundreds of dependencies into the Nix store.

However, most tools only show:
- the full closure size
- or the download size

They do not clearly explain:
- what is already available locally
- what actually needs downloading
- how much new disk space will really be used
- which packages are responsible for the largest costs

`nix-deps` solves that.

This tool is aimed at:
- NixOS newcomers trying to understand closures
- advanced users auditing dependency impact
- storage-conscious systems
- minimal setups

## Features

- 🔍 Analyze complete dependency closures directly from `cache.nixos.org`
- 📦 Shows real pending packages only
- 💾 Calculates actual additional SSD usage
- 🌐 Shows real download size after compression
- ⚡ Concurrent closure crawling for very fast analysis
- 📋 Detailed breakdown of largest pending dependencies
- 🧠 Detects packages already available in local `/nix/store`
- 🎨 Minimalist terminal UI inspired by classic Unix tools

## Example

```bash
nix-deps -k blender
```

Example output:

```text
🔍 nix-deps v1.9.0
   Keyword:    blender
   Channel:    nixos-unstable

  SUMMARY FOR BLENDER
  ──────────────────────────────────────────────────
  Total Closure (384 packages):
    Virtual Closure Size: 2.5 GB
    Resolved (Already OK): 329 packages
  ──────────────────────────────────────────────────
  Real Impact (55 packages pending):
    Estimated Download:   349.9 MB
    New Space on SSD:     1.4 GB (expanded)
  ──────────────────────────────────────────────────
  Pending Packages Break Down:
    ↳ blender-5.0.1                  DL: 72.8 MB Expanded: 269.7 MB
    ↳ python3.11-openusd-25.05.01    DL: 27.7 MB Expanded: 178.0 MB
    ↳ boost-1.87.0-dev               DL: 9.9 MB Expanded: 146.7 MB
```

## How It Works

`nix-deps`:
- evaluates the target derivation
- recursively crawls `.narinfo` metadata from `cache.nixos.org`
- reconstructs the full dependency closure
- compares it against the local `/nix/store`
- calculates the real incremental installation cost

No builds are performed.

## Installation

### Option 1 — Direct execution

```bash
chmod +x nix-deps.py
./nix-deps.py -k blender
```

### Option 2 — Install globally

```bash
sudo cp nix-deps.py /usr/local/bin/nix-deps
sudo chmod +x /usr/local/bin/nix-deps
```

## Usage

```bash
nix-deps [options]

Options:
  -k, --keyword <name>     Package keyword to analyze
  --channel <channel>      Nix channel (default: nixos-unstable)
  --limit <n>              Max search results (default: 40)
  -h, --help               Show help
```

## Requirements

- NixOS
- Python 3
- Internet access to `cache.nixos.org`

## Future Ideas

- JSON output
- Top dependency graphs
- Closure diffing between packages
- Export reports
- TUI mode
- Shared closure analysis

## License

MIT
