"""Thin subprocess wrapper around the `sports-skills` CLI.

The CLI prints a JSON payload on stdout and any source warnings/errors on
stderr, so the two never need to be mixed to get a clean parse.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass


class SportsSkillsNotInstalled(RuntimeError):
    pass


class SportsSkillsError(RuntimeError):
    def __init__(self, command: list[str], returncode: int, stderr: str):
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(
            f"sports-skills command failed ({returncode}): {' '.join(command)}\n{stderr}"
        )


@dataclass
class SportsSkillsResult:
    status: bool
    data: dict
    message: str
    warnings: str


def _binary_path() -> str:
    path = shutil.which("sports-skills")
    if path is None:
        raise SportsSkillsNotInstalled(
            "The 'sports-skills' CLI was not found on PATH. "
            "Install it with: pip install sports-skills"
        )
    return path


def call(command: str, **params: str | int) -> SportsSkillsResult:
    """Run `sports-skills football <command> --k=v ...` and parse the JSON result.

    Values that are None are skipped so callers can pass optional params
    directly without building a filtered dict themselves.
    """
    binary = _binary_path()
    args = [binary, "football", command]
    for key, value in params.items():
        if value is None:
            continue
        args.append(f"--{key}={value}")

    proc = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise SportsSkillsError(args, proc.returncode, proc.stderr)

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SportsSkillsError(args, proc.returncode, f"Non-JSON stdout: {exc}\n{proc.stdout[:500]}")

    return SportsSkillsResult(
        status=bool(payload.get("status", False)),
        data=payload.get("data", {}) or {},
        message=payload.get("message", "") or "",
        warnings=proc.stderr.strip(),
    )
