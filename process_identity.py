"""Read-only OS process identity for safe background-player fallback termination."""
import json
import os
from pathlib import Path
import subprocess


def identity(pid):
    if type(pid) is not int or pid <= 0:
        return None
    try:
        if os.name == "nt":
            # Only a numeric PID is interpolated. Do not print command lines: they may contain secrets.
            query = (f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}'; "
                     "if($p){@{start=$p.CreationDate.ToUniversalTime().Ticks.ToString(); "
                     "command=$p.CommandLine}|ConvertTo-Json -Compress}")
            result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", query],
                                    capture_output=True, text=True, timeout=10,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            value = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else None
            if not value or not value.get("start") or not value.get("command"):
                return None
            # CommandLineToArgvW follows Windows quoting, including paths with spaces.
            import ctypes
            from ctypes import wintypes
            count = ctypes.c_int()
            split = ctypes.windll.shell32.CommandLineToArgvW
            split.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
            split.restype = ctypes.POINTER(wintypes.LPWSTR)
            pointer = split(value["command"], ctypes.byref(count))
            if not pointer:
                return None
            try:
                arguments = [pointer[index] for index in range(count.value)]
            finally:
                ctypes.windll.kernel32.LocalFree(ctypes.cast(pointer, ctypes.c_void_p))
            return {"start": value["start"], "args": arguments}
        proc = Path("/proc") / str(pid)
        # comm can contain spaces and ')'; starttime is field 22 after its final ')'.
        stat = (proc / "stat").read_text().rsplit(")", 1)[1].split()
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        args = [part.decode("utf-8", errors="replace") for part in (proc / "cmdline").read_bytes().split(b"\0") if part]
        return {"start": boot + ":" + stat[19], "args": args}
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


def is_player(value, script):
    if not value:
        return False
    args = value.get("args", [])
    index = 1  # argv[0] is Python; do not mistake '-c ... codewalk.py serve' for the player.
    while index < len(args) and args[index] in ("-B", "-u", "-E", "-I", "-s", "-S"):
        index += 1
    return (index + 1 < len(args) and args[index + 1] == "serve" and
            os.path.normcase(os.path.abspath(args[index])) == os.path.normcase(str(Path(script).resolve())))
