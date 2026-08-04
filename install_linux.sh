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

# [1/11] Detect distro and install system deps
print_step 1 "Detecting OS and installing dependencies..."
if [ -f /etc/os-release ]; then
    . /etc/os-release
    case $ID in
        ubuntu|debian|pop)
            echo "Detected Ubuntu/Debian."
            sudo apt-get update
            sudo apt-get install -y build-essential cmake python3-dev python3-venv wget curl git
            ;;
        fedora|rhel|centos)
            echo "Detected Fedora/RHEL."
            sudo dnf groupinstall -y "Development Tools" "Development Libraries"
            sudo dnf install -y cmake python3-devel wget curl git
            ;;
        arch|manjaro)
            echo "Detected Arch Linux."
            sudo pacman -Sy --noconfirm base-devel cmake python wget curl git
            ;;
        *)
            print_warning "Unsupported distro: $ID. Please ensure dependencies are installed manually."
            ;;
    esac
else
    print_warning "Could not detect OS. Please ensure dependencies are installed manually."
fi
print_success "Dependencies installed."

# [2/11] Detect GPU
print_step 2 "Detecting GPU..."
GPU_TYPE="CPU"
CMAKE_FLAGS="-DGGML_NATIVE=ON"

if command -v nvidia-smi &> /dev/null || lspci | grep -i nvidia &> /dev/null; then
    GPU_TYPE="NVIDIA"
    CMAKE_FLAGS="-DGGML_CUDA=ON"
    print_success "NVIDIA GPU detected. Setting CUDA flags."
elif command -v rocm-smi &> /dev/null || [ -d /dev/kfd ] || lspci | grep -i amd &> /dev/null; then
    GPU_TYPE="AMD"
    CMAKE_FLAGS="-DGGML_HIP=ON"
    print_success "AMD GPU detected. Setting HIP flags."
elif lspci | grep -i vga | grep -i intel &> /dev/null || ls /dev/dri/renderD* &> /dev/null; then
    GPU_TYPE="INTEL"
    CMAKE_FLAGS="-DGGML_OPENCL=ON"
    print_success "Intel GPU detected. Setting OpenCL flags."
    # Try to install opencl icd if missing on ubuntu
    if [ "$ID" = "ubuntu" ] || [ "$ID" = "debian" ]; then
        sudo apt-get install -y intel-opencl-icd || true
    fi
else
    print_success "No dedicated GPU detected. Defaulting to CPU."
fi

# [3/11] Build llama.cpp
print_step 3 "Building llama.cpp from source..."
LLAMA_DIR="$WORKSPACE_DIR/software/llama.cpp"
if [ ! -d "$LLAMA_DIR" ]; then
    echo "Cloning llama.cpp..."
    mkdir -p "$WORKSPACE_DIR/software"
    git clone https://github.com/ggerganov/llama.cpp "$LLAMA_DIR"
fi

if [ -f "$LLAMA_DIR/build/bin/llama-server" ]; then
    print_success "llama.cpp binary already exists. Skipping build."
else
    cd "$LLAMA_DIR"
    mkdir -p build
    cd build
    cmake .. $CMAKE_FLAGS
    cmake --build . --config Release -j $(nproc)
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

if [ "$GPU_TYPE" = "CPU" ] || [ "$GPU_TYPE" = "INTEL" ]; then
    pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu
elif [ "$GPU_TYPE" = "AMD" ]; then
    pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/rocm5.6
else
    pip install -r requirements.txt
fi
pip install huggingface_hub
print_success "Python requirements installed."

# [6/11] Download ColBERT model
print_step 6 "Downloading ColBERT semantic search model..."
COLBERT_DIR="$WORKSPACE_DIR/answerai-colbert-small-v1"
if [ -d "$COLBERT_DIR" ] && [ "$(ls -A $COLBERT_DIR 2>/dev/null)" ]; then
    print_success "ColBERT model already exists."
else
    "$WORKSPACE_DIR/venv/bin/huggingface-cli" download answerdotai/answerai-colbert-small-v1 --local-dir "$COLBERT_DIR"
    print_success "ColBERT model downloaded."
fi

# [7/11] Download Granite model
print_step 7 "Downloading IBM Granite model..."
GRANITE_DIR="$WORKSPACE_DIR/models/granite"
if [ -f "$GRANITE_DIR/granite-4.1-3b-Q4_K_M.gguf" ]; then
    print_success "Granite model already exists."
else
    "$WORKSPACE_DIR/venv/bin/huggingface-cli" download ibm-granite/granite-4.1-3b-instruct-GGUF granite-4.1-3b-Q4_K_M.gguf --local-dir "$GRANITE_DIR"
    print_success "Granite model downloaded."
fi

# [8/11] Download Qwen model
print_step 8 "Downloading Qwen model..."
QWEN_DIR="$WORKSPACE_DIR/models/qwen"
if [ -f "$QWEN_DIR/qwen2.5-coder-3b-instruct-q4_k_m.gguf" ]; then
    print_success "Qwen model already exists."
else
    "$WORKSPACE_DIR/venv/bin/huggingface-cli" download Qwen/Qwen2.5-Coder-3B-Instruct-GGUF qwen2.5-coder-3b-instruct-q4_k_m.gguf --local-dir "$QWEN_DIR"
    print_success "Qwen model downloaded."
fi

# [9/11] Fix hardcoded paths
print_step 9 "Fixing hardcoded paths in scripts..."
if [ -f "$WORKSPACE_DIR/scripts/orchestrator_server.py" ]; then
    sed -i "s|/home/overwatch886/local_ai_workspace|$WORKSPACE_DIR|g" "$WORKSPACE_DIR/scripts/orchestrator_server.py"
    print_success "Fixed paths in orchestrator_server.py"
else
    print_warning "scripts/orchestrator_server.py not found, skipping sed replace."
fi

if [ -f "$WORKSPACE_DIR/run_4gb_bounded_server.sh" ]; then
    sed -i "s|/home/overwatch886/local_ai_workspace|$WORKSPACE_DIR|g" "$WORKSPACE_DIR/run_4gb_bounded_server.sh"
    print_success "Fixed paths in run_4gb_bounded_server.sh"
else
    print_warning "run_4gb_bounded_server.sh not found, skipping sed replace."
fi

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
