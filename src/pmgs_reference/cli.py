"""Command-line entry point for PMGS Reference."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from pmgs_reference.agent_kit import (
    install_agent_skills,
    prepare_agent_kit,
    resolve_clients,
)
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
from pmgs_reference.store import JSONDict, JSONValue, PMGSStore
from pmgs_reference.validation import validate_database, write_validation_report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pmgs", description="PMGS Referenceの構築と読み取り専用照会"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser("inventory", help="PMGS packageを棚卸しする")
    inventory.add_argument("source_dir", type=Path)
    inventory.add_argument("--output", type=Path, required=True)
    inventory.add_argument("--summary", type=Path)

    build = subparsers.add_parser("build", help="PMGSの正本SQLiteを構築する")
    build.add_argument("source_dir", type=Path)
    build.add_argument("--release", required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--report", type=Path)

    validate = subparsers.add_parser("validate", help="PMGS SQLiteを検証する")
    validate.add_argument("database", type=Path)
    validate.add_argument("--report", type=Path)

    lookup = subparsers.add_parser("lookup", help="特許分類を完全一致で照会する")
    lookup.add_argument("scheme", choices=("fi", "fterm", "ipc"))
    lookup.add_argument("code")
    _add_query_options(lookup)
    lookup.add_argument("--edition")
    lookup.add_argument("--json", action="store_true")

    search = subparsers.add_parser("search", help="PMGSを文字列検索する")
    search.add_argument("query")
    _add_query_options(search)
    search.add_argument("--scheme", action="append", choices=("fi", "fterm", "ipc"))
    search.add_argument(
        "--content-type", choices=("classification", "document"), default="classification"
    )
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--json", action="store_true")

    document = subparsers.add_parser("document", help="特許庁提供のPMGS文書を読む")
    document.add_argument("document_id")
    document.add_argument("--db", type=Path)
    document.add_argument("--page", type=int)
    document.add_argument("--json", action="store_true")

    mcp = subparsers.add_parser("mcp", help="読み取り専用stdio MCP serverを起動する")
    mcp.add_argument("--db", type=Path)

    doctor = subparsers.add_parser("doctor", help="ローカルDBと実stdio MCP接続を診断する")
    doctor.add_argument("--db", type=Path)
    doctor.add_argument("--python-executable", type=Path)
    doctor.add_argument("--json", action="store_true")

    agent_kit = subparsers.add_parser(
        "agent-kit", help="Codex・Claude Code用のローカル接続fileを生成する"
    )
    agent_kit.add_argument("--db", type=Path, required=True)
    agent_kit.add_argument("--output", type=Path, required=True)
    agent_kit.add_argument("--python-executable", type=Path)
    agent_kit.add_argument("--client", choices=("codex", "claude", "both"), default="both")

    install_skill = subparsers.add_parser(
        "install-agent-skill", help="共通PMGS参照skillをローカルへ導入する"
    )
    install_skill.add_argument("--client", choices=("codex", "claude", "both"), default="both")
    install_skill.add_argument("--home", type=Path)

    export = subparsers.add_parser("export-public", help="決定論的な公開候補を生成する")
    export.add_argument("--db", type=Path, required=True)
    export.add_argument("--policy", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--base-url", required=True)
    export.add_argument("--max-json-chunk-bytes", type=int, default=DEFAULT_MAX_JSON_CHUNK_BYTES)
    export.add_argument("--report", type=Path)

    validate_public = subparsers.add_parser(
        "validate-public", help="生成した公開候補treeを検証する"
    )
    validate_public.add_argument("public_root", type=Path)
    validate_public.add_argument("--report", type=Path)

    audit_public = subparsers.add_parser("audit-public", help="検証済み公開候補A/Bを監査する")
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
    parser.add_argument("--db", type=Path)
    parser.add_argument("--release", default="current")
    parser.add_argument("--language", choices=("ja", "en"), default="ja")


def _run_inventory(args: argparse.Namespace) -> int:
    manifest_path: Path = args.output
    summary_path: Path = args.summary or manifest_path.with_name("inventory-summary.json")
    inventory = build_inventory(args.source_dir)
    write_inventory(inventory, manifest_path, summary_path)
    print(json.dumps(inventory.summary(), ensure_ascii=False, sort_keys=True))
    return 1 if any(entry.status == "failed" for entry in inventory.entries) else 0


def _run_build(args: argparse.Namespace) -> int:
    result = build_database(
        args.source_dir,
        release_id=args.release,
        output_path=args.output,
        report_path=args.report,
    )
    print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0


def _run_validate(args: argparse.Namespace) -> int:
    result = validate_database(args.database)
    if args.report is not None:
        write_validation_report(result, args.report)
    print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if result.valid else 1


def _json_output(payload: JSONDict) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _list_items(payload: JSONDict, key: str) -> list[JSONValue]:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _run_lookup(args: argparse.Namespace) -> int:
    store = PMGSStore.open(args.db)
    payload = store.lookup(args.scheme, args.code, args.release, args.edition, args.language)
    if args.json:
        _json_output(payload)
    else:
        print(f"{payload['scheme']} {payload['code']} ({payload['match_status']})")
        for item in [*_list_items(payload, "labels"), *_list_items(payload, "texts")]:
            if isinstance(item, dict):
                print(item.get("text", ""))
    return 1 if payload["match_status"] == "not_found" else 0


def _run_search(args: argparse.Namespace) -> int:
    store = PMGSStore.open(args.db)
    if args.content_type == "document":
        payload = store.search_documents(args.query, args.release, args.language, args.limit)
    else:
        payload = store.search(args.query, args.scheme, args.release, args.language, args.limit)
    if args.json:
        _json_output(payload)
    else:
        for item in _list_items(payload, "results"):
            if isinstance(item, dict):
                identifier = item.get("code") or item.get("document_id")
                print(f"{identifier}\t{item.get('excerpt', '')}")
    return 0


def _run_document(args: argparse.Namespace) -> int:
    payload = PMGSStore.open(args.db).get_document(args.document_id, args.page)
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
        python_executable=args.python_executable or sys.executable,
    )
    if args.json:
        _json_output(result.as_dict())
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "inventory":
            return _run_inventory(args)
        if args.command == "build":
            return _run_build(args)
        if args.command == "validate":
            return _run_validate(args)
        if args.command == "lookup":
            return _run_lookup(args)
        if args.command == "search":
            return _run_search(args)
        if args.command == "document":
            return _run_document(args)
        if args.command == "mcp":
            run_stdio(args.db)
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
    except PMGSQueryError as exc:
        if getattr(args, "json", False):
            _json_output({"error": {"code": exc.code, "message": exc.message}})
            return 1
        parser.exit(1, f"error [{exc.code}]: {exc.message}\n")
    except (BuildError, OSError, ValueError) as exc:
        parser.exit(1, f"error: {exc}\n")
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
