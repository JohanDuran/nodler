"""Subprocess helper shared by the git and GitHub adapters."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.code == 0


class CommandError(RuntimeError):
    pass


def run(args: list[str] | str, cwd: str | None = None, check: bool = True, timeout: int = 600,
        shell: bool = False, input: str | None = None) -> Result:
    p = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, shell=shell, input=input,
    )
    res = Result(p.returncode, p.stdout, p.stderr)
    if check and not res.ok:
        shown = args if isinstance(args, str) else " ".join(args)
        raise CommandError(f"`{shown}` failed ({res.code}): {res.err.strip() or res.out.strip()}")
    return res
