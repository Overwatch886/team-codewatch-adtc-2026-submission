#!/bin/bash
CHUNK_DIR="/tmp/nemotron_chunks"
PID_FILE="/tmp/voice_stream_nemotron.pid"
LOOP_PID_FILE="/tmp/voice_stream_loop.pid"

PARAKEET_BIN="/home/overwatch886/local_ai_workspace/software/parakeet.cpp/build/examples/cli/parakeet-cli"
ASR_MODEL="/home/overwatch886/local_ai_workspace/models/audio/nemotron-3.5-asr-streaming-0.6b-q5_k.gguf"

export DISPLAY=:0

if [ -f "$PID_FILE" ]; then
    # --- STOP THE STREAMING LOOP ---
    LOOP_PID=$(cat "$LOOP_PID_FILE" 2>/dev/null)
    kill "$LOOP_PID" 2>/dev/null
    
    # Kill any active recording chunks
    pkill -f "arecord.*$CHUNK_DIR"
    
    rm -f "$PID_FILE" "$LOOP_PID_FILE"
    rm -rf "$CHUNK_DIR"
    
    # Double beep: Engine has stopped listening
    echo -en "\a" && sleep 0.1 && echo -en "\a"
    exit 0
fi

# --- START THE STREAMING LOOP ---
touch "$PID_FILE"
mkdir -p "$CHUNK_DIR"

# Single beep: Engine is live and listening
echo -en "\a"

# Run the background chunking loop
(
    while [ -f "$PID_FILE" ]; do
        CHUNK_FILE="$CHUNK_DIR/chunk_$(date +%s%N).wav"
        
        # Capture a brief 1.5-second audio slice
        arecord -D default -f S16_LE -r 16000 -c 1 -d 2 "$CHUNK_FILE" 2>/dev/null
        
        # Process the chunk immediately in the background if it contains data
        if [ -s "$CHUNK_FILE" ]; then
            (
                RAW_TEXT=$("$PARAKEET_BIN" transcribe --model "$ASR_MODEL" --input "$CHUNK_FILE" 2>/dev/null | tr -d '\r\n')
                rm -f "$CHUNK_FILE"
                
                if [ ! -z "$RAW_TEXT" ]; then
                    # Remove language tags and spacing artifacts
                    CLEAN_TEXT=$(echo "$RAW_TEXT" | sed -E 's/<[^>]*>//g' | sed 's/^[ \t]*//;s/[ \t]*$//')
                    
                    # Only inject if there's actual spoken text (ignores background hiss)
                    if [ ! -z "$CLEAN_TEXT" ]; then
                        xdotool type "$CLEAN_TEXT "
                    fi
                fi
            ) &
        fi
        
        # Tiny rest cycle before firing up the next audio slice
        sleep 0.1
    done
) &

echo $! > "$LOOP_PID_FILE"
