#!/usr/bin/env bash
set -e
set -u
set -o pipefail

# ==============================================================================
# LowaCode AI Tutor - System Performance Tuning Script
# ==============================================================================

# --- Colors and Output ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "\n${BLUE}=== [$step/$TOTAL_STEPS] $1 ===${NC}"; step=$((step + 1)); }

step=1
TOTAL_STEPS=7

SUMMARY_CHANGED=()
SUMMARY_SKIPPED=()

add_changed() { SUMMARY_CHANGED+=("$1"); }
add_skipped() { SUMMARY_SKIPPED+=("$1"); }

# --- Pre-flight Checks ---
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root. Please use sudo."
    exit 1
fi

REAL_USER=${SUDO_USER:-$USER}
if [[ "$REAL_USER" == "root" ]]; then
    log_warn "SUDO_USER is root. Memlock settings will be applied to root. It is recommended to run this via sudo from a normal user."
fi

# Detect WSL2
IS_WSL2=false
if grep -qi microsoft /proc/version; then
    IS_WSL2=true
    log_info "WSL2 environment detected. Skipping some hardware-specific optimizations."
fi


# --- Step 1: Shared Memory Increase to 4 GB ---
log_step "Configuring Shared Memory (/dev/shm) to 4GB"

current_shm=$(df -h /dev/shm | awk 'NR==2 {print $2}')
log_info "Current /dev/shm size: $current_shm"

if grep -q "tmpfs.*/dev/shm" /etc/fstab; then
    if grep "tmpfs.*/dev/shm" /etc/fstab | grep -q "size=4g"; then
        log_info "/dev/shm is already configured for 4GB in /etc/fstab"
        add_skipped "Shared Memory (/dev/shm)"
    else
        sed -i 's|tmpfs[[:space:]]*/dev/shm.*|tmpfs /dev/shm tmpfs defaults,size=4g 0 0|' /etc/fstab
        mount -o remount /dev/shm
        log_success "/dev/shm size updated to 4GB in /etc/fstab"
        add_changed "Shared Memory (/dev/shm)"
    fi
else
    echo "tmpfs /dev/shm tmpfs defaults,size=4g 0 0" >> /etc/fstab
    mount -o remount /dev/shm
    log_success "/dev/shm entry added to /etc/fstab (4GB)"
    add_changed "Shared Memory (/dev/shm)"
fi

new_shm=$(df -h /dev/shm | awk 'NR==2 {print $2}')
log_info "New /dev/shm size: $new_shm"


# --- Step 2: Swap Memory Increase to 12 GB ---
log_step "Configuring Swap Memory to 12GB"

if $IS_WSL2; then
    log_warn "WSL2 detected: Custom swapfile approach is not supported directly in WSL."
    log_info "To set swap, create/edit C:\\Users\\<USERNAME>\\.wslconfig in Windows:"
    echo -e "${YELLOW}[wsl2]\nmemory=8GB\nswap=12GB${NC}"
    add_skipped "Swap Memory (WSL2 requires manual Windows config)"
