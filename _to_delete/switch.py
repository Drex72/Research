#!/usr/bin/env python3
"""Run the code-switcher on one prompt, from the command line.

Standalone: standard library only, talks to your local Ollama directly, and
loads no experiment configuration. This is the module working on its own.

    python3 scripts/switch.py --profile languages/CS-EN-YO.json \
        --text "Please approve loan SWIFT-000001 for 300,000."

    python3 scripts/switch.py --profile languages/CS-EN-KO-YO.json \
        --file some_prompt.txt --model qwen3.5:27b

    python3 scripts/switch.py --profile languages/CS-EN-ES.json --show-instruction
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from csrt_mas.codeswitch import CodeSwitcher  # noqa: E402


def ollama_caller(model: str, base_url: str, timeout: int, temperature: float):
    """Return a (system, user) -> str callable backed by local Ollama."""

    def complete(system: str, user: str) -> str:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature, "num_predict": 2048},
        }
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise SystemExit(
                f"cannot reach Ollama at {base_url}: {exc}\n"
                "Is it running?  ollama serve"
            ) from exc
        return body.get("message", {}).get("content", "")

    return complete


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", required=True, help="path to a languages/*.json surface")
    parser.add_argument("--text", help="the prompt to switch")
    parser.add_argument("--file", help="read the prompt from a file instead")
    parser.add_argument("--model", default="qwen3.5:27b", help="Ollama model tag")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--attempts", type=int, default=3, help="validation retries")
    parser.add_argument("--show-instruction", action="store_true",
                        help="print the instruction that would be sent, call nothing")
    parser.add_argument("--check", action="store_true",
                        help="treat --text as an already-authored form and only validate it")
    parser.add_argument("--source", help="source text to check protected tokens against")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    text = args.text
    if args.file:
        text = pathlib.Path(args.file).read_text(encoding="utf-8")
    if not text and not args.show_instruction:
        parser.error("one of --text or --file is required")

    complete = ollama_caller(args.model, args.base_url, args.timeout, args.temperature)
    switcher = CodeSwitcher.from_profile(
        args.profile, complete=complete, model=args.model, max_attempts=args.attempts
    )

    if args.show_instruction:
        print(switcher.instruction(text or ""))
        return 0

    if args.check:
        problems = switcher.check(text, args.source)
        profile = switcher.language_profile(text)
        if args.json:
            print(json.dumps({"ok": not problems, "problems": problems, "languages": profile},
                             ensure_ascii=False, indent=2))
        else:
            print(f"languages detected: {profile}")
            print("PASS: structural checks satisfied" if not problems
                  else "FAIL:\n  - " + "\n  - ".join(problems))
            print("\nNote: this is a structural check, not meaning equivalence.")
        return 0 if not problems else 1

    print(f"surface   : {switcher.spec.surface_id}", file=sys.stderr)
    print(f"spec      : {switcher.spec.describe()}", file=sys.stderr)
    print(f"model     : {args.model}", file=sys.stderr)
    print("switching ...", file=sys.stderr)

    result = switcher.switch(text)

    if args.json:
        print(json.dumps({**result.as_dict(), "text": result.text,
                          "languages": switcher.language_profile(result.text)},
                         ensure_ascii=False, indent=2))
        return 0 if result.ok else 1

    print("\n" + "=" * 70)
    print("SOURCE")
    print("=" * 70)
    print(text.strip())
    print("\n" + "=" * 70)
    print(f"CODE-SWITCHED  ({'accepted' if result.ok else 'REJECTED'} after {result.attempts} attempt(s))")
    print("=" * 70)
    print(result.text.strip() or "(empty)")
    print("\n" + "=" * 70)
    print("CHECKS")
    print("=" * 70)
    print(f"tokens per language : {switcher.language_profile(result.text)}")
    if result.ok:
        print("structural checks   : PASS")
        print("\nThis is NOT meaning equivalence. A bilingual reviewer still has to")
        print("confirm the request asks for the same thing before this surface is")
        print("marked reviewed.")
    else:
        print("structural checks   : FAIL")
        for problem in result.problems:
            print(f"  - {problem}")
        print("\nNo substitution fallback ran. A rejected form stays rejected.")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
