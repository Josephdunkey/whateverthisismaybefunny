r"""One-click model switcher for BookCompiler, Hermes and Hindsight.

The three products have independent model configuration:

* BookCompiler judge -> project .env (BOOKCOMPILER_JUDGE_*)
* Hermes chat        -> D:\hermes agent\config.yaml (model block)
* Hindsight memory   -> D:\hindsight\.env (HINDSIGHT_API_LLM_*)

This tool never reads or prints API keys. It only writes provider, model and
base_url, and it backs up every config file before changing it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .config import project_root
from .model_settings import (
    hermes_status,
    reader_model_status,
    set_reader_default,
    hindsight_model_status,
    judge_model_status,
    set_hermes_default,
    set_hindsight_default,
    set_judge_default,
)

DEFAULT_LOCAL_MODEL = "qwen2.5:7b-instruct-q4_K_M"
PRESET_PATH = project_root() / "model-presets.json"
KEY_NAMES = ("BOOKCOMPILER_JUDGE_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY", "MIMO_API_KEY", "XIAOMI_API_KEY")


def _default_presets() -> dict[str, Any]:
    # Fixed DeepSeek route. Reading the live Hermes config here would let a
    # MiMo switch silently overwrite the "cloud" preset.
    cloud_hermes = {
        "model": "deepseek-v4-pro",
        "provider": "custom",
        "base_url": "https://api.deepseek.com/v1",
    }
    local_hermes = {
        "model": DEFAULT_LOCAL_MODEL,
        "provider": "ollama",
        "base_url": "http://127.0.0.1:11434/v1",
    }
    local_judge = {
        "provider": "ollama",
        "model": DEFAULT_LOCAL_MODEL,
        "base_url": "http://127.0.0.1:11434",
    }
    local_hindsight = {
        "provider": "ollama",
        "model": DEFAULT_LOCAL_MODEL,
        "base_url": "http://127.0.0.1:11434/v1",
    }
    cloud_judge = {
        "provider": "openai-compatible",
        "model": cloud_hermes["model"],
        "base_url": cloud_hermes["base_url"],
    }
    mimo_model = os.environ.get("MIMO_MODEL", "").strip() or "mimo-v2.6-flash"
    mimo_base = os.environ.get("MIMO_BASE_URL", "").strip() or "https://token-plan-cn.xiaomimimo.com/v1"
    mimo = {
        "hermes": {"model": mimo_model, "provider": "xiaomi", "base_url": mimo_base},
        "bookcompiler": {"provider": "openai-compatible", "model": mimo_model, "base_url": mimo_base},
        "hindsight": local_hindsight,
    }
    mimo_reader = {
        "provider": "openai-compatible",
        "model": mimo_model,
        "base_url": mimo_base,
    }
    return {
        "cloud": {
            "hermes": cloud_hermes,
            "bookcompiler": cloud_judge,
            # Reading is the expensive step: even the "cloud" preset keeps
            # the reader on MiMo and never silently routes books to DeepSeek.
            "reader": mimo_reader,
            "hindsight": local_hindsight,
        },
        "mimo": {**mimo, "reader": mimo_reader},
        "local": {"hermes": local_hermes, "bookcompiler": local_judge, "reader": local_judge, "hindsight": local_hindsight},
    }


def load_presets() -> dict[str, Any]:
    defaults = _default_presets()
    if not PRESET_PATH.is_file():
        save_presets(defaults)
        return defaults
    try:
        data = json.loads(PRESET_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaults
    for name, preset in defaults.items():
        loaded = data.get(name) if isinstance(data, dict) else None
        if isinstance(loaded, dict):
            for target, values in preset.items():
                if isinstance(loaded.get(target), dict):
                    values.update({k: str(v) for k, v in loaded[target].items() if v is not None})
    return defaults


def save_presets(presets: dict[str, Any]) -> None:
    PRESET_PATH.write_text(json.dumps(presets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _judge_key_available(provider: str = "", base_url: str = "") -> bool:
    """Whether the selected judge route has the key it needs."""
    judge_model_status()  # loads .env
    provider = (provider or "").strip().lower()
    if provider in {"ollama", "local"}:
        return True
    endpoint = (base_url or "").strip().lower()
    preferred: tuple[str, ...] = ()
    if "deepseek" in endpoint:
        preferred = ("BOOKCOMPILER_JUDGE_API_KEY", "DEEPSEEK_API_KEY")
    elif "openai.com" in endpoint:
        preferred = ("BOOKCOMPILER_JUDGE_API_KEY", "OPENAI_API_KEY")
    elif "dashscope" in endpoint or "aliyun" in endpoint:
        preferred = ("BOOKCOMPILER_JUDGE_API_KEY", "DASHSCOPE_API_KEY")
    elif "xiaomimimo" in endpoint or "mimo" in endpoint:
        preferred = ("BOOKCOMPILER_JUDGE_API_KEY", "MIMO_API_KEY", "XIAOMI_API_KEY")
    if preferred:
        return any(os.environ.get(name, "").strip() for name in preferred)
    return any(os.environ.get(name, "").strip() for name in KEY_NAMES)


def show() -> None:
    judge = judge_model_status()
    reader = reader_model_status()
    hermes = hermes_status()
    hindsight = hindsight_model_status()
    print("=" * 64)
    print("当前模型")
    print("=" * 64)
    print(f"BookCompiler 盲评 : {judge.get('provider')} / {judge.get('model')}")
    print(f"                  {judge.get('base_url')}")
    print(f"                  来源: {judge.get('source')}  ({judge.get('env_file')})")
    print(f"BookCompiler 读书 : {reader.get('provider')} / {reader.get('model')}")
    print(f"                  {reader.get('base_url')}")
    guard = "开启（DeepSeek 读书会被拒绝）" if reader.get("deepseek_guard_enabled") else "关闭（允许 DeepSeek 读书，会产生费用）"
    print(f"                  来源: {reader.get('source')}  费用闸: {guard}")
    print(f"Hermes 对话       : {hermes.get('provider')} / {hermes.get('model')}")
    print(f"                  {hermes.get('base_url')}")
    print(f"                  配置: {hermes.get('config_path')}")
    print(f"Hindsight 记忆    : {hindsight.get('provider')} / {hindsight.get('model')}")
    print(f"                  {hindsight.get('base_url')}")
    print(f"                  配置: {hindsight.get('env_file')}")
    print(f"云端 API key 可用 : {'是' if _judge_key_available() else '否（只影响 BookCompiler 盲评走云端）'}")
    print("=" * 64)


def _print_results(results: list[tuple[str, dict[str, Any]]]) -> None:
    print()
    for label, result in results:
        if result.get("error"):
            print(f"[跳过] {label}: {result['error']}")
            continue
        print(f"[完成] {label}: {result.get('provider', '')} / {result.get('model', '')}")
        if result.get("backup"):
            print(f"       备份: {result['backup']}")
    print()
    print("注意：")
    print("- Hermes 需要在会话里 /model 切换，或退出后重新启动；已运行会话不会自动变。")
    print("- Hindsight 需要重启 D:\\hindsight\\run_server.py 才会读取新 .env。")
    print("- BookCompiler GUI 需要重启，或在 GUI 的「模型」页重新保存一次。")
    print()


def apply_preset_data(name: str) -> list[tuple[str, dict[str, Any]]]:
    """Apply a preset and return per-target results (used by the GUI too)."""
    presets = load_presets()
    preset = presets.get(name)
    if not preset:
        return [("preset", {"error": f"未知预设: {name}"})]
    results: list[tuple[str, dict[str, Any]]] = []
    try:
        results.append(("Hermes", set_hermes_default(**preset["hermes"])))
    except Exception as exc:
        results.append(("Hermes", {"error": f"{type(exc).__name__}: {exc}"}))
    judge_route = preset.get("bookcompiler") or {}
    if _judge_key_available(str(judge_route.get("provider", "")), str(judge_route.get("base_url", ""))):
        try:
            results.append(("BookCompiler 盲评", set_judge_default(**judge_route)))
        except Exception as exc:
            results.append(("BookCompiler 盲评", {"error": f"{type(exc).__name__}: {exc}"}))
    else:
        results.append(
            (
                "BookCompiler 盲评",
                {"error": "未找到可用的 API key。云端盲评需要 DEEPSEEK_API_KEY、OPENAI_API_KEY、DASHSCOPE_API_KEY 或 MIMO_API_KEY。"},
            )
        )
    reader_route = preset.get("reader") or {}
    if reader_route and _judge_key_available(str(reader_route.get("provider", "")), str(reader_route.get("base_url", ""))):
        try:
            results.append(("BookCompiler 读书", set_reader_default(**reader_route)))
        except Exception as exc:
            results.append(("BookCompiler 读书", {"error": f"{type(exc).__name__}: {exc}"}))
    elif reader_route:
        results.append(("BookCompiler 读书", {"error": "未找到读书端点所需的 API key；保留原读书模型。"}))
    try:
        results.append(("Hindsight", set_hindsight_default(**preset["hindsight"])))
    except Exception as exc:
        results.append(("Hindsight", {"error": f"{type(exc).__name__}: {exc}"}))
    return results


def apply_preset(name: str) -> int:
    results = apply_preset_data(name)
    if results and results[0][0] == "preset" and results[0][1].get("error"):
        print(results[0][1]["error"])
        return 2
    _print_results(results)
    return 0

def set_one(target: str, model: str, provider: str, base_url: str = "") -> int:
    target = target.strip().lower()
    try:
        if target in {"hermes", "chat"}:
            result = set_hermes_default(model, provider, base_url)
            _print_results([("Hermes", result)])
        elif target in {"hindsight", "memory"}:
            result = set_hindsight_default(provider, model, base_url)
            _print_results([("Hindsight", result)])
        elif target in {"bookcompiler", "bookcompile", "judge", "bc"}:
            result = set_judge_default(provider, model, base_url)
            _print_results([("BookCompiler 盲评", result)])
        elif target in {"reader", "reading", "book-reader", "bc-reader"}:
            result = set_reader_default(provider, model, base_url)
            _print_results([("BookCompiler 读书", result)])
        else:
            print("target 必须是 hermes / hindsight / bookcompiler / reader")
            return 2
    except Exception as exc:
        print(f"失败: {type(exc).__name__}: {exc}")
        return 1
    return 0


def setup_cloud() -> None:
    presets = load_presets()
    cloud = presets["cloud"]["hermes"]
    print("设置云端 API 预设（只保存模型/接口，不保存 API key）")
    model = input(f"Hermes 模型 [{cloud.get('model')}]: ").strip() or cloud.get("model", "")
    provider = input(f"Provider [{cloud.get('provider')}]: ").strip() or cloud.get("provider", "custom")
    base_url = input(f"Base URL [{cloud.get('base_url')}]: ").strip() or cloud.get("base_url", "")
    cloud.update({"model": model, "provider": provider, "base_url": base_url})
    presets["cloud"]["bookcompiler"] = {
        "provider": "openai-compatible",
        "model": model,
        "base_url": base_url,
    }
    save_presets(presets)
    print(f"已保存到 {PRESET_PATH}")
    print("提醒：BookCompiler 盲评还需要 BOOKCOMPILER_JUDGE_API_KEY、DEEPSEEK_API_KEY 或 OPENAI_API_KEY 之一。")


def _ask_target_settings(target: str) -> tuple[str, str, str]:
    defaults = {
        "hermes": hermes_status(),
        "hindsight": hindsight_model_status(),
        "bookcompiler": judge_model_status(),
        "reader": reader_model_status(),
    }.get(target, {})
    model = input(f"模型 [{defaults.get('model', '')}]: ").strip() or str(defaults.get("model", ""))
    provider = input(f"Provider [{defaults.get('provider', '')}]: ").strip() or str(defaults.get("provider", ""))
    base_url = input(f"Base URL [{defaults.get('base_url', '')}]: ").strip() or str(defaults.get("base_url", ""))
    return model, provider, base_url


def menu() -> int:
    while True:
        print()
        print("=" * 64)
        print("BookCompiler / Hermes / Hindsight 模型切换器")
        print("=" * 64)
        print("1. 查看当前模型")
        print("2. 一键：阅读/对话走云端 API，记忆抽取走本地 Ollama")
        print("3. 一键：全部切到本地 Ollama（离线）")
        print("4. 只切 Hermes 对话模型")
        print("5. 只切 Hindsight 记忆模型")
        print("6. 只切 BookCompiler 盲评模型")
        print("9. 只切 BookCompiler 读书模型（DeepSeek 费用闸默认开启）")
        print("7. 设置云端 API 预设")
        print("8. 一键：MiMo 云端阅读 + 本地 Ollama 记忆")
        print("0. 退出")
        choice = input("请选择: ").strip()
        if choice == "0":
            return 0
        if choice == "1":
            show()
        elif choice == "2":
            apply_preset("cloud")
        elif choice == "3":
            apply_preset("local")
        elif choice in {"4", "5", "6", "9"}:
            target = {"4": "hermes", "5": "hindsight", "6": "bookcompiler", "9": "reader"}[choice]
            model, provider, base_url = _ask_target_settings(target)
            set_one(target, model, provider, base_url)
        elif choice == "7":
            setup_cloud()
        elif choice == "8":
            apply_preset("mimo")
        else:
            print("无效选择")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Switch models for BookCompiler, Hermes and Hindsight.")
    parser.add_argument("command", nargs="?", default="menu", choices=["menu", "show", "preset", "set", "setup-cloud"])
    parser.add_argument("value", nargs="?", default="")
    parser.add_argument("--target", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--provider", default="")
    parser.add_argument("--base-url", default="")
    args = parser.parse_args(argv)
    if args.command == "show":
        show()
        return 0
    if args.command == "preset":
        return apply_preset(args.value or "cloud")
    if args.command == "setup-cloud":
        setup_cloud()
        return 0
    if args.command == "set":
        return set_one(args.target, args.model, args.provider, args.base_url)
    return menu()


if __name__ == "__main__":
    raise SystemExit(main())