else
    DESIRED_SWAP_GB=12
    DESIRED_SWAP_BYTES=$((DESIRED_SWAP_GB * 1024 * 1024 * 1024))
    # Threshold (11 GiB) accounts for decimal GB (12 GB = 11.17 GiB), free-h rounding, and kernel swap header overhead
    MIN_SWAP_BYTES=$((11 * 1024 * 1024 * 1024))

    # --- Check total active swap across ALL sources (partitions + files) ---
    # 'free' reports in kibibytes; multiply by 1024 to get bytes.
    current_swap_kb=$(free -k | awk '/^Swap:/ {print $2}')
    current_swap_bytes=$(( current_swap_kb * 1024 ))
    current_swap_human=$(free -h | awk '/^Swap:/ {print $2}')

    log_info "Currently active swap (all sources): $current_swap_human"
    if [[ -s /proc/swaps ]]; then
        log_info "Active swap sources:"
        awk 'NR>1 {printf "  %-40s type=%-10s size=%s kB\n", $1, $2, $3}' /proc/swaps
    fi

    if [[ $current_swap_bytes -ge $MIN_SWAP_BYTES ]]; then
        log_info "Total swap is already >= ~${DESIRED_SWAP_GB}GB (detected $current_swap_human). No changes needed."
        add_skipped "Swap Memory (already >= ${DESIRED_SWAP_GB}GB across all sources)"
    else
        log_info "Total swap is below ${DESIRED_SWAP_GB}GB ($current_swap_human active). Checking existing swap files..."
        needs_swap=true

        # Find any existing swapfile (/swapfile or /swap.img)
        existing_swap=""
        if [[ -f /swapfile ]]; then
            existing_swap="/swapfile"
        elif [[ -f /swap.img ]]; then
            existing_swap="/swap.img"
        fi

        if [[ -n "$existing_swap" ]]; then
            swapfile_size=$(stat -c "%s" "$existing_swap" 2>/dev/null || echo 0)
            if [[ $swapfile_size -ge $MIN_SWAP_BYTES ]]; then
                # File exists and is large enough but may not be active
                log_info "$existing_swap is >= ~${DESIRED_SWAP_GB}GB but may not be active. Activating..."
                if ! grep -q "$existing_swap" /proc/swaps; then
                    swapon "$existing_swap"
                    log_success "$existing_swap activated."
                    add_changed "Swap Memory ($existing_swap re-activated)"
                else
                    log_info "$existing_swap is already active."
                    add_skipped "Swap Memory ($existing_swap already active)"
                fi
                needs_swap=false
            else
                log_info "Existing $existing_swap is smaller than ~${DESIRED_SWAP_GB}GB ($(( swapfile_size / 1024 / 1024 / 1024 ))GB). Removing it to recreate..."
                if grep -q "$existing_swap" /proc/swaps; then
                    swapoff "$existing_swap" || true
                fi
                rm -f "$existing_swap"
            fi
        fi

        if $needs_swap; then
            target_swap="/swapfile"
            log_info "Creating ${DESIRED_SWAP_GB}GB $target_swap..."
            if ! fallocate -l "${DESIRED_SWAP_GB}G" "$target_swap" 2>/dev/null; then
                log_warn "fallocate failed, falling back to dd (this will take a while)..."
                dd if=/dev/zero of="$target_swap" bs=1M count=$(( DESIRED_SWAP_GB * 1024 )) status=progress
            fi
            chmod 600 "$target_swap"
            mkswap "$target_swap"
            swapon "$target_swap"
            log_success "${DESIRED_SWAP_GB}GB $target_swap created and activated."
            add_changed "Swap Memory (${DESIRED_SWAP_GB}GB $target_swap created)"

            if ! grep -E -q "(/swapfile|/swap.img).*swap" /etc/fstab; then
                echo "$target_swap none swap sw 0 0" >> /etc/fstab
                log_success "Added $target_swap to /etc/fstab for persistence."
            else
                log_info "Swap entry already in /etc/fstab."
            fi
        fi
    fi

    new_swap_human=$(free -h | awk '/^Swap:/ {print $2}')
    log_info "Total Swap after step: $new_swap_human"
fi


# --- Step 3: Kernel VM Settings (Swappiness & Dirty Ratio) ---
log_step "Configuring Kernel VM Settings"

SYSCTL_CONF="/etc/sysctl.d/99-llm-vm.conf"
update_sysctl=false

check_and_set_sysctl() {
    local key=$1
    local expected=$2
    local current
    current=$(sysctl -n "$key" 2>/dev/null || echo "not_set")
    
    log_info "$key is currently $current"
    if [[ "$current" == "not_set" ]]; then
        log_warn "$key does not exist on this kernel. Skipping."
        add_skipped "Kernel setting $key (unsupported)"
        return
    fi
    if [[ "$current" != "$expected" ]]; then
        if sysctl -w "$key=$expected" >/dev/null 2>&1; then
            update_sysctl=true
            add_changed "Kernel setting $key=$expected"
        else
            log_warn "Failed to set $key=$expected"
            add_skipped "Kernel setting $key (failed)"
        fi
    else
        add_skipped "Kernel setting $key"
    fi
}

# swappiness=5: strongly prefer reclaiming file cache (mmap'd model pages can be re-read from disk)
# over swapping anonymous pages (KV cache, Python heap) which cause severe inference latency spikes.
# Combined with --mlock in llama-server, model weights are pinned and won't be evicted at all.
check_and_set_sysctl "vm.swappiness" "5"
check_and_set_sysctl "vm.dirty_ratio" "20"
check_and_set_sysctl "vm.dirty_background_ratio" "5"

if $update_sysctl; then
    cat > "$SYSCTL_CONF" <<EOF
