import argparse
import asyncio
import json
import os
import random
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from dotenv import load_dotenv


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api_key: str
    api_url: str
    timeout_seconds: int


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model_id: str
    display_name: str
    price_per_1k_prompt_usd: float
    price_per_1k_completion_usd: float


@dataclass(frozen=True)
class ModelResult:
    spec: ModelSpec
    ok: bool
    status: int
    text: str
    usage: Dict[str, Any]
    duration_seconds: float
    error: str = ""


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def load_provider_configs() -> Dict[str, ProviderConfig]:
    load_dotenv()

    configs: Dict[str, ProviderConfig] = {}

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        configs["groq"] = ProviderConfig(
            name="groq",
            api_key=groq_key,
            api_url=os.getenv(
                "GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions"
            ),
            timeout_seconds=_env_int("GROQ_API_TIMEOUT_SECONDS", 60),
        )

    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if deepseek_key:
        configs["deepseek"] = ProviderConfig(
            name="deepseek",
            api_key=deepseek_key,
            api_url=os.getenv(
                "DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"
            ),
            timeout_seconds=_env_int("DEEPSEEK_API_TIMEOUT_SECONDS", 60),
        )

    return configs


def default_models() -> List[ModelSpec]:
    return [
        ModelSpec(
            provider="groq",
            model_id=os.getenv("GROQ_LLAMA3_1_8B_MODEL", "llama-3.1-8b-instant"),
            display_name="Llama-3.1-8B (weak)",
            price_per_1k_prompt_usd=_env_float(
                "GROQ_LLAMA3_1_8B_PRICE_PER_1K_PROMPT_USD", 0.0
            ),
            price_per_1k_completion_usd=_env_float(
                "GROQ_LLAMA3_1_8B_PRICE_PER_1K_COMPLETION_USD", 0.0
            ),
        ),
        ModelSpec(
            provider="groq",
            model_id=os.getenv("GROQ_LLAMA3_1_70B_MODEL", "llama-3.3-70b-versatile"),
            display_name="Llama-3.3-70B (medium)",
            price_per_1k_prompt_usd=_env_float(
                "GROQ_LLAMA3_1_70B_PRICE_PER_1K_PROMPT_USD", 0.0
            ),
            price_per_1k_completion_usd=_env_float(
                "GROQ_LLAMA3_1_70B_PRICE_PER_1K_COMPLETION_USD", 0.0
            ),
        ),
        ModelSpec(
            provider="deepseek",
            model_id=os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-chat"),
            display_name="deepseek-chat (DeepSeek API)",
            price_per_1k_prompt_usd=_env_float(
                "DEEPSEEK_PRICE_PER_1K_PROMPT_USD", 0.00028
            ),
            price_per_1k_completion_usd=_env_float(
                "DEEPSEEK_PRICE_PER_1K_COMPLETION_USD", 0.00042
            ),
        ),
    ]


