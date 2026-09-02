#!/usr/bin/env python3
"""
Local development server launcher.
Runs both the FastAPI backend and HTTP frontend server.
"""
import subprocess
import time
import sys
import os

def main():
    print("=" * 60)
    print("🚀 Starting Signalwave Local Servers")
    print("=" * 60)
    
    # Change to project root
    project_root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_root)
    
    # Start backend
    print("\n[1/2] Starting FastAPI backend on http://localhost:9000")
    backend_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--port", "9000", "--reload"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    time.sleep(3)  # Wait for backend to start
    
    # Start frontend
    print("[2/2] Starting HTTP server for frontend on http://localhost:5000")
    docs_dir = os.path.join(project_root, "docs")
    frontend_proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", "5000", "-d", docs_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    print("\n" + "=" * 60)
    print("✅ Both servers are running!")
    print("=" * 60)
    print("\n📍 Frontend:  http://localhost:5000")
    print("📍 Backend:   http://localhost:9000")
    print("📍 API Docs:  http://localhost:9000/docs")
    print("\n💡 Press Ctrl+C to stop both servers")
    print("=" * 60 + "\n")
    
    try:
        backend_proc.wait()
        frontend_proc.wait()
    except KeyboardInterrupt:
        print("\n\n⛔ Shutting down servers...")
        backend_proc.terminate()
        frontend_proc.terminate()
        backend_proc.wait(timeout=5)
        frontend_proc.wait(timeout=5)
        print("✅ Servers stopped.")
        sys.exit(0)

if __name__ == "__main__":
    main()
