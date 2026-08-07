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

# 2. System dependencies, Vulkan 1.3+ headers & glslc shader compiler
echo -e "\n${BLUE}[2/11] Installing Ubuntu 22.04 system dependencies...${NC}"
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y build-essential cmake python3-dev python3-venv python3-pip wget curl git libssl-dev pciutils || true
    
    echo -e "${BLUE}Installing Vulkan development packages...${NC}"
    sudo apt-get install -y libvulkan-dev vulkan-tools mesa-vulkan-drivers glslang-tools spirv-headers || true

    # Install updated Vulkan-Headers (vulkan_handles.hpp) for Ubuntu 22.04 compatibility
    if [ ! -f /usr/local/include/vulkan/vulkan_handles.hpp ]; then
        echo -e "${BLUE}Installing modern Khronos Vulkan 1.3+ headers...${NC}"
        sudo rm -rf /tmp/Vulkan-Headers
        git clone --depth 1 https://github.com/KhronosGroup/Vulkan-Headers.git /tmp/Vulkan-Headers 2>/dev/null || true
        if [ -d /tmp/Vulkan-Headers/include/vulkan ]; then
            sudo cp -r /tmp/Vulkan-Headers/include/vulkan /usr/local/include/
            sudo cp -r /tmp/Vulkan-Headers/include/vk_video /usr/local/include/ 2>/dev/null || true
        fi
    fi

    # Ensure glslc shader compiler is available for Vulkan build
    if ! command -v glslc >/dev/null 2>&1 && [ ! -x /usr/local/bin/glslc ]; then
        echo -e "${BLUE}Installing glslc shader compiler from Vulkan SDK...${NC}"
        curl -sL https://sdk.lunarg.com/sdk/download/1.3.290.0/linux/vulkan-sdk.tar.xz | tar -xJ -C /tmp --wildcards '*/bin/glslc' 2>/dev/null || true
        if [ -f /tmp/1.3.290.0/x86_64/bin/glslc ]; then
            sudo cp /tmp/1.3.290.0/x86_64/bin/glslc /usr/local/bin/glslc
            sudo chmod +x /usr/local/bin/glslc
        fi
    fi

    echo -e "${BLUE}Installing OpenCL development packages...${NC}"
    sudo apt-get install -y clinfo intel-opencl-icd ocl-icd-opencl-dev opencl-headers || true

    echo -e "${BLUE}Installing Level-Zero development packages...${NC}"
    sudo apt-get install -y libze-dev libze1 || true
else
    echo -e "${RED}Error: Could not detect apt-get. This script requires an Ubuntu/Debian based distro.${NC}"
    exit 1
fi

# Function to dynamically resolve CMake flags for llama.cpp version compatibility (GGML_* vs LLAMA_*)
resolve_llama_flag() {
    local feature="$1" # e.g. VULKAN, CUDA, OPENCL, SYCL, NATIVE
    local llama_dir="$WORKSPACE_DIR/software/llama.cpp"
    local flag_name=""

    if [ -d "$llama_dir" ]; then
        if grep -q "option(GGML_${feature}" "$llama_dir/ggml/CMakeLists.txt" 2>/dev/null || \
           grep -q "option(GGML_${feature}" "$llama_dir/CMakeLists.txt" 2>/dev/null; then
            flag_name="-DGGML_${feature}=ON"
        elif grep -q "option(LLAMA_${feature}" "$llama_dir/ggml/CMakeLists.txt" 2>/dev/null || \
             grep -q "option(LLAMA_${feature}" "$llama_dir/CMakeLists.txt" 2>/dev/null; then
            flag_name="-DLLAMA_${feature}=ON"
        else
            flag_name="-DGGML_${feature}=ON"
        fi
    else
        flag_name="-DGGML_${feature}=ON"
    fi
    echo "$flag_name"
}

# Helper to verify Vulkan build header & library readiness
has_vulkan_dev_support() {
    if pkg-config --exists vulkan 2>/dev/null; then
        return 0
    fi
    if [ -f /usr/include/vulkan/vulkan.h ] || [ -f /usr/local/include/vulkan/vulkan.h ]; then
        if [ -f /usr/lib/x86_64-linux-gnu/libvulkan.so ] || [ -f /usr/lib64/libvulkan.so ] || [ -f /usr/lib/libvulkan.so ]; then
            return 0
        fi
    fi
    return 1
}

# 3. GPU Detection & Backend Selection
echo -e "\n${BLUE}[3/11] Detecting GPU in WSL2 and selecting acceleration backend...${NC}"

mkdir -p "$WORKSPACE_DIR/software"
if [ ! -f "$WORKSPACE_DIR/software/llama.cpp/CMakeLists.txt" ]; then
    echo -e "${BLUE}Cloning fresh llama.cpp repository...${NC}"
    rm -rf "$WORKSPACE_DIR/software/llama.cpp"
    git clone https://github.com/ggerganov/llama.cpp.git "$WORKSPACE_DIR/software/llama.cpp"
fi