def build_headers(api_key: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def calc_cost_usd(usage: Dict[str, Any], spec: ModelSpec) -> Optional[float]:
    pt = usage.get("prompt_tokens")
    ct = usage.get("completion_tokens")
    if pt is None or ct is None:
        return None
    return (pt / 1000.0) * spec.price_per_1k_prompt_usd + (
        ct / 1000.0
    ) * spec.price_per_1k_completion_usd


async def call_chat_completion(
    config: ProviderConfig,
    spec: ModelSpec,
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> ModelResult:
    headers = build_headers(config.api_key)
    messages = [{"role": "user", "content": prompt}]
    payload: Dict[str, Any] = {
        "model": spec.model_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    start_time = perf_counter()
    timeout = aiohttp.ClientTimeout(sock_read=config.timeout_seconds)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                config.api_url, headers=headers, json=payload
            ) as resp:
                status = resp.status
                body_text = await resp.text()
                duration = perf_counter() - start_time

                if status != 200:
                    return ModelResult(
                        spec=spec,
                        ok=False,
                        status=status,
                        text="",
                        usage={},
                        duration_seconds=duration,
                        error=body_text,
                    )

                try:
                    data = json.loads(body_text)
                except json.JSONDecodeError as e:
                    return ModelResult(
                        spec=spec,
                        ok=False,
                        status=status,
                        text="",
                        usage={},
                        duration_seconds=duration,
                        error=f"JSON decode error: {e}",
                    )

                try:
                    text = data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as e:
                    return ModelResult(
                        spec=spec,
                        ok=False,
                        status=status,
                        text="",
                        usage={},
                        duration_seconds=duration,
                        error=f"Malformed response: {e}",
                    )

                usage = data.get("usage", {})
                return ModelResult(
                    spec=spec,
                    ok=True,
                    status=status,
                    text=(text or "").strip(),
                    usage=usage,
                    duration_seconds=duration,
                )

    except asyncio.TimeoutError:
        return ModelResult(
            spec=spec,
            ok=False,
            status=0,
            text="",
            usage={},
            duration_seconds=perf_counter() - start_time,
            error="Request timeout (client-side).",
        )
    except aiohttp.ClientError as e:
        return ModelResult(
            spec=spec,
            ok=False,
            status=0,
            text="",
            usage={},
            duration_seconds=perf_counter() - start_time,
            error=f"Network error: {type(e).__name__}: {e}",
        )
    except Exception as e:
        return ModelResult(
            spec=spec,
            ok=False,
            status=0,
            text="",
            usage={},
            duration_seconds=perf_counter() - start_time,
            error=f"Unexpected error: {type(e).__name__}: {e}",
        )


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return None


def label_results_for_judge(
    results: List[ModelResult],
) -> List[Tuple[str, ModelResult]]:
    ok_results = [r for r in results if r.ok]
    random.shuffle(ok_results)
    labeled: List[Tuple[str, ModelResult]] = []
    for i, res in enumerate(ok_results):
        label = chr(ord("A") + i)
        labeled.append((label, res))
    return labeled


def build_judge_messages(
    prompt: str, labeled: List[Tuple[str, ModelResult]]
) -> List[Dict[str, str]]:
    system = (
        "You are a strict evaluator of response quality. "
        "Do not guess which model produced which response. "
        "Score each response from 1 to 10 for overall quality, correctness, "
        "completeness, clarity, and helpfulness. "
        "Return JSON only with schema: "
        '{"scores": {"A": {"score": 1-10, "reason": "..."}} , "best": "A"}. '
        "Keep reasons short."
    )

    responses = []
    for label, res in labeled:
        responses.append(f"Response {label}:\n{res.text}")
    user = f"User prompt:\n{prompt}\n\nResponses:\n" + "\n\n".join(responses)

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


async def judge_quality(
    config: Optional[ProviderConfig],
    prompt: str,
    labeled: List[Tuple[str, ModelResult]],
) -> Dict[str, Any]:
    if not config:
        return {"error": "DeepSeek config not available."}
    if not labeled:
        return {"error": "No successful responses to judge."}

    messages = build_judge_messages(prompt, labeled)
    payload: Dict[str, Any] = {
        "model": os.getenv("DEEPSEEK_API_MODEL", "deepseek-chat"),
        "messages": messages,
        "temperature": 0,
        "max_tokens": 800,
    }

    timeout = aiohttp.ClientTimeout(sock_read=config.timeout_seconds)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                config.api_url,
                headers=build_headers(config.api_key),
                json=payload,
            ) as resp:
                status = resp.status
                body_text = await resp.text()
                if status != 200:
                    return {"error": body_text}

        try:
            data = json.loads(body_text)
            content = data["choices"][0]["message"]["content"]
        except Exception as e:
            return {"error": f"Malformed judge response: {e}", "raw_text": body_text}

        parsed = None
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = _extract_json(content)

        if not isinstance(parsed, dict):
            return {"error": "Judge returned non-JSON output.", "raw_text": content}

        return {
            "scores": parsed.get("scores", {}),
            "best": parsed.get("best"),
            "raw_text": content,
        }
    except Exception as e:
        return {"error": f"Judge request failed: {type(e).__name__}: {e}"}


def jaccard_similarity(a: str, b: str) -> float:
    a_set = set(a.lower().split())
    b_set = set(b.lower().split())
    if not a_set and not b_set:
        return 1.0
    if not a_set or not b_set:
        return 0.0
    return len(a_set & b_set) / len(a_set | b_set)


def build_pairwise_similarity(
    results: List[ModelResult],
) -> List[Tuple[str, str, float]]:
    ok_results = [r for r in results if r.ok]
    pairs: List[Tuple[str, str, float]] = []
    for i in range(len(ok_results)):
        for j in range(i + 1, len(ok_results)):
            a = ok_results[i]
            b = ok_results[j]
            sim = jaccard_similarity(a.text, b.text)
            pairs.append((a.spec.display_name, b.spec.display_name, sim))
    return pairs


def print_summary(
    results: List[ModelResult],
    judge_data: Optional[Dict[str, Any]] = None,
    labeled: Optional[List[Tuple[str, ModelResult]]] = None,
) -> None:
    label_by_result: Dict[int, str] = {}
    label_to_result: Dict[str, ModelResult] = {}
    if labeled:
        for label, res in labeled:
            label_by_result[id(res)] = label
            label_to_result[label] = res

    scores = judge_data.get("scores", {}) if judge_data else {}

    def score_value(entry: Any) -> Optional[int]:
        if isinstance(entry, dict):
            val = entry.get("score")
            if isinstance(val, (int, float)):
                return int(val)
            if isinstance(val, str) and val.isdigit():
                return int(val)
            return None
        if isinstance(entry, (int, float)):
            return int(entry)
        if isinstance(entry, str) and entry.isdigit():
            return int(entry)
        return None

    print("\n=== Summary ===")
    for r in results:
        name = r.spec.display_name
        if not r.ok:
            print(f"- {name}: ERROR (HTTP {r.status}) {r.error}")
            continue
        usage = r.usage or {}
        pt = usage.get("prompt_tokens")
        ct = usage.get("completion_tokens")
        tt = usage.get("total_tokens")
        cost = calc_cost_usd(usage, r.spec)
        cost_text = f"${cost:.6f}" if cost is not None else "n/a"

        label = label_by_result.get(id(r))
        score_entry = scores.get(label) if label else None
        score = score_value(score_entry)
        quality_text = f"{score}/10" if score is not None else "n/a"
        reason = ""
        if isinstance(score_entry, dict):
            reason_val = score_entry.get("reason")
            if isinstance(reason_val, str) and reason_val.strip():
                reason = reason_val.strip()
        max_reason_len = 120
        if len(reason) > max_reason_len:
            reason = reason[: max_reason_len - 1].rstrip() + "…"
        reason_text = f" ({reason})" if reason else ""

        print(
            f"- {name}: quality={quality_text}{reason_text} | {r.duration_seconds:.2f}s | tokens: "
            f"prompt={pt}, completion={ct}, total={tt} | cost: {cost_text}"
        )

    ok_results = [r for r in results if r.ok]
    print("\n=== Summary: Comparison ===")
    if not ok_results:
        print("No successful responses to compare.")
        return

    best_label = judge_data.get("best") if judge_data else None
    if not best_label and scores:
        scored = []
        for label, entry in scores.items():
            val = score_value(entry)
            if val is not None:
                scored.append((label, val))
        if scored:
            best_label = max(scored, key=lambda x: x[1])[0]

    if best_label and best_label in label_to_result and scores:
        best_entry = scores.get(best_label)
        best_score = score_value(best_entry)
        best_name = label_to_result[best_label].spec.display_name
        best_score_text = f"{best_score}/10" if best_score is not None else "n/a"
        print(f"Quality winner: {best_name} ({best_score_text})")
    else:
        print("Quality winner: n/a (judge unavailable)")

    fastest = min(ok_results, key=lambda r: r.duration_seconds)
    print(
        f"Speed winner: {fastest.spec.display_name} ({fastest.duration_seconds:.2f}s)"
    )

    costs = []
    for r in ok_results:
        cost = calc_cost_usd(r.usage or {}, r.spec)
        if cost is not None:
            costs.append((r, cost))
    if costs:
        best_cost = min(costs, key=lambda x: x[1])
        print(
            f"Resource winner (lowest cost): {best_cost[0].spec.display_name} "
            f"(${best_cost[1]:.6f})"
        )
    else:

        def total_tokens(res: ModelResult) -> int:
            usage = res.usage or {}
            tt = usage.get("total_tokens")
            if isinstance(tt, int):
                return tt
            return 10**9

        lowest_tokens = min(ok_results, key=total_tokens)
        print(
            f"Resource winner (lowest tokens): {lowest_tokens.spec.display_name} "
            f"(total={total_tokens(lowest_tokens)})"
        )


def print_responses(results: List[ModelResult]) -> None:
    print("\n=== Responses ===")
    for r in results:
        title = r.spec.display_name
        print("\n" + "=" * 12 + f" {title} " + "=" * 12)
        if not r.ok:
            print(f"ERROR (HTTP {r.status}): {r.error}")
            continue
        print(r.text)


def print_comparison(results: List[ModelResult]) -> None:
    pairs = build_pairwise_similarity(results)
    if not pairs:
        print("\n=== Comparison ===")
        print("No successful responses to compare.")
        return

    print("\n=== Comparison (Jaccard similarity on words) ===")
    for a, b, sim in sorted(pairs, key=lambda x: x[2], reverse=True):
        print(f"- {a} vs {b}: {sim:.3f}")


async def compare_models(
    prompt: str,
    max_tokens: int = 512,
    temperature: float = 0.2,
    configs: Optional[Dict[str, ProviderConfig]] = None,
) -> List[ModelResult]:
    if configs is None:
        configs = load_provider_configs()
    models = default_models()

    results: List[ModelResult] = []
    for spec in models:
        config = configs.get(spec.provider)
        if not config:
            results.append(
                ModelResult(
                    spec=spec,
                    ok=False,
                    status=0,
                    text="",
                    usage={},
                    duration_seconds=0.0,
                    error=f"Provider '{spec.provider}' is not configured.",
                )
            )
            continue
        result = await call_chat_completion(
            config=config,
            spec=spec,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        results.append(result)

    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare responses across multiple models/providers."
    )
    parser.add_argument(
        "--prompt",
        default="",
        help="Prompt to send to all models (if empty, will ask interactively)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=1200,
        help="max_tokens for each model response",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="Sampling temperature",
    )
    parser.add_argument(
        "--no-responses",
        action="store_true",
        help="Do not print full responses",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if not args.prompt:
        args.prompt = input("Prompt: ").strip()
        if not args.prompt:
            print("No prompt provided. Exiting.")
            return

    configs = load_provider_configs()
    results = await compare_models(
        prompt=args.prompt,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        configs=configs,
    )

    labeled = label_results_for_judge(results)
    judge_data = await judge_quality(configs.get("deepseek"), args.prompt, labeled)

    print_summary(results, judge_data=judge_data, labeled=labeled)
    if not args.no_responses:
        print_responses(results)
    print_comparison(results)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Остановлено пользователем.")
