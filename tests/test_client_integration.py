from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

import pytest

import pmgs_reference.client_integration as client_integration_module
from pmgs_reference.agent_kit import install_agent_skills
from pmgs_reference.client_integration import (
    ClientTarget,
    CommandResult,
    SubprocessCommandRunner,
    integrate_clients,
    windows_batch_command,
)


class FakeClientRunner:
    def __init__(self, home: Path, *, fail_client: str | None = None) -> None:
        self.home = home
        self.fail_client = fail_client
        self.calls: list[tuple[str, list[str]]] = []
        self.codex_config: dict[str, object] | None = None

    def run(self, executable: Path, arguments: Sequence[str]) -> CommandResult:
        client = "codex" if "codex" in executable.name else "claude"
        args = list(arguments)
        self.calls.append((client, args))
        if client == "codex" and args == ["mcp", "list", "--json"]:
            servers: list[object] = []
            if self.codex_config is not None:
                servers.append(
                    {
                        "name": "pmgs-reference",
                        "transport": {"type": "stdio", **self.codex_config},
                    }
                )
            return CommandResult(0, json.dumps(servers), "")
        if self.fail_client == client:
            return CommandResult(7, "", "simulated failure")
        separator = args.index("--")
        server = args[separator + 1 :]
        config = {"type": "stdio", "command": server[0], "args": server[1:]}
        if client == "codex":
            self.codex_config = config
        else:
            self.home.mkdir(parents=True, exist_ok=True)
            (self.home / ".claude.json").write_text(
                json.dumps({"mcpServers": {"pmgs-reference": config}}),
                encoding="utf-8",
            )
        return CommandResult(0, "", "")


def _targets(tmp_path: Path) -> tuple[ClientTarget, ...]:
    return (
        ClientTarget("codex", tmp_path / "codex.exe"),
        ClientTarget("claude", tmp_path / "claude.exe"),
    )


def test_declined_clients_do_not_execute_or_write(tmp_path: Path) -> None:
    home = tmp_path / "home"
    runner = FakeClientRunner(home)

    statuses = integrate_clients(
        _targets(tmp_path),
        (),
        python_executable=tmp_path / "python.exe",
        data_dir=tmp_path / "data-root",
        home=home,
        runner=runner,
    )

    assert [item["status"] for item in statuses] == ["declined", "declined"]
    assert runner.calls == []
    assert not home.exists()


def test_codex_and_claude_register_data_dir_and_install_the_shared_skill(tmp_path: Path) -> None:
    home = tmp_path / "home"
    runner = FakeClientRunner(home)
    python = tmp_path / "tool" / "python.exe"
    data_root = tmp_path / "data-root"

    statuses = integrate_clients(
        _targets(tmp_path),
        ("codex", "claude"),
        python_executable=python,
        data_dir=data_root,
        home=home,
        runner=runner,
    )

    assert [item["status"] for item in statuses] == ["installed", "installed"]
    add_calls = [call for call in runner.calls if call[1][:2] == ["mcp", "add"]]
    assert len(add_calls) == 2
    for _client, arguments in add_calls:
        separator = arguments.index("--")
        assert arguments[separator + 1 :] == [
            str(python.absolute()),
            "-m",
            "pmgs_reference.cli",
            "mcp",
            "--data-dir",
            str(data_root.resolve()),
        ]
    assert "--scope" not in add_calls[0][1]
    assert add_calls[1][1][2:6] == ["--transport", "stdio", "--scope", "user"]
    assert (home / ".agents" / "skills" / "pmgs-reference" / "SKILL.md").is_file()
    assert (home / ".claude" / "skills" / "pmgs-reference" / "SKILL.md").is_file()


def test_conflicting_codex_server_is_not_overwritten(tmp_path: Path) -> None:
    home = tmp_path / "home"
    runner = FakeClientRunner(home)
    runner.codex_config = {"command": "different-python", "args": ["different-server"]}
    target = ClientTarget("codex", tmp_path / "codex.exe")

    status = integrate_clients(
        (target,),
        ("codex",),
        python_executable=tmp_path / "python.exe",
        data_dir=tmp_path / "data-root",
        home=home,
        runner=runner,
    )[0]

    assert status["status"] == "conflict"
    assert runner.calls == [("codex", ["mcp", "list", "--json"])]
    assert not (home / ".agents").exists()


