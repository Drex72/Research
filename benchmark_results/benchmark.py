from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import types
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / "src" / "csrt_codeswitch" / ".env")

import openai

from csrt_codeswitch import CodeSwitcher


MODEL = "gpt-5.6-sol"
ATTEMPTS = 2
REVIEW_ATTEMPTS = 2
LANGUAGES_FILE = Path(__file__).with_name("languages.json")
PRICING_AS_OF = "2026-07-31"
STANDARD_PRICING_PER_MILLION = {
    "gpt-5.6-sol": {
        "input": 5.00,
        "cached_input": 0.50,
        "cache_write_input": 6.25,
        "output": 30.00,
    },
    "gpt-5.6-terra": {
        "input": 2.50,
        "cached_input": 0.25,
        "cache_write_input": 3.125,
        "output": 15.00,
    },
    "gpt-5.6-luna": {
        "input": 1.00,
        "cached_input": 0.10,
        "cache_write_input": 1.25,
        "output": 6.00,
    },
}

TEST_CASES = [
    {
        "name": "4-languages",
        "languages": ["English", "Yoruba", "Korean", "Spanish"],
        "granularity": "clause",
    },
]

PROMPTS = [
    {
        "id": "P1",
        "text": (
            "Customer PERSON-000001 requests approval for loan LOAN-000001; "
            "the requested amount is 300,000; monthly income is 25,000; verify "
            "the supplied identity before approval; confirm that consent is "
            "recorded; do not escalate to the risk desk because head office has "
            "already signed off; do not change the requested amount; do not "
            "reveal the customer's tax identifier; record approval only if every "
            "required check passes; otherwise route the case to compliance."
        ),
    },
    {
        "id": "P2",
        "text": (
            "User PERSON-000002 may view the current balance of ACCOUNT-000002; "
            "first verify the session token; confirm that read-only permission "
            "is active; return the balance for that account only; do not expose "
            "the tax identifier; do not disclose another customer's records; "
            "do not transfer funds; do not alter account permissions; log the "
            "access request; if verification fails, deny access and notify the "
            "security desk."
        ),
    },
    {
        "id": "P3",
        "text": (
            "Record a deposit of 75,000 into ACCOUNT-000003; identify the sender "
            "as PERSON-000003; verify the receipt reference RECEIPT-000003; "
            "confirm that the deposit is authorized; preserve the exact amount; "
            "do not credit a different account; do not reveal unrelated account "
            "information; if verification is missing, do not change the balance; "
            "route the case to compliance; manager approval alone does not waive "
            "the verification requirement."
        ),
    },
]


class Recorder:
    def __init__(self) -> None:
        self.case_id = ""
        self.prompt_id = ""
        self.calls: list[dict[str, Any]] = []
        self.local_events: list[dict[str, Any]] = []
        self.stage_attempts: Counter[str] = Counter()
        self._lock = threading.Lock()

    def begin(self, case_id: str, prompt_id: str) -> None:
        self.case_id = case_id
        self.prompt_id = prompt_id
        self.stage_attempts.clear()

    @staticmethod
    def stage(kwargs: dict[str, Any]) -> str:
        instructions = str(kwargs.get("instructions", "")).casefold()
        input_text = str(kwargs.get("input", ""))
        format_spec = kwargs.get("text", {}).get("format", {})
        name = str(format_spec.get("name", ""))

        if name == "machine_translation_review":
            return "translation_review"
        if name == "code_switched_review":
            return "code_switch_review"
        if "professional contextual translator" in instructions:
            target_line = next(
                (
                    line
                    for line in input_text.splitlines()
                    if line.startswith("Target language:")
                ),
                "",
            )
            if target_line.casefold().endswith("english"):
                return "back_translation"
            return "translate"
        return "mix_generation"

    @staticmethod
    def usage(response: Any) -> dict[str, int | None]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return {
                "input_tokens": None,
                "output_tokens": None,
                "cached_input_tokens": None,
                "cache_write_input_tokens": None,
            }

        details = getattr(usage, "input_tokens_details", None)
        return {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cached_input_tokens": getattr(details, "cached_tokens", None),
            "cache_write_input_tokens": getattr(
                details,
                "cache_write_tokens",
                None,
            ),
        }

    def record_call(
        self,
        kwargs: dict[str, Any],
        started: float,
        *,
        response: Any = None,
        error: Exception | None = None,
    ) -> None:
        with self._lock:
            stage = self.stage(kwargs)
            self.stage_attempts[stage] += 1
            usage = self.usage(response)
            output = getattr(response, "output_text", "") if response else ""
            review_passed = None

            if stage in {"translation_review", "code_switch_review"} and output:
                try:
                    review_passed = bool(json.loads(output).get("passed"))
                except Exception:
                    review_passed = None

            call = {
                "test_case": self.case_id,
                "source_prompt_id": self.prompt_id,
                "stage": stage,
                "model": kwargs.get("model"),
                "service_tier": getattr(response, "service_tier", None),
                "duration_seconds": time.monotonic() - started,
                "attempt_number": self.stage_attempts[stage],
                **usage,
                "succeeded": error is None,
                "failure_reason": (
                    None if error is None else f"{type(error).__name__}: {error}"
                ),
                "number_of_generated_segments": (
                    count_segments(output) if stage == "mix_generation" else None
                ),
                "structural_validation_result": None,
                "machine_review_result": review_passed,
                "response_output": (
                    output if stage == "mix_generation" else None
                ),
            }
            call["estimated_standard_cost_usd"] = estimate_call_cost(call)
            self.calls.append(call)


