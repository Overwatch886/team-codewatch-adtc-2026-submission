#!/bin/bash
AUDIO_FILE="/tmp/system_voice_stream.wav"
AUDIO_FILE_CLEAN="/tmp/system_voice_stream_clean.wav"
PID_FILE="/tmp/voice_chat_record.pid"
VOICE_CLIENT="$HOME/local_ai_workspace/scripts/stream_voice_client.py"

if [ -f "$PID_FILE" ]; then
    # --- STOP RECORDING AND PROCESS ---
    PID=$(cat "$PID_FILE")
    rm -f "$PID_FILE"

    kill -2 "$PID" 2>/dev/null
    echo "Processing audio..."
    sleep 0.5

    if [ ! -s "$AUDIO_FILE" ]; then
        echo "❌ Recording file is empty!"
        /home/overwatch886/local_ai_workspace/scripts/speak.sh "Recording was empty."
        exit 1
    fi

    # Re-mux to a clean canonical WAV — fixes the header quirk that broke transcription
    ffmpeg -y -loglevel error -i "$AUDIO_FILE" -ar 16000 -ac 1 -c:a pcm_s16le "$AUDIO_FILE_CLEAN"

    if [ ! -s "$AUDIO_FILE_CLEAN" ]; then
        echo "❌ Audio cleanup failed!"
        /home/overwatch886/local_ai_workspace/scripts/speak.sh "Audio processing failed."
        exit 1
    fi

    # Stream to the model and play its spoken response live
    python3 "$VOICE_CLIENT" "$AUDIO_FILE_CLEAN"

    rm -f "$AUDIO_FILE" "$AUDIO_FILE_CLEAN"
else
    # --- START RECORDING ---
    echo "Recording started..."
    /home/overwatch886/local_ai_workspace/scripts/speak.sh "Listening"
    arecord -D default -f S16_LE -r 16000 -c 1 "$AUDIO_FILE" 2>/dev/null &
    echo $! > "$PID_FILE"
fi
