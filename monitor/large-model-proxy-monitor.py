#!/usr/bin/env python3
"""
llama-proxy‑monitor.py

Monitors GPU usage with `nvidia-smi` and automatically
starts/stops `large-model-proxy` with a *minimal* idle‑delay
policy:

* If the GPU is idle from the very beginning, the proxy is started
  immediately.
* After the first start, the 60‑second sustained‑idle rule keeps the
  proxy from being restarted too often.

All important events are written to the systemd journal
(`journalctl -u llama-proxy-monitor.service -f`).

Configuration is still done with environment variables (see the
unit‑file example below).
"""

import logging
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import List, Tuple

# ------------------------------------------------------------------
# CONFIGURATION (overridable via environment variables)
# ------------------------------------------------------------------
POLLING_INTERVAL = float(os.getenv("POLLING_INTERVAL", "5"))
IDLE_THRESHOLD = float(os.getenv("IDLE_THRESHOLD", "2"))  # percent
IDLE_DURATION = int(os.getenv("IDLE_DURATION", "60"))  # seconds
PROXY_CMD = os.getenv(
    "PROXY_CMD",
    "./large-model-proxy -c /etc/large-model-proxy/config.jsonc",
)
PID_FILE = Path(os.getenv("PID_FILE", "/run/large-model-proxy.pid"))

# ------------------------------------------------------------------
# LOGGING SETUP – writes to the systemd journal via stdout
# ------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------
def run_cmd(cmd: str) -> Tuple[str, str]:
    """Run a shell command, return (stdout, stderr)."""
    try:
        out = subprocess.check_output(
            shlex.split(cmd), stderr=subprocess.STDOUT
        )
        return out.decode().strip(), ""
    except subprocess.CalledProcessError as e:
        return e.output.decode().strip(), e.stderr.decode().strip()


def gpu_memory() -> Tuple[int, int]:
    """Return (used, total) GPU memory in MiB."""
    stdout, _ = run_cmd(
        "nvidia-smi --query-gpu=memory.used,memory.total "
        "--format=csv,noheader,nounits"
    )
    total_used = 0
    total_capacity = 0
    for line in stdout.splitlines():
        parts = line.split(",")
        if len(parts) == 2:
            try:
                total_used += int(parts[0].strip())
                total_capacity += int(parts[1].strip())
            except ValueError:
                continue
    return total_used, total_capacity


def gpu_processes() -> List[Tuple[int, str, int]]:
    """Return [(pid, name, used_memory)] for every compute app."""
    stdout, _ = run_cmd(
        "nvidia-smi --query-compute-apps=pid,process_name,used_memory "
        "--format=csv,noheader,nounits"
    )
    procs = []
    for line in stdout.splitlines():
        pid, name, mem = line.split(",")
        procs.append((int(pid.strip()), name.strip(), int(mem.strip())))
    return procs


def is_proxy_running() -> bool:
    """Return True if a PID file exists and the PID is alive."""
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)  # raise OSError if not running
        return True
    except (OSError, ValueError):
        return False


def write_pid(pid: int):
    """Persist the proxy PID."""
    PID_FILE.write_text(str(pid))
    logger.info(f"Proxy PID {pid} written to {PID_FILE}")


def remove_pid():
    """Delete the PID file."""
    if PID_FILE.exists():
        try:
            PID_FILE.unlink()
            logger.debug(f"PID file {PID_FILE} removed")
        except Exception as e:
            logger.warning(f"Failed to remove PID file: {e}")