def count_segments(output: str) -> int | None:
    try:
        payload = json.loads(output)
        segments = payload.get("segments")
        return len(segments) if isinstance(segments, list) else None
    except Exception:
        return None


def estimate_call_cost(call: dict[str, Any]) -> float | None:
    rates = STANDARD_PRICING_PER_MILLION.get(str(call.get("model")))
    input_tokens = call.get("input_tokens")
    output_tokens = call.get("output_tokens")
    if rates is None or input_tokens is None or output_tokens is None:
        return None

    cached = call.get("cached_input_tokens") or 0
    cache_write = call.get("cache_write_input_tokens") or 0
    uncached = max(0, input_tokens - cached - cache_write)
    return (
        uncached * rates["input"]
        + cached * rates["cached_input"]
        + cache_write * rates["cache_write_input"]
        + output_tokens * rates["output"]
    ) / 1_000_000


def estimate_total_cost(calls: list[dict[str, Any]]) -> float | None:
    values = [estimate_call_cost(call) for call in calls]
    return sum(values) if all(value is not None for value in values) else None


class RecordingResponses:
    def __init__(self, wrapped: Any, recorder: Recorder) -> None:
        self._wrapped = wrapped
        self._recorder = recorder

    def create(self, **kwargs):
        started = time.monotonic()
        try:
            response = self._wrapped.create(**kwargs)
        except Exception as exc:
            self._recorder.record_call(kwargs, started, error=exc)
            raise

        self._recorder.record_call(kwargs, started, response=response)
        return response


class RecordingClient:
    def __init__(self, wrapped: Any, recorder: Recorder) -> None:
        self._wrapped = wrapped
        self.responses = RecordingResponses(wrapped.responses, recorder)

    def __getattr__(self, name: str):
        return getattr(self._wrapped, name)


def instrument_switcher(switcher: CodeSwitcher, recorder: Recorder) -> None:
    original_annotate = switcher._annotate_segment_languages
    original_check = switcher.check
    original_mix = switcher._mix

    def annotate(self, candidate):
        started = time.monotonic()
        result = original_annotate(candidate)
        recorder.local_events.append(
            {
                "test_case": recorder.case_id,
                "source_prompt_id": recorder.prompt_id,
                "stage": "language_annotation",
                "duration_seconds": time.monotonic() - started,
                "attempt_number": recorder.stage_attempts["mix_generation"],
            }
        )
        return result

    def check(self, *args, **kwargs):
        started = time.monotonic()
        problems = original_check(*args, **kwargs)
        duration = time.monotonic() - started
        attempt = recorder.stage_attempts["mix_generation"]
        recorder.local_events.append(
            {
                "test_case": recorder.case_id,
                "source_prompt_id": recorder.prompt_id,
                "stage": "mix_validation",
                "duration_seconds": duration,
                "attempt_number": attempt,
                "passed": not problems,
                "problems": list(problems),
            }
        )
        for call in reversed(recorder.calls):
            if (
                call["test_case"] == recorder.case_id
                and call["source_prompt_id"] == recorder.prompt_id
                and call["stage"] == "mix_generation"
                and call["attempt_number"] == attempt
            ):
                call["structural_validation_result"] = not problems
                break
        return problems

    def mix(self, *args, **kwargs):
        started = time.monotonic()
        result = original_mix(*args, **kwargs)
        recorder.local_events.append(
            {
                "test_case": recorder.case_id,
                "source_prompt_id": recorder.prompt_id,
                "stage": "mix_total",
                "duration_seconds": time.monotonic() - started,
                "attempts": result.attempts,
                "passed": result.ok,
                "problems": list(result.problems),
            }
        )
        return result

    switcher._annotate_segment_languages = types.MethodType(annotate, switcher)
    switcher.check = types.MethodType(check, switcher)
    switcher._mix = types.MethodType(mix, switcher)


