#!/usr/bin/env python3
"""
Voice-activated home automation:
  - Double clap  → opens visualizer + welcome message + plays Spotify
  - "stop music" → pause Spotify + voice response
  - Any question → Claude searches the web and answers out loud

Dependencies:
    pip install sounddevice numpy SpeechRecognition pyaudio anthropic pygame

Requires:
    ANTHROPIC_API_KEY environment variable
"""

import os
import sys
import time
import threading
import subprocess

import numpy as np
import sounddevice as sd
import speech_recognition as sr
import anthropic

# ──────────────────────────────────────────────────────────────────────────────
#  Config
# ──────────────────────────────────────────────────────────────────────────────
SAMPLE_RATE   = 44100
BLOCK_SIZE    = int(SAMPLE_RATE * 0.05)
THRESHOLD     = 0.20
COOLDOWN      = 0.1
DOUBLE_WINDOW = 2.0

SPOTIFY_URI = "spotify:track:08mG3Y1vljYA6bvDt4Wqkj"
MENSAJE     = "Welcome home Sir. What should we do today."

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))

# ──────────────────────────────────────────────────────────────────────────────
#  Visualizer subprocess proxy
# ──────────────────────────────────────────────────────────────────────────────
_viz_proc = None


def _viz_send(msg: str):
    global _viz_proc
    if _viz_proc is None:
        return
    try:
        _viz_proc.stdin.write(msg + "\n")
        _viz_proc.stdin.flush()
    except Exception:
        pass


def start_visualizer():
    global _viz_proc
    script = os.path.join(SCRIPT_DIR, "visualizer.py")
    _viz_proc = subprocess.Popen(
        [sys.executable, script],
        stdin=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


class _Viz:
    def set_state(self, s: str):
        _viz_send(f"state:{s}")

    def set_amplitude(self, rms: float):
        _viz_send(f"amp:{min(1.0, rms * 6):.3f}")


viz = _Viz()

# ──────────────────────────────────────────────────────────────────────────────
#  State
# ──────────────────────────────────────────────────────────────────────────────
clap_times    : list[float] = []
triggered     = False
speaking      = False
music_playing = False
lock          = threading.Lock()


# ──────────────────────────────────────────────────────────────────────────────
#  Clap detection
# ──────────────────────────────────────────────────────────────────────────────
def audio_callback(indata, frames, time_info, status):
    global triggered, clap_times

    if triggered or speaking:
        return

    rms = float(np.sqrt(np.mean(indata ** 2)))
    now = time.time()

    viz.set_amplitude(rms)

    if rms > THRESHOLD:
        with lock:
            if clap_times and (now - clap_times[-1]) < COOLDOWN:
                return

            clap_times.append(now)
            clap_times = [t for t in clap_times if now - t <= DOUBLE_WINDOW]

            count = len(clap_times)
            print(f"  Clap {count}/2  (RMS={rms:.3f})")

            if count >= 2:
                triggered = True
                clap_times = []
                threading.Thread(target=run_welcome_sequence, daemon=True).start()


# ──────────────────────────────────────────────────────────────────────────────
#  Welcome sequence
# ──────────────────────────────────────────────────────────────────────────────
def run_welcome_sequence():
    global music_playing
    print("\nDouble clap detected!\n")
    start_visualizer()
    viz.set_state("listening")
    speak(MENSAJE)
    play_spotify()
    music_playing = True


def play_spotify():
    result = subprocess.run(
        ["osascript", "-e", f'tell application "Spotify" to play track "{SPOTIFY_URI}"'],
        capture_output=True,
    )
    if result.returncode != 0:
        subprocess.Popen(["open", SPOTIFY_URI])


# ──────────────────────────────────────────────────────────────────────────────
#  Voice command listener
# ──────────────────────────────────────────────────────────────────────────────
def voice_command_listener():
    recognizer = sr.Recognizer()
    mic        = sr.Microphone()

    print("  Voice commands ready. Say 'stop music' or ask anything.")

    with mic as source:
        recognizer.adjust_for_ambient_noise(source, duration=1)

    while True:
        if speaking:
            time.sleep(0.1)
            continue
        try:
            with mic as source:
                audio = recognizer.listen(source, timeout=10, phrase_time_limit=15)
            text = recognizer.recognize_google(audio).lower()
            print(f"\n  Heard: \"{text}\"")
            threading.Thread(target=handle_command, args=(text,), daemon=True).start()
        except sr.WaitTimeoutError:
            pass
        except sr.UnknownValueError:
            pass
        except Exception as e:
            print(f"  Voice error: {e}")


# ──────────────────────────────────────────────────────────────────────────────
#  Command handling
# ──────────────────────────────────────────────────────────────────────────────
def handle_command(text: str):
    global music_playing

    if "shut down" in text or "shutdown" in text:
        speak("Shutting down. Goodbye Sir.")
        if _viz_proc:
            _viz_proc.terminate()
        os._exit(0)
    elif "stop music" in text or "stop the music" in text:
        subprocess.run(
            ["osascript", "-e", 'tell application "Spotify" to pause'],
            capture_output=True,
        )
        music_playing = False
        speak("Music stopped. What should we do today?")
    elif music_playing:
        print(f"  Ignoring (music playing): \"{text}\"")
    else:
        print(f"  Asking Claude: {text}")
        viz.set_state("thinking")
        answer = ask_claude(text)
        speak(answer)


def ask_claude(question: str) -> str:
    try:
        client = anthropic.Anthropic()
        with client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=512,
            system=[{
                "type": "text",
                "text": (
                    "You are a voice assistant. Search the web when needed, "
                    "then answer in 2-3 plain sentences with no markdown, "
                    "no bullet points, and no special characters. "
                    "Speak naturally as if talking out loud."
                ),
                "cache_control": {"type": "ephemeral"},
            }],
            tools=[{"type": "web_search_20260209", "name": "web_search"}],
            messages=[{"role": "user", "content": question}],
        ) as stream:
            final = stream.get_final_message()
            for block in reversed(final.content):
                if block.type == "text":
                    return block.text
        return "I could not find an answer."
    except Exception as e:
        print(f"  Claude error: {e}")
        return "I had trouble getting an answer. Please try again."


# ──────────────────────────────────────────────────────────────────────────────
#  TTS
# ──────────────────────────────────────────────────────────────────────────────
def speak(text: str):
    global speaking
    speaking = True
    viz.set_state("speaking")
    print(f"  Saying: {text}")
    result = subprocess.run(["say", "-v", "Samantha", text], capture_output=True)
    if result.returncode != 0:
        subprocess.run(["say", text], capture_output=True)
    time.sleep(1.0)
    speaking = False
    viz.set_state("listening")


# ──────────────────────────────────────────────────────────────────────────────
#  Audio loop (background thread)
# ──────────────────────────────────────────────────────────────────────────────
def audio_loop():
    global triggered
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        blocksize=BLOCK_SIZE,
        channels=1,
        dtype="float32",
        callback=audio_callback,
    ):
        while True:
            time.sleep(0.1)
            if triggered:
                time.sleep(5)
                triggered = False
                print("\nListening again...\n")


# ──────────────────────────────────────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 50)
    print("  Listening for claps... (Ctrl+C to quit)")
    print(f"  Threshold: {THRESHOLD}  (adjust THRESHOLD if needed)")
    print("=" * 50)

    threading.Thread(target=voice_command_listener, daemon=True).start()
    threading.Thread(target=audio_loop, daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        if _viz_proc:
            _viz_proc.terminate()
        print("\nBye!")
        sys.exit(0)


if __name__ == "__main__":
    main()