# ------------------------------------------------------------------
# PROXY CONTROL
# ------------------------------------------------------------------
def start_proxy():
    """Start the proxy, log its stdout/stderr, and remember its PID."""
    if is_proxy_running():
        logger.info("Proxy already running – skipping start")
        return

    logger.info(f"Starting proxy with command: {PROXY_CMD}")

    # Ensure we get the real path (e.g. ~ expands)
    cmd_parts = shlex.split(PROXY_CMD)
    try:
        # Redirect stdout/stderr to the journal via the systemd unit
        proc = subprocess.Popen(
            cmd_parts,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # binary mode
            text=False,
            bufsize=0,
        )
        write_pid(proc.pid)

        # Non‑blocking read of the proxy output and write it to the log
        def stream_reader(pipe, level=logging.INFO):
            for line_bytes in iter(pipe.readline, b''):
                # Decode with a tolerant strategy
                line = line_bytes.decode('utf-8', errors='replace')
                logger.log(level, f"PROXY: {line.rstrip()}")
            pipe.close()

        t_out = threading.Thread(
            target=stream_reader, args=(proc.stdout, logging.INFO), daemon=True
        )
        t_err = threading.Thread(
            target=stream_reader, args=(proc.stderr, logging.WARNING), daemon=True
        )
        t_out.start()
        t_err.start()

        logger.info(f"Proxy started (pid={proc.pid})")
    except Exception as e:
        logger.error(f"Failed to launch proxy: {e}")


def stop_proxy():
    """Terminate the proxy gracefully; kill if it refuses."""
    if not is_proxy_running():
        logger.debug("Proxy not running – nothing to stop")
        return

    pid = int(PID_FILE.read_text().strip())
    logger.info(f"Stopping proxy (pid={pid})")

    try:
        os.kill(pid, 15)  # SIGTERM
    except Exception as e:
        logger.warning(f"Failed to send SIGTERM: {e}")

    # Give it a few moments to exit cleanly
    for _ in range(10):
        if not is_proxy_running():
            break
        time.sleep(0.1)

    if is_proxy_running():
        logger.warning("Proxy did not terminate – sending SIGKILL")
        try:
            os.kill(pid, 9)  # SIGKILL
        except Exception as e:
            logger.error(f"Failed to SIGKILL: {e}")

    remove_pid()
    logger.info("Proxy stopped")


# ------------------------------------------------------------------
# MAIN LOOP
# ------------------------------------------------------------------
def main_loop():
    idle_since = None  # timestamp when GPU first became idle
    first_start_done = False  # true after the very first start

    while True:
        used, total = gpu_memory()
        free_pct = (total - used) * 100 / total if total else 0

        # Log a quick snapshot (you can comment this out if you want less noise)
        logger.debug(
            f"GPU snapshot: used={used}MiB / {total}MiB ({free_pct:.1f}% free)"
        )

        # Determine memory used by *other* processes
        other_mem = sum(
            mem
            for _, name, mem in gpu_processes()
            if "llama-server" not in name.lower()
        )
        other_pct = other_mem * 100 / total if total else 0

        # If a higher‑priority workload appears, kill the proxy
        if other_pct > IDLE_THRESHOLD:
            if is_proxy_running():
                logger.warning(
                    f"Other workload ({other_pct:.1f}%) exceeds "
                    f"threshold ({IDLE_THRESHOLD}%) – stopping proxy"
                )
                stop_proxy()
            idle_since = None
            first_start_done = False
            continue

        # GPU is idle – decide whether to start or keep idle
        if free_pct >= IDLE_THRESHOLD:
            # Idle from the very beginning – start immediately
            if not first_start_done:
                logger.info(
                    f"GPU idle ({free_pct:.1f}%) – starting proxy immediately"
                )
                start_proxy()
                first_start_done = True
                idle_since = None  # no need to track idle time for future
                continue

            # After the first start, enforce the sustained‑idle rule
            if idle_since is None:
                idle_since = time.time()
                logger.debug("Idle timer started")
            elif time.time() - idle_since >= IDLE_DURATION:
                if not is_proxy_running():
                    logger.info(
                        f"GPU idle for {IDLE_DURATION}s – starting proxy"
                    )
                    start_proxy()
                idle_since = None
        else:
            # GPU not idle – reset timers
            idle_since = None

        time.sleep(POLLING_INTERVAL)


if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        logger.info("Interrupted – shutting down")
        stop_proxy()
