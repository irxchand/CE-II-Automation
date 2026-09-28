"""
CE-II Automation — One-time setup script.

Run this ONCE after cloning the repo:
    python setup.py

What it does:
1. Notifies the repo owner (via ntfy.sh) that the repo was cloned.
2. Registers a background auto-pull task that runs `git pull` every 1 minute
   so you always have the latest code without running anything manually.

Supports: Windows (Task Scheduler) and macOS (launchd).
"""

import os
import sys
import platform
import subprocess
import socket
import datetime
import json

# ──────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────
NTFY_TOPIC = "ceii-auto-irxchand"  # Subscribe at https://ntfy.sh/ceii-auto-irxchand
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_DIR = os.path.join(REPO_DIR, ".local")
MARKER_FILE = os.path.join(LOCAL_DIR, ".setup_done")
TASK_NAME = "CE-II-AutoPull"

# ──────────────────────────────────────────────────────────────────────
# Notification
# ──────────────────────────────────────────────────────────────────────
def send_clone_notification():
    """Send a push notification to the repo owner via ntfy.sh."""
    import urllib.request

    try:
        username = os.getlogin()
    except Exception:
        username = os.environ.get("USER", os.environ.get("USERNAME", "unknown"))

    hostname = socket.gethostname()
    os_info = f"{platform.system()} {platform.release()}"
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    message = (
        f"👤 User: {username}\n"
        f"💻 Machine: {hostname}\n"
        f"🖥️ OS: {os_info}\n"
        f"📁 Path: {REPO_DIR}\n"
        f"🕐 Time: {timestamp}"
    )

    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={
            "Title": "CE-II Automation: New Clone Detected",
            "Priority": "high",
            "Tags": "wave,computer",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        print("  ✅ Owner notified successfully.")
    except Exception as e:
        print(f"  ⚠️  Could not send notification (network issue?): {e}")


# ──────────────────────────────────────────────────────────────────────
# Auto-pull: Windows (Task Scheduler)
# ──────────────────────────────────────────────────────────────────────
def setup_auto_pull_windows():
    """Register a Scheduled Task that silently runs git pull every 1 minute."""
    ps_script = os.path.join(REPO_DIR, "auto_pull.ps1")

    # Write the auto-pull PowerShell script with the correct repo path baked in
    with open(ps_script, "w", encoding="utf-8") as f:
        f.write(f'Set-Location "{REPO_DIR}"\n')
        f.write("git pull 2>&1 | Out-Null\n")

    # Remove existing task if any (ignore errors)
    subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Create new scheduled task: every 1 minute, hidden window
    result = subprocess.run(
        [
            "schtasks", "/Create",
            "/TN", TASK_NAME,
            "/TR", f'powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File "{ps_script}"',
            "/SC", "MINUTE",
            "/MO", "1",
            "/F",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print(f"  ✅ Scheduled Task '{TASK_NAME}' created (runs every 1 minute).")
    else:
        print(f"  ❌ Failed to create Scheduled Task: {result.stderr.strip()}")
        print("     Try running this script as Administrator.")
        return False
    return True


# ──────────────────────────────────────────────────────────────────────
# Auto-pull: macOS (launchd)
# ──────────────────────────────────────────────────────────────────────
def setup_auto_pull_macos():
    """Register a launchd agent that runs git pull every 60 seconds."""
    # Create the shell script
    sh_script = os.path.join(REPO_DIR, "auto_pull.sh")
    with open(sh_script, "w", encoding="utf-8") as f:
        f.write("#!/bin/bash\n")
        f.write(f'cd "{REPO_DIR}" && git pull 2>/dev/null\n')
    os.chmod(sh_script, 0o755)

    label = "com.ceii.autopull"
    plist_dir = os.path.expanduser("~/Library/LaunchAgents")
    os.makedirs(plist_dir, exist_ok=True)
    plist_path = os.path.join(plist_dir, f"{label}.plist")

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sh_script}</string>
    </array>
    <key>StartInterval</key>
    <integer>60</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/dev/null</string>
    <key>StandardErrorPath</key>
    <string>/dev/null</string>
</dict>
</plist>
"""
    with open(plist_path, "w", encoding="utf-8") as f:
        f.write(plist_content)

    # Unload if already loaded, then load
    subprocess.run(["launchctl", "unload", plist_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    result = subprocess.run(["launchctl", "load", plist_path],
                             capture_output=True, text=True)

    if result.returncode == 0:
        print(f"  ✅ launchd agent '{label}' registered (runs every 60 seconds).")
    else:
        print(f"  ❌ Failed to load launchd agent: {result.stderr.strip()}")
        return False
    return True


# ──────────────────────────────────────────────────────────────────────
# Auto-pull: Linux (cron)
# ──────────────────────────────────────────────────────────────────────
def setup_auto_pull_linux():
    """Add a cron job that runs git pull every minute."""
    cron_comment = "# CE-II-AutoPull"
    cron_line = f"* * * * * cd {REPO_DIR} && git pull > /dev/null 2>&1 {cron_comment}"

    # Get existing crontab
    try:
        existing = subprocess.check_output(["crontab", "-l"], text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        existing = ""

    # Remove any old CE-II entries and add new one
    lines = [l for l in existing.strip().split("\n") if cron_comment not in l and l.strip()]
    lines.append(cron_line)
    new_crontab = "\n".join(lines) + "\n"

    proc = subprocess.run(["crontab", "-"], input=new_crontab, text=True,
                           capture_output=True)
    if proc.returncode == 0:
        print("  ✅ Cron job registered (runs every 1 minute).")
    else:
        print(f"  ❌ Failed to set cron: {proc.stderr.strip()}")
        return False
    return True


# ──────────────────────────────────────────────────────────────────────
# Uninstall
# ──────────────────────────────────────────────────────────────────────
def uninstall():
    """Remove the background auto-pull task."""
    system = platform.system()
    if system == "Windows":
        subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
                        capture_output=True)
        print(f"  ✅ Scheduled Task '{TASK_NAME}' removed.")
    elif system == "Darwin":
        label = "com.ceii.autopull"
        plist_path = os.path.expanduser(f"~/Library/LaunchAgents/{label}.plist")
        subprocess.run(["launchctl", "unload", plist_path],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(plist_path):
            os.remove(plist_path)
        print(f"  ✅ launchd agent '{label}' removed.")
    else:
        cron_comment = "# CE-II-AutoPull"
        try:
            existing = subprocess.check_output(["crontab", "-l"], text=True, stderr=subprocess.DEVNULL)
            lines = [l for l in existing.strip().split("\n") if cron_comment not in l and l.strip()]
            subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True)
            print("  ✅ Cron job removed.")
        except Exception:
            print("  ⚠️  Could not modify crontab.")

    if os.path.exists(MARKER_FILE):
        os.remove(MARKER_FILE)
    print("  Done. Auto-pull is disabled.")


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────
def main():
    # Handle --uninstall flag
    if len(sys.argv) > 1 and sys.argv[1] in ("--uninstall", "--remove", "uninstall"):
        print("\n🗑️  Removing auto-pull...")
        uninstall()
        return

    print()
    print("=" * 60)
    print("  CE-II Automation — Setup")
    print("=" * 60)

    # Check if already set up
    if os.path.exists(MARKER_FILE):
        print("\n  ℹ️  Setup was already completed on this machine.")
        print(f"  Marker: {MARKER_FILE}")
        print("  To re-run, delete .local/.setup_done and run again.")
        print("  To uninstall: python setup.py --uninstall")
        return

    os.makedirs(LOCAL_DIR, exist_ok=True)

    # Step 1: Notify the owner
    print("\n📡 Step 1: Notifying repo owner...")
    send_clone_notification()

    # Step 2: Set up auto-pull
    print("\n🔄 Step 2: Setting up background auto-pull (every 1 minute)...")
    system = platform.system()
    success = False
    if system == "Windows":
        success = setup_auto_pull_windows()
    elif system == "Darwin":
        success = setup_auto_pull_macos()
    else:
        success = setup_auto_pull_linux()

    if not success:
        print("\n  ⚠️  Auto-pull setup failed. You can still use 'python main.py' (it pulls on launch).")

    # Save marker
    setup_info = {
        "setup_at": datetime.datetime.now().isoformat(),
        "machine": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "repo_dir": REPO_DIR,
    }
    with open(MARKER_FILE, "w", encoding="utf-8") as f:
        json.dump(setup_info, f, indent=2)

    print("\n" + "=" * 60)
    print("  ✅ Setup complete!")
    print("=" * 60)
    print(f"\n  Auto-pull runs every 1 minute in the background.")
    print(f"  No need to run anything manually — just use: python main.py")
    print(f"\n  To remove auto-pull: python setup.py --uninstall")
    print()


if __name__ == "__main__":
    main()