# LowaCode AI Tuning
# swappiness=5: protect anonymous pages (KV cache) from swap; prefer dropping file cache
vm.swappiness=5
vm.dirty_ratio=20
vm.dirty_background_ratio=5
EOF
    log_success "Persisted VM settings to $SYSCTL_CONF"
fi


# --- Step 4: Unlimited Memlock ---
log_step "Configuring Memlock Limits"

LIMITS_CONF="/etc/security/limits.d/99-llm-memlock.conf"

if [[ -f "$LIMITS_CONF" ]] && grep -q "$REAL_USER.*memlock.*unlimited" "$LIMITS_CONF"; then
    log_info "Memlock is already unlimited for user $REAL_USER in $LIMITS_CONF"
    add_skipped "Memlock limits"
else
    cat > "$LIMITS_CONF" <<EOF
$REAL_USER soft memlock unlimited
$REAL_USER hard memlock unlimited
EOF
    log_success "Set unlimited memlock for $REAL_USER in $LIMITS_CONF"
    add_changed "Memlock limits"
fi


# --- Step 5: CPU Governor & THP (madvise) ---
log_step "Configuring CPU Governor and Transparent HugePages (THP)"

if $IS_WSL2; then
    log_info "Skipping CPU Governor and THP configuration in WSL2."
    add_skipped "CPU Governor & THP (WSL2)"
else
    SERVICE_FILE="/etc/systemd/system/llm-sys-tune.service"
    SERVICE_SCRIPT="/usr/local/bin/llm-sys-tune.sh"
    
    # Create the universal CPU tuning script
    cat > "$SERVICE_SCRIPT" <<'EOF'
#!/usr/bin/env bash
# 1. Set THP to madvise
if [[ -f /sys/kernel/mm/transparent_hugepage/enabled ]]; then
    echo madvise > /sys/kernel/mm/transparent_hugepage/enabled
fi

# 2. Universal Linux cpufreq scaling governor -> performance (Intel & AMD)
for governor in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    if [[ -f "$governor" ]]; then
        echo performance > "$governor" 2>/dev/null || true
    fi
done

# 3. Universal power-profiles-daemon profile -> performance (Intel & AMD)
if command -v powerprofilesctl &>/dev/null; then
    powerprofilesctl set performance 2>/dev/null || true
fi

# 4. Intel CPU Specific Turbo Boost (intel_pstate)
if [[ -f /sys/devices/system/cpu/intel_pstate/no_turbo ]]; then
    echo 0 > /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null || true
fi

# 5. AMD CPU Specific Boost (amd_pstate / ryzenadj)
if [[ -f /sys/devices/system/cpu/amd_pstate/status ]]; then
    echo active > /sys/devices/system/cpu/amd_pstate/status 2>/dev/null || true
fi

if command -v ryzenadj &> /dev/null; then
    ryzenadj --stapm-limit=22000 --fast-limit=22000 --slow-limit=22000 --tctl-temp=80 2>/dev/null || true
fi
EOF
    chmod +x "$SERVICE_SCRIPT"

    # Create and enable the systemd service
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=LowaCode AI System Tuning (CPU Governor & THP)
After=multi-user.target

[Service]
Type=oneshot
ExecStart=$SERVICE_SCRIPT
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    if systemctl is-enabled --quiet llm-sys-tune.service 2>/dev/null; then
        log_info "CPU Governor & THP service already enabled."
        systemctl start llm-sys-tune.service
        add_skipped "CPU Governor & THP service"
    else
        systemctl enable --now llm-sys-tune.service
        log_success "CPU Governor & THP service created and started."
        add_changed "CPU Governor & THP service"
    fi
fi


# --- Step 6: RyzenAdj Power Limit ---
log_step "Configuring RyzenAdj (Optional)"

if $IS_WSL2; then
    log_info "Skipping RyzenAdj configuration in WSL2."
    add_skipped "RyzenAdj (WSL2)"