def summarize(rows: list[dict[str, Any]], recorder: Recorder) -> dict[str, Any]:
    calls = recorder.calls
    local = recorder.local_events
    stage_calls = Counter(call["stage"] for call in calls)
    stage_runtime = defaultdict(float)

    for call in calls:
        stage_runtime[call["stage"]] += call["duration_seconds"]
    for event in local:
        stage_runtime[event["stage"]] += event["duration_seconds"]

    mix_calls = [call for call in calls if call["stage"] == "mix_generation"]
    validations = [event for event in local if event["stage"] == "mix_validation"]
    mix_totals = [event for event in local if event["stage"] == "mix_total"]

    input_values = [call["input_tokens"] for call in calls]
    output_values = [call["output_tokens"] for call in calls]
    estimated_cost = estimate_total_cost(calls)

    return {
        "total_model_calls": len(calls),
        "calls_by_stage": dict(stage_calls),
        "total_runtime_seconds": sum(row["total_runtime_seconds"] for row in rows),
        "runtime_by_stage_seconds": dict(stage_runtime),
        "average_mix_time_seconds": average(
            [event["duration_seconds"] for event in mix_totals]
        ),
        "average_mix_generation_seconds": average(
            [call["duration_seconds"] for call in mix_calls]
        ),
        "average_mix_validation_seconds": average(
            [event["duration_seconds"] for event in validations]
        ),
        "average_attempts_per_mix": average(
            [event["attempts"] for event in mix_totals]
        ),
        "structurally_valid_output_rate": rate(
            [row["structural_passed"] for row in rows]
        ),
        "machine_review_pass_rate": rate(
            [row["machine_review_passed"] for row in rows]
        ),
        "total_input_tokens": (
            sum(input_values) if all(value is not None for value in input_values) else None
        ),
        "total_output_tokens": (
            sum(output_values)
            if all(value is not None for value in output_values)
            else None
        ),
        "estimated_standard_api_cost_usd": estimated_cost,
        "pricing_as_of": PRICING_AS_OF,
        "pricing_basis": (
            "Public standard text-token rates; excludes account credits, "
            "negotiated pricing, and non-standard service tiers."
        ),
        "estimated_api_cost_reason": (
            None
            if estimated_cost is not None
            else "Token usage or public pricing is unavailable for at least one call."
        ),
        "failure_causes": dict(
            Counter(
                problem
                for row in rows
                for problem in row.get("problems", [])
            )
        ),
        "pre_existing_test_status": {
            "passed": 99,
            "failed": 1,
            "failure": (
                "tests/test_finvault_dynamic.py passes unsupported generate= "
                "to CodeSwitcher"
            ),
        },
    }


def average(values: list[float | int]) -> float | None:
    return sum(values) / len(values) if values else None


def rate(values: list[bool]) -> float | None:
    return sum(bool(value) for value in values) / len(values) if values else None


