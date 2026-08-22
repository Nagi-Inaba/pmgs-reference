"""Command-line entry point for PMGS Reference."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Never, cast

from pmgs_reference import __version__
from pmgs_reference.agent_kit import (
    AgentClient,
    install_agent_skills,
    prepare_agent_kit,
    resolve_clients,
)
from pmgs_reference.client_integration import ClientSelection, detect_client_targets
from pmgs_reference.data_paths import CurrentPointerError, default_data_root
from pmgs_reference.diagnostics import doctor_database
from pmgs_reference.errors import PMGSQueryError
from pmgs_reference.ingest.build import BuildError, build_database
from pmgs_reference.ingest.inventory import build_inventory, write_inventory
from pmgs_reference.mcp_server import run_stdio
from pmgs_reference.publication import (
    DEFAULT_MAX_JSON_CHUNK_BYTES,
    audit_public_release,
    export_public,
    validate_public_export,
)
from pmgs_reference.publication.validation import write_public_validation_report
from pmgs_reference.setup import (
    SetupOperationError,
    SetupResult,
    SetupUsageError,
    setup_reference,
)
from pmgs_reference.store import JSONDict, JSONValue, PMGSStore
from pmgs_reference.validation import validate_database, write_validation_report


class LocalizedArgumentParser(argparse.ArgumentParser):
    """Render parser help and errors in the selected UI language."""

    def __init__(
        self,
        *args: object,
        ui_language: str = "ja",
        json_mode: bool = False,
        **kwargs: object,
    ) -> None:
        self.ui_language = ui_language
        self.json_mode = json_mode
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    def format_help(self) -> str:
        text = super().format_help()
        if self.ui_language == "en":
            return text
        for original, translated in (
            ("usage:", "使い方:"),
            ("positional arguments:", "位置引数:"),
            ("options:", "オプション:"),
            ("show this help message and exit", "このヘルプを表示して終了"),
        ):
            text = text.replace(original, translated)
        return text

    def format_usage(self) -> str:
        text = super().format_usage()
        return text if self.ui_language == "en" else text.replace("usage:", "使い方:", 1)

    def error(self, message: str) -> Never:
        if self.json_mode:
            command = self.prog.split(maxsplit=1)[1] if " " in self.prog else None
            _json_output(
                {
                    "schema_version": "1.0",
                    "status": "failed",
                    "command": command,
                    "error": {"code": "ARGUMENT_ERROR", "message": message},
                }
            )
            self.exit(2)
        self.print_usage(sys.stderr)
        prefix = "error" if self.ui_language == "en" else "エラー"
        self.exit(2, f"{self.prog}: {prefix}: {message}\n")


class UILanguageError(ValueError):
    """Raised when the global UI-language option is malformed."""


_ALWAYS_JSON_COMMANDS = frozenset(
    {
        "inventory",
        "build",
        "validate",
        "agent-kit",
        "install-agent-skill",
        "export-public",
        "validate-public",
        "audit-public",
    }
)


def _extract_ui_language(argv: Sequence[str]) -> tuple[str, list[str], bool]:
    language = "ja"
    explicit = False
    cleaned: list[str] = []
    index = 0
    items = list(argv)
    while index < len(items):
        token = items[index]
        if token == "--ui-language":
            if explicit:
                raise UILanguageError("--ui-language may be specified only once")
            if index + 1 >= len(items):
                raise UILanguageError("--ui-language requires ja or en")
            language = items[index + 1]
            explicit = True
            index += 2
            continue
        if token.startswith("--ui-language="):
            if explicit:
                raise UILanguageError("--ui-language may be specified only once")
            language = token.partition("=")[2]
            explicit = True
            index += 1
            continue
        cleaned.append(token)
        index += 1
    if language not in {"ja", "en"}:
        raise UILanguageError("--ui-language must be ja or en")
    return language, cleaned, explicit


def _command_hint(argv: Sequence[str]) -> str | None:
    return next((token for token in argv if not token.startswith("-")), None)


def _json_mode(argv: Sequence[str]) -> bool:
    return "--json" in argv or _command_hint(argv) in _ALWAYS_JSON_COMMANDS


def _message(ui_language: str, japanese: str, english: str) -> str:
    return english if ui_language == "en" else japanese


def _build_parser(ui_language: str = "ja", *, json_mode: bool = False) -> argparse.ArgumentParser:
    class SelectedArgumentParser(LocalizedArgumentParser):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(
                *args,
                ui_language=ui_language,
                json_mode=json_mode,
                **kwargs,
            )

    parser = SelectedArgumentParser(
        prog="pmgs",
        description=_message(
            ui_language,
            "PMGS Referenceの構築と読み取り専用照会",
            "Build and query PMGS Reference through read-only interfaces",
        ),
    )
    parser.add_argument(
        "--ui-language",
        choices=("ja", "en"),
        default=ui_language,
        help=_message(ui_language, "CLI表示の言語", "language for CLI help and human output"),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(
        dest="command", required=True, parser_class=SelectedArgumentParser
    )

    inventory = subparsers.add_parser(
        "inventory",
        help=_message(ui_language, "PMGS packageを棚卸しする", "inventory a PMGS package"),
    )
    inventory.add_argument("source_dir", type=Path)
    inventory.add_argument("--output", type=Path, required=True)
    inventory.add_argument("--summary", type=Path)

    build = subparsers.add_parser(
        "build",
        help=_message(
            ui_language, "PMGSの正本SQLiteを構築する", "build the canonical PMGS SQLite database"
        ),
    )
    build.add_argument("source_dir", type=Path)
    build.add_argument("--release", required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--report", type=Path)

    setup = subparsers.add_parser(
        "setup",
        help=_message(
            ui_language,
            "PMGSを安全に構築しCodexやClaude Codeへ接続する",
            "safely build PMGS and connect Codex or Claude Code",
        ),
    )
    setup.add_argument(
        "source",
        type=Path,
        help="展開済みPMGSディレクトリまたはその親ディレクトリ",
    )
    setup.add_argument("--release", help="PMGSの版。省略時はJPPMディレクトリ名から判定")
    setup.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_root(),
        help="SQLite、現行版pointer、検査reportの保存先",
    )
    setup.add_argument(
        "--client",
        choices=("auto", "none", "codex", "claude", "both"),
        default="auto",
        help="接続するAIクライアント。既定はインストール済みclientの自動検出",
    )
    registration = setup.add_mutually_exclusive_group()
    registration.add_argument(
        "--register", dest="register", action="store_true", help="確認せず選択clientへ登録"
    )
    registration.add_argument(
        "--no-register", dest="register", action="store_false", help="client設定を変更しない"
    )
    setup.set_defaults(register=None)
    setup.add_argument(
        "--non-interactive", action="store_true", help="対話確認を行わない。登録方針の明示が必要"
    )
    setup.add_argument(
        "--dry-run", action="store_true", help="入力を棚卸しして予定を表示し、変更は行わない"
    )
    setup.add_argument("--json", action="store_true", help="結果をJSONオブジェクト1件で出力")
    setup.add_argument("--language", choices=("ja", "en"), default="ja", help="進捗と案内の言語")

    validate = subparsers.add_parser(
        "validate",
        help=_message(ui_language, "PMGS SQLiteを検証する", "validate a PMGS SQLite database"),
    )
    validate.add_argument("database", type=Path)
    validate.add_argument("--report", type=Path)

    lookup = subparsers.add_parser(
        "lookup",
        help=_message(
            ui_language, "特許分類を完全一致で照会する", "look up an exact patent classification"
        ),
    )
    lookup.add_argument("scheme", choices=("fi", "fterm", "ipc"))
    lookup.add_argument("code")
    _add_query_options(lookup)
    lookup.add_argument("--edition")
    lookup.add_argument("--ipc-version", dest="version")
    lookup.add_argument("--relation-limit", type=int, default=50)
    lookup.add_argument("--relation-offset", type=int, default=0)
    lookup.add_argument("--json", action="store_true")

    search = subparsers.add_parser(
        "search", help=_message(ui_language, "PMGSを文字列検索する", "search PMGS text")
    )
    search.add_argument("query")
    _add_query_options(search)
    search.add_argument("--scheme", action="append", choices=("fi", "fterm", "ipc"))
    search.add_argument(
        "--content-type",
        action="append",
        choices=("classification", "document"),
        help="省略時は分類と文書をそれぞれ検索する",
    )
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--json", action="store_true")

    document = subparsers.add_parser(
        "document",
        help=_message(
            ui_language, "特許庁提供のPMGS文書を読む", "read a JPO-provided PMGS document"
        ),
    )
    document.add_argument("document_id")
    _add_database_options(document)
    document.add_argument("--page", type=int)
    document.add_argument("--json", action="store_true")

    mcp = subparsers.add_parser(
        "mcp",
        help=_message(
            ui_language,
            "読み取り専用stdio MCP serverを起動する",
            "run the read-only stdio MCP server",
        ),
    )
    _add_database_options(mcp)

    doctor = subparsers.add_parser(
        "doctor",
        help=_message(
            ui_language,
            "ローカルDBと実stdio MCP接続を診断する",
            "diagnose the local database and stdio MCP connection",
        ),
    )
    _add_database_options(doctor)
    doctor.add_argument("--python-executable", type=Path)
    doctor.add_argument("--json", action="store_true")

    agent_kit = subparsers.add_parser(
        "agent-kit",
        help=_message(
            ui_language,
            "Codex・Claude Code用のローカル接続fileを生成する",
            "generate local connection files for Codex and Claude Code",
        ),
    )
    _add_database_options(agent_kit, required=True)
    agent_kit.add_argument("--output", type=Path, required=True)
    agent_kit.add_argument("--python-executable", type=Path)
    agent_kit.add_argument("--client", choices=("codex", "claude", "both"), default="both")

    install_skill = subparsers.add_parser(
        "install-agent-skill",
        help=_message(
            ui_language,
            "共通PMGS参照skillをローカルへ導入する",
            "install the shared PMGS reference skill",
        ),
    )
    install_skill.add_argument("--client", choices=("codex", "claude", "both"), default="both")
    install_skill.add_argument("--home", type=Path)

    export = subparsers.add_parser(
        "export-public",
        help=_message(
            ui_language, "決定論的な公開候補を生成する", "generate a deterministic public candidate"
        ),
    )
    export.add_argument("--db", type=Path, required=True)
    export.add_argument("--policy", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--base-url", required=True)
    export.add_argument("--max-json-chunk-bytes", type=int, default=DEFAULT_MAX_JSON_CHUNK_BYTES)
    export.add_argument("--report", type=Path)

    validate_public = subparsers.add_parser(
        "validate-public",
        help=_message(
            ui_language,
            "生成した公開候補treeを検証する",
            "validate a generated public candidate tree",
        ),
    )
    validate_public.add_argument("public_root", type=Path)
    validate_public.add_argument("--report", type=Path)

    audit_public = subparsers.add_parser(
        "audit-public",
        help=_message(
            ui_language, "検証済み公開候補A/Bを監査する", "audit two validated public candidates"
        ),
    )
    audit_public.add_argument("--db", type=Path, required=True)
    audit_public.add_argument("--first-root", type=Path, required=True)
    audit_public.add_argument("--second-root", type=Path, required=True)
    audit_public.add_argument("--first-export-report", type=Path, required=True)
    audit_public.add_argument("--second-export-report", type=Path, required=True)
    audit_public.add_argument("--first-validation-report", type=Path, required=True)
    audit_public.add_argument("--second-validation-report", type=Path, required=True)
    audit_public.add_argument("--expected-database-sha256", required=True)
    audit_public.add_argument("--expected-source-manifest-sha256", required=True)
    audit_public.add_argument("--report", type=Path)
    return parser


def _add_query_options(parser: argparse.ArgumentParser) -> None:
    _add_database_options(parser)
    parser.add_argument("--release", default="current")
    parser.add_argument("--language", choices=("ja", "en"), default="ja")


def _add_database_options(parser: argparse.ArgumentParser, *, required: bool = False) -> None:
    database = parser.add_mutually_exclusive_group(required=required)
    database.add_argument("--db", type=Path)
    database.add_argument("--data-dir", type=Path)


def _run_inventory(args: argparse.Namespace) -> int:
    manifest_path: Path = args.output
    summary_path: Path = args.summary or manifest_path.with_name("inventory-summary.json")
    inventory = build_inventory(args.source_dir)
    write_inventory(inventory, manifest_path, summary_path)
    print(json.dumps(inventory.summary(), ensure_ascii=True, sort_keys=True))
    return 1 if any(entry.status == "failed" for entry in inventory.entries) else 0


def _run_build(args: argparse.Namespace) -> int:
    result = build_database(
        args.source_dir,
        release_id=args.release,
        output_path=args.output,
        report_path=args.report,
    )
    print(json.dumps(result.as_dict(), ensure_ascii=True, sort_keys=True))
    return 0


_SETUP_PROGRESS = {
    "ja": {
        "preflight": "入力と保存先を確認しています。",
        "inventory": "PMGS原資料を棚卸ししています。",
        "reuse": "既存の検証済みDBを確認しています。",
        "build": "SQLiteを構築しています。",
        "build_database": "PMGSレコードをSQLiteへ取り込んでいます。",
        "source_check": "構築中に原資料が変わっていないか確認しています。",
        "validate": "SQLiteを検証しています。",
        "doctor": "stdio MCPの実接続を診断しています。",
        "activate": "検証済みDBをcurrentへ切り替えています。",
        "clients": "AIクライアントの接続状態を反映しています。",
        "complete": "setupが完了しました。",
    },
    "en": {
        "preflight": "Checking the source and data directory.",
        "inventory": "Inventorying the PMGS source package.",
        "reuse": "Checking for a verified existing database.",
        "build": "Building SQLite.",
        "build_database": "Importing PMGS records into SQLite.",
        "source_check": "Checking that the source did not change during setup.",
        "validate": "Validating SQLite.",
        "doctor": "Running a real stdio MCP diagnostic.",
        "activate": "Activating the verified database.",
        "clients": "Reconciling AI client connections.",
        "complete": "Setup completed.",
    },
}


def _prompt_registration(client: str, executable: Path, language: str) -> bool:
    display_executable = "".join(
        character if character.isprintable() else f"\\u{ord(character):04x}"
        for character in str(executable)
    )
    if language == "en":
        prompt = f"Register PMGS Reference with {client} (executable: {display_executable})? [Y/n] "
    else:
        prompt = (
            f"{client}にPMGS Referenceを登録しますか? (実行ファイル: {display_executable}) [Y/n] "
        )
    print(prompt, end="", file=sys.stderr, flush=True)
    answer = sys.stdin.readline().strip().lower()
    return answer not in {"n", "no"}


def _setup_human_output(result: SetupResult, language: str) -> None:
    planned_build = result.storage.get("planned_build") is True
    required = result.storage.get("required_free_bytes")
    free = result.storage.get("free_bytes")
    retained_count = result.storage.get("retained_database_count")
    retained_bytes = result.storage.get("retained_database_bytes")
    if language == "en":
        print(f"PMGS setup: {result.status}")
        print(f"Release: {result.release_id}")
        if result.database is not None:
            print(f"Database: {result.database}")
        if planned_build:
            print(f"Storage required/free: {required}/{free} bytes")
        if isinstance(retained_count, int) and retained_count > 0:
            print(
                f"Warning: {retained_count} retained database(s) use {retained_bytes} bytes.",
                file=sys.stderr,
            )
        if result.restart_required:
            print("Restart or reconnect Codex/Claude Code before using the updated server.")
    else:
        print(f"PMGS setup: {result.status}")
        print(f"リリース: {result.release_id}")
        if result.database is not None:
            print(f"データベース: {result.database}")
        if planned_build:
            print(f"必要/空き容量: {required}/{free} bytes")
        if isinstance(retained_count, int) and retained_count > 0:
            print(
                f"警告: 保持中のデータベース{retained_count}件が"
                f"{retained_bytes} bytesを使用しています。",
                file=sys.stderr,
            )
        if result.restart_required:
            print("更新した接続を使う前にCodexまたはClaude Codeを再起動してください。")
    for error in result.errors:
        print(f"error: {error}", file=sys.stderr)
    for client in result.clients:
        status = client.get("status")
        client_error = client.get("error")
        if status not in {"not_detected", "conflict", "failed"}:
            continue
        name = client.get("client", "unknown")
        detail = f" - {client_error}" if isinstance(client_error, str) and client_error else ""
        if language == "en":
            print(f"client {name}: {status}{detail}", file=sys.stderr)
        else:
            print(f"クライアント {name}: {status}{detail}", file=sys.stderr)


def _run_setup(args: argparse.Namespace) -> int:
    ui_language = args.ui_language if args.ui_language_explicit else args.language
    non_interactive = bool(args.non_interactive or args.json)
    if non_interactive and args.register is None:
        raise SetupUsageError(
            "--non-interactive and --json require either --register or --no-register"
        )
    targets = detect_client_targets(cast(ClientSelection, args.client))
    approved: list[AgentClient] = []
    if args.register is True:
        approved = [target.client for target in targets]
    elif args.register is None:
        if not sys.stdin.isatty():
            raise SetupUsageError("non-TTY setup requires --register or --no-register")
        approved = [
            target.client
            for target in targets
            if target.executable is not None
            and _prompt_registration(target.client, target.executable, str(ui_language))
        ]

    messages = _SETUP_PROGRESS[str(ui_language)]

    def progress(stage: str) -> None:
        message = messages.get(stage)
        if message is not None:
            print(message, file=sys.stderr, flush=True)

    result = setup_reference(
        args.source,
        release_id=args.release,
        data_dir=args.data_dir,
        client_targets=targets,
        approved_clients=approved,
        dry_run=bool(args.dry_run),
        progress=progress,
    )
    if args.json:
        _json_output(result.as_dict())
    else:
        _setup_human_output(result, str(ui_language))
    return 0 if result.status in {"ready", "already_ready", "dry_run"} else 1


def _run_validate(args: argparse.Namespace) -> int:
    result = validate_database(args.database)
    if args.report is not None:
        write_validation_report(result, args.report)
    print(json.dumps(result.as_dict(), ensure_ascii=True, sort_keys=True))
    return 0 if result.valid else 1


def _json_output(payload: JSONDict) -> None:
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True))


def _list_items(payload: JSONDict, key: str) -> list[JSONValue]:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _run_lookup(args: argparse.Namespace) -> int:
    store = PMGSStore.open(args.db, data_dir=args.data_dir)
    payload = store.lookup(
        args.scheme,
        args.code,
        args.release,
        args.edition,
        args.language,
        version=args.version,
        relation_limit=args.relation_limit,
        relation_offset=args.relation_offset,
    )
    if args.json:
        _json_output(payload)
    else:
        print(f"{payload['scheme']} {payload['code']} ({payload['match_status']})")
        for item in [*_list_items(payload, "labels"), *_list_items(payload, "texts")]:
            if isinstance(item, dict):
                print(item.get("text", ""))
    return 0 if payload["match_status"] in {"exact", "normalized_exact"} else 1


def _run_search(args: argparse.Namespace) -> int:
    store = PMGSStore.open(args.db, data_dir=args.data_dir)
    payload = store.search_pmgs(
        args.query,
        args.scheme,
        args.content_type,
        args.release,
        args.language,
        args.limit,
    )
    if args.json:
        _json_output(payload)
    else:
        groups = payload.get("results_by_type")
        if isinstance(groups, dict):
            for content_type in ("classification", "document"):
                group = groups.get(content_type)
                if not isinstance(group, dict):
                    continue
                for item in _list_items(group, "results"):
                    if isinstance(item, dict):
                        identifier = item.get("code") or item.get("document_id")
                        print(f"{identifier}\t{item.get('excerpt', '')}")
    return 0


def _run_document(args: argparse.Namespace) -> int:
    payload = PMGSStore.open(args.db, data_dir=args.data_dir).get_document(
        args.document_id, args.page
    )
    if args.json:
        _json_output(payload)
    else:
        print(payload["title"])
        for segment in _list_items(payload, "segments"):
            if isinstance(segment, dict):
                print(segment.get("text", ""))
    return 0


def _run_doctor(args: argparse.Namespace) -> int:
    result = doctor_database(
        args.db,
        data_dir=args.data_dir,
        python_executable=args.python_executable or sys.executable,
    )
    if args.json:
        _json_output(result.as_dict())
    else:
        if args.ui_language == "en":
            state = "success" if result.ok else "failure"
            print(f"PMGS diagnostic: {state}")
            print(f"Release: {result.release['release_id']}")
            print(f"Tools: {', '.join(result.tool_names)}")
            for error in result.errors:
                print(f"Error: {error}")
        else:
            state = "成功" if result.ok else "失敗"
            print(f"PMGS診断: {state}")
            print(f"リリース: {result.release['release_id']}")
            print(f"tool: {', '.join(result.tool_names)}")
            for error in result.errors:
                print(f"エラー: {error}")
    return 0 if result.ok else 1


def _run_agent_kit(args: argparse.Namespace) -> int:
    result = prepare_agent_kit(
        args.db,
        args.output,
        python_executable=args.python_executable or sys.executable,
        clients=resolve_clients(args.client),
        data_dir=args.data_dir,
    )
    _json_output(result.as_dict())
    return 0


def _run_install_agent_skill(args: argparse.Namespace) -> int:
    statuses = install_agent_skills(resolve_clients(args.client), home=args.home)
    _json_output(
        {
            "schema_version": "1.0",
            "skills": [cast(JSONValue, item) for item in statuses],
        }
    )
    return 0


def _run_export_public(args: argparse.Namespace) -> int:
    result = export_public(
        args.db,
        args.policy,
        args.output,
        base_url=args.base_url,
        max_json_chunk_bytes=args.max_json_chunk_bytes,
        report_path=args.report,
    )
    _json_output(result.as_dict())
    return 0


def _run_validate_public(args: argparse.Namespace) -> int:
    result = validate_public_export(args.public_root)
    if args.report is not None:
        write_public_validation_report(result, args.report)
    _json_output(result.as_dict())
    return 0 if result.valid else 1


def _run_audit_public(args: argparse.Namespace) -> int:
    result = audit_public_release(
        args.db,
        args.first_root,
        args.second_root,
        args.first_export_report,
        args.second_export_report,
        args.first_validation_report,
        args.second_validation_report,
        expected_database_sha256=args.expected_database_sha256,
        expected_source_manifest_sha256=args.expected_source_manifest_sha256,
        report_path=args.report,
    )
    _json_output(result.as_dict())
    return 0 if result.ready else 1


def _json_requested(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "json", False) or args.command in _ALWAYS_JSON_COMMANDS)


def _runtime_error_payload(command: str | None, code: str, message: str) -> JSONDict:
    return {
        "schema_version": "1.0",
        "status": "failed",
        "command": command,
        "error": {"code": code, "message": message},
    }


def _emit_runtime_error(
    args: argparse.Namespace, code: str, message: str, *, exit_code: int = 1
) -> int:
    _json_output(_runtime_error_payload(args.command, code, message))
    return exit_code


def _human_runtime_error(
    parser: argparse.ArgumentParser, ui_language: str, code: str, message: str
) -> Never:
    prefix = "error" if ui_language == "en" else "エラー"
    parser.exit(1, f"{parser.prog}: {prefix} [{code}]: {message}\n")


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    json_mode = _json_mode(raw_argv)
    try:
        ui_language, cleaned_argv, ui_language_explicit = _extract_ui_language(raw_argv)
    except UILanguageError as exc:
        parser = _build_parser("ja", json_mode=json_mode)
        parser.error(str(exc))
    parser = _build_parser(ui_language, json_mode=json_mode)
    args = parser.parse_args(cleaned_argv)
    args.ui_language = ui_language
    args.ui_language_explicit = ui_language_explicit
    try:
        if args.command == "inventory":
            return _run_inventory(args)
        if args.command == "build":
            return _run_build(args)
        if args.command == "setup":
            return _run_setup(args)
        if args.command == "validate":
            return _run_validate(args)
        if args.command == "lookup":
            return _run_lookup(args)
        if args.command == "search":
            return _run_search(args)
        if args.command == "document":
            return _run_document(args)
        if args.command == "mcp":
            run_stdio(args.db, data_dir=args.data_dir)
            return 0
        if args.command == "doctor":
            return _run_doctor(args)
        if args.command == "agent-kit":
            return _run_agent_kit(args)
        if args.command == "install-agent-skill":
            return _run_install_agent_skill(args)
        if args.command == "export-public":
            return _run_export_public(args)
        if args.command == "validate-public":
            return _run_validate_public(args)
        if args.command == "audit-public":
            return _run_audit_public(args)
    except SetupUsageError as exc:
        if _json_requested(args):
            return _emit_runtime_error(args, "SETUP_USAGE", str(exc), exit_code=2)
        parser.error(str(exc))
    except SetupOperationError as exc:
        if _json_requested(args):
            return _emit_runtime_error(args, "SETUP_FAILED", "PMGS setup failed")
        _human_runtime_error(parser, ui_language, "SETUP_FAILED", str(exc))
    except CurrentPointerError as exc:
        if _json_requested(args):
            return _emit_runtime_error(
                args, "CURRENT_POINTER_INVALID", "PMGS current pointer is invalid"
            )
        _human_runtime_error(parser, ui_language, "CURRENT_POINTER_INVALID", str(exc))
    except PMGSQueryError as exc:
        if _json_requested(args):
            return _emit_runtime_error(args, exc.code, exc.message)
        _human_runtime_error(parser, ui_language, exc.code, exc.message)
    except FileNotFoundError as exc:
        if _json_requested(args):
            return _emit_runtime_error(
                args, "FILE_NOT_FOUND", "PMGS Reference database was not found"
            )
        _human_runtime_error(parser, ui_language, "FILE_NOT_FOUND", str(exc))
    except BuildError as exc:
        if _json_requested(args):
            return _emit_runtime_error(args, "BUILD_FAILED", "PMGS build failed")
        _human_runtime_error(parser, ui_language, "BUILD_FAILED", str(exc))
    except OSError as exc:
        if _json_requested(args):
            return _emit_runtime_error(
                args, "IO_ERROR", "PMGS operation failed due to an I/O error"
            )
        _human_runtime_error(parser, ui_language, "IO_ERROR", str(exc))
    except ValueError as exc:
        if _json_requested(args):
            return _emit_runtime_error(
                args, "INVALID_STATE", "PMGS operation rejected invalid state or input"
            )
        _human_runtime_error(parser, ui_language, "INVALID_STATE", str(exc))
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