LLAMA_CMAKE_FLAGS="$(resolve_llama_flag NATIVE)"
SELECTED_BACKEND="CPU"

if [ -c /dev/dxg ] || command -v nvidia-smi >/dev/null 2>&1 || lspci 2>/dev/null | grep -iE "(nvidia|amd|intel|vga|3d|display)" >/dev/null 2>&1; then
    if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
        echo -e "${GREEN}NVIDIA GPU detected with CUDA support.${NC}"
        LLAMA_CMAKE_FLAGS="$(resolve_llama_flag CUDA)"
        SELECTED_BACKEND="CUDA"
    elif lspci 2>/dev/null | grep -i "amd" >/dev/null 2>&1 || dmesg 2>/dev/null | grep -i "amd" >/dev/null 2>&1 || [ -c /dev/kfd ]; then
        echo -e "${GREEN}AMD GPU detected. Preparing Vulkan acceleration...${NC}"
        if has_vulkan_dev_support; then
            LLAMA_CMAKE_FLAGS="$(resolve_llama_flag VULKAN)"
            SELECTED_BACKEND="Vulkan (AMD)"
        else
            echo -e "${YELLOW}Vulkan development packages not found. Falling back to CPU.${NC}"
            LLAMA_CMAKE_FLAGS="$(resolve_llama_flag NATIVE)"
            SELECTED_BACKEND="CPU (AMD Fallback)"
        fi
    elif lspci 2>/dev/null | grep -iE "(intel|vga)" >/dev/null 2>&1 || [ -e /dev/dri/renderD128 ]; then
        echo -e "${BLUE}Intel GPU detected. Evaluation cascade: Level Zero / SYCL -> OpenCL -> Vulkan -> CPU...${NC}"
        
        SYCL_FLAG="$(resolve_llama_flag SYCL)"
        if [ -f /usr/lib/x86_64-linux-gnu/libze_loader.so ] || [ -f /usr/lib64/libze_loader.so ] || command -v sycl-ls >/dev/null 2>&1; then
            echo -e "${GREEN}Intel Level Zero / SYCL supported. Using SYCL backend.${NC}"
            LLAMA_CMAKE_FLAGS="$SYCL_FLAG"
            SELECTED_BACKEND="SYCL / Level Zero (Intel)"
        elif command -v clinfo >/dev/null 2>&1 && clinfo 2>/dev/null | grep -i "Intel" >/dev/null 2>&1; then
            echo -e "${GREEN}Intel OpenCL supported. Using OpenCL backend.${NC}"
            LLAMA_CMAKE_FLAGS="$(resolve_llama_flag OPENCL)"
            SELECTED_BACKEND="OpenCL (Intel)"
        elif has_vulkan_dev_support && (command -v vulkaninfo >/dev/null 2>&1 || [ -f /usr/share/vulkan/icd.d/intel_icd.x86_64.json ]); then
            echo -e "${GREEN}Vulkan supported on Intel GPU. Using Vulkan backend.${NC}"
            LLAMA_CMAKE_FLAGS="$(resolve_llama_flag VULKAN)"
            SELECTED_BACKEND="Vulkan (Intel)"
        else
            echo -e "${YELLOW}No Intel GPU acceleration API verified. Falling back to CPU.${NC}"
            LLAMA_CMAKE_FLAGS="$(resolve_llama_flag NATIVE)"
            SELECTED_BACKEND="CPU (Intel Fallback)"
        fi
    else
        if has_vulkan_dev_support && command -v vulkaninfo >/dev/null 2>&1; then
            echo -e "${GREEN}Generic GPU with Vulkan support detected. Using Vulkan backend.${NC}"
            LLAMA_CMAKE_FLAGS="$(resolve_llama_flag VULKAN)"
            SELECTED_BACKEND="Vulkan"
        else
            echo -e "${YELLOW}Falling back to CPU mode.${NC}"
            LLAMA_CMAKE_FLAGS="$(resolve_llama_flag NATIVE)"
            SELECTED_BACKEND="CPU"
        fi
    fi
else
    echo -e "${GREEN}No WSL GPU passthrough (/dev/dxg) or supported GPU detected. Using CPU mode.${NC}"
fi

echo -e "${GREEN}Selected Acceleration Backend: ${SELECTED_BACKEND} (CMake Flags: ${LLAMA_CMAKE_FLAGS})${NC}"

# 4. Build llama.cpp
echo -e "\n${BLUE}[4/11] Building llama.cpp...${NC}"
    if [ ! -d "$WORKSPACE_DIR/software/llama.cpp" ]; then
        git clone --depth 1 https://github.com/ggerganov/llama.cpp.git "$WORKSPACE_DIR/software/llama.cpp"
    fi
    cd "$WORKSPACE_DIR/software/llama.cpp"
    rm -rf build
    if ! cmake -B build $LLAMA_CMAKE_FLAGS || ! cmake --build build --config Release --target llama-server llama-cli llama-bench -j $(nproc) 2>/dev/null; then
        echo -e "${YELLOW}CMake configuration failed with ${LLAMA_CMAKE_FLAGS}. Falling back to CPU build (-DGGML_NATIVE=ON)...${NC}"
        rm -rf build
        LLAMA_CMAKE_FLAGS="$(resolve_llama_flag NATIVE)"
        cmake -B build $LLAMA_CMAKE_FLAGS
        cmake --build build --config Release --target llama-server llama-cli llama-bench -j $(nproc) 2>/dev/null || \
        cmake --build build --config Release -j $(nproc)
    fi
    cd "$WORKSPACE_DIR"