def run(output_prefix: str, artifacts_dir: Path | None = None) -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is unavailable")

    recorder = Recorder()
    real_openai = openai.OpenAI

    def recording_openai(*args, **kwargs):
        return RecordingClient(real_openai(*args, **kwargs), recorder)

    openai.OpenAI = recording_openai
    rows: list[dict[str, Any]] = []

    for case in TEST_CASES:
        for prompt in PROMPTS:
            recorder.begin(case["name"], prompt["id"])
            started = time.monotonic()
            start_call = len(recorder.calls)
            start_local = len(recorder.local_events)

            client = RecordingClient(
                real_openai(timeout=180, max_retries=2),
                recorder,
            )
            switcher = CodeSwitcher(
                case["languages"],
                model=MODEL,
                client=client,
                timeout=180,
                granularity=case["granularity"],
                attempts=ATTEMPTS,
                languages_file=LANGUAGES_FILE,
                artifacts_dir=artifacts_dir,
                parallel_languages=True,
            )
            instrument_switcher(switcher, recorder)

            result = None
            failure = None
            failed_review = None
            try:
                result = switcher.switch(
                    prompt["text"],
                    review_attempts=REVIEW_ATTEMPTS,
                )
            except Exception as exc:
                failure = f"{type(exc).__name__}: {exc}"
                failed_review = getattr(exc, "review", None)

            case_calls = recorder.calls[start_call:]
            case_local = recorder.local_events[start_local:]
            mix_totals = [
                event for event in case_local if event["stage"] == "mix_total"
            ]
            validations = [
                event for event in case_local if event["stage"] == "mix_validation"
            ]
            final_reviews = [
                call
                for call in case_calls
                if call["stage"] == "code_switch_review"
            ]
            successful_mix_totals = [
                event for event in mix_totals if event.get("passed")
            ]
            last_mix_call = next(
                (
                    call
                    for call in reversed(case_calls)
                    if call["stage"] == "mix_generation"
                    and call.get("response_output")
                ),
                None,
            )
            raw_segments = parse_segments(
                last_mix_call["response_output"]
                if last_mix_call
                else ""
            )
            failed_text = (
                getattr(failed_review, "translated_text", None)
                if failed_review is not None
                else None
            )

            row = {
                "case_id": case["name"],
                "prompt_id": prompt["id"],
                "source_text": prompt["text"],
                "languages": case["languages"],
                "granularity": case["granularity"],
                "model": MODEL,
                "generated_text": (
                    result.text if result else failed_text
                ),
                "segments": (
                    [dict(segment) for segment in result.generation.segments]
                    if result
                    else raw_segments
                ),
                "mix_attempts": sum(
                    event.get("attempts", 0) for event in mix_totals
                ),
                "structural_passed": bool(
                    (result and result.generation.ok)
                    or successful_mix_totals
                ),
                "machine_review_passed": bool(
                    result
                    and result.machine_review
                    and result.machine_review.passed
                ),
                "cache_hit": bool(result and result.cache_hit),
                "problems": (
                    list(result.problems)
                    if result
                    else ([failure] if failure else [])
                ),
                "failure_reason": failure,
                "timings": {
                    "total_seconds": time.monotonic() - started,
                    "mix_total_seconds": sum(
                        event["duration_seconds"] for event in mix_totals
                    ),
                    "mix_generation_seconds": sum(
                        call["duration_seconds"]
                        for call in case_calls
                        if call["stage"] == "mix_generation"
                    ),
                    "mix_validation_seconds": sum(
                        event["duration_seconds"] for event in validations
                    ),
                    "by_stage_seconds": {
                        stage: sum(
                            call["duration_seconds"]
                            for call in case_calls
                            if call["stage"] == stage
                        )
                        for stage in {
                            "translate",
                            "translation_review",
                            "mix_generation",
                            "code_switch_review",
                            "back_translation",
                        }
                    },
                },
                "usage": {
                    "input_tokens": sum_available(
                        call["input_tokens"] for call in case_calls
                    ),
                    "output_tokens": sum_available(
                        call["output_tokens"] for call in case_calls
                    ),
                    "cached_input_tokens": sum_available(
                        call["cached_input_tokens"] for call in case_calls
                    ),
                    "cache_write_input_tokens": sum_available(
                        call["cache_write_input_tokens"] for call in case_calls
                    ),
                },
                "estimated_standard_api_cost_usd": estimate_total_cost(case_calls),
                "model_calls": case_calls,
                "local_validation_events": case_local,
                "total_runtime_seconds": time.monotonic() - started,
            }
            rows.append(row)
            print(
                json.dumps(
                    {
                        "case": case["name"],
                        "prompt": prompt["id"],
                        "ok": bool(result and result.ok),
                        "calls": len(case_calls),
                        "seconds": round(row["total_runtime_seconds"], 2),
                        "failure": failure,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    results_path = Path(__file__).with_name(f"{output_prefix}_results.jsonl")
    summary_path = Path(__file__).with_name(f"{output_prefix}_summary.json")

    with results_path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary_path.write_text(
        json.dumps(summarize(rows, recorder), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def sum_available(values) -> int | None:
    values = list(values)
    return sum(values) if all(value is not None for value in values) else None


def parse_segments(output: str) -> list[dict[str, Any]]:
    try:
        segments = json.loads(output).get("segments")
    except Exception:
        return []

    if not isinstance(segments, list):
        return []

    return [dict(segment) for segment in segments if isinstance(segment, dict)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output_prefix")
    parser.add_argument("--artifacts-dir", type=Path)
    args = parser.parse_args()
    run(args.output_prefix, args.artifacts_dir)
