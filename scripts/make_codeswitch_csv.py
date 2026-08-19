#!/usr/bin/env python3
"""Code-switch one scenario's attack prompts and write them to a CSV.

Standalone. It does not read ``experiment.json``, it does not freeze anything,
and it does not touch the corpus the pilot runs on. Point it at a scenario, name
the languages you want, and it writes one row per turn with the English source
beside its code-switched form so you can read them side by side.

    python3 scripts/make_codeswitch_csv.py --scenario 00
    python3 scripts/make_codeswitch_csv.py --scenario 13 --languages English Yoruba --limit 5
    python3 scripts/make_codeswitch_csv.py --scenario 00 \
        --languages English Korean Yoruba Spanish \
        --granularity word --max-dominance 0.6 --min-hits 2

Multi-turn cases are expanded: a case with two follow-ups becomes three rows,
numbered by ``turn_index``, so a conversation stays reconstructable.

See what it would do without spending anything:

    python3 scripts/make_codeswitch_csv.py --scenario 00 --dry

Generation calls OpenAI through ``csrt_codeswitch``, so ``OPENAI_API_KEY`` has
to be set. Rows are written as they are produced, and a rejected turn is
recorded with its reasons rather than aborting the run, so a long job survives
a bad prompt or a dropped connection.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# The CSV is the deliverable and carries nothing but the pair. Everything that
# used to sit beside it — provenance, token cost, rejection reasons, detected
# languages — is still recorded, in the .stages.jsonl sidecar, the .done index
# and the terminal log, so dropping the columns loses no evidence.
FIELDS = ["english", "code_switched"]


# ---------------------------------------------------------------------------
# token accounting
# ---------------------------------------------------------------------------


class TokenMeter:
    """Tally OpenAI usage across every client the switcher builds.

    One turn is not one API call. Producing a mixed form runs a translation and
    a review per non-English language, then the mixing call, then a review of
    the result, and a rejected attempt spends all of that again on the retry.
    The per-turn columns exist so a rejection's cost is visible rather than
    averaged away.

    Usage is read from each response rather than estimated from text length,
    so reasoning and cached tokens are counted as the API reports them.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.input = 0
        self.output = 0
        self.reasoning = 0
        self.cached = 0

    def record(self, usage) -> None:
        if usage is None:
            return
        get = (lambda name, default=0: getattr(usage, name, default)) if not isinstance(
            usage, dict
        ) else (lambda name, default=0: usage.get(name, default))
        self.calls += 1
        self.input += int(get("input_tokens") or 0)
        self.output += int(get("output_tokens") or 0)
        details = get("output_tokens_details", None)
        if details is not None:
            self.reasoning += int(
                (details.get("reasoning_tokens", 0) if isinstance(details, dict)
                 else getattr(details, "reasoning_tokens", 0)) or 0
            )
        details = get("input_tokens_details", None)
        if details is not None:
            self.cached += int(
                (details.get("cached_tokens", 0) if isinstance(details, dict)
                 else getattr(details, "cached_tokens", 0)) or 0
            )

    def snapshot(self) -> dict[str, int]:
        return {
            "api_calls": self.calls, "input_tokens": self.input,
            "output_tokens": self.output, "reasoning_tokens": self.reasoning,
            "cached_tokens": self.cached,
        }

    def since(self, before: dict[str, int]) -> dict[str, int]:
        now = self.snapshot()
        return {key: now[key] - before[key] for key in now}

    @property
    def total(self) -> int:
        return self.input + self.output


# Set by install_meter, read by the stage wrappers so each stage can be charged
# for what it spent. A module global rather than a parameter because the
# wrappers are installed on classes inside csrt_codeswitch, which has no place
# to hand one through.
METER: "TokenMeter | None" = None
STAGE_TOKENS: dict[str, dict[str, int]] = {}

USAGE_FIELDS = ("api_calls", "input_tokens", "output_tokens",
                "reasoning_tokens", "cached_tokens")


def _cost(spent: dict[str, int], args) -> float:
    """Dollar estimate for one stage's usage.

    Reasoning tokens are already inside output_tokens as the API reports them,
    and they bill at the output rate, so they are not added again here.
    """
    return (spent["input_tokens"] / 1e6 * args.input_price
            + spent["output_tokens"] / 1e6 * args.output_price)