# 5. Create Python venv
echo -e "\n${BLUE}[5/11] Setting up Python environment...${NC}"
if [ ! -d "$WORKSPACE_DIR/venv" ]; then
    python3 -m venv "$WORKSPACE_DIR/venv"
fi
source "$WORKSPACE_DIR/venv/bin/activate"

if [ -f "$WORKSPACE_DIR/requirements.txt" ]; then
    pip install -r "$WORKSPACE_DIR/requirements.txt"
else
    pip install fastapi uvicorn huggingface_hub psutil
fi

# Model audit helper function: check if file exists and has size >= min_size_bytes
audit_model_file() {
    local file_path="$1"
    local min_size_bytes="$2"
    
    if [ -f "$file_path" ]; then
        local file_size
        file_size=$(stat -c%s "$file_path" 2>/dev/null || stat -f%z "$file_path" 2>/dev/null || echo 0)
        if [ "$file_size" -ge "$min_size_bytes" ]; then
            return 0
        fi
    fi
    return 1
}

# 6. Download ColBERT model
echo -e "\n${BLUE}[6/11] Auditing and downloading ColBERT model...${NC}"
COLBERT_DIR="$WORKSPACE_DIR/model/answerai-colbert-small-v1"
mkdir -p "$COLBERT_DIR"
if audit_model_file "$COLBERT_DIR/model_int8.onnx" 10000000; then
    echo -e "${GREEN}ColBERT model is already fully downloaded (${COLBERT_DIR}/model_int8.onnx). Skipping.${NC}"
else
    echo -e "${YELLOW}ColBERT model missing or incomplete. Downloading...${NC}"
    huggingface-cli download answerdotai/answerai-colbert-small-v1 --local-dir "$COLBERT_DIR"
fi

# 7. Download Granite 4.1 3B model
echo -e "\n${BLUE}[7/11] Auditing and downloading Granite 4.1 3B Q4_K_M model...${NC}"
GRANITE_DIR="$WORKSPACE_DIR/model/granite"
mkdir -p "$GRANITE_DIR"
if audit_model_file "$GRANITE_DIR/granite-4.1-3b-Q4_K_M.gguf" 1000000000; then
    echo -e "${GREEN}Granite 4.1 3B model is already fully downloaded (${GRANITE_DIR}/granite-4.1-3b-Q4_K_M.gguf). Skipping.${NC}"
else
    echo -e "${YELLOW}Granite model missing or incomplete. Downloading...${NC}"
    huggingface-cli download ibm-granite/granite-4.1-3b-instruct-GGUF granite-4.1-3b-Q4_K_M.gguf --local-dir "$GRANITE_DIR"
fi

# 8. Download Qwen 2.5 Coder 3B model
echo -e "\n${BLUE}[8/11] Auditing and downloading Qwen 2.5 Coder 3B Q4_K_M model...${NC}"
QWEN_DIR="$WORKSPACE_DIR/model/qwen"
mkdir -p "$QWEN_DIR"
if audit_model_file "$QWEN_DIR/qwen2.5-coder-3b-instruct-q4_k_m.gguf" 1000000000; then
    echo -e "${GREEN}Qwen 2.5 Coder 3B model is already fully downloaded (${QWEN_DIR}/qwen2.5-coder-3b-instruct-q4_k_m.gguf). Skipping.${NC}"
else
    echo -e "${YELLOW}Qwen model missing or incomplete. Downloading...${NC}"
    huggingface-cli download Qwen/Qwen2.5-Coder-3B-Instruct-GGUF qwen2.5-coder-3b-instruct-q4_k_m.gguf --local-dir "$QWEN_DIR"
fi

# 9. Fix hardcoded paths across scripts
echo -e "\n${BLUE}[9/11] Fixing workspace paths in Python and Shell scripts...${NC}"
find "$WORKSPACE_DIR" -type f \( -name "*.py" -o -name "*.sh" \) ! -path "*/venv/*" ! -path "*/software/*" -exec sed -i "s|/home/overwatch886/team-codewatch-adtc-2026-submission|$WORKSPACE_DIR|g" {} + 2>/dev/null || true
echo -e "${GREEN}Workspace paths updated.${NC}"

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
echo -e "  2. Open your Windows browser and go to ${BLUE}http://localhost:8085${NC}"
echo -e ""
echo -e "${YELLOW}Note: Windows Defender may show a network prompt when the server starts.${NC}"
echo -e "${YELLOW}Please click 'Allow' so you can access it from your browser.${NC}"
