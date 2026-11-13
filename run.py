import os
import sys
import webbrowser
import socket
import uvicorn

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def find_available_port(start_port: int = 8000) -> int:
    port = start_port
    while is_port_in_use(port) and port < 8050:
        port += 1
    return port

if __name__ == "__main__":
    port = 8000
    try:
        port = find_available_port(8000)
    except:
        port = 8000

    url = f"http://localhost:{port}"
    print("=" * 60)
    print(f"🚀 AppFlows Studio - Appllama Archive & Flow Downloader")
    print(f"🌐 Server running at: {url}")
    print(f"📁 Watching storage folder: {os.path.abspath('apps')}")
    print("=" * 60)
    print("\n👉 To view flows, open the URL above in your browser.")
    print("👉 Whenever you download a new Appllama webpage, save it into 'apps/' and click 'Scan Folder'.\n")

    # Attempt to open browser
    try:
        webbrowser.open(url)
    except:
        pass

    # Run Uvicorn Server
    uvicorn.run("server:app", host="127.0.0.1", port=port, log_level="info", reload=False)