def test_existing_matching_integrations_are_no_op(tmp_path: Path) -> None:
    home = tmp_path / "home"
    runner = FakeClientRunner(home)
    python = (tmp_path / "python.exe").absolute()
    data_root = (tmp_path / "data-root").resolve()
    expected = {
        "command": str(python),
        "args": ["-m", "pmgs_reference.cli", "mcp", "--data-dir", str(data_root)],
    }
    runner.codex_config = expected
    home.mkdir(parents=True)
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"pmgs-reference": {"type": "stdio", **expected}}}),
        encoding="utf-8",
    )
    install_agent_skills(("codex", "claude"), home=home)

    statuses = integrate_clients(
        _targets(tmp_path),
        ("codex", "claude"),
        python_executable=python,
        data_dir=data_root,
        home=home,
        runner=runner,
    )

    assert [item["status"] for item in statuses] == ["already_present", "already_present"]
    assert runner.calls == [("codex", ["mcp", "list", "--json"])]


def test_one_client_failure_does_not_undo_the_other_client(tmp_path: Path) -> None:
    home = tmp_path / "home"
    runner = FakeClientRunner(home, fail_client="claude")

    statuses = integrate_clients(
        _targets(tmp_path),
        ("codex", "claude"),
        python_executable=tmp_path / "python.exe",
        data_dir=tmp_path / "data-root",
        home=home,
        runner=runner,
    )

    assert statuses[0]["status"] == "installed"
    assert statuses[1]["status"] == "failed"
    assert runner.codex_config is not None
    assert not (home / ".claude.json").exists()


def test_registration_keeps_restart_required_when_skill_install_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    runner = FakeClientRunner(home)

    def fail_skill_install(*args: object, **kwargs: object) -> list[dict[str, object]]:
        raise OSError("simulated skill failure")

    monkeypatch.setattr(client_integration_module, "install_agent_skills", fail_skill_install)

    status = integrate_clients(
        (ClientTarget("codex", tmp_path / "codex.exe"),),
        ("codex",),
        python_executable=tmp_path / "python.exe",
        data_dir=tmp_path / "data-root",
        home=home,
        runner=runner,
    )[0]

    assert status["status"] == "failed"
    assert status["mcp"] == "installed"
    assert status["skill"] == "missing"
    assert status["restart_required"] is True
    assert runner.codex_config is not None


def test_claude_custom_config_directory_is_used_consistently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    custom = tmp_path / "claude-profile"
    python = (tmp_path / "python.exe").absolute()
    data_root = (tmp_path / "data-root").resolve()
    expected = {
        "type": "stdio",
        "command": str(python),
        "args": ["-m", "pmgs_reference.cli", "mcp", "--data-dir", str(data_root)],
    }
    custom.mkdir()
    (custom / ".claude.json").write_text(
        json.dumps({"mcpServers": {"pmgs-reference": expected}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(custom))
    install_agent_skills(("claude",), home=home)
    runner = FakeClientRunner(home)

    status = integrate_clients(
        (ClientTarget("claude", tmp_path / "claude.exe"),),
        ("claude",),
        python_executable=python,
        data_dir=data_root,
        home=home,
        runner=runner,
    )[0]

    assert status["status"] == "already_present"
    assert runner.calls == []
    assert (custom / "skills" / "pmgs-reference" / "SKILL.md").is_file()
    assert not (home / ".claude").exists()


def test_windows_batch_command_rejects_shell_metacharacters() -> None:
    with pytest.raises(ValueError, match="metacharacters"):
        windows_batch_command(
            Path("C:/tools/claude.cmd"),
            ["mcp", "add", "--data-dir", "C:/managed&whoami"],
        )

    safe = windows_batch_command(
        Path("C:/Program Files/Claude/claude.cmd"),
        ["mcp", "list", "--json"],
    )
    assert " /d /v:off /s /c " in safe


@pytest.mark.skipif(os.name != "nt", reason="Windows cmd.exe integration test")
def test_subprocess_runner_executes_a_safe_batch_launcher(tmp_path: Path) -> None:
    launcher = tmp_path / "client tools" / "fake client.cmd"
    launcher.parent.mkdir()
    launcher.write_text(
        '@echo off\nif "%~1"=="mcp" exit /b 0\nexit /b 9\n',
        encoding="utf-8",
    )

    result = SubprocessCommandRunner().run(launcher, ("mcp", "list", "--json"))

    assert result.returncode == 0
