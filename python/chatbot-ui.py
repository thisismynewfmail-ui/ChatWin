"""
chatbot-ui.py - GPIO button handler and socket server for ChatWin.

Simplified version: no physical LCD display rendering.
Display is handled via the HTML webview (web-display.ts).

This process:
  1. Initializes GPIO button input via WhisplayBoard
  2. Runs a TCP socket server on port 12345
  3. Forwards button press/release events to connected Node.js clients
  4. Accepts and acknowledges display commands from Node.js (no-op rendering)
"""

import os
import json
import sys
import socket
import threading
import signal

from whisplay import WhisplayBoard

clients = {}


def on_button_pressed():
    """Forward button press event to all connected clients."""
    print("[Server] Button pressed")
    notification = {"event": "button_pressed"}
    send_to_all_clients(notification)


def on_button_release():
    """Forward button release event to all connected clients."""
    print("[Server] Button released")
    notification = {"event": "button_released"}
    send_to_all_clients(notification)


def send_to_all_clients(message):
    """Send message to all connected clients."""
    message_json = json.dumps(message).encode("utf-8") + b"\n"
    for addr, client_socket in list(clients.items()):
        try:
            client_socket.sendall(message_json)
        except Exception as e:
            print(f"[Server] Failed to send to client {addr}: {e}")


def handle_client(client_socket, addr, whisplay):
    """Handle a connected client (Node.js).

    Accepts JSON display commands and acknowledges them.
    No LCD rendering - display is handled by the HTML webview.
    """
    print(f"[Socket] Client {addr} connected")
    clients[addr] = client_socket
    try:
        buffer = ""
        while True:
            data = client_socket.recv(4096).decode("utf-8")
            if not data:
                break
            buffer += data

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if not line.strip():
                    continue

                try:
                    content = json.loads(line)

                    # Acknowledge the command
                    client_socket.send(b"OK\n")

                    # Forward response if requested
                    response_to_client = content.get("response", None)
                    if response_to_client:
                        try:
                            response_bytes = (
                                json.dumps({"response": response_to_client}).encode(
                                    "utf-8"
                                )
                                + b"\n"
                            )
                            client_socket.send(response_bytes)
                        except Exception as e:
                            print(f"[Socket - {addr}] Response error: {e}")

                except json.JSONDecodeError:
                    client_socket.send(b"ERROR: invalid JSON\n")
                except Exception as e:
                    print(f"[Socket - {addr}] Error: {e}")
                    client_socket.send(f"ERROR: {e}\n".encode("utf-8"))

    except Exception as e:
        print(f"[Socket - {addr}] Connection error: {e}")
    finally:
        print(f"[Socket] Client {addr} disconnected")
        if addr in clients:
            del clients[addr]
        client_socket.close()


def start_socket_server(whisplay, host="0.0.0.0", port=12345):
    """Start the TCP socket server for communication with Node.js."""
    # Register button event handlers
    whisplay.on_button_press(on_button_pressed)
    whisplay.on_button_release(on_button_release)

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(5)
    print(f"[Socket] Listening on {host}:{port} ...")

    try:
        while True:
            client_socket, addr = server_socket.accept()
            client_thread = threading.Thread(
                target=handle_client, args=(client_socket, addr, whisplay)
            )
            client_thread.daemon = True
            client_thread.start()
    except KeyboardInterrupt:
        print("[Socket] Server stopped")
    finally:
        server_socket.close()


if __name__ == "__main__":
    whisplay = WhisplayBoard()
    print("[GPIO] Button handler initialized")
    print("[Display] Web display mode - no physical LCD rendering")

    def cleanup_and_exit(signum, frame):
        print("[System] Exiting...")
        whisplay.cleanup()
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup_and_exit)
    signal.signal(signal.SIGINT, cleanup_and_exit)

    start_socket_server(whisplay, host="0.0.0.0", port=12345)
