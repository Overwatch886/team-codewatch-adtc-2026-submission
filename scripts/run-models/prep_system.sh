#!/bin/bash

# prep_system.sh
# Common system optimization routine sourced by all launch scripts.

echo "Optimizing system settings for low-RAM performance..."

# 1. Force CPU governor to performance mode
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor >/dev/null

# 2. Set swappiness to 60 (aggressively push idle memory to zram during peak spikes)
sudo sysctl -w vm.swappiness=60 >/dev/null


# 3. Disable Zswap so zRAM handles compressed RAM swap cleanly
#if [ -f /sys/module/zswap/parameters/enabled ]; then
 #   echo 0 | sudo tee /sys/module/zswap/parameters/enabled >/dev/null
#fi

# 4. Clear file system caches to free up clean physical RAM
sync && echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null

# 5. Raise APU power limit to 18W and cap thermal limit to 84C (prevents overheating)
if command -v ryzenadj >/dev/null 2>&1; then
    sudo ryzenadj --stapm-limit=22000 --fast-limit=22000 --slow-limit=22000 --apu-slow-limit=22000 --tctl-temp=82 >/dev/null
fi
