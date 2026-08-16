from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pandas as pd


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from advisor_data import DataGateError  # noqa: E402
from advisor_data.market_data import MarketBundle  # noqa: E402
from advisor_data_cli import build_parser, main  # noqa: E402
from tests.test_alpaca import bar, crypto_envelope  # noqa: E402
from tests.test_treasury import (  # noqa: E402
    inferred_treasury_envelope,
    treasury_envelope,
    treasury_observation,
)
from tests.test_wolfram import financial_envelope, observation  # noqa: E402
from tests.test_wolfram_fx import (  # noqa: E402
    fx_observation,
    wolfram_fx_envelope,
)


class FakeGateway:
    def __init__(self) -> None:
        self.search_queries: list[str] = []

    def search(self, query: str, instrument_type: str, max_results: int) -> list[dict]:
        self.search_queries.append(query)
        if query == "삼성전자":
            return []
        return [
            {
                "symbol": "005930.KS",
                "short_name": "Samsung Electronics Co., Ltd.",
                "long_name": "Samsung Electronics Co., Ltd.",
                "exchange": "KSC",
                "exchange_display": "Korea Stock Exchange",
                "quote_type": "EQUITY",
                "type_display": "Equity",
                "yahoo_score": 20001.0,
            }
        ]


class CliTests(unittest.TestCase):
    def test_wolfram_fx_parser_keeps_validation_and_completion_inputs_separate(self) -> None:
        parser = build_parser()
        validate = parser.parse_args(
            [
                "wolfram-fx-validate",
                "--input",
                "eur.json",
                "--start",
                "2026-01-01",
                "--end",
                "2026-02-01",
            ]
        )
        complete = parser.parse_args(
            [
                "complete-portfolio",
                "--workspace",
                "workspace.json",
                "--wolfram-input",
                "asset.json",
                "--wolfram-fx-input",
                "eur.json",
                "--wolfram-fx-input",
                "krw.json",
            ]
        )

        self.assertEqual(validate.command, "wolfram-fx-validate")
        self.assertEqual(complete.wolfram_input, ["asset.json"])
        self.assertEqual(complete.wolfram_fx_input, ["eur.json", "krw.json"])

    def test_complete_portfolio_help_is_provider_neutral(self) -> None:
        parser = build_parser()
        subparsers = next(
            action for action in parser._actions if action.dest == "command"
        )
        help_text = subparsers.choices["complete-portfolio"].description or ""
        summary = subparsers._choices_actions[
            list(subparsers.choices).index("complete-portfolio")
        ].help
        self.assertIn("validated fallback evidence", f"{summary} {help_text}")
        self.assertNotIn("Merge validated Alpaca evidence", f"{summary} {help_text}")

    def _write_json(self, directory: str, name: str, payload: dict) -> Path:
        path = Path(directory) / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_search_emits_normalized_json_candidates(self) -> None:
        gateway = FakeGateway()
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(
                [
                    "search",
                    "--query",
                    "삼성전자",
                    "--query-variant",
                    "Samsung Electronics",
                    "--instrument-type",
                    "stock",
                ],
                gateway=gateway,
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["candidates"][0]["symbol"], "005930.KS")
        self.assertEqual(payload["candidates"][0]["matched_queries"], ["Samsung Electronics"])
        self.assertEqual(payload["queries_attempted"], ["삼성전자", "Samsung Electronics"])
        self.assertEqual(gateway.search_queries, ["삼성전자", "Samsung Electronics"])

    def test_search_deduplicates_symbol_across_query_variants(self) -> None:
        gateway = FakeGateway()
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(
                [
                    "search",
                    "--query",
                    "Samsung Electronics",
                    "--query-variant",
                    "005930",
                ],
                gateway=gateway,
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(len(payload["candidates"]), 1)
        self.assertEqual(
            payload["candidates"][0]["matched_queries"],
            ["Samsung Electronics", "005930"],
        )

    def test_single_asset_portfolio_stops_before_network_access(self) -> None:
        def forbidden_loader(**_: object) -> MarketBundle:
            raise AssertionError("network loader should not run")

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = main(
                ["portfolio", "--symbols", "AAPL", "--start", "2021-01-01"],
                gateway=FakeGateway(),
                market_loader=forbidden_loader,
            )

        payload = json.loads(stderr.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["code"], "insufficient_assets")

    def test_portfolio_emits_receipt_and_candidates(self) -> None:
        index = pd.to_datetime(["2026-01-02", "2026-01-09", "2026-01-16", "2026-01-23"])
        prices = pd.DataFrame(
            {"AAPL": [100.0, 102.0, 101.0, 104.0], "005930.KS": [70000.0, 71000.0, 70500.0, 72000.0]},
            index=index,
        )
        krw_per_usd = pd.Series([1300.0, 1310.0, 1290.0, 1305.0], index=index, name="KRW=X")

        def loader(**_: object) -> MarketBundle:
            return MarketBundle(
                prices=prices,
                currencies={"AAPL": "USD", "005930.KS": "KRW"},
                fx_prices={"KRW": 1.0 / krw_per_usd},
                receipt={"source": "fixture"},
            )

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(
                [
                    "portfolio",
                    "--symbols",
                    "AAPL",
                    "005930.KS",
                    "--start",
                    "2026-01-01",
                    "--min-observations",
                    "3",
                    "--max-weight",
                    "1.0",
                ],
                gateway=FakeGateway(),
                market_loader=loader,
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["download_receipt"]["source"], "fixture")
        self.assertEqual(payload["return_receipt"]["observation_count"], 3)
        self.assertIn("minimum_variance", payload["portfolio_candidates"])

    def test_alpaca_validate_emits_normalized_receipt(self) -> None:
        envelope = crypto_envelope(
            bars=[
                bar("BTC/USD", "2026-01-05T00:00:00+00:00", 90000.0),
                bar("BTC/USD", "2026-01-12T00:00:00+00:00", 91000.0),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            input_path = self._write_json(tmp, "btc.json", envelope)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "alpaca-validate",
                        "--input",
                        str(input_path),
                        "--start",
                        "2026-01-01",
                        "--end",
                        "2026-02-01",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["validation"]["provider"], "alpaca")
        self.assertEqual(payload["validation"]["symbol"], "BTC-USD")
        self.assertEqual(payload["normalized"]["observation_count"], 2)

    def test_wolfram_validate_emits_normalized_receipt(self) -> None:
        envelope = financial_envelope(
            request_end="2026-01-13",
            observations=[
                observation("2026-01-05T00:00:00+00:00", 100.0),
                observation("2026-01-12T00:00:00+00:00", 101.0),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            input_path = self._write_json(tmp, "aapl-wolfram.json", envelope)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "wolfram-validate",
                        "--input",
                        str(input_path),
                        "--start",
                        "2026-01-01",
                    "--end",
                    "2026-01-13",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["validation"]["provider"], "wolfram")
        self.assertEqual(payload["normalized"]["observation_count"], 2)

    def test_wolfram_fx_validate_emits_pair_orientation_and_provenance(self) -> None:
        envelope = wolfram_fx_envelope(
            currency="EUR",
            base_currency="EUR",
            quote_currency="USD",
            symbol="EUR/USD",
            unit_numerator="USD",
            unit_denominator="EUR",
            observations=[
                fx_observation("2026-01-05", 1.15),
                fx_observation("2026-01-30", 1.16),
            ],
            start="2026-01-01",
            end="2026-02-01",
        )
        envelope["primary_failure"]["details"]["currency"] = "EUR"
        envelope["primary_failure"]["message"] = "Yahoo EUR FX failed."
        with tempfile.TemporaryDirectory() as tmp:
            input_path = self._write_json(tmp, "eur-wolfram-fx.json", envelope)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "wolfram-fx-validate",
                        "--input",
                        str(input_path),
                        "--start",
                        "2026-01-01",
                        "--end",
                        "2026-02-01",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["validation"]["requested_pair"], "EUR/USD")
        self.assertFalse(payload["validation"]["inversion_applied"])
        self.assertEqual(payload["validation"]["source_annotation_status"], "unavailable")
        self.assertEqual(payload["normalized"]["currency"], "EUR")
        self.assertEqual(payload["normalized"]["observation_count"], 2)

    def test_treasury_validate_emits_qualifiers_and_range(self) -> None:
        envelope = treasury_envelope(
            observations=[
                treasury_observation("2026-08-12T00:00:00+00:00", 4.55),
                treasury_observation("2026-08-13T00:00:00+00:00", 4.63),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            input_path = self._write_json(tmp, "us10y-wolfram.json", envelope)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["treasury-validate", "--input", str(input_path)])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["validation"]["qualifiers"]["maturity_duration"], "10Year")
        self.assertEqual(payload["normalized"]["observation_count"], 2)

    def test_treasury_validate_discloses_lower_confidence_tier(self) -> None:
        envelope = inferred_treasury_envelope(
            evidence_kind="us_treasury_current",
            observations=[treasury_observation("2026-08-13", 4.63)],
        )
        with tempfile.TemporaryDirectory() as tmp:
            input_path = self._write_json(tmp, "us10y-labeled.json", envelope)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["treasury-validate", "--input", str(input_path)])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["validation"]["evidence_tier"], "provider_labeled_inferred")
        self.assertEqual(payload["validation"]["evidence_confidence"], "lower")
        self.assertEqual(payload["validation"]["exact_qualifier_status"], "unavailable")

    def test_prepare_and_complete_portfolio_merge_alpaca_history(self) -> None:
        index = pd.to_datetime(
            [
                "2026-01-05T00:00:00+00:00",
                "2026-01-12T00:00:00+00:00",
                "2026-01-19T00:00:00+00:00",
                "2026-01-26T00:00:00+00:00",
            ]
        )

        def loader(*, symbols: list[str], **_: object) -> MarketBundle:
            if symbols == ["AAPL"]:
                return MarketBundle(
                    prices=pd.DataFrame(
                        {"AAPL": [100.0, 102.0, 101.0, 104.0]},
                        index=index,
                    ),
                    currencies={"AAPL": "USD"},
                    fx_prices={},
                    receipt={"source": "Yahoo fixture"},
                )
            raise DataGateError(
                "price_history_unavailable",
                "Yahoo returned no usable crypto history.",
            )

        envelope = crypto_envelope(
            bars=[
                bar("BTC/USD", "2026-01-05T00:00:00+00:00", 90000.0),
                bar("BTC/USD", "2026-01-12T00:00:00+00:00", 91000.0),
                bar("BTC/USD", "2026-01-19T00:00:00+00:00", 89000.0),
                bar("BTC/USD", "2026-01-26T00:00:00+00:00", 93000.0),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            workspace_path = Path(tmp) / "workspace.json"
            alpaca_path = self._write_json(tmp, "btc.json", envelope)
            prepare_stdout = io.StringIO()
            with redirect_stdout(prepare_stdout):
                prepare_code = main(
                    [
                        "prepare-portfolio",
                        "--symbols",
                        "AAPL",
                        "BTC-USD",
                        "--start",
                        "2026-01-01",
                        "--end",
                        "2026-02-01",
                        "--base-currency",
                        "USD",
                        "--workspace",
                        str(workspace_path),
                    ],
                    market_loader=loader,
                )
            complete_stdout = io.StringIO()
            with redirect_stdout(complete_stdout):
                complete_code = main(
                    [
                        "complete-portfolio",
                        "--workspace",
                        str(workspace_path),
                        "--alpaca-input",
                        str(alpaca_path),
                        "--frequency",
                        "weekly",
                        "--min-observations",
                        "3",
                        "--max-weight",
                        "1.0",
                    ]
                )

        prepare_payload = json.loads(prepare_stdout.getvalue())
        complete_payload = json.loads(complete_stdout.getvalue())
        self.assertEqual(prepare_code, 0)
        self.assertEqual(
            prepare_payload["fallback_required_symbols"],
            ["BTC-USD"],
        )
        self.assertEqual(complete_code, 0)
        self.assertEqual(
            complete_payload["download_receipt"]["providers"],
            {"AAPL": "yahoo", "BTC-USD": "alpaca"},
        )
        self.assertEqual(complete_payload["return_receipt"]["observation_count"], 3)
        self.assertIn("minimum_variance", complete_payload["portfolio_candidates"])

    def test_prepare_and_complete_portfolio_merge_wolfram_history(self) -> None:
        index = pd.to_datetime(
            [
                "2026-01-05T00:00:00+00:00",
                "2026-01-12T00:00:00+00:00",
                "2026-01-19T00:00:00+00:00",
                "2026-01-26T00:00:00+00:00",
            ]
        )

        def loader(*, symbols: list[str], **_: object) -> MarketBundle:
            if symbols == ["AAPL"]:
                return MarketBundle(
                    prices=pd.DataFrame(
                        {"AAPL": [100.0, 102.0, 101.0, 104.0]},
                        index=index,
                    ),
                    currencies={"AAPL": "USD"},
                    fx_prices={},
                    receipt={"source": "Yahoo fixture"},
                )
            raise DataGateError(
                "price_history_unavailable",
                "Yahoo returned no usable MSFT price history.",
            )

        envelope = financial_envelope(
            symbol="MSFT",
            provider_entity="NASDAQ:MSFT",
            observations=[
                observation("2026-01-05T00:00:00+00:00", 200.0),
                observation("2026-01-12T00:00:00+00:00", 202.0),
                observation("2026-01-19T00:00:00+00:00", 201.0),
                observation("2026-01-26T00:00:00+00:00", 204.0),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            workspace_path = Path(tmp) / "workspace.json"
            wolfram_path = self._write_json(tmp, "msft-wolfram.json", envelope)
            prepare_stdout = io.StringIO()
            with redirect_stdout(prepare_stdout):
                prepare_code = main(
                    [
                        "prepare-portfolio",
                        "--symbols",
                        "AAPL",
                        "MSFT",
                        "--start",
                        "2026-01-01",
                        "--end",
                        "2026-02-01",
                        "--base-currency",
                        "USD",
                        "--workspace",
                        str(workspace_path),
                    ],
                    market_loader=loader,
                )
            complete_stdout = io.StringIO()
            with redirect_stdout(complete_stdout):
                complete_code = main(
                    [
                        "complete-portfolio",
                        "--workspace",
                        str(workspace_path),
                        "--wolfram-input",
                        str(wolfram_path),
                        "--frequency",
                        "weekly",
                        "--min-observations",
                        "3",
                        "--max-weight",
                        "1.0",
                    ]
                )

        prepare_payload = json.loads(prepare_stdout.getvalue())
        complete_payload = json.loads(complete_stdout.getvalue())
        self.assertEqual(prepare_code, 0)
        self.assertEqual(prepare_payload["fallback_required_symbols"], ["MSFT"])
        self.assertEqual(complete_code, 0)
        self.assertEqual(
            complete_payload["download_receipt"]["providers"],
            {"AAPL": "yahoo", "MSFT": "wolfram"},
        )
        self.assertEqual(complete_payload["return_receipt"]["observation_count"], 3)
        self.assertIn("minimum_variance", complete_payload["portfolio_candidates"])

    def test_complete_portfolio_recovers_failed_yahoo_fx_with_wolfram_input(self) -> None:
        dates = [
            "2026-01-05T00:00:00+00:00",
            "2026-01-12T00:00:00+00:00",
            "2026-01-19T00:00:00+00:00",
            "2026-01-26T00:00:00+00:00",
        ]
        fx_failure = {
            "code": "fx_history_unavailable",
            "message": "Yahoo EUR FX failed.",
            "details": {"stage": "fx_history", "currency": "EUR"},
        }
        workspace = {
            "schema_version": 1,
            "symbols": ["AAPL", "SAP.DE"],
            "start": "2026-01-01",
            "end": "2026-02-01",
            "base_currency": "USD",
            "assets": {
                "AAPL": {
                    "currency": "USD",
                    "prices": {
                        "name": "AAPL",
                        "observations": [
                            {"timestamp": date, "value": value}
                            for date, value in zip(dates, [100.0, 102.0, 101.0, 104.0], strict=True)
                        ],
                    },
                    "receipt": {"source": "Yahoo fixture"},
                },
                "SAP.DE": {
                    "currency": "EUR",
                    "prices": {
                        "name": "SAP.DE",
                        "observations": [
                            {"timestamp": date, "value": value}
                            for date, value in zip(dates, [200.0, 203.0, 202.0, 206.0], strict=True)
                        ],
                    },
                    "receipt": {"source": "Yahoo fixture"},
                },
            },
            "failures": {},
            "yahoo_currency_evidence": {
                "AAPL": {"currency": "USD"},
                "SAP.DE": {"currency": "EUR"},
            },
            "fx_prices": {},
            "fx_receipts": {},
            "fx_failures": {"EUR": fx_failure},
            "fallback_required_fx": ["EUR"],
            "retrieved_at": "2026-08-17T00:00:00+00:00",
        }
        fx_envelope = wolfram_fx_envelope(
            currency="EUR",
            base_currency="EUR",
            quote_currency="USD",
            symbol="EUR/USD",
            unit_numerator="USD",
            unit_denominator="EUR",
            observations=[
                fx_observation(date, value)
                for date, value in zip(dates, [1.15, 1.16, 1.14, 1.17], strict=True)
            ],
            start="2026-01-01",
            end="2026-02-01",
        )
        fx_envelope["primary_failure"] = {"provider": "yahoo", **fx_failure}

        with tempfile.TemporaryDirectory() as tmp:
            workspace_path = self._write_json(tmp, "workspace.json", workspace)
            fx_path = self._write_json(tmp, "eur-fx.json", fx_envelope)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "complete-portfolio",
                        "--workspace",
                        str(workspace_path),
                        "--wolfram-fx-input",
                        str(fx_path),
                        "--frequency",
                        "weekly",
                        "--min-observations",
                        "3",
                        "--max-weight",
                        "1.0",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["download_receipt"]["fx_providers"], {"EUR": "wolfram"})
        self.assertEqual(payload["return_receipt"]["observation_count"], 3)
        self.assertIn("minimum_variance", payload["portfolio_candidates"])

    def test_complete_portfolio_without_required_alpaca_input_emits_no_weights(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_path = Path(tmp) / "workspace.json"
            prepare_stdout = io.StringIO()
            with redirect_stdout(prepare_stdout):
                prepare_code = main(
                    [
                        "prepare-portfolio",
                        "--symbols",
                        "BTC-USD",
                        "ETH-USD",
                        "--start",
                        "2026-01-01",
                        "--base-currency",
                        "USD",
                        "--workspace",
                        str(workspace_path),
                    ],
                    market_loader=lambda **_: (_ for _ in ()).throw(
                        DataGateError(
                            "price_history_unavailable",
                            "Yahoo failed.",
                        )
                    ),
                )
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                complete_code = main(
                    ["complete-portfolio", "--workspace", str(workspace_path)]
                )

        payload = json.loads(stderr.getvalue())
        self.assertEqual(prepare_code, 0)
        self.assertEqual(complete_code, 2)
        self.assertEqual(payload["error"]["code"], "fallback_not_supported")
        self.assertNotIn("portfolio_candidates", payload)


if __name__ == "__main__":
    unittest.main()
