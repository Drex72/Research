from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_ENV = "CSRT_EXPERIMENT_PATH"


class ConfigurationError(ValueError):
    pass


SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigurationError(f"{name} must be an object")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{name} must be a non-empty string")
    return value


def _identifier(value: Any, name: str) -> str:
    result = _string(value, name)
    if not SAFE_IDENTIFIER.fullmatch(result) or ".." in result:
        raise ConfigurationError(f"{name} must be a filename-safe identifier")
    return result


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigurationError(f"{name} must be a boolean")
    return value


def _number(
    value: Any,
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigurationError(f"{name} must be numeric")
    result = float(value)
    if minimum is not None and result < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise ConfigurationError(f"{name} must be at most {maximum}")
    return result


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ConfigurationError(f"{name} must be an integer of at least {minimum}")
    return value


def _strings(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ConfigurationError(f"{name} must be a non-empty string array")
    if len(set(value)) != len(value):
        raise ConfigurationError(f"{name} contains duplicates")
    return tuple(value)


def _identifiers(value: Any, name: str) -> tuple[str, ...]:
    return tuple(_identifier(item, f"{name} item") for item in _strings(value, name))


def _project_path(root: Path, value: Any, name: str) -> Path:
    relative = Path(_string(value, name))
    if relative.is_absolute():
        raise ConfigurationError(f"{name} must be relative to the project root")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ConfigurationError(f"{name} escapes the project root") from exc
    return resolved


def _local_runtime_url(value: Any, name: str) -> str:
    result = _string(value, name).rstrip("/")
    parsed = urlparse(result)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ConfigurationError(f"{name} must be a local HTTP Ollama endpoint")
    try:
        if parsed.port is None:
            raise ConfigurationError(f"{name} must include an explicit port")
    except ValueError as exc:
        raise ConfigurationError(f"{name} contains an invalid port") from exc
    return result


def _relative_resource_path(root: Path, parent: Path, value: Any, name: str) -> Path:
    relative = Path(_string(value, name))
    if relative.is_absolute():
        raise ConfigurationError(f"{name} must be relative")
    resolved = (parent / relative).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ConfigurationError(f"{name} escapes the project root") from exc
    return resolved


def active_experiment_path(root: Path = ROOT) -> Path:
    configured = os.environ.get(EXPERIMENT_ENV)
    if not configured:
        return root / "experiment.json"
    path = Path(configured)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


@dataclass(frozen=True)
class DecodeSettings:
    temperature: float
    seed: int
    num_ctx: int
    num_predict: int
    think: bool


@dataclass(frozen=True)
class ExperimentMetadata:
    title: str
    aim: str
    research_question: str
    hypothesis: str
    domain: str
    risk_outcomes: tuple[str, ...]
    tags: tuple[str, ...]
    parent_experiment: str | None


@dataclass(frozen=True)
class ModelProfile:
    path: Path
    profile_id: str
    provider: str
    model: str
    digest: str


@dataclass(frozen=True)
class AgentSettings:
    role: str
    profile: ModelProfile
    prompt_key: str
    tools: tuple[str, ...]

    @property
    def provider(self) -> str:
        return self.profile.provider

    @property
    def model(self) -> str:
        return self.profile.model

    @property
    def digest(self) -> str:
        return self.profile.digest


@dataclass(frozen=True)
class ScenarioSettings:
    path: Path
    scenario_id: str
    adapter: str
    upstream_root: Path
    upstream_commit: str
    instance_id: str
    stimuli_path: Path
    qualification_path: Path
    outcome_rules_path: Path
    expected_semantic_rows: int
    expected_pairs: int
    expected_qualification_rows: int
    executor_tools: tuple[str, ...]


@dataclass(frozen=True)
class PromptSet:
    path: Path
    prompt_set_id: str
    prompts: dict[str, str]
    prompt_paths: dict[str, Path]
    executor_system_override: str | None
    override_path: Path | None

    def get(self, key: str) -> str:
        try:
            return self.prompts[key]
        except KeyError as exc:
            raise ConfigurationError(f"prompt set does not define: {key}") from exc

    @property
    def case_officer_system(self) -> str:
        return self.get("case_officer_system")

    @property
    def executor_system_suffix(self) -> str:
        return self.get("executor_system_suffix")

    @property
    def author_system(self) -> str:
        return self.get("author_system")

    @property
    def executor_continuation(self) -> str:
        return self.get("executor_continuation")

    @property
    def files(self) -> tuple[Path, ...]:
        values = {self.path, *self.prompt_paths.values()}
        if self.override_path is not None:
            values.add(self.override_path)
        return tuple(sorted(values))


@dataclass(frozen=True)
class PipelineDefinition:
    path: Path
    name: str
    use_case_officer: bool
    include_original: bool
    handoff: str


@dataclass(frozen=True)
class PipelineSet:
    pipelines: dict[str, PipelineDefinition]

    @property
    def pipeline_set_id(self) -> str:
        return "+".join(self.pipelines)

    @property
    def files(self) -> tuple[Path, ...]:
        return tuple(item.path for item in self.pipelines.values())


@dataclass(frozen=True)
class ExperimentConfig:
    path: Path
    root: Path
    raw: dict[str, Any]
    frozen: bool
    package_id: str | None
    experiment_id: str
    metadata: ExperimentMetadata
    status: str
    scenario: ScenarioSettings
    agents: dict[str, AgentSettings]
    runtime_base_url: str
    runtime_version: str
    runtime_timeout_seconds: int
    decode: DecodeSettings
    prompt_path: Path
    pipeline_refs: tuple[str, ...]
    pipeline_ids: tuple[str, ...]
    surfaces: tuple[str, ...]
    frames: tuple[str, ...]
    policy_properties: tuple[str, ...]
    max_executor_steps: int
    qualification_repeats_per_cell: int
    default_shards: int
    baseline_surface: str
    target_monolingual_surface: str
    code_switch_surface: str
    single_topology: str
    handoff_topology: str
    trust_break_topology: str
    bootstrap_seed: int
    bootstrap_iterations: int
    minimum_practical_effect: float
    maximum_technical_failure_rate: float
    minimum_utility_overall: float
    minimum_utility_each_surface: float
    maximum_code_switch_utility_gap: float
    protocol_path: Path

    @property
    def scenario_adapter(self) -> str:
        return self.scenario.adapter

    @property
    def finvault_root(self) -> Path:
        return self.scenario.upstream_root

    @property
    def finvault_commit(self) -> str:
        return self.scenario.upstream_commit

    @property
    def scenario_id(self) -> str:
        return self.scenario.instance_id

    @property
    def stimuli_path(self) -> Path:
        return self.scenario.stimuli_path

    @property
    def qualification_stimuli_path(self) -> Path:
        return self.scenario.qualification_path

    @property
    def outcome_rules_path(self) -> Path:
        return self.scenario.outcome_rules_path

    @property
    def expected_semantic_rows(self) -> int:
        return self.scenario.expected_semantic_rows

    @property
    def expected_pairs(self) -> int:
        return self.scenario.expected_pairs

    @property
    def qualification_rows(self) -> int:
        return self.scenario.expected_qualification_rows

    @property
    def topologies(self) -> tuple[str, ...]:
        return self.pipeline_ids

    @property
    def qualification_repeats(self) -> int:
        return self.qualification_repeats_per_cell * len(self.surfaces) * len(self.topologies)

    @property
    def output_dir(self) -> Path:
        return self.root / "runs" / self.experiment_id

    @property
    def package_dir(self) -> Path:
        return self.output_dir / "package"

    @property
    def manifest_path(self) -> Path:
        return self.output_dir / "frozen-manifest.json"

    @property
    def gate_plan_path(self) -> Path:
        return self.output_dir / "plans" / "gate.jsonl"

    @property
    def pilot_plan_path(self) -> Path:
        return self.output_dir / "plans" / "pilot.jsonl"

    @property
    def raw_trace_path(self) -> Path:
        return self.output_dir / "traces" / "collected.jsonl"

    @property
    def lock_dir(self) -> Path:
        return self.output_dir

    def agent(self, role: str) -> AgentSettings:
        try:
            return self.agents[role]
        except KeyError as exc:
            raise ConfigurationError(f"missing agent role: {role}") from exc


def _load_json(path: Path, name: str) -> dict[str, Any]:
    if not path.exists():
        raise ConfigurationError(f"{name} does not exist: {path}")
    try:
        return _mapping(json.loads(path.read_text(encoding="utf-8")), name)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"{name} is not valid JSON: {path}") from exc


def _scenario_path(root: Path, reference: str) -> Path:
    if "/" in reference or reference.endswith(".json"):
        return _project_path(root, reference, "scenario")
    return _project_path(root, f"scenarios/{reference}/scenario.json", "scenario")


def _pipeline_path(root: Path, reference: str) -> Path:
    if "/" in reference or reference.endswith(".json"):
        return _project_path(root, reference, f"pipeline {reference}")
    return _project_path(root, f"pipelines/{reference}.json", f"pipeline {reference}")


def _load_scenario(root: Path, reference: str) -> ScenarioSettings:
    path = _scenario_path(root, reference)
    raw = _load_json(path, "scenario")
    if raw.get("schema_version") != 1:
        raise ConfigurationError("unsupported scenario schema_version")
    upstream = _mapping(raw.get("upstream"), "scenario.upstream")
    data = _mapping(raw.get("data"), "scenario.data")
    return ScenarioSettings(
        path=path,
        scenario_id=_identifier(raw.get("scenario_id"), "scenario.scenario_id"),
        adapter=_string(raw.get("adapter"), "scenario.adapter"),
        upstream_root=_project_path(root, upstream.get("root"), "scenario.upstream.root"),
        upstream_commit=_string(upstream.get("commit"), "scenario.upstream.commit"),
        instance_id=_string(upstream.get("instance_id"), "scenario.upstream.instance_id"),
        stimuli_path=_project_path(root, data.get("cases"), "scenario.data.cases"),
        qualification_path=_project_path(root, data.get("qualification_cases"), "scenario.data.qualification_cases"),
        outcome_rules_path=_project_path(root, data.get("outcome_rules"), "scenario.data.outcome_rules"),
        expected_semantic_rows=_integer(data.get("expected_semantic_rows"), "scenario.data.expected_semantic_rows", minimum=1),
        expected_pairs=_integer(data.get("expected_pairs"), "scenario.data.expected_pairs", minimum=1),
        expected_qualification_rows=_integer(data.get("expected_qualification_rows"), "scenario.data.expected_qualification_rows", minimum=1),
        executor_tools=_strings(raw.get("executor_tools"), "scenario.executor_tools"),
    )


def _load_model_profile(root: Path, value: Any, name: str) -> ModelProfile:
    path = _project_path(root, value, name)
    raw = _load_json(path, name)
    if raw.get("schema_version") != 1:
        raise ConfigurationError(f"unsupported model profile schema_version: {path}")
    digest = _string(raw.get("digest"), f"{name}.digest")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest.lower()):
        raise ConfigurationError(f"{name}.digest must be a 64-character hexadecimal digest")
    return ModelProfile(
        path=path,
        profile_id=_identifier(raw.get("profile_id"), f"{name}.profile_id"),
        provider=_string(raw.get("provider"), f"{name}.provider"),
        model=_string(raw.get("model"), f"{name}.model"),
        digest=digest,
    )


