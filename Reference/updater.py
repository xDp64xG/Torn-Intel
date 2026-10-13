"""Keep TornIntel on the latest branch commit and run exactly one bot and listener.

Usage (Linux, inside tmux):
    python updater.py            # watch the branch, restart services after updates
    python updater.py --restart  # update if needed, restart services once, exit
    python updater.py --status   # show which service processes are running
"""

import argparse
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path


BRANCH = "developer"
CHECK_INTERVAL = 60
STOP_TIMEOUT = 20
START_GRACE = 8
TUNNEL_SESSION = "cftunnel"
TUNNEL_PORT = 8765
# tmux session name -> main.py arguments. The arguments also identify stray copies to stop.
SERVICES = {
    "ReviveListener": ["revive_listener", "serve", "--host", "0.0.0.0", "--port", str(TUNNEL_PORT)],
    "DiscordBot": ["discord", "serve"],
}
PROC_ROOT = Path("/proc")


def find_repo_root(script_path=None, cwd=None, home=None):
    """Find the checkout even when updater.py is copied outside the repo."""
    script = Path(script_path or __file__).expanduser().resolve()
    working_directory = Path(cwd or Path.cwd()).expanduser().resolve()
    home_directory = Path(home or Path.home()).expanduser().resolve()
    explicit_root = os.environ.get("TORNINTEL_REPO_ROOT", "").strip()

    candidates = []
    if explicit_root:
        candidates.append(Path(explicit_root).expanduser().resolve())
    candidates.append(script.parent / "Torn-Intel")
    candidates.append(working_directory / "Torn-Intel")
    candidates.extend(script.parents)
    candidates.extend(working_directory.parents)
    candidates.append(working_directory)
    candidates.append(home_directory / "Torn-Intel")

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / ".git").exists():
            return candidate

    checked = ", ".join(str(path) for path in candidates)
    raise RuntimeError(
        "Could not locate the Torn-Intel Git checkout. Set TORNINTEL_REPO_ROOT "
        f"to the checkout path. Checked: {checked}"
    )


REPO_ROOT = find_repo_root()
PYTHON = REPO_ROOT / "venv" / "bin" / "python"
PIP = REPO_ROOT / "venv" / "bin" / "pip"
LOCK_DIR = Path(os.environ.get("TORNINTEL_UPDATER_LOCK_DIR", "/tmp"))
TUNNEL_LOG = Path("/tmp/tunnel.log")
TUNNEL_URL_FILE = Path.home() / "tunnel_url.txt"


def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def run_command(command, check=False):
    """Run a command from the checkout root and return stdout."""
    result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        raise RuntimeError(f"Command failed ({result.returncode}): {detail}")
    return result.stdout.strip()


@contextmanager
def file_lock(name, blocking):
    """flock-based lock; the kernel releases it automatically if this process dies."""
    import fcntl

    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    handle = open(LOCK_DIR / f"tornintel-{name}.lock", "a+")
    try:
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(handle.fileno(), flags)
        except BlockingIOError:
            raise RuntimeError(f"Another updater already holds the {name!r} lock.") from None
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


# ---------------------------------------------------------------- tmux helpers

def list_tmux_sessions():
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return []
    return [name.strip() for name in result.stdout.splitlines() if name.strip()]


def kill_tmux_session(name):
    subprocess.run(
        ["tmux", "kill-session", "-t", f"={name}"],
        cwd=REPO_ROOT, capture_output=True, check=False,
    )


def start_tmux_session(name, command):
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", name, "-c", str(REPO_ROOT), command],
        cwd=REPO_ROOT, check=True,
    )


# ---------------------------------------------------------------- process helpers

def iter_processes(proc_root=None):
    """Yield (pid, argv) for every readable process."""
    root = Path(proc_root or PROC_ROOT)
    if not root.is_dir():
        return
    for entry in root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        argv = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
        if argv:
            yield int(entry.name), argv


def is_service_process(argv, service_args):
    """Match `python main.py <service args>` regardless of interpreter path or extra flags."""
    for index, token in enumerate(argv):
        if os.path.basename(token) == "main.py":
            return argv[index + 1:index + 1 + 2] == service_args[:2]
    return False


def find_service_pids(service_args, proc_root=None):
    own = os.getpid()
    return sorted(
        pid for pid, argv in iter_processes(proc_root)
        if pid != own and is_service_process(argv, service_args)
    )


