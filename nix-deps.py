#!/usr/bin/env python3
"""
nix-deps: Analyzes the dependency cost of installing a NixOS package.
Compares internet cache closures against local store paths.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# --- Colors (Matching nix-search.sh) ---
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
CYAN = '\033[0;36m'
MAGENTA = '\033[0;35m'
BOLD = '\033[1m'
DIM = '\033[2m'
RESET = '\033[0m'

def c(color, text): return f"{color}{text}{RESET}"
def bold(t): return c(BOLD, t)
def dim(t):  return c(DIM, t)

# --- Helpers ---
def human_bytes(n):
    if n is None or n == 0: return dim("0 B")
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

def run(cmd, **kw):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, **kw)
        return result.stdout.strip(), result.returncode
    except Exception:
        return "", -1

# --- Layout Headers (Minimalist) ---
def print_header_block(label):
    print("")
    print(f"{BOLD}{CYAN}══════════════════════════════════════════{RESET}")
    print(f"{BOLD}{GREEN}  {label}{RESET}")
    print(f"{BOLD}{CYAN}══════════════════════════════════════════{RESET}")

# --- Nix Local Store Paths ---
def get_local_paths():
    paths = set()
    store = Path("/nix/store")
    if store.exists():
        try:
            for p in store.iterdir():
                if p.is_dir():
                    paths.add(p.name)
        except Exception:
            pass
    return paths

# --- Detect Version in Local Store ---
def find_local_installed_version(pkg_name):
    store = Path("/nix/store")
    if not store.exists():
        return None, None
        
    best_path = None
    best_version = None
    pattern = re.compile(rf"^[a-z0-9]{{32}}-{re.escape(pkg_name)}-([\d\.]+[^/]*)$")
    
    try:
        for p in store.iterdir():
            if p.is_dir():
                match = pattern.match(p.name)
                if match:
                    ver = match.group(1)
                    if not best_version or ver > best_version:
                        best_version = ver
                        best_path = str(p)
    except Exception:
        pass
        
    return best_path, best_version

# --- Package Search ---
def search_packages(keyword, channel="nixos-unstable", limit=50):
    keyword_lower = keyword.lower()
    results = _search_via_nix_cli(keyword_lower, channel, limit)
    if results:
        return results
    return _search_via_json_index(keyword_lower, channel, limit)

def _search_via_nix_cli(keyword, channel, limit):
    cmd = ["nix", "search", "nixpkgs", keyword, "--json", "--extra-experimental-features", "nix-command flakes"]
    out, rc = run(cmd, timeout=30)
    if rc != 0 or not out.strip():
        return []

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []

    results = []
    for attr, info in data.items():
        parts = attr.split(".")
        if "legacyPackages" in parts:
            idx = parts.index("legacyPackages")
            attr_clean = ".".join(parts[idx+2:])
        else:
            attr_clean = parts[-1] if parts else attr

        if keyword not in attr_clean.lower():
            continue

        results.append({
            "attr":    attr_clean if attr_clean else attr,
            "name":    attr_clean,
            "version": info.get("version", ""),
            "desc":    info.get("description", ""),
        })
        if len(results) >= limit:
            break
    return results

def _search_via_json_index(keyword, channel, limit):
    url = f"https://search.nixos.org/api/search?channel={channel}&query={keyword}&type=packages&size={limit}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (nix-deps)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception:
        return []

    results = []
    hits = data.get("hits", {}).get("hits", [])
    for hit in hits:
        src = hit.get("_source", {})
        pkg_name = src.get("package_attr_name", "")
        if keyword not in pkg_name.lower():
            continue
        results.append({
            "attr":    pkg_name,
            "name":    pkg_name,
            "version": src.get("package_version", ""),
            "desc":    src.get("package_description", ""),
        })
    return results

# --- Fetch metadata and references directly from cache.nixos.org ---
def fetch_narinfo_by_hash(nar_hash):
    url = f"https://cache.nixos.org/{nar_hash}.narinfo"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            content = resp.read().decode()
        
        file_size = 0
        nar_size = 0
        references = []
        store_path = ""

        for line in content.splitlines():
            if line.startswith("StorePath:"):
                store_path = line.split(":", 1)[1].strip()
            elif line.startswith("FileSize:"):
                file_size = int(line.split(":", 1)[1].strip())
            elif line.startswith("NarSize:"):
                nar_size = int(line.split(":", 1)[1].strip())
            elif line.startswith("References:"):
                refs_raw = line.split(":", 1)[1].strip()
                if refs_raw:
                    references = refs_raw.split()
        return {"store_path": store_path, "file_size": file_size, "nar_size": nar_size, "references": references}
    except Exception:
        return None

# --- Recursively resolve full remote closure from cache.nixos.org ---
def resolve_remote_closure(root_hash):
    closure = {}
    to_visit = [root_hash]
    visited = set()

    while to_visit:
        current_batch = [h for h in to_visit if h not in visited]
        to_visit = []
        if not current_batch:
            break

        with ThreadPoolExecutor(max_workers=15) as ex:
            future_to_hash = {ex.submit(fetch_narinfo_by_hash, h): h for h in current_batch}
            for future in as_completed(future_to_hash):
                h = future_to_hash[future]
                visited.add(h)
                res = future.result()
                if res:
                    closure[h] = res
                    for ref_name in res["references"]:
                        ref_hash = ref_name.split("-")[0]
                        if ref_hash not in visited and ref_hash not in to_visit:
                            to_visit.append(ref_hash)
    return closure

# --- Interactive Selection ---
def pick_package(packages):
    print_header_block("📦 PACKAGES FOUND")
    
    for i, pkg in enumerate(packages, 1):
        num = f"  {BOLD}{i:>2}.{RESET}"
        name = bold(pkg["name"])
        ver = dim(f"v{pkg['version']}") if pkg.get('version') else ""
        desc = dim(pkg.get("desc", "")[:70]) if pkg.get("desc") else ""
        print(f"{num}  {name} {ver}")
        if desc: 
            print(f"        {desc}")
    print("")

    while True:
        try:
            raw = input(f"  {bold('Select a number')} {dim('(or q to quit)')}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
        if raw.lower() in ("q", "quit", "exit"):
            sys.exit(0)
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(packages):
                return packages[idx]
        print(c(YELLOW, f"  ⚠  Invalid number. Choose a value between 1 and {len(packages)}."))

# --- Main Analysis Logic ---
def analyze(pkg, local_store_names):
    attr_name = pkg["attr"]
    remote_version = pkg.get("version", "")

    print(f"\n  {bold('Evaluating base path derivation for')} {c(CYAN, attr_name)} ...")
    
    cmd_eval = ["nix-instantiate", "--eval", "-E", f'(import <nixpkgs> {{}}).{attr_name}.outPath']
    out_eval, rc_e = run(cmd_eval)
    if rc_e != 0 or not out_eval:
        print(c(RED, f"  ✗ Could not evaluate channel expression for '{attr_name}'."))
        return
        
    target_path = out_eval.strip().strip('"')
    target_basename = os.path.basename(target_path)
    root_hash = target_basename.split("-")[0]

    print(f"  {bold('Resolving complete dependency closure directly from cache.nixos.org')} ...")
    closure = resolve_remote_closure(root_hash)

    if not closure:
        print(c(RED, f"  ✗ Failed to crawl cache closure metadata."))
        return

    resolved_count = 0
    pending_count = 0
    
    # Mides de la closure global (el mapa teòric complet)
    closure_download = 0
    closure_installed = 0
    
    # Mides reals del que falta (el que realment s'afegirà)
    pending_download = 0
    pending_installed = 0
    
    pending_details = []

    # Classificació i suma separada
    for h, data in closure.items():
        path_name = os.path.basename(data["store_path"])
        
        # Sumem sempre a la closure global
        closure_download += data["file_size"]
        closure_installed += data["nar_size"]
        
        # Mirem si ja el tenim localment
        if path_name in local_store_names:
            resolved_count += 1
        else:
            pending_count += 1
            pending_download += data["file_size"]
            pending_installed += data["nar_size"]

            clean_pkg_name = "-".join(path_name.split("-")[1:])
            pending_details.append((clean_pkg_name, data["file_size"], data["nar_size"]))

    # Ordenem els detalls pendents de més gran a més petit
    pending_details.sort(key=lambda x: x[1], reverse=True)

    _, local_version = find_local_installed_version(pkg["name"])

    # PRESENTACIÓ MINIMALISTA RETOCADA
    print(f"\n  {BOLD}SUMMARY FOR {pkg['name'].upper()}{RESET}")
    print(f"  " + "─" * 50)

    if local_version and remote_version and local_version != remote_version:
        print(f"  {c(YELLOW, '⚠ Update Available:')} New release v{remote_version} available on channel.")
        print(f"  {dim('Current System:')}    v{local_version}")
        print(f"  " + "─" * 50)
    elif local_version:
        print(f"  {c(GREEN, '✓ Status:')}           v{local_version} (Up to date)")
        print(f"  " + "─" * 50)

    # 1. Total Closure
    print(f"  {BOLD}Total Closure ({len(closure)} packages):{RESET}")
    print(f"    Virtual Closure Size: {c(DIM, human_bytes(closure_installed))}")
    print(f"    Resolved (Already OK): {c(GREEN, str(resolved_count))} packages")
    print(f"  " + "─" * 50)

    # 2. Impacte real
    print(f"  {BOLD}Real Impact ({pending_count} packages pending):{RESET}")
    print(f"    Estimated Download:   {c(CYAN, human_bytes(pending_download))}")
    print(f"    New Space on SSD:     {c(BLUE, human_bytes(pending_installed))} (expanded)")
    print(f"  " + "─" * 50)
    
    # 3. Detall del pending
    if pending_details:
        print(f"  {BOLD}Pending Packages Break Down:{RESET}")
        for name, f_size, n_size in pending_details[:15]:
            print(
                f"    ↳ {name[:30]:<30} "
                f"{dim('DL:')} {c(CYAN, human_bytes(f_size)):<8} "
                f"{dim('Expanded:')} {c(BLUE, human_bytes(n_size))}"
            )

        if len(pending_details) > 15:
            print(f"    ... and {len(pending_details) - 15} more small packages.")

        print(f"  " + "─" * 50)
    
    print(f"  {MAGENTA}↳ Net Disk Cost:{RESET} {BOLD}{human_bytes(pending_installed)}{RESET} will be added to your system.\n")

if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(prog="nix-deps")
        parser.add_argument("-k", "--keyword", required=True)
        parser.add_argument("--channel", default="nixos-unstable")
        parser.add_argument("--limit", type=int, default=40)
        args = parser.parse_args()

        print(f"\n{BOLD}🔍 nix-deps{RESET} {MAGENTA}v1.9.0{RESET}")
        keyword = args.keyword.strip().lower()
        print(f"   Keyword:    {CYAN}{keyword}{RESET}")
        print(f"   Channel:    {CYAN}{args.channel}{RESET}")
        
        print(f"\n  {bold('Searching')} packages matching {c(CYAN, repr(keyword))} ...")
        packages = search_packages(keyword, channel=args.channel, limit=args.limit)

        if not packages:
            print(c(RED, f"\n  ✗ No packages found matching '{keyword}'."))
            sys.exit(1)

        pkg = packages[0] if len(packages) == 1 else pick_package(packages)
        
        print(f"  {bold('Reading Nix local store ...')}")
        local_store_names = get_local_paths()
        
        analyze(pkg, local_store_names)
        
    except Exception as e:
        import traceback
        print(c(RED, f"\n  ✗ Script failed catastrophically!"))
        print(dim(traceback.format_exc()))
        sys.exit(1)