def charge(stage: str, spent: dict[str, int]) -> None:
    """Add one call's usage to a stage's running total."""
    running = STAGE_TOKENS.setdefault(stage, dict.fromkeys(USAGE_FIELDS, 0))
    for key in USAGE_FIELDS:
        running[key] += spent.get(key, 0)


# Stages nest: back_translation is a wrapper around a batch of translate calls,
# so charging both the whole delta would count the same tokens twice and the
# shares would not add to 100%. Each frame accumulates what its children spent,
# and a stage is charged its own delta minus that.
_FRAMES: list[dict[str, int]] = []


def _enter_frame() -> None:
    _FRAMES.append(dict.fromkeys(USAGE_FIELDS, 0))


def _leave_frame(delta: dict[str, int]) -> dict[str, int]:
    children = _FRAMES.pop()
    own = {key: delta.get(key, 0) - children[key] for key in USAGE_FIELDS}
    if _FRAMES:
        for key in USAGE_FIELDS:
            _FRAMES[-1][key] += delta.get(key, 0)
    return own


def install_meter() -> TokenMeter:
    """Count usage without touching the switcher's source.

    ``csrt_codeswitch`` builds its own clients inside ``Translator``,
    ``MachineReviewValidator`` and ``CodeSwitcher``, with no injection point and
    no usage recorded. Each of them imports ``OpenAI`` from the module at call
    time, so replacing the module attribute here catches every client any of
    them creates, and the counting is a thin wrapper around the real one.
    """
    global METER
    meter = TokenMeter()
    METER = meter
    try:
        import openai
    except ImportError:
        return meter

    real = openai.OpenAI

    def counting(*args, **kwargs):
        client = real(*args, **kwargs)
        try:
            original = client.responses.create
        except AttributeError:
            return client

        def create(*call_args, **call_kwargs):
            response = original(*call_args, **call_kwargs)
            meter.record(getattr(response, "usage", None))
            return response

        try:
            client.responses.create = create
        except Exception:  # noqa: BLE001 - SDK may forbid assignment; count nothing
            pass
        return client

    openai.OpenAI = counting
    return meter


# ---------------------------------------------------------------------------
# logging
# ---------------------------------------------------------------------------


log = logging.getLogger("csrt_codeswitch.pipeline")


