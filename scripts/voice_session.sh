#!/bin/bash
# voice_session.sh - Interactive voice loop using Nemotron STT, Orchestrator (Granite), and Kokoro TTS.

WORKSPACE_DIR="/home/overwatch886/local_ai_workspace"
PARAKEET_BIN="${WORKSPACE_DIR}/software/parakeet.cpp/build/examples/cli/parakeet-cli"
ASR_MODEL="${WORKSPACE_DIR}/models/audio/nemotron-3.5-asr-streaming-0.6b-q5_k.gguf"
SPEAK_SH="${WORKSPACE_DIR}/scripts/speak.sh"
ORCHESTRATOR_URL="http://localhost:8085/v1/chat/completions"
AUDIO_FILE="/tmp/voice_session_user.wav"

# Check if services are running
if ! curl -s http://localhost:8085/ > /dev/null; then
    echo "❌ Orchestrator Server is not running on port 8085!"
    echo "Please start the services first using: scripts/start-all-services-no-sudo.sh"
    exit 1
fi

echo "🎤 Code Persona Voice Session Active"
echo "--------------------------------------"
echo "Voice style: af_heart (Kokoro TTS)"
echo "STT model: Nemotron 3.5 ASR"
echo "LLM core: Granite 4.0 Tiny"
echo "Press Ctrl+C to exit at any time."
echo "--------------------------------------"

# Initial welcome
"${SPEAK_SH}" "Voice session started. I am listening."

while true; do
    echo ""
    echo "👉 Press [ENTER] to start recording your question..."
    read -r

    # Start recording
    echo "🎙️ Recording... Press [ENTER] to stop."
    # arecord captures audio in the background
    arecord -D default -f S16_LE -r 16000 -c 1 "$AUDIO_FILE" 2>/dev/null &
    RECORD_PID=$!

    # Wait for user to press ENTER again to stop
    read -r
    kill -2 "$RECORD_PID" 2>/dev/null
    wait "$RECORD_PID" 2>/dev/null

    if [ ! -s "$AUDIO_FILE" ]; then
        echo "⚠️ Recording was empty or failed. Please try again."
        continue
    fi

    echo "⚙️ Transcribing..."
    RAW_TEXT=$("$PARAKEET_BIN" transcribe --model "$ASR_MODEL" --input "$AUDIO_FILE" 2>/dev/null | tr -d '\r\n')
    rm -f "$AUDIO_FILE"

    CLEAN_TEXT=$(echo "$RAW_TEXT" | sed -E 's/<[^>]*>//g' | sed 's/^[ \t]*//;s/[ \t]*$//')

    if [ -z "$CLEAN_TEXT" ]; then
        echo "⚠️ Could not understand the audio. Please try again."
        continue
    fi

    echo "👤 You: $CLEAN_TEXT"
    echo "⚙️ Thinking..."

    # Get response from Orchestrator
    RESPONSE_JSON=$(curl -s -X POST "$ORCHESTRATOR_URL" \
      -H "Content-Type: application/json" \
      -d "{\"messages\": [{\"role\": \"user\", \"content\": \"$CLEAN_TEXT\"}], \"stream\": false}")

    RESPONSE_TEXT=$(echo "$RESPONSE_JSON" | jq -r '.choices[0].message.content')

    if [ -z "$RESPONSE_TEXT" ] || [ "$RESPONSE_TEXT" = "null" ]; then
        echo "❌ Error: Failed to get response from orchestrator."
        echo "Raw response: $RESPONSE_JSON"
        continue
    fi

    echo "🤖 Code Persona: $RESPONSE_TEXT"
    
    # Speak the response using speak.sh
    "${SPEAK_SH}" "$RESPONSE_TEXT"
done
