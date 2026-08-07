#!/usr/bin/env bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOTAL_STEPS=11

print_step() {
    local step=$1
    local msg=$2
    echo -e "\n${CYAN}[${step}/${TOTAL_STEPS}] ${msg}${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}! $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# [1/11] Detect distro and install Ubuntu 22.04 system deps
print_step 1 "Detecting OS and installing dependencies..."
if [ -f /etc/os-release ]; then
    . /etc/os-release
    case ${ID:-} in
        ubuntu|debian|pop)
            echo "Detected Ubuntu/Debian."
            sudo apt-get update
            sudo apt-get install -y build-essential cmake python3-dev python3-venv python3-pip wget curl git pciutils libssl-dev || true
            
            echo "Installing Vulkan development packages..."
            sudo apt-get install -y libvulkan-dev vulkan-tools mesa-vulkan-drivers glslang-tools spirv-headers || true

            # Install updated Vulkan-Headers for Ubuntu 22.04 compatibility
            if [ ! -f /usr/local/include/vulkan/vulkan_handles.hpp ]; then
                echo "Installing modern Khronos Vulkan 1.3+ headers..."
                sudo rm -rf /tmp/Vulkan-Headers
                git clone --depth 1 https://github.com/KhronosGroup/Vulkan-Headers.git /tmp/Vulkan-Headers 2>/dev/null || true
                if [ -d /tmp/Vulkan-Headers/include/vulkan ]; then
                    sudo cp -r /tmp/Vulkan-Headers/include/vulkan /usr/local/include/
                    sudo cp -r /tmp/Vulkan-Headers/include/vk_video /usr/local/include/ 2>/dev/null || true
                fi
            fi

            # Ensure glslc shader compiler is available for Vulkan build
            if ! command -v glslc >/dev/null 2>&1 && [ ! -x /usr/local/bin/glslc ]; then
                echo "Installing glslc shader compiler from Vulkan SDK..."
                curl -sL https://sdk.lunarg.com/sdk/download/1.3.290.0/linux/vulkan-sdk.tar.xz | tar -xJ -C /tmp --wildcards '*/bin/glslc' 2>/dev/null || true
                if [ -f /tmp/1.3.290.0/x86_64/bin/glslc ]; then
                    sudo cp /tmp/1.3.290.0/x86_64/bin/glslc /usr/local/bin/glslc
                    sudo chmod +x /usr/local/bin/glslc
                fi
            fi

            echo "Installing OpenCL development packages..."
            sudo apt-get install -y clinfo intel-opencl-icd ocl-icd-opencl-dev opencl-headers || true

            echo "Installing Level-Zero development packages..."
            sudo apt-get install -y libze-dev libze1 || true
            ;;
        fedora|rhel|centos)
            echo "Detected Fedora/RHEL."
            sudo dnf groupinstall -y "Development Tools" "Development Libraries" || true
            sudo dnf install -y cmake python3-devel wget curl git pciutils vulkan-tools vulkan-loader-devel || true
            ;;
        arch|manjaro)
            echo "Detected Arch Linux."
            sudo pacman -Sy --noconfirm base-devel cmake python wget curl git vulkan-icd-loader clinfo || true
            ;;
        *)
            print_warning "Unsupported distro: ${ID:-unknown}. Please ensure dependencies are installed manually."
            ;;
    esac
else
    print_warning "Could not detect OS. Please ensure dependencies are installed manually."
fi
print_success "Dependencies installed."