def load_experiment(path: Path | None = None, *, project_root: Path | None = None) -> ExperimentConfig:
    explicit_path = path is not None
    if path is None:
        path = active_experiment_path()
    path = path.resolve()
    root = (project_root or (path.parent if explicit_path else ROOT)).resolve()
    raw = _load_json(path, "experiment")
    if raw.get("schema_version") != 2:
        raise ConfigurationError("unsupported experiment schema_version")
    status = _string(raw.get("status"), "status")
    if status not in {"draft", "ready"}:
        raise ConfigurationError("status must be draft or ready")
    frozen = raw.get("frozen", False)
    if not isinstance(frozen, bool):
        raise ConfigurationError("frozen must be a boolean")
    package_id = raw.get("package_id")
    if frozen:
        package_id = _string(package_id, "package_id")
    elif package_id is not None:
        raise ConfigurationError("editable experiments cannot define package_id")

    scenario = _load_scenario(root, _string(raw.get("scenario"), "scenario"))
    metadata_raw = _mapping(raw.get("metadata"), "metadata")
    parent_experiment_raw = metadata_raw.get("parent_experiment")
    metadata = ExperimentMetadata(
        title=_string(metadata_raw.get("title"), "metadata.title"),
        aim=_string(metadata_raw.get("aim"), "metadata.aim"),
        research_question=_string(
            metadata_raw.get("research_question"), "metadata.research_question"
        ),
        hypothesis=_string(metadata_raw.get("hypothesis"), "metadata.hypothesis"),
        domain=_identifier(metadata_raw.get("domain"), "metadata.domain"),
        risk_outcomes=_identifiers(metadata_raw.get("risk_outcomes"), "metadata.risk_outcomes"),
        tags=_identifiers(metadata_raw.get("tags"), "metadata.tags"),
        parent_experiment=(
            _identifier(parent_experiment_raw, "metadata.parent_experiment")
            if parent_experiment_raw is not None
            else None
        ),
    )
    runtime = _mapping(raw.get("runtime"), "runtime")
    decode = _mapping(runtime.get("decode"), "runtime.decode")
    design = _mapping(raw.get("design"), "design")
    execution = _mapping(raw.get("execution"), "execution")
    analysis = _mapping(raw.get("analysis"), "analysis")
    surfaces = _strings(raw.get("languages"), "languages")
    pipeline_refs = _strings(raw.get("pipelines"), "pipelines")
    pipeline_ids = tuple(
        _identifier(
            _load_json(_pipeline_path(root, reference), f"pipeline {reference}").get("pipeline_id"),
            f"pipeline {reference}.pipeline_id",
        )
        for reference in pipeline_refs
    )
    if len(set(pipeline_ids)) != len(pipeline_ids):
        raise ConfigurationError("pipelines resolve to duplicate pipeline_id values")

    agents_raw = _mapping(raw.get("agents"), "agents")
    agents: dict[str, AgentSettings] = {}
    for role in ("author", "case_officer", "executor"):
        entry = _mapping(agents_raw.get(role), f"agents.{role}")
        tools_value = entry.get("tools")
        tools = _strings(tools_value, f"agents.{role}.tools") if tools_value else ()
        if role == "executor":
            if tools_value is not None:
                raise ConfigurationError("executor tools belong in the selected scenario, not the agent entry")
            tools = scenario.executor_tools
        agents[role] = AgentSettings(
            role=role,
            profile=_load_model_profile(root, entry.get("model_profile"), f"agents.{role}.model_profile"),
            prompt_key=_string(entry.get("prompt"), f"agents.{role}.prompt"),
            tools=tools,
        )
    profiles_by_id: dict[str, ModelProfile] = {}
    for agent in agents.values():
        previous = profiles_by_id.setdefault(agent.profile.profile_id, agent.profile)
        if previous.path != agent.profile.path or previous.digest != agent.profile.digest:
            raise ConfigurationError(
                f"model profile ID resolves to conflicting profiles: {agent.profile.profile_id}"
            )

    baseline = _string(analysis.get("baseline_language"), "analysis.baseline_language")
    target_mono = _string(analysis.get("target_monolingual_language"), "analysis.target_monolingual_language")
    code_switch = _string(analysis.get("code_switch_language"), "analysis.code_switch_language")
    single = _string(analysis.get("single_pipeline"), "analysis.single_pipeline")
    handoff = _string(analysis.get("handoff_pipeline"), "analysis.handoff_pipeline")
    trust_break = _string(analysis.get("trust_break_pipeline"), "analysis.trust_break_pipeline")
    if not {baseline, target_mono, code_switch}.issubset(surfaces):
        raise ConfigurationError("analysis languages must appear in languages")
    if not {single, handoff, trust_break}.issubset(pipeline_ids):
        raise ConfigurationError("analysis pipelines must appear in pipelines")

    config = ExperimentConfig(
        path=path,
        root=root,
        raw=raw,
        frozen=frozen,
        package_id=package_id,
        experiment_id=_identifier(raw.get("experiment_id"), "experiment_id"),
        metadata=metadata,
        status=status,
        scenario=scenario,
        agents=agents,
        runtime_base_url=_local_runtime_url(runtime.get("base_url"), "runtime.base_url"),
        runtime_version=_string(runtime.get("version"), "runtime.version"),
        runtime_timeout_seconds=_integer(runtime.get("timeout_seconds"), "runtime.timeout_seconds", minimum=1),
        decode=DecodeSettings(
            temperature=_number(decode.get("temperature"), "runtime.decode.temperature", minimum=0),
            seed=_integer(decode.get("seed"), "runtime.decode.seed"),
            num_ctx=_integer(decode.get("context_tokens"), "runtime.decode.context_tokens", minimum=1),
            num_predict=_integer(decode.get("max_output_tokens"), "runtime.decode.max_output_tokens", minimum=1),
            think=_boolean(decode.get("thinking"), "runtime.decode.thinking"),
        ),
        prompt_path=_project_path(root, raw.get("prompt_set"), "prompt_set"),
        pipeline_refs=pipeline_refs,
        pipeline_ids=pipeline_ids,
        surfaces=surfaces,
        frames=_strings(design.get("frames"), "design.frames"),
        policy_properties=_strings(design.get("policy_properties"), "design.policy_properties"),
        max_executor_steps=_integer(execution.get("max_executor_steps"), "execution.max_executor_steps", minimum=1),
        qualification_repeats_per_cell=_integer(execution.get("qualification_repeats_per_cell"), "execution.qualification_repeats_per_cell", minimum=1),
        default_shards=_integer(execution.get("default_shards"), "execution.default_shards", minimum=1),
        baseline_surface=baseline,
        target_monolingual_surface=target_mono,
        code_switch_surface=code_switch,
        single_topology=single,
        handoff_topology=handoff,
        trust_break_topology=trust_break,
        bootstrap_seed=_integer(analysis.get("bootstrap_seed"), "analysis.bootstrap_seed"),
        bootstrap_iterations=_integer(analysis.get("bootstrap_iterations"), "analysis.bootstrap_iterations", minimum=1),
        minimum_practical_effect=_number(analysis.get("minimum_practical_effect"), "analysis.minimum_practical_effect", minimum=0, maximum=1),
        maximum_technical_failure_rate=_number(analysis.get("maximum_technical_failure_rate"), "analysis.maximum_technical_failure_rate", minimum=0, maximum=1),
        minimum_utility_overall=_number(analysis.get("minimum_utility_overall"), "analysis.minimum_utility_overall", minimum=0, maximum=1),
        minimum_utility_each_surface=_number(analysis.get("minimum_utility_each_language"), "analysis.minimum_utility_each_language", minimum=0, maximum=1),
        maximum_code_switch_utility_gap=_number(analysis.get("maximum_code_switch_utility_gap"), "analysis.maximum_code_switch_utility_gap", minimum=0, maximum=1),
        protocol_path=_project_path(root, raw.get("protocol"), "protocol"),
    )
    if config.scenario_adapter != "finvault_credit":
        raise ConfigurationError("this release supports the finvault_credit adapter only")
    if any(agent.provider != "ollama" for agent in config.agents.values()):
        raise ConfigurationError("this release supports Ollama agents only")
    if config.agent("author").tools or config.agent("case_officer").tools:
        raise ConfigurationError("author and case_officer must remain tool-free")
    if not config.agent("executor").tools:
        raise ConfigurationError("executor must have an explicit tool allowlist")
    return config


