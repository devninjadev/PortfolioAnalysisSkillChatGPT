"""Install missing runtime dependencies without mutating the system interpreter."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, MutableSequence, Sequence


REQUIRED_MODULES = ("yfinance", "pandas", "numpy", "scipy")


class DependencyBootstrapError(RuntimeError):
    """Raised when missing dependencies cannot be installed and imported."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details or {}


def _default_requirements_path() -> Path:
    return Path(__file__).resolve().parents[2] / "requirements.txt"


def _default_target_dir(requirements_path: Path) -> Path:
    override = os.environ.get("EVIDENCE_ADVISOR_DEPS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    digest = hashlib.sha256(requirements_path.read_bytes()).hexdigest()[:12]
    version = f"py{sys.version_info.major}{sys.version_info.minor}-{digest}"
    return Path.cwd() / ".advisor-runtime" / version


def _missing_modules(
    required_modules: Sequence[str], importer: Callable[[str], object]
) -> list[str]:
    missing: list[str] = []
    for module_name in required_modules:
        try:
            importer(module_name)
        except (ImportError, ModuleNotFoundError):
            missing.append(module_name)
    return missing


def _unavailable_modules(
    required_modules: Sequence[str], availability_checker: Callable[[str], object | None]
) -> list[str]:
    return [name for name in required_modules if availability_checker(name) is None]


def _prepare_target(target_dir: Path, allow_temp_fallback: bool) -> Path:
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir
    except OSError as first_error:
        if not allow_temp_fallback:
            raise DependencyBootstrapError(
                "dependency_install_failed",
                "The isolated dependency directory is not writable.",
                {"target_dir": str(target_dir), "error_type": first_error.__class__.__name__},
            ) from first_error
        fallback = (
            Path(tempfile.gettempdir())
            / "evidence-first-portfolio-advisor"
            / target_dir.name
        )
        try:
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback
        except OSError as fallback_error:
            raise DependencyBootstrapError(
                "dependency_install_failed",
                "No writable isolated dependency directory is available.",
                {
                    "target_dir": str(target_dir),
                    "fallback_dir": str(fallback),
                    "error_type": fallback_error.__class__.__name__,
                },
            ) from fallback_error


def ensure_runtime_dependencies(
    required_modules: Sequence[str] = REQUIRED_MODULES,
    requirements_path: Path | None = None,
    target_dir: Path | None = None,
    availability_checker: Callable[[str], object | None] = importlib.util.find_spec,
    importer: Callable[[str], object] = importlib.import_module,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    runtime_path: MutableSequence[str] = sys.path,
    executable: str = sys.executable,
) -> dict[str, Any]:
    """Import dependencies, installing requirements into an isolated directory when needed."""

    resolved_requirements = requirements_path or _default_requirements_path()
    if not resolved_requirements.is_file():
        raise DependencyBootstrapError(
            "requirements_missing",
            "The skill requirements file is missing.",
            {"requirements_path": str(resolved_requirements)},
        )

    explicit_target = target_dir is not None or bool(os.environ.get("EVIDENCE_ADVISOR_DEPS_DIR"))
    resolved_target = target_dir or _default_target_dir(resolved_requirements)
    if resolved_target.is_dir() and str(resolved_target) not in runtime_path:
        runtime_path.insert(0, str(resolved_target))

    missing_before = _unavailable_modules(required_modules, availability_checker)
    if not missing_before:
        missing_before = _missing_modules(required_modules, importer)
    if not missing_before:
        return {
            "installed": False,
            "missing_before": [],
            "missing_after": [],
            "target_dir": str(resolved_target) if resolved_target.is_dir() else None,
            "interpreter": executable,
        }

    resolved_target = _prepare_target(resolved_target, allow_temp_fallback=not explicit_target)
    command = [
        executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--upgrade",
        "--target",
        str(resolved_target),
        "-r",
        str(resolved_requirements),
    ]
    retry_command = [*command[:5], "--no-cache-dir", *command[5:]]
    install_error: OSError | subprocess.CalledProcessError | None = None
    install_attempts = 0
    for active_command in (command, retry_command):
        install_attempts += 1
        try:
            runner(active_command, check=True, capture_output=True, text=True)
            install_error = None
            break
        except (OSError, subprocess.CalledProcessError) as exc:
            install_error = exc
    if install_error is not None:
        stderr = getattr(install_error, "stderr", None)
        raise DependencyBootstrapError(
            "dependency_install_failed",
            "Missing Python dependencies could not be installed after a no-cache retry.",
            {
                "missing_modules": missing_before,
                "target_dir": str(resolved_target),
                "install_attempts": install_attempts,
                "error_type": install_error.__class__.__name__,
                "return_code": getattr(install_error, "returncode", None),
                "stderr_tail": stderr[-2000:] if isinstance(stderr, str) else None,
            },
        ) from install_error

    if str(resolved_target) in runtime_path:
        runtime_path.remove(str(resolved_target))
    runtime_path.insert(0, str(resolved_target))
    importlib.invalidate_caches()
    missing_after = _missing_modules(required_modules, importer)
    if missing_after:
        raise DependencyBootstrapError(
            "dependency_import_failed",
            "Dependencies were installed but remain unavailable to the active interpreter.",
            {
                "missing_modules": missing_after,
                "target_dir": str(resolved_target),
                "interpreter": executable,
            },
        )

    return {
        "installed": True,
        "missing_before": missing_before,
        "missing_after": [],
        "target_dir": str(resolved_target),
        "interpreter": executable,
    }


__all__ = [
    "DependencyBootstrapError",
    "REQUIRED_MODULES",
    "ensure_runtime_dependencies",
]
