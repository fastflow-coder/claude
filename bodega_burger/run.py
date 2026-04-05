"""
Bodega Burger — Launcher
Starts both the Telegram bot and FastAPI web dashboard as separate subprocesses.

Usage:
    python run.py
"""
import signal
import subprocess
import sys
import time


def main():
    print("=" * 50)
    print("  Bodega Burger Restaurant Manager")
    print("  Toronto, CA")
    print("=" * 50)
    print()

    procs = []

    try:
        # Start Telegram bot
        bot_proc = subprocess.Popen(
            [sys.executable, "bot.py"],
            cwd=".",
        )
        procs.append(("Telegram Bot", bot_proc))
        print("[+] Telegram bot started (PID %d)" % bot_proc.pid)

        # Brief delay so DB is initialised before web app starts
        time.sleep(1)

        # Start FastAPI web dashboard
        web_proc = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                "web_app:app",
                "--host", "0.0.0.0",
                "--port", "8000",
                "--reload",
            ],
            cwd=".",
        )
        procs.append(("Web Dashboard", web_proc))
        print("[+] Web dashboard started (PID %d) → http://localhost:8000" % web_proc.pid)
        print()
        print("Press Ctrl+C to stop both services.")
        print()

        # Wait for either process to exit (which would be unexpected)
        while True:
            for name, proc in procs:
                ret = proc.poll()
                if ret is not None:
                    print(f"\n[!] {name} exited with code {ret}. Shutting down...")
                    raise KeyboardInterrupt
            time.sleep(2)

    except KeyboardInterrupt:
        print("\nShutting down...")

    finally:
        for name, proc in procs:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                print(f"[-] {name} stopped.")


if __name__ == "__main__":
    main()