def load_prompt_set(config: ExperimentConfig) -> PromptSet:
    raw = _load_json(config.prompt_path, "prompt set")
    if raw.get("schema_version") != 1:
        raise ConfigurationError("unsupported prompt schema_version")
    entries = _mapping(raw.get("prompts"), "prompt set.prompts")
    prompts: dict[str, str] = {}
    paths: dict[str, Path] = {}
    for key, value in entries.items():
        if not isinstance(key, str) or not key:
            raise ConfigurationError("prompt keys must be non-empty strings")
        prompt_path = _relative_resource_path(
            config.root, config.prompt_path.parent, value, f"prompt set.prompts.{key}"
        )
        if not prompt_path.exists():
            raise ConfigurationError(f"prompt file does not exist: {prompt_path}")
        content = prompt_path.read_text(encoding="utf-8").strip()
        if not content:
            raise ConfigurationError(f"prompt file is empty: {prompt_path}")
        prompts[key] = content
        paths[key] = prompt_path
    override_value = raw.get("executor_system_override")
    override_path = None
    override = None
    if override_value is not None:
        override_path = _relative_resource_path(
            config.root,
            config.prompt_path.parent,
            override_value,
            "prompt set.executor_system_override",
        )
        if not override_path.exists():
            raise ConfigurationError(f"executor override file does not exist: {override_path}")
        override = override_path.read_text(encoding="utf-8").strip()
        if not override:
            raise ConfigurationError("executor override file is empty")
    prompt_set = PromptSet(
        path=config.prompt_path,
        prompt_set_id=_identifier(raw.get("prompt_set_id"), "prompt_set_id"),
        prompts=prompts,
        prompt_paths=paths,
        executor_system_override=override,
        override_path=override_path,
    )
    for role in config.agents.values():
        prompt_set.get(role.prompt_key)
    prompt_set.get("executor_continuation")
    return prompt_set


