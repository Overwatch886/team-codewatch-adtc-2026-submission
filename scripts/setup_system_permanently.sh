#!/bin/bash

# setup_system_permanently.sh
# Run this once with sudo to apply permanent LLM performance optimizations.
# Usage: sudo ./setup_system_permanently.sh

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (using sudo)."
  exit 1
fi

REAL_USER=${SUDO_USER:-$USER}
echo "Configuring permanent LLM optimizations for user: ${REAL_USER}"

# ----------------------------------------------------
# 2. Configure vm.swappiness = 10
# ----------------------------------------------------
echo "==> Configuring Swappiness..."
cat <<EOF > /etc/sysctl.d/99-llm-swappiness.conf
vm.swappiness=10
EOF
sysctl -p /etc/sysctl.d/99-llm-swappiness.conf
echo "Swappiness set to 10."

# ----------------------------------------------------
# 3. Configure Unlimited Memlock (for --mlock)
# ----------------------------------------------------
echo "==> Configuring memlock limits..."
LIMITS_FILE="/etc/security/limits.d/99-llm-memlock.conf"
cat <<EOF > ${LIMITS_FILE}
${REAL_USER} soft memlock unlimited
${REAL_USER} hard memlock unlimited
EOF
echo "Unlimited memlock configured for ${REAL_USER} in ${LIMITS_FILE}."

# ----------------------------------------------------
# 4. Create Boot-Time Optimization Service (THP, CPU Governor, Zswap, Ryzenadj)
# ----------------------------------------------------
echo "==> Creating llm-system-tune systemd service..."

# Create the helper script that runs at boot
TUNE_SCRIPT="/usr/local/bin/llm-system-tune.sh"
cat <<'EOF' > ${TUNE_SCRIPT}
#!/bin/bash
# CPU Governor -> Performance
echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor >/dev/null

# THP -> Madvise
echo madvise | tee /sys/kernel/mm/transparent_hugepage/enabled >/dev/null

# Disable Zswap (lets zRAM handle compression cleanly)
#if [ -f /sys/module/zswap/parameters/enabled ]; then
    #echo 0 | tee /sys/module/zswap/parameters/enabled >/dev/null
#fi

# Ryzenadj -> 18W limit & 84C thermal throttle ceiling (if installed)
if command -v ryzenadj >/dev/null 2>&1; then
    ryzenadj --stapm-limit=22000 --fast-limit=22000 --slow-limit=22000 --apu-slow-limit=22000 --tctl-temp=83 >/dev/null
fi
EOF

chmod +x ${TUNE_SCRIPT}

# Create the systemd service unit
SERVICE_FILE="/etc/systemd/system/llm-system-tune.service"
cat <<EOF > ${SERVICE_FILE}
[Unit]
Description=LLM Local Performance Tuning Service
After=multi-user.target

[Service]
Type=oneshot
ExecStart=${TUNE_SCRIPT}
RemainAfterExit=yes

[Unit]
After=systemd-zram-setup@zram0.service

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now llm-system-tune.service
echo "llm-system-tune service enabled and running."

# ----------------------------------------------------
# 5. Flush memory cache right now
# ----------------------------------------------------
echo "==> Dropping memory caches..."
sync && echo 3 > /proc/sys/vm/drop_caches
echo "Memory caches dropped."

echo "===================================================="
# Check if running in desktop environment or shell to advice reboot
echo "Optimizations successfully applied!"
echo "Please LOG OUT and LOG BACK IN (or reboot) for memlock limits to take effect."
echo "===================================================="
