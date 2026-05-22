import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import openrouter_paid_ai_index as index  # noqa: E402


def flight_html(payload):
    chunk = '41:["$","$L57",null,{"rankingData":' + json.dumps(payload) + "}]"
    encoded = json.dumps(chunk)[1:-1]
    return f'<script>self.__next_f.push([1,"{encoded}"])</script>'


class OpenRouterPaidAiIndexTests(unittest.TestCase):
    def test_extract_ranking_data_from_next_flight_payload(self):
        rows = [
            {
                "date": "2026-05-12 00:00:00",
                "model_permaslug": "vendor/model-20260501",
                "variant": "standard",
                "variant_permaslug": "vendor/model-20260501",
                "total_prompt_tokens": 100,
                "total_completion_tokens": 50,
            }
        ]

        self.assertEqual(index.extract_ranking_data(flight_html(rows)), rows)

    def test_parse_server_action_ranking_data(self):
        rows = [
            {
                "date": "2026-05-17 00:00:00",
                "model_permaslug": "vendor/model-20260501",
                "variant": "standard",
                "variant_permaslug": "vendor/model-20260501",
                "total_prompt_tokens": 100,
                "total_completion_tokens": 50,
            }
        ]
        response = '0:{"a":"$@1","f":"","q":"","i":false}\n1:' + json.dumps(rows) + "\n"

        self.assertEqual(index.parse_server_action_ranking_data(response), rows)

    def test_ranking_type_from_url_defaults_to_week(self):
        self.assertEqual(index.ranking_type_from_url("https://openrouter.ai/rankings?view=month"), "month")
        self.assertEqual(index.ranking_type_from_url("https://openrouter.ai/rankings"), "week")
        self.assertEqual(index.ranking_type_from_url("https://openrouter.ai/rankings?view=invalid"), "week")

    def test_build_model_maps_matches_free_variant_by_variant_slug(self):
        models_json = {
            "data": [
                {
                    "id": "vendor/model",
                    "canonical_slug": "vendor/model-20260501",
                    "name": "Vendor Model",
                    "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                },
                {
                    "id": "vendor/model:free",
                    "canonical_slug": "vendor/model-20260501",
                    "name": "Vendor Model Free",
                    "pricing": {"prompt": "0", "completion": "0"},
                },
            ]
        }
        maps = index.build_model_maps(models_json)

        self.assertEqual(maps.by_variant_slug["vendor/model-20260501"]["id"], "vendor/model")
        self.assertEqual(maps.by_variant_slug["vendor/model-20260501:free"]["id"], "vendor/model:free")

    def test_snapshot_excludes_free_models_from_paid_revenue_proxy(self):
        ranking_data = [
            {
                "date": "2026-05-12 00:00:00",
                "model_permaslug": "vendor/paid-20260501",
                "variant": "standard",
                "variant_permaslug": "vendor/paid-20260501",
                "total_prompt_tokens": 1000,
                "total_completion_tokens": 500,
                "total_native_tokens_reasoning": 100,
                "total_native_tokens_cached": 200,
                "count": 2,
            },
            {
                "date": "2026-05-12 00:00:00",
                "model_permaslug": "vendor/free-20260501",
                "variant": "free",
                "variant_permaslug": "vendor/free-20260501:free",
                "total_prompt_tokens": 2000,
                "total_completion_tokens": 1000,
                "count": 3,
            },
        ]
        models_json = {
            "data": [
                {
                    "id": "vendor/paid",
                    "canonical_slug": "vendor/paid-20260501",
                    "name": "Vendor Paid",
                    "pricing": {
                        "prompt": "0.000001",
                        "completion": "0.000002",
                        "internal_reasoning": "0.000003",
                        "input_cache_read": "0.0000005",
                        "request": "0.01",
                    },
                },
                {
                    "id": "vendor/free:free",
                    "canonical_slug": "vendor/free-20260501",
                    "name": "Vendor Free",
                    "pricing": {"prompt": "0", "completion": "0"},
                },
            ]
        }

        snapshot = index.build_snapshot(ranking_data, models_json)

        self.assertEqual(snapshot["totals"]["paid_visible_tokens"], 1500)
        self.assertEqual(snapshot["totals"]["free_visible_tokens"], 3000)
        self.assertEqual(snapshot["totals"]["paid_model_variants"], 1)
        self.assertEqual(snapshot["totals"]["free_model_variants"], 1)
        self.assertEqual(Decimal(snapshot["totals"]["revenue_proxy_usd"]), Decimal("0.022400"))

    def test_constant_price_revenue_uses_base_snapshot_prices(self):
        ranking_data = [
            {
                "date": "2026-05-12 00:00:00",
                "model_permaslug": "vendor/paid-20260501",
                "variant": "standard",
                "variant_permaslug": "vendor/paid-20260501",
                "total_prompt_tokens": 1000,
                "total_completion_tokens": 500,
                "count": 2,
            }
        ]
        models_json = {
            "data": [
                {
                    "id": "vendor/paid",
                    "canonical_slug": "vendor/paid-20260501",
                    "name": "Vendor Paid",
                    "pricing": {
                        "prompt": "0.000001",
                        "completion": "0.000002",
                        "request": "0.01",
                    },
                }
            ]
        }
        base_snapshot = {
            "pricing_by_variant_slug": {
                "vendor/paid-20260501": {
                    "prompt": "0.000002",
                    "completion": "0.000004",
                    "request": "0.02",
                }
            }
        }

        snapshot = index.build_snapshot(ranking_data, models_json, base_snapshot=base_snapshot)

        self.assertEqual(Decimal(snapshot["totals"]["revenue_proxy_usd"]), Decimal("0.022000"))
        self.assertEqual(Decimal(snapshot["totals"]["constant_price_revenue_usd"]), Decimal("0.044000"))

    def test_free_variant_fallback_to_standard_model_does_not_use_standard_price(self):
        ranking_data = [
            {
                "date": "2026-05-12 00:00:00",
                "model_permaslug": "vendor/model-20260501",
                "variant": "free",
                "variant_permaslug": "vendor/model-20260501:free",
                "total_prompt_tokens": 1000,
                "total_completion_tokens": 500,
                "count": 2,
            }
        ]
        models_json = {
            "data": [
                {
                    "id": "vendor/model",
                    "canonical_slug": "vendor/model-20260501",
                    "name": "Vendor Model",
                    "pricing": {
                        "prompt": "0.000001",
                        "completion": "0.000002",
                        "request": "0.01",
                    },
                }
            ]
        }

        snapshot = index.build_snapshot(ranking_data, models_json)

        self.assertEqual(snapshot["totals"]["paid_visible_tokens"], 0)
        self.assertEqual(snapshot["totals"]["free_visible_tokens"], 1500)
        self.assertEqual(Decimal(snapshot["top_free_by_tokens"][0]["estimated_cost_usd"]), Decimal("0.000000"))

    def test_markdown_report_is_rendered_in_chinese(self):
        ranking_data = [
            {
                "date": "2026-05-12 00:00:00",
                "model_permaslug": "vendor/paid-20260501",
                "variant": "standard",
                "variant_permaslug": "vendor/paid-20260501",
                "total_prompt_tokens": 1000,
                "total_completion_tokens": 500,
                "count": 2,
            }
        ]
        models_json = {
            "data": [
                {
                    "id": "vendor/paid",
                    "canonical_slug": "vendor/paid-20260501",
                    "name": "Vendor Paid",
                    "pricing": {
                        "prompt": "0.000001",
                        "completion": "0.000002",
                        "request": "0.01",
                    },
                }
            ]
        }
        snapshot = index.build_snapshot(ranking_data, models_json)

        report = index.render_markdown_report(snapshot, top=1)

        self.assertIn("# OpenRouter 付费 AI 推理指数", report)
        self.assertIn("## 指标总览", report)
        self.assertIn("- 榜单日期：2026-05-12 00:00:00", report)
        self.assertIn("| # | 模型 | Token | 估算费用 | 文本 $/百万 Token |", report)
        self.assertIn("## 按估算费用排序的付费模型", report)
        self.assertIn("## 注意事项", report)
        self.assertIn("这是一组付费推理需求代理指标", report)
        self.assertNotIn("# OpenRouter Paid AI Inference Index", report)
        self.assertNotIn("## Indexes", report)
        self.assertNotIn("## Notes", report)
        self.assertNotIn("visible tokens", report)

    def test_markdown_report_formats_decimals_units_and_calculation_notes(self):
        ranking_data = [
            {
                "date": "2026-05-12 00:00:00",
                "model_permaslug": "vendor/large-20260501",
                "variant": "standard",
                "variant_permaslug": "vendor/large-20260501",
                "total_prompt_tokens": 1234567890123,
                "total_completion_tokens": 123456789012,
                "count": 2,
            }
        ]
        models_json = {
            "data": [
                {
                    "id": "vendor/large",
                    "canonical_slug": "vendor/large-20260501",
                    "name": "Vendor Large",
                    "pricing": {
                        "prompt": "0.000012345",
                        "completion": "0.00006789",
                    },
                }
            ]
        }
        snapshot = index.build_snapshot(ranking_data, models_json)

        report = index.render_markdown_report(snapshot, top=1)

        self.assertIn("- 收入代理估算：$23,622,222.01（约 2,362.22 万美元）", report)
        self.assertIn("万美元", report)
        self.assertIn("| 1 | Vendor Large | 1.36T | $23,622,222.01（约 2,362.22 万美元） | 17.39 |", report)
        self.assertIn("## 计算口径", report)
        self.assertIn("文本 $/百万 Token =", report)
        self.assertIn("(prompt_tokens × prompt_price + completion_tokens × completion_price)", report)
        self.assertNotRegex(report, r"\d+\.\d{3,}")

    def test_markdown_report_includes_research_brief_sections(self):
        ranking_data = [
            {
                "date": "2026-05-12 00:00:00",
                "model_permaslug": "vendor/paid-20260501",
                "variant": "standard",
                "variant_permaslug": "vendor/paid-20260501",
                "total_prompt_tokens": 8000,
                "total_completion_tokens": 2000,
                "count": 10,
            },
            {
                "date": "2026-05-12 00:00:00",
                "model_permaslug": "vendor/free-20260501",
                "variant": "free",
                "variant_permaslug": "vendor/free-20260501:free",
                "total_prompt_tokens": 1500,
                "total_completion_tokens": 500,
                "count": 20,
            },
        ]
        models_json = {
            "data": [
                {
                    "id": "vendor/paid",
                    "canonical_slug": "vendor/paid-20260501",
                    "name": "Vendor Paid",
                    "pricing": {
                        "prompt": "0.000004",
                        "completion": "0.000012",
                    },
                },
                {
                    "id": "vendor/free:free",
                    "canonical_slug": "vendor/free-20260501",
                    "name": "Vendor Free",
                    "pricing": {"prompt": "0", "completion": "0"},
                },
            ]
        }
        snapshot = index.build_snapshot(ranking_data, models_json)

        report = index.render_markdown_report(snapshot, top=1)

        self.assertIn("## 研究框架", report)
        self.assertIn("本报告衡量的是 OpenRouter 平台上的付费推理需求", report)
        self.assertIn("免费模型更适合作为实验热度和潜在转化信号", report)
        self.assertIn("固定价格收入估算用于剥离价格变化影响", report)
        self.assertIn("## 本周读法", report)
        self.assertIn("当前未提供上一期 `--compare-json`", report)
        self.assertIn("## 趋势判读规则", report)
        self.assertIn("加速：付费 Token、固定价格收入和高端付费 Token 占比同步上升", report)
        self.assertIn("停滞：付费 Token 持平", report)
        self.assertIn("倒退：付费 Token 和固定价格收入同步下降", report)


if __name__ == "__main__":
    unittest.main()