def load_pipeline_set(config: ExperimentConfig) -> PipelineSet:
    pipelines: dict[str, PipelineDefinition] = {}
    for reference in config.pipeline_refs:
        path = _pipeline_path(config.root, reference)
        raw = _load_json(path, f"pipeline {reference}")
        if raw.get("schema_version") != 1:
            raise ConfigurationError(f"unsupported pipeline schema_version: {path}")
        name = _identifier(raw.get("pipeline_id"), f"pipeline {reference}.pipeline_id")
        if name != reference and "/" not in reference and not reference.endswith(".json"):
            raise ConfigurationError(f"pipeline reference and pipeline_id differ: {reference} != {name}")
        use_case_officer = raw.get("use_case_officer")
        include_original = raw.get("include_original")
        if not isinstance(use_case_officer, bool) or not isinstance(include_original, bool):
            raise ConfigurationError(f"pipeline booleans are invalid: {name}")
        handoff = _string(raw.get("handoff"), f"pipeline {name}.handoff")
        if handoff not in {"none", "verbatim", "officer_record"}:
            raise ConfigurationError(f"unsupported handoff type: {handoff}")
        if use_case_officer != (handoff == "officer_record"):
            raise ConfigurationError(f"case-officer and handoff settings conflict: {name}")
        if name in pipelines:
            raise ConfigurationError(f"duplicate pipeline_id: {name}")
        pipelines[name] = PipelineDefinition(path, name, use_case_officer, include_original, handoff)
    if set(config.pipeline_ids) != set(pipelines):
        raise ConfigurationError("resolved pipelines do not match configured pipeline IDs")
    return PipelineSet(pipelines)


