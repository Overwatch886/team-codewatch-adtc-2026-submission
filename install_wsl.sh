#!/usr/bin/env bash
set -e
set -u

# Colors for terminal output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$WORKSPACE_DIR"

echo -e "${BLUE}====================================================${NC}"
echo -e "${BLUE}        LowaCode AI Tutor - WSL2 Installer          ${NC}"
echo -e "${BLUE}====================================================${NC}"

# 1. Verify WSL2
echo -e "\n${BLUE}[1/11] Verifying WSL2 environment...${NC}"
if ! grep -qiE "(microsoft|wsl)" /proc/version; then
    echo -e "${RED}Error: This script is intended to run inside WSL2 (Windows Subsystem for Linux).${NC}"
    echo -e "${RED}Please run this from your WSL terminal.${NC}"
    exit 1
fi
echo -e "${GREEN}WSL2 environment detected.${NC}"

# 2. System dependencies
echo -e "\n${BLUE}[2/11] Installing system dependencies...${NC}"
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y build-essential cmake python3-dev python3-venv python3-pip wget curl git libssl-dev pciutils
else
    echo -e "${RED}Error: Could not detect apt-get. This script requires an Ubuntu/Debian based WSL distro.${NC}"
    exit 1
fi

# 3. GPU Detection
echo -e "\n${BLUE}[3/11] Detecting GPU in WSL2...${NC}"
LLAMA_CMAKE_FLAGS="-DLLAMA_NATIVE=ON"

if [ -c /dev/dxg ]; then
    if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
        echo -e "${GREEN}NVIDIA GPU detected with CUDA support.${NC}"
        LLAMA_CMAKE_FLAGS="-DLLAMA_CUDA=ON"
    elif lspci 2>/dev/null | grep -i "amd" >/dev/null 2>&1 || dmesg 2>/dev/null | grep -i "amd" >/dev/null 2>&1; then
        echo -e "${YELLOW}AMD GPU detected. ROCm in WSL2 is experimental. Falling back to CPU.${NC}"
    else
        echo -e "${GREEN}Intel iGPU/Arc or generic GPU detected. Setting up OpenCL support...${NC}"
        sudo apt-get install -y intel-opencl-icd
        LLAMA_CMAKE_FLAGS="-DLLAMA_OPENCL=ON"
    fi
else
    echo -e "${GREEN}No WSL GPU passthrough (/dev/dxg) detected. Using CPU mode.${NC}"
fi

# 4. Build llama.cpp
echo -e "\n${BLUE}[4/11] Building llama.cpp...${NC}"
if [ -f "$WORKSPACE_DIR/software/llama.cpp/build/bin/llama-server" ]; then
    echo -e "${GREEN}llama.cpp is already built. Skipping.${NC}"
else
    mkdir -p "$WORKSPACE_DIR/software"
    if [ ! -d "$WORKSPACE_DIR/software/llama.cpp" ]; then
        git clone https://github.com/ggerganov/llama.cpp.git "$WORKSPACE_DIR/software/llama.cpp"
    fi
    cd "$WORKSPACE_DIR/software/llama.cpp"
    cmake -B build $LLAMA_CMAKE_FLAGS
    cmake --build build --config Release -j $(nproc)
    cd "$WORKSPACE_DIR"
fi

# 5. Create Python venv
echo -e "\n${BLUE}[5/11] Setting up Python environment...${NC}"
if [ ! -d "$WORKSPACE_DIR/venv" ]; then
    python3 -m venv "$WORKSPACE_DIR/venv"
fi
source "$WORKSPACE_DIR/venv/bin/activate"

if [ -f "$WORKSPACE_DIR/requirements.txt" ]; then
    pip install -r "$WORKSPACE_DIR/requirements.txt"
else
    # Install defaults in case requirements.txt is missing
    pip install fastapi uvicorn huggingface_hub
fi

# 6. Download ColBERT model
echo -e "\n${BLUE}[6/11] Downloading ColBERT model...${NC}"
mkdir -p "$WORKSPACE_DIR/models/answerai-colbert-small-v1"
huggingface-cli download answerdotai/answerai-colbert-small-v1 --local-dir "$WORKSPACE_DIR/models/answerai-colbert-small-v1"

# 7. Download Granite 4.1 3B model
echo -e "\n${BLUE}[7/11] Downloading Granite 4.1 3B Q4_K_M model...${NC}"
mkdir -p "$WORKSPACE_DIR/models"
huggingface-cli download ibm-granite/granite-4.1-3b-instruct-GGUF granite-4.1-3b-instruct-Q4_K_M.gguf --local-dir "$WORKSPACE_DIR/models"

# 8. Download Qwen 2.5 Coder 3B model
echo -e "\n${BLUE}[8/11] Downloading Qwen 2.5 Coder 3B Q4_K_M model...${NC}"
huggingface-cli download Qwen/Qwen2.5-Coder-3B-Instruct-GGUF qwen2.5-coder-3b-instruct-q4_k_m.gguf --local-dir "$WORKSPACE_DIR/models"

# 9. Fix hardcoded paths
echo -e "\n${BLUE}[9/11] Fixing hardcoded paths...${NC}"
if [ -f "$WORKSPACE_DIR/scripts/orchestrator_server.py" ]; then
    sed -i "s|/home/overwatch886/local_ai_workspace|$WORKSPACE_DIR|g" "$WORKSPACE_DIR/scripts/orchestrator_server.py"
    echo -e "${GREEN}Updated orchestrator_server.py${NC}"
fi
if [ -f "$WORKSPACE_DIR/run_4gb_bounded_server.sh" ]; then
    sed -i "s|/home/overwatch886/local_ai_workspace|$WORKSPACE_DIR|g" "$WORKSPACE_DIR/run_4gb_bounded_server.sh"
    echo -e "${GREEN}Updated run_4gb_bounded_server.sh${NC}"
fi

# 10. WSL-specific memory/systemd check
echo -e "\n${BLUE}[10/11] Checking systemd for memory limits...${NC}"
if [ ! -d /run/systemd/private ]; then
    echo -e "${YELLOW}TIP: Enable systemd for memory limits: add [boot] systemd=true to /etc/wsl.conf then run: wsl --shutdown in PowerShell${NC}"
else
    echo -e "${GREEN}systemd is enabled.${NC}"
fi

# 11. Create start.sh
echo -e "\n${BLUE}[11/11] Creating start script...${NC}"
cat << 'EOF' > "$WORKSPACE_DIR/start.sh"
#!/usr/bin/env bash
WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$WORKSPACE_DIR"

source "$WORKSPACE_DIR/venv/bin/activate"

if [ -f "$WORKSPACE_DIR/run_4gb_bounded_server.sh" ]; then
    bash "$WORKSPACE_DIR/run_4gb_bounded_server.sh"
else
    echo "Error: run_4gb_bounded_server.sh not found in $WORKSPACE_DIR"
    exit 1
fi
EOF
chmod +x "$WORKSPACE_DIR/start.sh"

echo -e "\n${GREEN}====================================================${NC}"
echo -e "${GREEN}               INSTALLATION COMPLETE!               ${NC}"
echo -e "${GREEN}====================================================${NC}"
echo -e "To start LowaCode AI Tutor:"
echo -e "  1. Run ${YELLOW}./start.sh${NC} from this WSL terminal"
echo -e "  2. Open your Windows browser and go to ${BLUE}http://localhost:8000${NC}"
echo -e ""
echo -e "${YELLOW}Note: Windows Defender may show a network prompt when the server starts.${NC}"
echo -e "${YELLOW}Please click 'Allow' so you can access it from your browser.${NC}"
