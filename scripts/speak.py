#!/usr/bin/env python3
import sys
import os
import argparse
import subprocess
import soundfile as sf
import onnxruntime as rt
from kokoro_onnx import Kokoro

# Paths
MODEL_PATH = "/home/overwatch886/local_ai_workspace/models/audio/kokoro/kokoro-v1.0.onnx"
VOICES_PATH = "/home/overwatch886/local_ai_workspace/models/audio/kokoro/voices-v1.0.bin"

def main():
    parser = argparse.ArgumentParser(description="Kokoro TTS CLI Wrapper")
    parser.add_argument("text", type=str, help="Text to speak")
    parser.add_argument("--voice", type=str, default="af_heart", help="Voice style (e.g., af_heart)")
    parser.add_argument("--speed", type=float, default=1.0, help="Speech speed")
    parser.add_argument("--output", type=str, default=None, help="Save to WAV file path")
    args = parser.parse_args()

    if not os.path.exists(MODEL_PATH) or not os.path.exists(VOICES_PATH):
        print(f"Error: Model or voices file not found.\nModel: {MODEL_PATH}\nVoices: {VOICES_PATH}", file=sys.stderr)
        sys.exit(1)

    # Initialize Kokoro with optimized thread configuration
    opts = rt.SessionOptions()
    opts.intra_op_num_threads = 6
    opts.inter_op_num_threads = 1
    session = rt.InferenceSession(MODEL_PATH, sess_options=opts, providers=['CPUExecutionProvider'])
    kokoro = Kokoro.from_session(session, VOICES_PATH)

    # Generate speech
    samples, sample_rate = kokoro.create(
        args.text,
        voice=args.voice,
        speed=args.speed,
        lang="en-us"
    )

    # Output file
    output_file = args.output if args.output else "/tmp/speak_temp.wav"
    sf.write(output_file, samples, sample_rate)

    # Play audio using aplay (standard Linux utility)
    try:
        subprocess.run(["aplay", "-q", output_file], check=True)
    except Exception as e:
        print(f"Warning: Audio playback failed: {e}", file=sys.stderr)

    # Clean up temporary file if we created it
    if not args.output and os.path.exists(output_file):
        try:
            os.remove(output_file)
        except Exception:
            pass

if __name__ == "__main__":
    main()
