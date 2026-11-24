"""DeepSeek 客户端连通性与输出校验测试（阶段二验收脚本）。

用法（先在 backend/.env 中本地填写真实 Key，Key 不会被读取或打印）：
    .venv\\Scripts\\python.exe backend\\test_deepseek.py

输出仅包含：是否调用成功、模型名称、六字段 JSON、校验结果、Token 用量、错误类型。
绝不输出 API Key。
"""

import re
import sys

import deepseek_client as ds

TEST_QUESTION = "我要投诉并要求三倍赔偿。"
TEST_CONTEXT = "[来源：《售后SOP》]现有资料没有明确的赔偿标准。投诉、赔偿和金额争议需要转人工客服处理。AI不得直接承诺赔偿金额或处理结果。"
# 从测试资料中提取来源标签，用于校验 sources 是否来自提供的标签
CONTEXT_SOURCES = re.findall(r"\[来源：(.+?)\]", TEST_CONTEXT)


def validate(result: dict) -> tuple[bool, list[str]]:
    """校验六字段结构、依据标注与本题业务预期，返回 (是否全部通过, 失败项列表)。"""
    sources = result.get("sources")
    checks: list[tuple[bool, str]] = [
        (bool(result.get("category")), "category 存在"),
        (bool(str(result.get("answer", "")).strip()), "answer 非空"),
        (isinstance(sources, list), "sources 为数组"),
        (bool(sources) and all(isinstance(s, str) and s.strip() for s in sources),
         "sources 至少包含一个非空字符串（不得为空）"),
        (result.get("risk_level") in ("低", "中", "高"), "risk_level 为 低/中/高 之一"),
        (isinstance(result.get("handoff_required"), bool), "handoff_required 为布尔值"),
        (bool(str(result.get("handoff_reason", "")).strip()), "handoff_reason 存在"),
        (result.get("handoff_required") is True, "本问题预期 handoff_required=true（投诉赔偿必须转人工）"),
        ("三倍赔偿" not in str(result.get("answer", ""))
         or "不" in str(result.get("answer", ""))
         or "无法" in str(result.get("answer", ""))
         or "转人工" in str(result.get("answer", "")),
         "不允许直接承诺三倍赔偿（回复须体现转人工/不承诺）"),
        # 依据校验：资料含来源标签时，sources 必须来自提供的标签
        (bool(CONTEXT_SOURCES) and all(s in CONTEXT_SOURCES for s in sources or []),
         f"sources 必须来自资料提供的来源标签 {CONTEXT_SOURCES}（不得编造来源）"),
        (bool(CONTEXT_SOURCES) and CONTEXT_SOURCES[0] in (sources or []),
         f"本测试 sources 必须包含：{CONTEXT_SOURCES[0]}"),
    ]
    failed = [name for ok, name in checks if not ok]
    return not failed, failed


def main() -> int:
    model = ds.get_model()
    print(f"模型名称: {model}")
    try:
        result = ds.generate_reply(TEST_QUESTION, TEST_CONTEXT)
    except ds.DeepSeekConfigError as exc:
        print(f"调用成功: 否（错误类型: DeepSeekConfigError）\n说明: {exc}")
        return 1
    except ds.DeepSeekRequestError as exc:
        print(f"调用成功: 否（错误类型: DeepSeekRequestError）\n说明: {exc}")
        return 1
    except ds.DeepSeekEmptyResponseError as exc:
        print(f"调用成功: 否（错误类型: DeepSeekEmptyResponseError）\n说明: {exc}")
        return 1
    except ds.DeepSeekJSONError as exc:
        print(f"调用成功: 否（错误类型: DeepSeekJSONError）\n说明: {exc}")
        return 1
    except ds.DeepSeekFieldError as exc:
        print(f"调用成功: 否（错误类型: DeepSeekFieldError）\n说明: {exc}")
        return 1

    print("调用成功: 是")
    import json
    print("六字段JSON:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    ok, failed = validate(result)
    print(f"校验通过: {'是' if ok else '否'}")
    for name in failed:
        print(f"  ✗ 未通过项: {name}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
