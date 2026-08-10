from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from advisor_data.bootstrap import (  # noqa: E402
    DependencyBootstrapError,
    ensure_runtime_dependencies,
)


class DependencyBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.target_dir = Path(self.temporary_directory.name) / ".advisor-deps"
        self.requirements_path = SKILL_ROOT / "requirements.txt"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_missing_dependencies_are_installed_to_isolated_target_and_rechecked(self) -> None:
        installed = False
        commands: list[list[str]] = []
        runtime_path: list[str] = []

        def importer(name: str) -> object:
            if not installed:
                raise AssertionError("dependencies must not be imported before installation")
            return object()

        def availability_checker(_: str) -> object | None:
            return object() if installed else None

        def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            nonlocal installed
            commands.append(command)
            installed = True
            return subprocess.CompletedProcess(command, 0, stdout="installed", stderr="")

        receipt = ensure_runtime_dependencies(
            required_modules=("yfinance", "pandas"),
            requirements_path=self.requirements_path,
            target_dir=self.target_dir,
            availability_checker=availability_checker,
            importer=importer,
            runner=runner,
            runtime_path=runtime_path,
            executable="/runtime/python",
        )

        self.assertTrue(receipt["installed"])
        self.assertEqual(receipt["missing_before"], ["yfinance", "pandas"])
        self.assertEqual(receipt["missing_after"], [])
        self.assertEqual(runtime_path[0], str(self.target_dir))
        self.assertEqual(
            commands[0],
            [
                "/runtime/python",
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--upgrade",
                "--target",
                str(self.target_dir),
                "-r",
                str(self.requirements_path),
            ],
        )

    def test_available_dependencies_skip_installation(self) -> None:
        def forbidden_runner(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
            raise AssertionError("pip must not run when imports already succeed")

        receipt = ensure_runtime_dependencies(
            required_modules=("yfinance", "pandas"),
            requirements_path=self.requirements_path,
            target_dir=self.target_dir,
            availability_checker=lambda _: object(),
            importer=lambda _: object(),
            runner=forbidden_runner,
            runtime_path=[],
            executable="/runtime/python",
        )

        self.assertFalse(receipt["installed"])
        self.assertEqual(receipt["missing_before"], [])

    def test_failed_install_is_reported_as_dependency_install_failure(self) -> None:
        attempts = 0

        def failed_runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            nonlocal attempts
            attempts += 1
            raise subprocess.CalledProcessError(1, command, stderr="index unavailable")

        with self.assertRaises(DependencyBootstrapError) as raised:
            ensure_runtime_dependencies(
                required_modules=("yfinance",),
                requirements_path=self.requirements_path,
                target_dir=self.target_dir,
                availability_checker=lambda _: None,
                importer=lambda _: object(),
                runner=failed_runner,
                runtime_path=[],
                executable="/runtime/python",
            )

        self.assertEqual(raised.exception.code, "dependency_install_failed")
        self.assertEqual(raised.exception.details["missing_modules"], ["yfinance"])
        self.assertEqual(attempts, 2)

    def test_install_retries_once_without_cache_after_pip_failure(self) -> None:
        installed = False
        commands: list[list[str]] = []

        def importer(name: str) -> object:
            if not installed:
                raise ModuleNotFoundError(name=name)
            return object()

        def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            nonlocal installed
            commands.append(command)
            if len(commands) == 1:
                raise subprocess.CalledProcessError(2, command, stderr="BadZipFile")
            installed = True
            return subprocess.CompletedProcess(command, 0, stdout="installed", stderr="")

        receipt = ensure_runtime_dependencies(
            required_modules=("yfinance",),
            requirements_path=self.requirements_path,
            target_dir=self.target_dir,
            availability_checker=lambda _: object() if installed else None,
            importer=importer,
            runner=runner,
            runtime_path=[],
            executable="/runtime/python",
        )

        self.assertTrue(receipt["installed"])
        self.assertEqual(len(commands), 2)
        self.assertNotIn("--no-cache-dir", commands[0])
        self.assertIn("--no-cache-dir", commands[1])

    def test_successful_pip_without_importable_modules_is_reported_separately(self) -> None:
        def missing_import(name: str) -> object:
            raise ModuleNotFoundError(name=name)

        with self.assertRaises(DependencyBootstrapError) as raised:
            ensure_runtime_dependencies(
                required_modules=("yfinance",),
                requirements_path=self.requirements_path,
                target_dir=self.target_dir,
                availability_checker=lambda _: None,
                importer=missing_import,
                runner=lambda command, **_: subprocess.CompletedProcess(command, 0, stdout="", stderr=""),
                runtime_path=[],
                executable="/runtime/python",
            )

        self.assertEqual(raised.exception.code, "dependency_import_failed")


if __name__ == "__main__":
    unittest.main()
