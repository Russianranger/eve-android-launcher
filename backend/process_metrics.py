"""Small Linux process metrics shared by client/server monitoring."""

from pathlib import Path


def available_memory_kib(meminfo: Path = Path("/proc/meminfo")) -> int | None:
    """Read just MemAvailable for the client's frequent memory-reserve check."""
    try:
        for line in meminfo.read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                fields = line.split()
                if len(fields) != 3 or fields[2] != "kB":
                    return None
                value = int(fields[1])
                return value if value >= 0 else None
    except (OSError, ValueError, UnicodeError):
        pass
    return None
