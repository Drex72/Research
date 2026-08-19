from __future__ import annotations

from .settings import ROOT, ExperimentConfig, load_experiment, load_pipeline_set


# Configuration is selected before imports by csrt_mas.bootstrap. Each worker
# process therefore sees either the editable root design or one frozen package.
CONFIG: ExperimentConfig = load_experiment()
PIPELINE_SET = load_pipeline_set(CONFIG)
PIPELINES = PIPELINE_SET.pipelines

FINVAULT_ROOT = CONFIG.finvault_root
FINVAULT_SANDBOX = FINVAULT_ROOT / "sandbox"
STIMULUS_ROOT = CONFIG.stimuli_path.parent
ARTIFACT_ROOT = CONFIG.output_dir
STIMULI_PATH = CONFIG.stimuli_path
QUALIFICATION_STIMULI_PATH = CONFIG.qualification_stimuli_path
OUTCOME_RULES_PATH = CONFIG.outcome_rules_path
GATE_PLAN_PATH = CONFIG.gate_plan_path
PILOT_PLAN_PATH = CONFIG.pilot_plan_path
RAW_TRACE_PATH = CONFIG.raw_trace_path
METRICS_DIR = ARTIFACT_ROOT / "metrics"
REPORT_DIR = ARTIFACT_ROOT / "report"
GATE_REPORT_PATH = METRICS_DIR / "gate-report.json"
RESULTS_PATH = METRICS_DIR / "results.json"
REPORT_PATH = REPORT_DIR / "REPORT.md"
HTML_REPORT_PATH = REPORT_DIR / "EXPERIMENT_REPORT.html"
ACTION_CELL_PATH = METRICS_DIR / "action-cell-metrics.csv"
ACTION_DISTRIBUTION_PATH = METRICS_DIR / "action-distribution.csv"
MECHANISM_PATH = METRICS_DIR / "mechanism-metrics.csv"
DASHBOARD_PATH = REPORT_DIR / "SUPERVISOR_DASHBOARD.svg"
MANIFEST_PATH = CONFIG.manifest_path
PROTOCOL_PATH = CONFIG.protocol_path
PROMPT_PATH = CONFIG.prompt_path
PIPELINE_PATHS = PIPELINE_SET.files

FINVAULT_COMMIT = CONFIG.finvault_commit
SCENARIO_ID = CONFIG.scenario_id
MODEL = CONFIG.agent("executor").model
MODEL_DIGEST = CONFIG.agent("executor").digest
OFFICER_MODEL = CONFIG.agent("case_officer").model
OFFICER_MODEL_DIGEST = CONFIG.agent("case_officer").digest
OLLAMA_VERSION = CONFIG.runtime_version
SEED = CONFIG.decode.seed
BOOTSTRAP_SEED = CONFIG.bootstrap_seed
BOOTSTRAP_ITERATIONS = CONFIG.bootstrap_iterations
MAX_EXECUTOR_STEPS = CONFIG.max_executor_steps
QUALIFICATION_REPEATS = CONFIG.qualification_repeats
EXPECTED_SEMANTIC_ROWS = CONFIG.expected_semantic_rows
EXPECTED_PAIRS = CONFIG.expected_pairs
QUALIFICATION_ROWS = CONFIG.qualification_rows

SURFACES = CONFIG.surfaces
TOPOLOGIES = CONFIG.topologies
FRAMES = CONFIG.frames
POLICY_PROPERTIES = CONFIG.policy_properties

BASELINE_SURFACE = CONFIG.baseline_surface
TARGET_MONOLINGUAL_SURFACE = CONFIG.target_monolingual_surface
CODE_SWITCH_SURFACE = CONFIG.code_switch_surface
SINGLE_TOPOLOGY = CONFIG.single_topology
HANDOFF_TOPOLOGY = CONFIG.handoff_topology
TRUST_BREAK_TOPOLOGY = CONFIG.trust_break_topology
MINIMUM_PRACTICAL_EFFECT = CONFIG.minimum_practical_effect
MAXIMUM_TECHNICAL_FAILURE_RATE = CONFIG.maximum_technical_failure_rate
MINIMUM_UTILITY_OVERALL = CONFIG.minimum_utility_overall
MINIMUM_UTILITY_EACH_SURFACE = CONFIG.minimum_utility_each_surface
MAXIMUM_CODE_SWITCH_UTILITY_GAP = CONFIG.maximum_code_switch_utility_gap

DECODE = CONFIG.decode