def find_other_updater_pids(proc_root=None):
    """Other long-running updater loops (e.g. an older copy) that would fight this one."""
    own = os.getpid()
    pids = []
    for pid, argv in iter_processes(proc_root):
        if pid == own or not os.path.basename(argv[0]).startswith("python"):
            continue
        script = next((token for token in argv[1:] if not token.startswith("-")), "")
        if os.path.basename(script) != "updater.py":
            continue
        if "--restart" in argv or "--status" in argv:
            continue
        pids.append(pid)
    return sorted(pids)


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # Zombies still accept signals; treat them as exited.
    try:
        status = (PROC_ROOT / str(pid) / "stat").read_text()
        return status.rsplit(")", 1)[-1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def stop_pids(pids, label, timeout=STOP_TIMEOUT):
    """SIGTERM, wait, then SIGKILL anything that refuses to exit."""
    pids = [pid for pid in pids if pid_alive(pid)]
    if not pids:
        return
    log(f"Stopping {label} (PID {', '.join(map(str, pids))})...")
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pids = [pid for pid in pids if pid_alive(pid)]
        if not pids:
            return
        time.sleep(0.5)
    for pid in pids:
        log(f"{label} PID {pid} ignored SIGTERM; killing it.")
        try:
            os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        except ProcessLookupError:
            pass


# ---------------------------------------------------------------- services

def service_command(name, service_args):
    """Run the service, and keep the pane open after it exits so the error stays visible."""
    command = " ".join(shlex.quote(part) for part in [str(PYTHON), "main.py", *service_args])
    return (
        f"{command}; code=$?; echo; "
        f"echo \"[{name} exited with code $code at $(date). Restart with: python updater.py --restart]\"; "
        "exec sleep infinity"
    )


def stop_service(name, service_args):
    kill_tmux_session(name)
    stop_pids(find_service_pids(service_args), name)
    leftovers = [pid for pid in find_service_pids(service_args) if pid_alive(pid)]
    if leftovers:
        raise RuntimeError(f"{name} is still running after stop (PID {', '.join(map(str, leftovers))}).")


def verify_services(verbose=True):
    """Return True when every service has exactly one live process."""
    healthy = True
    for name, service_args in SERVICES.items():
        pids = [pid for pid in find_service_pids(service_args) if pid_alive(pid)]
        if len(pids) == 1:
            if verbose:
                log(f"{name} is running (PID {pids[0]}).")
        elif not pids:
            healthy = False
            log(f"WARNING: {name} is not running. Check its output with: tmux attach -t {name}")
        else:
            healthy = False
            log(f"WARNING: {name} has {len(pids)} copies running (PID {', '.join(map(str, pids))}).")
    return healthy


def restart_bot_scripts():
    """Stop every copy of each service (tmux or not), then start exactly one of each."""
    for name, service_args in SERVICES.items():
        stop_service(name, service_args)
    for name, service_args in SERVICES.items():
        log(f"Starting {name}...")
        start_tmux_session(name, service_command(name, service_args))
    time.sleep(START_GRACE)
    return verify_services()


def manage_cloudflare_tunnel(force=False):
    """Keep a live tunnel so its URL stays stable; only (re)start it when missing."""
    if not force and TUNNEL_SESSION in list_tmux_sessions():
        log("Cloudflare tunnel already running; keeping the current URL.")
        return None
    kill_tmux_session(TUNNEL_SESSION)
    start_tmux_session(
        TUNNEL_SESSION,
        f"exec cloudflared tunnel --url http://localhost:{TUNNEL_PORT} > {TUNNEL_LOG} 2>&1",
    )
    log("Waiting for Cloudflare to assign a public URL...")
    for _ in range(15):
        time.sleep(2)
        if TUNNEL_LOG.exists():
            match = re.search(
                r"https://[a-zA-Z0-9-]+\.trycloudflare\.com",
                TUNNEL_LOG.read_text(encoding="utf-8", errors="replace"),
            )
            if match:
                url = match.group(0)
                TUNNEL_URL_FILE.write_text(url + "\n", encoding="utf-8")
                log(f"Listener tunnel is live at: {url} (saved to {TUNNEL_URL_FILE})")
                return url
    log(f"Tunnel started, but no URL was found yet. Check {TUNNEL_LOG}.")
    return None


def sync_repository():
    run_command(["git", "fetch", "origin", BRANCH], check=True)
    local_hash = run_command(["git", "rev-parse", "HEAD"], check=True)
    remote_hash = run_command(["git", "rev-parse", f"origin/{BRANCH}"], check=True)
    if local_hash == remote_hash:
        return False
    log(f"Updating checkout {local_hash[:8]} -> {remote_hash[:8]} (origin/{BRANCH})...")
    run_command(["git", "reset", "--hard", f"origin/{BRANCH}"], check=True)
    run_command([str(PIP), "install", "-r", "requirements.txt"], check=True)
    return True


def restart_all_services(force_tunnel=False):
    with file_lock("services", blocking=True):
        restart_bot_scripts()
        manage_cloudflare_tunnel(force=force_tunnel)


def watch():
    with file_lock("watch", blocking=False):
        others = find_other_updater_pids()
        if others:
            stop_pids(others, "older updater loop")
        log(f"Auto-updater started. Watching the '{BRANCH}' branch every {CHECK_INTERVAL}s...")
        try:
            sync_repository()
        except Exception as exc:
            log(f"Initial update check failed: {type(exc).__name__}: {exc}")
        restart_all_services()
        while True:
            time.sleep(CHECK_INTERVAL)
            try:
                if sync_repository():
                    restart_all_services()
                    continue
                with file_lock("services", blocking=True):
                    if not verify_services(verbose=False):
                        log("Service health check failed; restarting services.")
                        restart_bot_scripts()
            except Exception as exc:
                log(f"Update check failed: {type(exc).__name__}: {exc}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Update TornIntel and keep one copy of each service running.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--restart", action="store_true",
        help=f"Update from origin/{BRANCH} if needed, restart services once and exit.",
    )
    group.add_argument("--status", action="store_true", help="Show running service processes and exit.")
    parser.add_argument("--new-tunnel", action="store_true", help="Also restart the Cloudflare tunnel (new URL).")
    args = parser.parse_args(argv)

    if args.status:
        return 0 if verify_services() else 1
    if args.restart:
        sync_repository()
        restart_all_services(force_tunnel=args.new_tunnel)
        return 0
    try:
        watch()
    except RuntimeError as exc:
        log(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
