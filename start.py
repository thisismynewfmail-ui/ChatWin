#!/usr/bin/env python3
"""
start.py - ChatWin launcher

Starts the chatbot application with standard GPIO button support
and an HTML webview display. No WhisPi HAT required.

Usage:
    python3 start.py
"""

import os
import sys
import subprocess
import signal
import shutil
import time


def load_env(env_file=".env"):
    """Load key=value pairs from .env file into os.environ."""
    if not os.path.exists(env_file):
        print(f"Error: {env_file} not found.")
        print("Please create one based on .env.template:")
        print("  cp .env.template .env")
        sys.exit(1)

    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ[key] = value


def get_env(key, default=""):
    return os.environ.get(key, default)


def find_node():
    """Find the node executable, checking NVM first."""
    nvm_dir = os.environ.get("NVM_DIR", os.path.expanduser("~/.nvm"))
    nvm_sh = os.path.join(nvm_dir, "nvm.sh")
    if os.path.exists(nvm_sh):
        result = subprocess.run(
            f'source "{nvm_sh}" && which node',
            shell=True,
            capture_output=True,
            text=True,
            executable="/bin/bash",
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()

    node_path = shutil.which("node")
    if node_path:
        return node_path

    return None


def setup_audio():
    """Set up audio volume using ALSA if available."""
    if sys.platform != "linux":
        return

    if not shutil.which("amixer"):
        print("[Audio] amixer not found, skipping volume setup.")
        return

    volume = get_env("INITIAL_VOLUME_LEVEL", "114")

    # Find a usable sound card
    card_index = None
    try:
        with open("/proc/asound/cards", "r") as f:
            for line in f:
                parts = line.strip().split()
                if parts and parts[0].isdigit():
                    card_index = parts[0]
                    break
    except FileNotFoundError:
        pass

    if card_index is None:
        print("[Audio] No sound cards found, skipping volume setup.")
        return

    try:
        subprocess.run(
            ["amixer", "-c", card_index, "set", "Speaker", volume],
            capture_output=True,
            timeout=5,
        )
        print(f"[Audio] Volume set to {volume} on card {card_index}")
    except Exception as e:
        print(f"[Audio] Volume setup failed: {e}")


def print_env_info():
    """Print environment information for debugging."""
    print(f"===== ChatWin starting: {time.strftime('%Y-%m-%d %H:%M:%S')} =====")
    print(f"Working directory: {os.getcwd()}")
    print(f"Platform: {sys.platform}")

    try:
        result = subprocess.run(
            ["python3", "--version"], capture_output=True, text=True
        )
        print(f"Python: {result.stdout.strip()}")
    except Exception:
        print(f"Python: {sys.version}")


def main():
    working_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(working_dir)

    # Load environment variables from .env
    load_env()

    print_env_info()

    # Force web display mode (HTML webview as primary display)
    os.environ["WHISPLAY_WEB_ENABLED"] = "true"
    # Keep device enabled for GPIO button support via the socket server
    os.environ.setdefault("WHISPLAY_DEVICE_ENABLED", "true")

    # Forward relevant env vars
    for key in [
        "CUSTOM_FONT_PATH",
        "INITIAL_VOLUME_LEVEL",
        "WHISPER_MODEL_SIZE",
        "FASTER_WHISPER_MODEL_SIZE",
    ]:
        val = get_env(key)
        if val:
            os.environ[key] = val

    # Set up audio
    setup_audio()

    # Find Node.js
    node = find_node()
    if not node:
        print("Error: Node.js not found. Please install Node.js.")
        sys.exit(1)
    print(f"Node.js: {node}")

    # Check that the project is built
    dist_index = os.path.join(working_dir, "dist", "index.js")
    if not os.path.exists(dist_index):
        print("Error: dist/index.js not found. Please build the project first:")
        print("  bash build.sh")
        sys.exit(1)

    processes = []

    # Start Ollama if configured
    if get_env("SERVE_OLLAMA", "").lower() == "true":
        ollama_path = shutil.which("ollama")
        if ollama_path:
            print("[Ollama] Starting Ollama server...")
            ollama_env = os.environ.copy()
            ollama_env["OLLAMA_KEEP_ALIVE"] = "-1"
            ollama_env["OLLAMA_HOST"] = "0.0.0.0:11434"
            ollama_proc = subprocess.Popen(
                [ollama_path, "serve"], env=ollama_env
            )
            processes.append(("ollama", ollama_proc))
        else:
            print("[Ollama] Warning: ollama not found in PATH, skipping.")

    # Determine how to start Node.js (prefer yarn, fall back to npm)
    use_npm = os.path.exists(os.path.join(working_dir, "use_npm"))
    nvm_dir = os.environ.get("NVM_DIR", os.path.expanduser("~/.nvm"))
    nvm_sh = os.path.join(nvm_dir, "nvm.sh")
    nvm_prefix = ""
    if os.path.exists(nvm_sh):
        nvm_prefix = f'source "{nvm_sh}" && '

    # Build the shell command for Node.js
    if use_npm or not shutil.which("yarn"):
        start_cmd = f"{nvm_prefix}npm start"
    else:
        start_cmd = f"{nvm_prefix}yarn start"

    sound_card_env = os.environ.copy()
    # Pass sound card index if we found one
    try:
        with open("/proc/asound/cards", "r") as f:
            for line in f:
                parts = line.strip().split()
                if parts and parts[0].isdigit():
                    sound_card_env["SOUND_CARD_INDEX"] = parts[0]
                    break
    except FileNotFoundError:
        pass

    print("[Node.js] Starting application...")
    web_port = get_env("WHISPLAY_WEB_PORT", "17880")
    print(f"[WebUI] Display will be available at http://0.0.0.0:{web_port}")

    node_proc = subprocess.Popen(
        start_cmd,
        shell=True,
        executable="/bin/bash",
        cwd=working_dir,
        env=sound_card_env,
    )
    processes.append(("node", node_proc))

    def cleanup(signum=None, frame=None):
        print("\n[ChatWin] Shutting down...")
        for name, proc in reversed(processes):
            try:
                print(f"[ChatWin] Stopping {name}...")
                proc.terminate()
            except Exception:
                pass
        for name, proc in reversed(processes):
            try:
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        node_proc.wait()
    except KeyboardInterrupt:
        pass

    cleanup()


if __name__ == "__main__":
    main()
