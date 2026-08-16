#!/usr/bin/env python3
"""JSON CLI for evidence-first Yahoo and portfolio data workflows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable, Sequence

from advisor_data import DataGateError
from advisor_data.bootstrap import DependencyBootstrapError, ensure_runtime_dependencies


def _emit(payload: dict[str, Any], stream: Any) -> None:
    json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
    stream.write("\n")


def _read_json(path: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataGateError(
            "evidence_workspace_invalid",
            f"JSON evidence could not be read from {path}.",
            {"error_type": exc.__class__.__name__},
        ) from exc
    if not isinstance(payload, dict):
        raise DataGateError(
            "evidence_workspace_invalid",
            f"JSON evidence at {path} must contain an object.",
        )
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", help="Return Yahoo candidates without selecting one")
    search.add_argument("--query", required=True)
    search.add_argument(
        "--query-variant",
        action="append",
        default=[],
        help="LLM-generated official, local-language, romanized, or ticker-like query; repeatable",
    )
    search.add_argument("--instrument-type", choices=["all", "stock", "equity", "etf"], default="all")
    search.add_argument("--max-results", type=int, default=10)

    validate = subparsers.add_parser("validate", help="Validate a selected symbol against returned candidates")
    validate.add_argument("--symbol", required=True)
    validate.add_argument("--candidate-symbols", nargs="+", required=True)

    fundamentals = subparsers.add_parser("fundamentals", help="Return a missingness-preserving snapshot")
    fundamentals.add_argument("--symbol", required=True)

    news = subparsers.add_parser("news", help="Return Yahoo news candidates for later source verification")
    news.add_argument("--symbol", required=True)
    news.add_argument("--count", type=int, default=10)

    alpaca_validate = subparsers.add_parser(
        "alpaca-validate",
        help="Validate a structured Alpaca fallback envelope",
    )
    alpaca_validate.add_argument("--input", required=True)
    alpaca_validate.add_argument("--start", required=True)
    alpaca_validate.add_argument("--end")

    wolfram_validate = subparsers.add_parser(
        "wolfram-validate",
        help="Validate a structured Wolfram financial fallback envelope",
    )
    wolfram_validate.add_argument("--input", required=True)
    wolfram_validate.add_argument("--start", required=True)
    wolfram_validate.add_argument("--end")

    wolfram_fx_validate = subparsers.add_parser(
        "wolfram-fx-validate",
        help="Validate a structured official-plugin Wolfram FX fallback envelope",
    )
    wolfram_fx_validate.add_argument("--input", required=True)
    wolfram_fx_validate.add_argument("--start", required=True)
    wolfram_fx_validate.add_argument("--end")

    treasury_validate = subparsers.add_parser(
        "treasury-validate",
        help="Validate a structured Wolfram U.S. Treasury envelope",
    )
    treasury_validate.add_argument("--input", required=True)

    portfolio = subparsers.add_parser("portfolio", help="Build evidence-gated multi-market candidates")
    portfolio.add_argument("--symbols", nargs="+", required=True)
    portfolio.add_argument("--start", required=True)
    portfolio.add_argument("--end")
    portfolio.add_argument("--base-currency", default="KRW", help="ISO major currency such as KRW, USD, JPY, or EUR")
    portfolio.add_argument("--frequency", choices=["weekly", "daily"], default="weekly")
    portfolio.add_argument("--min-observations", type=int, default=104)
    portfolio.add_argument("--max-weight", type=float, default=0.7)

    prepare = subparsers.add_parser(
        "prepare-portfolio",
        help="Preserve Yahoo evidence per symbol and report fallback requirements",
    )
    prepare.add_argument("--symbols", nargs="+", required=True)
    prepare.add_argument("--start", required=True)
    prepare.add_argument("--end")
    prepare.add_argument("--base-currency", default="KRW")
    prepare.add_argument("--workspace", required=True)

    complete = subparsers.add_parser(
        "complete-portfolio",
        help="Merge validated fallback evidence and build portfolio candidates",
    )
    complete.add_argument("--workspace", required=True)
    complete.add_argument("--alpaca-input", action="append", default=[])
    complete.add_argument("--wolfram-input", action="append", default=[])
    complete.add_argument("--wolfram-fx-input", action="append", default=[])
    complete.add_argument("--frequency", choices=["weekly", "daily"], default="weekly")
    complete.add_argument("--min-observations", type=int, default=104)
    complete.add_argument("--max-weight", type=float, default=0.7)
    return parser


def main(
    argv: Sequence[str] | None = None,
    gateway: Any = None,
    market_loader: Callable[..., Any] | None = None,
    workspace_preparer: Callable[..., Any] | None = None,
    workspace_completer: Callable[..., Any] | None = None,
    alpaca_normalizer: Callable[..., Any] | None = None,
    wolfram_normalizer: Callable[..., Any] | None = None,
    wolfram_fx_normalizer: Callable[..., Any] | None = None,
    treasury_normalizer: Callable[..., Any] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    runtime_receipt: dict[str, Any] | None = None
    try:
        runtime_receipt = ensure_runtime_dependencies()
        from advisor_data.alpaca import normalize_alpaca_envelope
        from advisor_data.evidence_workspace import (
            complete_market_bundle,
            prepare_yahoo_workspace,
            read_workspace,
            workspace_summary,
            write_workspace,
        )
        from advisor_data.market_data import build_return_matrix, download_market_bundle
        from advisor_data.portfolio import build_portfolio_candidates
        from advisor_data.treasury import normalize_treasury_envelope
        from advisor_data.wolfram import normalize_wolfram_envelope
        from advisor_data.wolfram_fx import normalize_wolfram_fx_envelope
        from advisor_data.yahoo import YahooGateway

        yahoo = gateway or YahooGateway()
        active_market_loader = market_loader or download_market_bundle
        active_workspace_preparer = workspace_preparer or prepare_yahoo_workspace
        active_workspace_completer = workspace_completer or complete_market_bundle
        active_alpaca_normalizer = alpaca_normalizer or normalize_alpaca_envelope
        active_wolfram_normalizer = wolfram_normalizer or normalize_wolfram_envelope
        active_wolfram_fx_normalizer = (
            wolfram_fx_normalizer or normalize_wolfram_fx_envelope
        )
        active_treasury_normalizer = treasury_normalizer or normalize_treasury_envelope
        if args.command == "search":
            queries = list(dict.fromkeys([args.query, *args.query_variant]))
            candidate_by_symbol: dict[str, dict[str, Any]] = {}
            for query in queries:
                for candidate in yahoo.search(query, args.instrument_type, args.max_results):
                    symbol = str(candidate["symbol"])
                    if symbol not in candidate_by_symbol:
                        candidate_by_symbol[symbol] = {**candidate, "matched_queries": [query]}
                    elif query not in candidate_by_symbol[symbol]["matched_queries"]:
                        candidate_by_symbol[symbol]["matched_queries"].append(query)
            _emit(
                {
                    "status": "ok",
                    "runtime_receipt": runtime_receipt,
                    "query": args.query,
                    "queries_attempted": queries,
                    "candidates": list(candidate_by_symbol.values()),
                },
                sys.stdout,
            )
            return 0
        if args.command == "validate":
            candidates = [{"symbol": symbol} for symbol in args.candidate_symbols]
            receipt = yahoo.validate_candidate(args.symbol, candidates)
            _emit(
                {"status": "ok", "runtime_receipt": runtime_receipt, "validation": receipt},
                sys.stdout,
            )
            return 0
        if args.command == "fundamentals":
            _emit(
                {
                    "status": "ok",
                    "runtime_receipt": runtime_receipt,
                    "fundamentals": yahoo.fundamentals(args.symbol),
                },
                sys.stdout,
            )
            return 0
        if args.command == "news":
            _emit(
                {
                    "status": "ok",
                    "runtime_receipt": runtime_receipt,
                    "symbol": args.symbol,
                    "news_candidates": yahoo.news(args.symbol, args.count),
                },
                sys.stdout,
            )
            return 0
        if args.command == "alpaca-validate":
            history = active_alpaca_normalizer(
                _read_json(args.input),
                start=args.start,
                end=args.end,
            )
            _emit(
                {
                    "status": "ok",
                    "runtime_receipt": runtime_receipt,
                    "validation": history.receipt,
                    "normalized": {
                        "observation_count": len(history.series),
                        "first_at": history.series.index.min().isoformat(),
                        "last_at": history.series.index.max().isoformat(),
                    },
                },
                sys.stdout,
            )
            return 0
        if args.command == "wolfram-validate":
            history = active_wolfram_normalizer(
                _read_json(args.input),
                start=args.start,
                end=args.end,
            )
            _emit(
                {
                    "status": "ok",
                    "runtime_receipt": runtime_receipt,
                    "validation": history.receipt,
                    "normalized": {
                        "observation_count": len(history.series),
                        "first_at": history.series.index.min().isoformat(),
                        "last_at": history.series.index.max().isoformat(),
                    },
                },
                sys.stdout,
            )
            return 0
        if args.command == "wolfram-fx-validate":
            history = active_wolfram_fx_normalizer(
                _read_json(args.input),
                start=args.start,
                end=args.end,
            )
            _emit(
                {
                    "status": "ok",
                    "runtime_receipt": runtime_receipt,
                    "validation": history.receipt,
                    "normalized": {
                        "currency": history.currency,
                        "observation_count": len(history.series),
                        "first_at": history.series.index.min().isoformat(),
                        "last_at": history.series.index.max().isoformat(),
                    },
                },
                sys.stdout,
            )
            return 0
        if args.command == "treasury-validate":
            treasury = active_treasury_normalizer(_read_json(args.input))
            _emit(
                {
                    "status": "ok",
                    "runtime_receipt": runtime_receipt,
                    "validation": treasury.receipt,
                    "normalized": {
                        "observation_count": len(treasury.series),
                        "first_at": treasury.series.index.min().isoformat(),
                        "last_at": treasury.series.index.max().isoformat(),
                        "maturity_years": treasury.maturity_years,
                    },
                },
                sys.stdout,
            )
            return 0
        if args.command == "portfolio":
            if len(args.symbols) < 2:
                raise DataGateError("insufficient_assets", "MPT requires at least two symbols.")
            bundle = active_market_loader(
                symbols=args.symbols,
                start=args.start,
                end=args.end,
                base_currency=args.base_currency,
            )
            matrix = build_return_matrix(
                bundle.prices,
                bundle.currencies,
                base_currency=args.base_currency,
                fx_prices=bundle.fx_prices,
                frequency=args.frequency,
                min_observations=args.min_observations,
            )
            candidates = build_portfolio_candidates(
                matrix.returns,
                max_weight=args.max_weight,
                periods_per_year=matrix.receipt["periods_per_year"],
            )
            _emit(
                {
                    "status": "ok",
                    "runtime_receipt": runtime_receipt,
                    "download_receipt": bundle.receipt,
                    "return_receipt": matrix.receipt,
                    "portfolio_candidates": candidates,
                },
                sys.stdout,
            )
            return 0
        if args.command == "prepare-portfolio":
            if len(args.symbols) < 2:
                raise DataGateError("insufficient_assets", "MPT requires at least two symbols.")
            workspace = active_workspace_preparer(
                symbols=args.symbols,
                start=args.start,
                end=args.end,
                base_currency=args.base_currency,
                market_loader=active_market_loader,
            )
            write_workspace(Path(args.workspace), workspace)
            _emit(
                {
                    "status": "ok",
                    "runtime_receipt": runtime_receipt,
                    "workspace": str(Path(args.workspace)),
                    **workspace_summary(workspace),
                },
                sys.stdout,
            )
            return 0
        if args.command == "complete-portfolio":
            workspace = read_workspace(Path(args.workspace))
            symbols = list(workspace.get("symbols", []))
            if len(symbols) < 2:
                raise DataGateError("insufficient_assets", "MPT requires at least two symbols.")
            envelopes = [
                *(_read_json(path) for path in args.alpaca_input),
                *(_read_json(path) for path in args.wolfram_input),
            ]
            fx_envelopes = [
                *(_read_json(path) for path in args.wolfram_fx_input),
            ]
            bundle = active_workspace_completer(
                workspace,
                envelopes,
                fx_envelopes=fx_envelopes,
                fx_normalizer=active_wolfram_fx_normalizer,
            )
            matrix = build_return_matrix(
                bundle.prices,
                bundle.currencies,
                base_currency=str(workspace.get("base_currency")),
                fx_prices=bundle.fx_prices,
                frequency=args.frequency,
                min_observations=args.min_observations,
            )
            candidates = build_portfolio_candidates(
                matrix.returns,
                max_weight=args.max_weight,
                periods_per_year=matrix.receipt["periods_per_year"],
            )
            _emit(
                {
                    "status": "ok",
                    "runtime_receipt": runtime_receipt,
                    "download_receipt": bundle.receipt,
                    "return_receipt": matrix.receipt,
                    "portfolio_candidates": candidates,
                },
                sys.stdout,
            )
            return 0
    except DependencyBootstrapError as exc:
        _emit(
            {
                "status": "error",
                "error": {"code": exc.code, "message": exc.message, "details": exc.details},
            },
            sys.stderr,
        )
        return 2
    except DataGateError as exc:
        _emit(
            {
                "status": "error",
                "runtime_receipt": runtime_receipt,
                "error": {"code": exc.code, "message": exc.message, "details": exc.details},
            },
            sys.stderr,
        )
        return 2
    except Exception as exc:
        _emit(
            {
                "status": "error",
                "runtime_receipt": runtime_receipt,
                "error": {
                    "code": "unexpected_error",
                    "message": str(exc),
                    "details": {"error_type": exc.__class__.__name__},
                },
            },
            sys.stderr,
        )
        return 3
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