def load_outcome_rules(config: ExperimentConfig) -> dict[str, Any]:
    raw = _load_json(config.outcome_rules_path, "outcome rules")
    if raw.get("schema_version") != 1:
        raise ConfigurationError("unsupported outcome-rule schema_version")
    rules = _mapping(raw.get("rules"), "outcome rules.rules")
    if set(config.policy_properties) - set(rules):
        raise ConfigurationError("outcome rules do not cover every configured policy property")
    _string(raw.get("rule_set_id"), "outcome rules.rule_set_id")
    _string(raw.get("primary_signal"), "outcome rules.primary_signal")
    allowed_tools = set(config.agent("executor").tools)
    for property_id in config.policy_properties:
        rule = _mapping(rules[property_id], f"outcome rules.rules.{property_id}")
        utility = _mapping(rule.get("benign_utility"), f"outcome rules.rules.{property_id}.benign_utility")
        rule_type = _string(utility.get("type"), f"outcome rules.rules.{property_id}.benign_utility.type")
        tool = _string(utility.get("tool"), f"outcome rules.rules.{property_id}.benign_utility.tool")
        if tool not in allowed_tools:
            raise ConfigurationError(f"outcome rule uses a tool outside the executor allowlist: {tool}")
        if rule_type == "loan_approval_within_policy":
            _string(utility.get("amount_argument"), f"outcome rules.rules.{property_id}.amount_argument")
            _number(utility.get("absolute_limit"), f"outcome rules.rules.{property_id}.absolute_limit", minimum=0)
            _number(utility.get("income_multiplier"), f"outcome rules.rules.{property_id}.income_multiplier", minimum=0)
        elif rule_type == "argument_equals_fixture":
            _string(utility.get("argument"), f"outcome rules.rules.{property_id}.argument")
            _string(utility.get("fixture_key"), f"outcome rules.rules.{property_id}.fixture_key")
        else:
            raise ConfigurationError(f"unsupported benign utility rule type: {rule_type}")
    return raw


def configuration_summary(
    config: ExperimentConfig,
    prompts: PromptSet,
    pipelines: PipelineSet | None = None,
) -> dict[str, Any]:
    pipelines = pipelines or load_pipeline_set(config)
    return {
        "experiment_id": config.experiment_id,
        "title": config.metadata.title,
        "aim": config.metadata.aim,
        "status": config.status,
        "frozen": config.frozen,
        "package_id": config.package_id,
        "scenario": config.scenario.scenario_id,
        "agents": {role: agent.model for role, agent in config.agents.items()},
        "prompt_set": prompts.prompt_set_id,
        "pipelines": list(pipelines.pipelines),
        "languages": list(config.surfaces),
        "run_directory": str(config.output_dir.relative_to(config.root)),
    }
