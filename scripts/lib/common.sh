#!/bin/bash
# common.sh - Shared shell utilities for boss-skill scripts
# Source this file, then set LOG_TAG before calling functions.
# Example:
#   source "$(cd "$(dirname "$0")" && pwd)/../lib/common.sh"
#   LOG_TAG="HARNESS"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Default LOG_TAG (override after sourcing)
LOG_TAG="${LOG_TAG:-BOSS}"

# --- Standard logging (stdout, error to stderr) ---
info()    { echo -e "${BLUE}[${LOG_TAG}]${NC} $1"; }
success() { echo -e "${GREEN}[${LOG_TAG}]${NC} $1"; }
warn()    { echo -e "${YELLOW}[${LOG_TAG}]${NC} $1"; }
error()   { echo -e "${RED}[${LOG_TAG}]${NC} $1" >&2; exit 1; }

# --- Gate logging (all to stderr, stdout reserved for JSON) ---
gate_info() { echo -e "${BLUE}[${LOG_TAG}]${NC} $1" >&2; }
gate_pass() { echo -e "${GREEN}[${LOG_TAG}]${NC} ✅ $1" >&2; }
gate_fail() { echo -e "${RED}[${LOG_TAG}]${NC} ❌ $1" >&2; }

# --- Gate helper: add a check result to CHECKS json array ---
add_check() {
    local name="$1" passed="$2" detail="${3:-}"
    CHECKS=$(echo "$CHECKS" | jq \
        --arg name "$name" \
        --argjson passed "$passed" \
        --arg detail "$detail" \
        '. += [{"name": $name, "passed": $passed, "detail": $detail}]')
}

# --- Validation helpers ---
require_jq() {
    command -v jq >/dev/null 2>&1 || error "需要 jq 工具（brew install jq）"
}

require_exec_json() {
    local feature="$1"
    EXEC_JSON=".boss/$feature/.meta/execution.json"
    [[ -f "$EXEC_JSON" ]] || error "未找到执行文件: $EXEC_JSON"
}

validate_stage() {
    local stage="$1"
    [[ "$stage" =~ ^[1-4]$ ]] || error "stage 必须是 1-4"
}

# --- Date helpers (cross-platform: macOS -> Linux -> Node.js) ---
iso_now() {
    date -u +%Y-%m-%dT%H:%M:%SZ
}

date_ymd() {
    date +%Y-%m-%d
}

iso_to_epoch() {
    local ts="$1"
    # macOS (BSD date)
    if date -j -f "%Y-%m-%dT%H:%M:%SZ" "$ts" +%s 2>/dev/null; then
        return
    fi
    # GNU/Linux date
    if date -d "$ts" +%s 2>/dev/null; then
        return
    fi
    # Ultimate fallback: Node.js (available since project requires node >= 16)
    node -e "console.log(Math.floor(new Date('$ts').getTime()/1000))" 2>/dev/null || echo "0"
}