class StageRecorder(logging.Handler):
    """Keep the structured half of every pipeline log line.

    The console gets readable text; this keeps the machine-readable fields the
    pipeline attaches under ``extra={"csrt": ...}``, so a run can be checked
    afterwards by counting stages rather than by re-reading the console.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[dict] = []
        self.context: dict = {}

    def emit(self, record: logging.LogRecord) -> None:
        fields = getattr(record, "csrt", None)
        if isinstance(fields, dict):
            self.records.append({**self.context, **fields, "level": record.levelname})

    def take(self) -> list[dict]:
        taken, self.records = self.records, []
        return taken


def instrument_pipeline() -> None:
    """Log every pipeline stage from outside csrt_codeswitch.

    The stages worth seeing live inside that package, but it is not ours to
    edit, so each method is wrapped on its class here instead. Same visibility,
    nothing changed in the module: remove this call and the package behaves
    exactly as before.

    Excerpts are never logged at INFO. A reviewer's summary can quote the
    source and these are attack prompts, so INFO carries stage names, verdicts,
    categories and timings only.
    """
    from csrt_codeswitch import reviewer as reviewer_module
    from csrt_codeswitch import switcher as switcher_module
    from csrt_codeswitch import translator as translator_module
    from csrt_codeswitch import validation as validation_module

    if getattr(translator_module.Translator, "_csrt_instrumented", False):
        return

    def describe_review(result) -> dict:
        severities = [issue.severity for issue in result.issues]
        return {
            "passed": result.passed,
            "issues": len(result.issues),
            "blocking_issues": sum(s in {"major", "critical"} for s in severities),
            "categories": sorted({issue.category for issue in result.issues}),
            "worst_severity": ("critical" if "critical" in severities
                               else "major" if "major" in severities
                               else "minor" if severities else "none"),
            "target": getattr(result, "target_language", ""),
        }

    def wrap(owner, name, stage, describe):
        original = getattr(owner, name)

        def wrapped(self, *args, **kwargs):
            mark = time.monotonic()
            before = METER.snapshot() if METER is not None else None
            if before is not None:
                _enter_frame()
            spent = {}

            def usage():
                # Charged even when the stage raises: a failed call is billed
                # exactly like a successful one, and a cost report that only
                # counts successes understates the expensive half of the run.
                if before is None:
                    return {}
                own = _leave_frame(METER.since(before))
                charge(stage, own)
                return own

            try:
                result = original(self, *args, **kwargs)
            except Exception as exc:
                spent = usage()
                log.error("%s FAILED: %s: %s", stage, type(exc).__name__, exc,
                          extra={"csrt": {"stage": stage, "passed": False,
                                          "error": type(exc).__name__,
                                          **spent,
                                          "seconds": round(time.monotonic() - mark, 2)}})
                raise
            spent = usage()
            fields = {"stage": stage, "seconds": round(time.monotonic() - mark, 2),
                      **spent}
            fields.update(describe(result))
            if fields.get("passed", True):
                log.info("%s ok (%.1fs)%s", stage, fields["seconds"],
                         _suffix(fields), extra={"csrt": fields})
            else:
                log.error("%s FAILED (%.1fs)%s", stage, fields["seconds"],
                          _suffix(fields), extra={"csrt": fields})
                for issue in getattr(result, "issues", ()):
                    if issue.severity in {"major", "critical"}:
                        log.error("    [%s] %s: %s", issue.severity, issue.category,
                                  " ".join(str(issue.description).split())[:200])
                for problem in getattr(result, "problems", ())[:6]:
                    log.error("    %s", problem)
                log.debug("    summary: %s", getattr(result, "summary", ""))
            return result

        setattr(owner, name, wrapped)

    wrap(translator_module.Translator, "translate", "translate",
         lambda r: {"language": r.target_language, "chars": len(r.translated_text),
                    "backend": r.backend})
    if hasattr(translator_module.Translator, "translate_many"):
        # Charged separately from `translate` so the cost report can show what
        # batching back-translation actually bought.
        wrap(translator_module.Translator, "translate_many", "translate_batch",
             lambda r: {"language": r.target_language,
                        "fragments": len(r.translated_texts),
                        "backend": r.backend})
    wrap(reviewer_module.MachineReviewValidator, "review", "translation_review",
         describe_review)
    wrap(reviewer_module.MachineReviewValidator, "review_code_switched",
         "code_switch_review", describe_review)
    wrap(validation_module.BackTranslationValidator, "validate", "back_translation",
         lambda r: {"passed": r.passed, "similarity": r.similarity,
                    "threshold": r.threshold, "problems": list(r.problems)})
    wrap(switcher_module.CodeSwitcher, "_mix", "mix",
         lambda r: {"passed": r.ok, "attempts": r.attempts,
                    "segments": len(r.segments), "problems": list(r.problems)})

    translator_module.Translator._csrt_instrumented = True


def _suffix(fields: dict) -> str:
    bits = []
    if fields.get("language"):
        bits.append(str(fields["language"]))
    if fields.get("target"):
        bits.append(str(fields["target"]))
    if fields.get("similarity") is not None:
        bits.append(f"similarity {fields['similarity']:.3f}")
    if fields.get("attempts"):
        bits.append(f"{fields['attempts']} attempt(s)")
    if fields.get("categories"):
        bits.append(", ".join(fields["categories"]))
    return "  " + " | ".join(bits) if bits else ""


def configure_logging(level: str, log_file: str | None) -> StageRecorder:
    """Send pipeline stages to the terminal as they happen."""
    root = logging.getLogger("csrt_codeswitch")
    root.setLevel(logging.DEBUG)
    for existing in list(root.handlers):
        root.removeHandler(existing)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(getattr(logging, level.upper(), logging.INFO))
    console.setFormatter(logging.Formatter("      %(levelname)-5s %(message)s"))
    root.addHandler(console)

    if log_file:
        handle = logging.FileHandler(log_file, encoding="utf-8")
        handle.setLevel(logging.DEBUG)
        handle.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s %(message)s")
        )
        root.addHandler(handle)

    recorder = StageRecorder()
    root.addHandler(recorder)
    return recorder


def switch_with_retries(switcher, source: str, args, factory):
    """Run the pipeline once, then optionally once more at a coarser unit.

    Review resampling lives inside the pipeline now, driven by
    ``review_attempts``. What stays here is the last-ditch option: if the
    mixture keeps drifting, retry at a coarser switching unit, because most
    meaning drift comes from the mixer fusing or resplitting clauses and whole
    sentences leave it less room.
    """
    attempts = max(0, args.retries) + 1

    def attempt(active):
        try:
            result = active.switch(source, review_attempts=attempts)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad turn must not end the run
            return None, summarise_failure(exc)
        return result, [str(p) for p in getattr(result, "problems", ())]

    result, problems = attempt(switcher)
    if result is not None and getattr(result, "ok", False):
        return True, str(getattr(result, "text", "") or ""), _attempts_of(result), []

    if args.retry_granularity and args.retry_granularity != args.granularity:
        log.info("retrying at %s granularity", args.retry_granularity,
                 extra={"csrt": {"stage": "retry",
                                 "granularity": args.retry_granularity}})
        relaxed = argparse.Namespace(**vars(args))
        relaxed.granularity = args.retry_granularity
        result, problems = attempt(factory(relaxed))
        if result is not None and getattr(result, "ok", False):
            return True, str(getattr(result, "text", "") or ""), _attempts_of(result), []

    text = str(getattr(result, "text", "") or "") if result is not None else ""
    return False, text, _attempts_of(result), problems


def _attempts_of(result) -> str:
    if result is None:
        return ""
    return getattr(getattr(result, "generation", None), "attempts", "") or getattr(
        result, "attempts", ""
    )


def summarise_failure(exc: Exception) -> list[str]:
    """Turn a pipeline exception into short, sortable reasons.

    ``MachineReviewFailed`` carries a full review: a summary paragraph, an issue
    list, and often a complete corrected translation. Putting all of that in one
    CSV cell makes the column unreadable in a spreadsheet and impossible to
    count. This keeps the stage, the blocking issues and a trimmed summary; the
    whole thing is still in the log file and the stage sidecar.
    """
    review = getattr(exc, "review", None)
    if review is None:
        return [f"{type(exc).__name__}: {exc}"]

    target = str(getattr(review, "target_language", ""))
    stage = "code_switch_review" if " + " in target else "translation_review"
    reasons = [f"stage={stage}", f"language={target}"]
    for issue in getattr(review, "issues", ()):
        if issue.severity in {"major", "critical"}:
            reasons.append(
                f"[{issue.severity}] {issue.category}: "
                f"{' '.join(str(issue.description).split())[:160]}"
            )
    if len(reasons) == 2:  # nothing blocking, so the model's own verdict failed it
        reasons.append("[unspecified] review returned passed=false with no blocking issue")
    summary = " ".join(str(getattr(review, "summary", "")).split())
    if summary:
        reasons.append(f"summary: {summary[:200]}")
    return reasons


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_pairs(values, label):
    """``--dominance English=3 Korean=1`` into a dict."""
    out = {}
    for item in values or []:
        if "=" not in item:
            raise SystemExit(f"{label} entries must look like Name=value, got {item!r}")
        key, _, raw = item.partition("=")
        out[key.strip()] = raw.strip()
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--scenario", required=True,
                        help="FinVault scenario id, e.g. 00 or 13")
    parser.add_argument("--dataset", default="attack_datasets_synthesis",
                        choices=("attack_datasets_synthesis", "attack_datasets",
                                 "normal_datasets"),
                        help="default is the synthesised attack set, which carries follow-ups")
    parser.add_argument("--families", nargs="+",
                        help="synthesis families to include; default is all of them")
    parser.add_argument("--limit", type=int,
                        help="stop after this many CASES (a multi-turn case still "
                             "contributes all of its turns)")
    parser.add_argument("--limit-order", default="spread",
                        choices=("spread", "sequential"),
                        help="with --limit, 'spread' samples across families and "
                             "properties so a small slice still spans the design")
    parser.add_argument("--limit-turns", type=int,
                        help="stop after this many generated turns, whichever comes first")
    parser.add_argument("--first-turn-only", action="store_true",
                        help="ignore follow-ups and keep only the opening prompt")

    condition = parser.add_argument_group("code-switching condition")
    condition.add_argument("--languages", nargs="+", default=["English", "Korean"],
                           help="languages to mix; one alone means a monolingual rewrite")
    condition.add_argument("--granularity", nargs="+", default=["clause"],
                           help="sentence, clause, phrase, word, tag or semantic_role. "
                                "Name several to sweep them: each gets its own run and "
                                "its own CSV, and the summary compares them")
    condition.add_argument("--matrix", help="the frame language; defaults to the first")
    condition.add_argument("--order", nargs="+",
                           help="which language the reader meets first")
    condition.add_argument("--dominance", nargs="+", metavar="LANG=WEIGHT",
                           help="relative share, e.g. English=3 Korean=1 for 75/25")
    condition.add_argument("--roles", nargs="+", metavar="ROLE=LANG",
                           help="semantic-role allocation, e.g. negation=Yoruba")
    condition.add_argument("--tags", nargs="+",
                           help="tag categories, for --granularity tag")
    condition.add_argument("--switch-rate", type=float,
                           help="density of switching, 0 to 1")
    condition.add_argument("--min-hits", type=int, default=2,
                           help="tokens a language needs before it counts as present")
    condition.add_argument("--max-dominance", type=float, default=0.7,
                           help="ceiling above which a mixture is really monolingual")
    condition.add_argument("--attempts", type=int, default=3,
                           help="mixing retries INSIDE one pipeline run, each given "
                                "the previous structural rejection")
    condition.add_argument("--retries", type=int, default=1,
                           help="how many times a machine-review rejection is "
                                "resampled inside the pipeline before it stands. The "
                                "reviewer is a model, so one rejection is a sample, "
                                "not a measurement. 0 accepts the first verdict")
    condition.add_argument("--retry-granularity",
                           help="use this coarser granularity on the final retry, e.g. "
                                "'sentence'. Whole sentences are harder for the mixer "
                                "to fuse, which is what most meaning-drift comes from")
    condition.add_argument("--model", help="mixing model name, passed to the switcher")

    parser.add_argument("--out", help="CSV path; default names itself from the condition")
    parser.add_argument("--resume", action="store_true",
                        help="skip turns already present in the output file")
    parser.add_argument("--input-price", type=float, default=5.0,
                        help="USD per 1M input tokens, for the cost report only "
                             "(gpt-5.6-sol 5.0, terra 2.5, luna 1.0)")
    parser.add_argument("--output-price", type=float, default=30.0,
                        help="USD per 1M output tokens, for the cost report only "
                             "(gpt-5.6-sol 30.0, terra 15.0, luna 6.0). Reasoning "
                             "tokens bill at this rate")
    parser.add_argument("--dry", action="store_true",
                        help="call no model: list the turns and print the instruction")

    logs = parser.add_argument_group("logging")
    logs.add_argument("--log-level", default="INFO",
                      choices=("DEBUG", "INFO", "WARNING", "ERROR"),
                      help="console verbosity. INFO shows every pipeline stage; "
                           "WARNING shows only failures; DEBUG adds review summaries")
    logs.add_argument("--log-file",
                      help="also write full DEBUG logs here, including review summaries")
    logs.add_argument("--no-stage-log", action="store_true",
                      help="skip the per-stage JSONL sidecar written next to the CSV")
    return parser


def default_output(args) -> Path:
    tag = "-".join(name[:2].upper() for name in args.languages)
    return ROOT / "runs" / f"codeswitch-scn{args.scenario}-{tag}-{args.granularity}.csv"


def load_rows(args):
    from csrt_mas.corpus import build_corpus
    from csrt_mas.finvault_dynamic.catalog import FinVaultCatalog

    catalog = FinVaultCatalog(ROOT / "vendor" / "FinVault", ROOT / "scenarios" / "finvault")
    families = None
    if args.dataset == "attack_datasets_synthesis":
        families = list(args.families) if args.families else list(catalog.synthesis_families)
    elif args.families:
        raise SystemExit("--families only applies to attack_datasets_synthesis")

    rows = build_corpus(
        catalog,
        dataset=args.dataset,
        scenarios=[args.scenario],
        families=families,
        include_normal_controls=False,
        preserve_multi_turn=not args.first_turn_only,
    )
    if args.limit:
        rows = _limited(rows, args.limit, args.limit_order)
    return rows, families


def _limited(rows, limit: int, mode: str):
    """Cut the corpus down without cutting the design down.

    Rows are ordered by identifier, so families sit together and taking the
    first N gives N variants of one attack family. That is a bad look at the
    data: a limit of 4 should show four different things, not the same thing
    four times. The default deals cards round-robin across (family, property),
    so a small limit still spans the design. Pass ``--limit-order sequential``
    when reproducing an earlier slice exactly.
    """
    if mode == "sequential":
        return rows[:limit]
    from collections import defaultdict

    groups: dict[tuple[str, str], list] = defaultdict(list)
    for row in rows:
        groups[(row.family or "", row.property_id)].append(row)

    families = sorted({family for family, _ in groups})
    properties = sorted({prop for _, prop in groups})
    family_index = {name: i for i, name in enumerate(families)}
    property_index = {name: i for i, name in enumerate(properties)}

    # Walk the family-by-property grid diagonally rather than row by row, so
    # the first four picks differ in BOTH family and property instead of being
    # four properties of one family.
    def diagonal(key):
        family, prop = key
        f, p = family_index[family], property_index[prop]
        return ((p - f) % max(len(properties), 1), f, p)

    keys = sorted(groups, key=diagonal)
    picked = []
    depth = 0
    while len(picked) < limit and any(len(groups[key]) > depth for key in keys):
        for key in keys:
            if len(picked) >= limit:
                break
            if len(groups[key]) > depth:
                picked.append(groups[key][depth])
        depth += 1
    picked.sort(key=lambda item: item.semantic_id)
    return picked


def build_switcher(args):
    from csrt_codeswitch import CodeSwitcher

    settings = {
        "languages": list(args.languages),
        "granularity": args.granularity,
        "min_hits": args.min_hits,
        "max_dominance": args.max_dominance,
        "attempts": args.attempts,
        "label": "CS-" + "-".join(n[:2].upper() for n in args.languages),
    }
    if args.matrix:
        settings["matrix"] = args.matrix
    if args.order:
        settings["order"] = list(args.order)
    if args.dominance:
        settings["dominance"] = {
            key: float(value) for key, value in parse_pairs(args.dominance, "--dominance").items()
        }
    if args.roles:
        settings["roles"] = parse_pairs(args.roles, "--roles")
    if args.tags:
        settings["tags"] = list(args.tags)
    if args.switch_rate is not None:
        settings["switch_rate"] = args.switch_rate
    if args.model:
        settings["model"] = args.model
    return CodeSwitcher(**settings)


def index_path(output: Path) -> Path:
    """Sidecar holding one record per row written to the CSV.

    The CSV itself is now two columns, so it can no longer say which turn a row
    came from — and ``--resume`` needs exactly that. The index carries the
    provenance the columns used to, one JSON object per CSV row, in the same
    order, so row *n* of the CSV is row *n* of the index.
    """
    return output.with_suffix(".index.jsonl")


def already_done(output: Path) -> set[tuple[str, str, str]]:
    """Turns already generated, keyed so the key is actually unique.

    Case identifiers repeat across synthesis families: every family contains an
    ``ATTACK_V1_001_...``. Keying on (case_id, turn_index) alone collides, so a
    resumed run would skip a turn it had never generated.
    """
    path = index_path(output)
    if not path.exists():
        return set()
    done = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        done.add((record.get("family", ""), record["case_id"],
                  str(record["turn_index"])))
    return done


def main(argv=None) -> int:
    """Run the condition once per granularity named, then compare them.

    Granularity is the setting most likely to decide whether a turn survives
    the pipeline at all — word-level mixing of two languages with opposite
    word order fails structurally where clause-level mixing does not — so the
    useful unit of work is a sweep, not a single run.
    """
    args = build_parser().parse_args(argv)
    levels = list(args.granularity)
    if len(levels) > 1 and args.out:
        raise SystemExit(
            "--out names a single file; drop it when sweeping several "
            "granularities, and each run will name its own"
        )

    results = []
    for position, level in enumerate(levels, 1):
        if len(levels) > 1:
            print(f"\n{'=' * 64}")
            print(f"granularity {position} of {len(levels)}: {level}")
            print("=" * 64)
        single = argparse.Namespace(**vars(args))
        single.granularity = level
        results.append(run_one(single))

    if len(results) > 1:
        print(f"\n{'=' * 64}")
        print(f"{'granularity':16} {'ok':>5} {'rej':>5} {'pass rate':>10}  file")
        for summary in results:
            attempted = summary["generated"] + summary["rejected"]
            rate = f"{summary['generated'] / attempted:.0%}" if attempted else "-"
            print(f"{summary['granularity']:16} {summary['generated']:5} "
                  f"{summary['rejected']:5} {rate:>10}  {summary['output'].name}")

    # A non-zero exit means no granularity produced anything at all. One empty
    # level in a sweep is a finding, not a failure of the run.
    return 1 if results and all(
        r["rejected"] and not r["generated"] for r in results
    ) else 0


def run_one(args) -> dict:
    STAGE_TOKENS.clear()
    output = Path(args.out) if args.out else default_output(args)
    output.parent.mkdir(parents=True, exist_ok=True)

    rows, families = load_rows(args)
    turns_total = sum(len(row.turns) for row in rows)
    multi = sum(1 for row in rows if len(row.turns) > 1)

    print(f"scenario     : {args.scenario}")
    print(f"dataset      : {args.dataset}")
    if families:
        print(f"families     : {len(families)}  {families}")
    print(f"cases        : {len(rows)}  ({multi} multi-turn)")
    print(f"turns        : {turns_total}")
    print(f"languages    : {', '.join(args.languages)}")
    print(f"granularity  : {args.granularity}")
    print(f"output       : {output}")

    recorder = configure_logging(args.log_level, args.log_file)
    instrument_pipeline()
    meter = install_meter()
    switcher = build_switcher(args)
    print(f"condition    : {switcher.describe()}")

    if args.dry:
        print("\n[--dry] no model will be called. The instruction it would send:\n")
        sample = rows[0].turns[0] if rows else ""
        print("\n".join("   " + line for line in switcher.instruction(sample).splitlines()))
        print(f"\n[--dry] would generate {turns_total} turn(s) across {len(rows)} case(s).")
        return {"granularity": args.granularity, "generated": 0, "rejected": 0,
                "output": output}

    done = already_done(output) if args.resume else set()
    if done:
        print(f"resume       : {len(done)} turn(s) already complete, skipping them")

    stage_log = None
    if not args.no_stage_log:
        stage_path = output.with_suffix(".stages.jsonl")
        stage_log = stage_path.open("a" if args.resume else "w", encoding="utf-8")
        print(f"stage log    : {stage_path}")

    fresh = not output.exists() or not args.resume
    handle = output.open("w" if fresh else "a", encoding="utf-8", newline="")
    writer = csv.DictWriter(handle, fieldnames=FIELDS)
    if fresh:
        writer.writeheader()
    index_log = index_path(output).open("w" if fresh else "a", encoding="utf-8")
    print(f"index        : {index_path(output)}")

    generated = rejected = skipped = 0
    produced = 0
    print()
    try:
        for row in rows:
            for index, english in enumerate(row.turns):
                if (row.family or "", row.case_id, str(index)) in done:
                    skipped += 1
                    continue
                if args.limit_turns is not None and produced >= args.limit_turns:
                    break

                recorder.context = {
                    "family": row.family or "", "case_id": row.case_id,
                    "turn_index": index,
                }
                print(f"\n> {row.family or '-'} / {row.case_id} turn {index} "
                      f"({len(english)} chars)", flush=True)
                before = meter.snapshot()
                ok, text, attempts, problems = switch_with_retries(
                    switcher, english, args, build_switcher
                )

                produced += 1
                spent = meter.since(before)
                if stage_log is not None:
                    for entry in recorder.take():
                        stage_log.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    stage_log.flush()
                else:
                    recorder.take()
                detected = switcher.profile(text) if text else {}

                # Only a turn that survived the pipeline earns a row. A
                # rejection is not written as an empty pair: it is reported on
                # the terminal, its stages are in the sidecar, and it is
                # counted in the summary, so nothing disappears — but the file
                # handed to the next step contains only usable pairs.
                if ok:
                    writer.writerow({"english": english, "code_switched": text})
                    handle.flush()
                    index_log.write(json.dumps({
                        "scenario_id": row.scenario_id,
                        "dataset": row.dataset,
                        "family": row.family or "",
                        "case_id": row.case_id,
                        "property_id": row.property_id,
                        "turn_index": index,
                        "turn_count": len(row.turns),
                        "is_follow_up": bool(index),
                        "attempts": attempts,
                        "languages_detected": {
                            name: count for name, count in detected.items() if count
                        },
                        **spent,
                        "english_sha256": sha256(english),
                        "code_switched_sha256": sha256(text),
                    }, ensure_ascii=False) + "\n")
                    index_log.flush()
                    generated += 1
                else:
                    rejected += 1
                # Identifiers and counts only; the prompts themselves stay in the file.
                status = "ok " if ok else "REJ"
                cost = (f"{spent['api_calls']} calls, "
                        f"{spent['input_tokens'] + spent['output_tokens']} tok"
                        if spent["api_calls"] else "no usage reported")
                print(f"  {status} {row.case_id[:30]:32} turn {index}  "
                      f"[{generated} ok / {rejected} rej]  {cost}", flush=True)
                if not ok:
                    # The reason no longer has a column to live in, so it has
                    # to be said here, where you are already looking.
                    for problem in problems:
                        print(f"      why: {problem}", flush=True)
            else:
                continue
            break
    except KeyboardInterrupt:
        print("\ninterrupted; rows written so far are complete and usable")
    finally:
        handle.close()
        index_log.close()
        if stage_log is not None:
            stage_log.close()

    print(f"\ngenerated : {generated}")
    print(f"rejected  : {rejected}")
    if meter.calls:
        print(f"\nAPI calls : {meter.calls}")
        print(f"  input   : {meter.input:,} tokens" +
              (f" ({meter.cached:,} cached)" if meter.cached else ""))
        print(f"  output  : {meter.output:,} tokens" +
              (f" ({meter.reasoning:,} reasoning)" if meter.reasoning else ""))
        print(f"  total   : {meter.total:,} tokens")
        if produced:
            print(f"  per turn: {meter.calls / produced:.1f} calls, "
                  f"{meter.total / produced:,.0f} tokens")
    else:
        print("\nAPI calls : none recorded "
              "(the client reported no usage, or nothing was generated)")
    if STAGE_TOKENS:
        # Where the money actually went. The whole-run totals above include
        # rejected turns; so does this, which is the point — a rejected turn
        # pays for every attempt it made.
        print(f"\n{'stage':20} {'calls':>6} {'input':>10} {'output':>10} "
              f"{'reasoning':>10} {'$':>8}  share")
        rows = sorted(STAGE_TOKENS.items(),
                      key=lambda kv: -_cost(kv[1], args))
        whole = sum(_cost(spent, args) for _, spent in rows) or 1.0
        for stage, spent in rows:
            money = _cost(spent, args)
            print(f"{stage:20} {spent['api_calls']:6} {spent['input_tokens']:10,} "
                  f"{spent['output_tokens']:10,} {spent['reasoning_tokens']:10,} "
                  f"{money:8.3f}  {money / whole:.0%}")
        usage_path = output.with_suffix(".usage.json")
        usage_path.write_text(json.dumps({
            "scenario": args.scenario,
            "granularity": args.granularity,
            "languages": list(args.languages),
            "turns_attempted": produced,
            "generated": generated,
            "rejected": rejected,
            "input_price_per_1m": args.input_price,
            "output_price_per_1m": args.output_price,
            "estimated_cost": round(whole, 4),
            "totals": meter.snapshot(),
            "by_stage": STAGE_TOKENS,
        }, indent=2), encoding="utf-8")
        print(f"\ncost note : prices are --input-price {args.input_price} / "
              f"--output-price {args.output_price} per 1M, one tier for every\n"
              "            call, so a run that mixes tiers is approximate. "
              "Counts are exact.")
        print(f"usage     : {usage_path}")

    if skipped:
        print(f"skipped   : {skipped} (already present)")
    print(f"written   : {output}")
    if rejected:
        print(f"\n{rejected} turn(s) were rejected and are NOT in the CSV. Their reasons\n"
              "were printed above and their stages are in the .stages.jsonl sidecar.\n"
              "Read those before changing --min-hits or --max-dominance: a condition\n"
              "that only validates because the check was weakened is not a condition.")
    return {"granularity": args.granularity, "generated": generated,
            "rejected": rejected, "output": output}


if __name__ == "__main__":
    raise SystemExit(main())