else
    if command -v ryzenadj &> /dev/null; then
        log_info "RyzenAdj found. Applying power limits for this session..."
        # Units are milliwatts: 22000 = 22W
        # --stapm-limit : sustained (skin temperature aware) power limit
        # --fast-limit  : peak/burst power limit (short duration boost)
        # --slow-limit  : average power limit over a longer window
        # --tctl-temp   : CPU die thermal throttle ceiling in °C
        if ryzenadj \
            --stapm-limit=22000 \
            --fast-limit=22000 \
            --slow-limit=22000 \
            --tctl-temp=80 \
            >/dev/null 2>&1; then
            log_success "RyzenAdj power limits applied (22W, tctl-temp=80°C)."
            log_info "RyzenAdj settings are also persisted via llm-sys-tune.service (reapplied on every boot)."
            add_changed "RyzenAdj limits (22W, 80°C throttle, persistent via systemd)"
        else
            log_warn "RyzenAdj failed to apply limits (this is normal on some hardware/kernels)."
            add_skipped "RyzenAdj (failed to apply)"
        fi
    else
        log_info "RyzenAdj not installed or not in PATH. Skipping."
        add_skipped "RyzenAdj (Not found)"
    fi
# --- Step 7: iGPU VRAM & GTT Memory Allocation (Intel & AMD 5096 MB) ---
log_step "Configuring iGPU VRAM & GTT Memory Allocation (5096 MB)"

if $IS_WSL2; then
    log_info "Skipping iGPU GTT configuration in WSL2."
    add_skipped "iGPU GTT (WSL2)"
else
    # 1. AMD APU GTT Allocation (5096 MB)
    if [[ -d /sys/module/amdgpu ]]; then
        AMDGPU_CONF="/etc/modprobe.d/amdgpu.conf"
        log_info "AMD GPU driver detected. Setting GTT buffer size to 5096 MB..."
        if [[ -f "$AMDGPU_CONF" ]] && grep -q "gttsize=5096" "$AMDGPU_CONF"; then
            log_info "AMD iGPU GTT size is already set to 5096 MB in $AMDGPU_CONF"
            add_skipped "AMD iGPU GTT (5096 MB)"
        else
            echo "options amdgpu gttsize=5096" > "$AMDGPU_CONF"
            log_success "Persisted AMD iGPU GTT size (5096 MB) to $AMDGPU_CONF"
            add_changed "AMD iGPU GTT memory allocation (5096 MB)"
        fi
    fi

    # 2. Intel iGPU (i915 / Xe) Dynamic VRAM Allocation
    if [[ -d /sys/module/i915 ]] || [[ -d /sys/module/xe ]]; then
        INTEL_CONF="/etc/modprobe.d/i915.conf"
        log_info "Intel iGPU driver detected. Enabling GuC/HuC hardware submission for max VRAM aperture..."
        if [[ -f "$INTEL_CONF" ]] && grep -q "enable_guc=3" "$INTEL_CONF"; then
            log_info "Intel iGPU GuC settings are already configured in $INTEL_CONF"
            add_skipped "Intel iGPU VRAM tuning"
        else
            echo "options i915 enable_guc=3" > "$INTEL_CONF"
            log_success "Persisted Intel iGPU GuC settings to $INTEL_CONF"
            add_changed "Intel iGPU hardware submission & VRAM aperture tuning"
        fi
    fi

    if [[ ! -d /sys/module/amdgpu ]] && [[ ! -d /sys/module/i915 ]] && [[ ! -d /sys/module/xe ]]; then
        log_info "No integrated AMD or Intel GPU module active. Skipping iGPU tuning."
        add_skipped "iGPU Memory Allocation (No active iGPU module found)"
    fi
fi


# --- Final Summary ---
echo -e "\n${BLUE}==============================================================================${NC}"
echo -e "${BLUE}                           Tuning Summary                                     ${NC}"
echo -e "${BLUE}==============================================================================${NC}"

echo -e "\n${GREEN}Changes Applied:${NC}"
if [[ ${#SUMMARY_CHANGED[@]} -eq 0 ]]; then
    echo "  None"
else
    for item in "${SUMMARY_CHANGED[@]}"; do
        echo "  - $item"
    done
fi

echo -e "\n${YELLOW}Skipped / Already Configured:${NC}"
if [[ ${#SUMMARY_SKIPPED[@]} -eq 0 ]]; then
    echo "  None"
else
    for item in "${SUMMARY_SKIPPED[@]}"; do
        echo "  - $item"
    done
fi

echo -e "\n${BLUE}==============================================================================${NC}"
log_info "System tuning complete."
log_warn "Some settings (like memlock) require you to log out and log back in, or simply reboot."
echo -e "${YELLOW}Please REBOOT your system for all changes to take full effect.${NC}\n"

exit 0