# Helper to dynamically resolve llama.cpp CMake flags
resolve_llama_flag() {
    local feature="$1"
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

# [2/11] Detect GPU & Select Acceleration Backend
print_step 2 "Detecting GPU and selecting acceleration backend..."
mkdir -p "$WORKSPACE_DIR/software"
if [ ! -f "$WORKSPACE_DIR/software/llama.cpp/CMakeLists.txt" ]; then
    echo "Cloning fresh llama.cpp repository (shallow clone)..."
    rm -rf "$WORKSPACE_DIR/software/llama.cpp"
    git clone --depth 1 https://github.com/ggerganov/llama.cpp "$WORKSPACE_DIR/software/llama.cpp"
fi

GPU_TYPE="CPU"
CMAKE_FLAGS="$(resolve_llama_flag NATIVE)"

if command -v nvidia-smi &> /dev/null || lspci 2>/dev/null | grep -i nvidia &> /dev/null; then
    GPU_TYPE="NVIDIA"
    CMAKE_FLAGS="$(resolve_llama_flag CUDA)"
    print_success "NVIDIA GPU detected. Setting CUDA flags (${CMAKE_FLAGS})."
elif command -v rocm-smi &> /dev/null || [ -d /dev/kfd ] || lspci 2>/dev/null | grep -i amd &> /dev/null; then
    GPU_TYPE="AMD"
    if has_vulkan_dev_support; then
        CMAKE_FLAGS="$(resolve_llama_flag VULKAN)"
        print_success "AMD GPU detected. Setting Vulkan flags (${CMAKE_FLAGS})."
    else
        CMAKE_FLAGS="$(resolve_llama_flag NATIVE)"
        print_warning "AMD GPU detected, but Vulkan dev headers/libs missing. Falling back to CPU flags (${CMAKE_FLAGS})."
    fi
elif lspci 2>/dev/null | grep -iE "(intel|vga)" &> /dev/null || ls /dev/dri/renderD* &> /dev/null; then
    GPU_TYPE="INTEL"
    echo "Intel GPU detected. Evaluation cascade: Level Zero / SYCL -> OpenCL -> Vulkan -> CPU..."
    
    SYCL_FLAG="$(resolve_llama_flag SYCL)"
    if [ -f /usr/lib/x86_64-linux-gnu/libze_loader.so ] || [ -f /usr/lib64/libze_loader.so ] || command -v sycl-ls &> /dev/null; then
        CMAKE_FLAGS="$SYCL_FLAG"
        print_success "Intel Level Zero / SYCL supported. Setting SYCL flags (${CMAKE_FLAGS})."
    elif command -v clinfo &> /dev/null && clinfo 2>/dev/null | grep -i "Intel" &> /dev/null; then
        CMAKE_FLAGS="$(resolve_llama_flag OPENCL)"
        print_success "Intel OpenCL supported. Setting OpenCL flags (${CMAKE_FLAGS})."
    elif has_vulkan_dev_support && (command -v vulkaninfo &> /dev/null || [ -f /usr/share/vulkan/icd.d/intel_icd.x86_64.json ]); then
        CMAKE_FLAGS="$(resolve_llama_flag VULKAN)"
        print_success "Vulkan supported on Intel GPU. Setting Vulkan flags (${CMAKE_FLAGS})."
    else
        CMAKE_FLAGS="$(resolve_llama_flag NATIVE)"
        print_warning "No Intel GPU acceleration API verified. Falling back to CPU (${CMAKE_FLAGS})."
    fi
else
    if has_vulkan_dev_support && command -v vulkaninfo &> /dev/null; then
        CMAKE_FLAGS="$(resolve_llama_flag VULKAN)"
        print_success "Generic GPU with Vulkan support detected. Setting Vulkan flags (${CMAKE_FLAGS})."
    else
        print_success "No dedicated GPU detected. Defaulting to CPU (${CMAKE_FLAGS})."
    fi
fi

# [3/11] Build llama.cpp
print_step 3 "Building llama.cpp from source..."
LLAMA_DIR="$WORKSPACE_DIR/software/llama.cpp"

if [ -f "$LLAMA_DIR/build/bin/llama-server" ]; then
    print_success "llama.cpp binary already exists. Skipping build."
else
    cd "$LLAMA_DIR"
    rm -rf build
    # Target-specific build: compile ONLY llama-server, llama-cli, and llama-bench binaries for fast build speed
    if ! cmake -B build $CMAKE_FLAGS || ! cmake --build build --config Release --target llama-server llama-cli llama-bench -j $(nproc) 2>/dev/null; then
        if ! cmake --build build --config Release --target server main bench -j $(nproc) 2>/dev/null; then
            print_warning "Build with ${CMAKE_FLAGS} failed. Falling back to CPU build (-DGGML_NATIVE=ON)..."
            rm -rf build
            CMAKE_FLAGS="$(resolve_llama_flag NATIVE)"
            cmake -B build $CMAKE_FLAGS
            cmake --build build --config Release --target llama-server llama-cli llama-bench -j $(nproc) 2>/dev/null || \
            cmake --build build --config Release -j $(nproc)
        fi
    fi
    print_success "llama.cpp built successfully."
fi
cd "$WORKSPACE_DIR"

# [4/11] Create Python venv
print_step 4 "Creating Python virtual environment..."
if [ -d "$WORKSPACE_DIR/venv" ]; then
    print_success "Virtual environment already exists."
else
    python3 -m venv "$WORKSPACE_DIR/venv"
    print_success "Virtual environment created."
fi

# [5/11] Install Python requirements
print_step 5 "Installing Python requirements..."
source "$WORKSPACE_DIR/venv/bin/activate"
pip install --upgrade pip

if [ -f "$WORKSPACE_DIR/requirements.txt" ]; then
    pip install -r requirements.txt
fi

if [ "$GPU_TYPE" = "CPU" ] || [ "$GPU_TYPE" = "INTEL" ]; then
    pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu || pip install -r requirements.txt
elif [ "$GPU_TYPE" = "AMD" ]; then
    pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/rocm5.6 || pip install -r requirements.txt
else
    pip install -r requirements.txt
fi
pip install huggingface_hub psutil
print_success "Python requirements installed."

# Helper for model auditing
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

# [6/11] Download ColBERT model
print_step 6 "Downloading ColBERT semantic search model..."
COLBERT_DIR="$WORKSPACE_DIR/model/answerai-colbert-small-v1"
mkdir -p "$COLBERT_DIR"
if audit_model_file "$COLBERT_DIR/model_int8.onnx" 10000000; then
    print_success "ColBERT model already exists and is complete."
else
    "$WORKSPACE_DIR/venv/bin/huggingface-cli" download answerdotai/answerai-colbert-small-v1 --local-dir "$COLBERT_DIR"
    print_success "ColBERT model downloaded."
fi

# [7/11] Download Granite model
print_step 7 "Downloading IBM Granite model..."
GRANITE_DIR="$WORKSPACE_DIR/model/granite"
mkdir -p "$GRANITE_DIR"
if audit_model_file "$GRANITE_DIR/granite-4.1-3b-Q4_K_M.gguf" 1000000000; then
    print_success "Granite model already exists and is complete."
else
    "$WORKSPACE_DIR/venv/bin/huggingface-cli" download ibm-granite/granite-4.1-3b-instruct-GGUF granite-4.1-3b-Q4_K_M.gguf --local-dir "$GRANITE_DIR"
    print_success "Granite model downloaded."
fi

# [8/11] Download Qwen model
print_step 8 "Downloading Qwen model..."
QWEN_DIR="$WORKSPACE_DIR/model/qwen"
mkdir -p "$QWEN_DIR"
if audit_model_file "$QWEN_DIR/qwen2.5-coder-3b-instruct-q4_k_m.gguf" 1000000000; then
    print_success "Qwen model already exists and is complete."
else
    "$WORKSPACE_DIR/venv/bin/huggingface-cli" download Qwen/Qwen2.5-Coder-3B-Instruct-GGUF qwen2.5-coder-3b-instruct-q4_k_m.gguf --local-dir "$QWEN_DIR"
fi

# [9/11] Fix hardcoded paths across scripts
print_step 9 "Fixing workspace paths in Python and Shell scripts..."
find "$WORKSPACE_DIR" -type f \( -name "*.py" -o -name "*.sh" \) ! -path "*/venv/*" ! -path "*/software/*" -exec sed -i "s|/home/overwatch886/team-codewatch-adtc-2026-submission|$WORKSPACE_DIR|g" {} + 2>/dev/null || true
print_success "Workspace paths updated."

# [10/11] Create start.sh and make scripts executable
print_step 10 "Creating start.sh and setting permissions..."
cat << 'EOF' > "$WORKSPACE_DIR/start.sh"
#!/usr/bin/env bash
WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$WORKSPACE_DIR/venv/bin/activate"

if [ -f "$WORKSPACE_DIR/run_4gb_bounded_server.sh" ]; then
    exec "$WORKSPACE_DIR/run_4gb_bounded_server.sh"
else
    echo "Error: run_4gb_bounded_server.sh not found!"
    exit 1
fi
EOF

chmod +x "$WORKSPACE_DIR/start.sh"
if [ -f "$WORKSPACE_DIR/run_4gb_bounded_server.sh" ]; then
    chmod +x "$WORKSPACE_DIR/run_4gb_bounded_server.sh"
fi
print_success "Permissions set."

# [11/11] Completion
print_step 11 "Installation Complete!"
echo -e "${GREEN}=================================================================${NC}"
echo -e "${GREEN}✓ LowaCode AI Tutor successfully installed!${NC}"
echo -e "${GREEN}=================================================================${NC}"
echo -e "${CYAN}To launch the application, run:${NC}"
echo -e "${CYAN}  cd $WORKSPACE_DIR && ./start.sh${NC}"
echo -e "${GREEN}=================================================================${NC}"
