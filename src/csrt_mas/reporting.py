from __future__ import annotations

import html
import math
from pathlib import Path
from typing import Any, Iterable


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _number(value: Any, digits: int = 3) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "NA"
    return "NA" if not math.isfinite(number) else f"{number:.{digits}f}"


def _pct(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "NA"
    return "NA" if not math.isfinite(number) else f"{100 * number:.1f}%"


def _seconds(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "NA"
    if not math.isfinite(number):
        return "NA"
    if number < 60:
        return f"{number:.1f} s"
    hours, remainder = divmod(int(number), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours} h {minutes} m {seconds} s"
    return f"{minutes} m {seconds} s"


def _chips(values: Iterable[Any]) -> str:
    return "".join(f'<span class="chip">{_e(value)}</span>' for value in values)


def _bar(value: Any, *, kind: str = "risk") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return '<span class="na">NA</span>'
    if not math.isfinite(number):
        return '<span class="na">NA</span>'
    bounded = min(max(number, 0.0), 1.0)
    return (
        f'<div class="bar" role="img" aria-label="{_pct(number)}">'
        f'<span class="bar-fill {kind}" style="width:{100 * bounded:.2f}%"></span>'
        f'<strong>{_pct(number)}</strong></div>'
    )


def _table(headers: list[str], rows: list[list[str]], *, compact: bool = False) -> str:
    class_name = "compact" if compact else ""
    head = "".join(f"<th scope=\"col\">{_e(header)}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows
    )
    return (
        f'<div class="table-wrap"><table class="{class_name}"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _status(value: bool) -> str:
    label = "PASS" if value else "FAIL"
    css = "pass" if value else "fail"
    return f'<span class="status {css}">{label}</span>'


def write_experiment_html(
    result: dict[str, Any],
    gate: dict[str, Any],
    manifest: dict[str, Any],
    path: Path,
) -> None:
    research = result["research"]
    configuration = result["configuration"]
    execution = result["execution"]
    agents = configuration["agents"]
    interval = result["primary_delta_ci95"]
    package_id = str(result.get("package_id") or manifest.get("package_id") or "")
    decision = str(result.get("decision", "unknown"))
    decision_label = decision.replace("_", " ").title()

    agent_rows: list[list[str]] = []
    calls_by_role = execution.get("model_calls_by_role", {})
    for role, agent in agents.items():
        digest = str(agent.get("digest", ""))
        tools = agent.get("tools", [])
        agent_rows.append(
            [
                _e(role.replace("_", " ").title()),
                _e(agent.get("profile_id")),
                _e(agent.get("provider")),
                _e(agent.get("model")),
                f'<span class="mono" title="{_e(digest)}">{_e(digest[:12])}…</span>',
                _e(agent.get("prompt")),
                _e(calls_by_role.get(role, 0)),
                _e(", ".join(tools) if tools else "None"),
            ]
        )

    risk_headers = ["Language", *[value.replace("-", " ").title() for value in configuration["pipelines"]]]
    risk_rows = [
        [
            f"<strong>{_e(surface)}</strong>",
            *[
                _bar(result["risk_by_cell"].get(surface, {}).get(pipeline), kind="risk")
                for pipeline in configuration["pipelines"]
            ],
        ]
        for surface in configuration["languages"]
    ]

    utility_rows = [
        [f"<strong>{_e(surface)}</strong>", _bar(value, kind="utility")]
        for surface, value in result["benign_utility_by_surface"].items()
    ]

    gate_rows = [
        [_e(name.replace("_", " ").title()), _status(bool(passed))]
        for name, passed in gate.get("gates", {}).items()
    ]
    validity_rows = [
        [_e(name.replace("_", " ").title()), _status(bool(passed))]
        for name, passed in result["validity_gates"].items()
    ]

    cell_rows = []
    for row in result.get("action_cell_metrics", []):
        cell_rows.append(
            [
                _e(row.get("surface")),
                _e(str(row.get("topology", "")).replace("-", " ").title()),
                _e(row.get("intent")),
                _e(row.get("property_id")),
                _e(row.get("planned_n")),
                _e(row.get("valid_n")),
                _e(row.get("technical_failure_n")),
                _e(row.get("target_triggered_n")),
                _pct(row.get("target_triggered_rate")),
                _e(row.get("utility_success_n")),
                _pct(row.get("utility_success_rate")),
                _number(row.get("mean_action_steps"), 2),
            ]
        )

    action_rows = [
        [
            _e(row.get("surface")),
            _e(str(row.get("topology", "")).replace("-", " ").title()),
            _e(row.get("intent")),
            _e(row.get("property_id")),
            _e(row.get("final_action")),
            _e(row.get("count")),
        ]
        for row in result.get("action_distribution", [])
    ]

    mechanism_rows = [
        [
            _e(row.get("surface")),
            _e(str(row.get("topology", "")).replace("-", " ").title()),
            _e(row.get("valid_n")),
            _e(row.get("officer_compromised_n")),
            _pct(row.get("officer_compromised_rate")),
            _e(row.get("propagation_n")),
            _pct(row.get("propagation_rate_given_compromise")),
            _e(row.get("recovery_n")),
        ]
        for row in result.get("mechanism_metrics", [])
    ]

    packages = manifest.get("python_packages", {})
    package_rows = [[_e(name), _e(version)] for name, version in sorted(packages.items())]
    source_rows = [
        [_e(name), f'<span class="mono">{_e(str(digest)[:16])}…</span>']
        for name, digest in sorted(manifest.get("source_inputs", {}).items())
    ]

    artifacts = [
        ("Frozen manifest", "../frozen-manifest.json"),
        ("Frozen experiment configuration", "../package/experiment.json"),
        ("Qualification report", "../metrics/gate-report.json"),
        ("Machine-readable results", "../metrics/results.json"),
        ("Action-cell metrics", "../metrics/action-cell-metrics.csv"),
        ("Action distribution", "../metrics/action-distribution.csv"),
        ("Handoff mechanism metrics", "../metrics/mechanism-metrics.csv"),
        ("Collected hash-chained trace", "../traces/collected.jsonl"),
        ("SVG presentation dashboard", "SUPERVISOR_DASHBOARD.svg"),
        ("Markdown summary", "REPORT.md"),
    ]
    artifact_html = "".join(
        f'<li><a href="{_e(href)}">{_e(label)}</a></li>' for label, href in artifacts
    )

    parent = research.get("parent_experiment") or "None"
    html_text = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(research['title'])} — Experiment Report</title>
<style>
:root {{
  color-scheme: light dark;
  --bg: #f4f7fb; --surface: #ffffff; --surface-soft: #eef3f8; --text: #152033;
  --muted: #5d6b80; --border: #d5deea; --accent: #315efb; --accent-soft: #e7edff;
  --risk: #d9485f; --utility: #21835b; --pass: #19714e; --fail: #b4374b;
  --shadow: 0 12px 34px rgba(24, 39, 75, .09);
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #0f1520; --surface: #171f2d; --surface-soft: #202b3b; --text: #e8edf5;
    --muted: #a9b5c7; --border: #334157; --accent: #86a2ff; --accent-soft: #25345e;
    --risk: #ff7588; --utility: #5bc997; --pass: #66d5a5; --fail: #ff8293;
    --shadow: 0 12px 34px rgba(0, 0, 0, .25);
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--text); font: 15px/1.55 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
main {{ max-width: 1280px; margin: 0 auto; padding: 40px 24px 80px; }}
h1, h2, h3 {{ line-height: 1.2; font-weight: 500; }}
h1 {{ margin: 10px 0 12px; font-size: clamp(30px, 5vw, 52px); letter-spacing: -.03em; }}
h2 {{ margin: 52px 0 18px; font-size: 25px; }}
h3 {{ margin: 28px 0 12px; font-size: 18px; }}
p {{ max-width: 88ch; }}
a {{ color: var(--accent); }}
.eyebrow {{ color: var(--accent); font-weight: 500; letter-spacing: .08em; text-transform: uppercase; }}
.lead {{ color: var(--muted); font-size: 18px; max-width: 78ch; }}
.decision {{ display: inline-block; margin-top: 12px; padding: 8px 12px; background: var(--accent-soft); border-radius: 999px; font-weight: 500; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px; margin: 22px 0; }}
.card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 18px; box-shadow: var(--shadow); }}
.card .label {{ color: var(--muted); font-size: 13px; }}
.card .value {{ margin-top: 6px; font-size: 26px; font-weight: 500; overflow-wrap: anywhere; }}
.meta {{ display: grid; grid-template-columns: minmax(150px, .35fr) 1fr; gap: 10px 20px; margin: 16px 0; }}
.meta dt {{ color: var(--muted); }} .meta dd {{ margin: 0; }}
.chips {{ display: flex; flex-wrap: wrap; gap: 7px; }}
.chip {{ display: inline-block; padding: 5px 9px; border: 1px solid var(--border); border-radius: 999px; background: var(--surface-soft); }}
.table-wrap {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }}
table {{ width: 100%; border-collapse: collapse; min-width: 720px; }}
th, td {{ padding: 12px 14px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: middle; }}
th {{ color: var(--muted); background: var(--surface-soft); font-size: 13px; font-weight: 500; white-space: nowrap; }}
tbody tr:last-child td {{ border-bottom: 0; }}
table.compact th, table.compact td {{ padding: 9px 11px; font-size: 13px; }}
.bar {{ position: relative; min-width: 125px; height: 30px; border-radius: 7px; overflow: hidden; background: var(--surface-soft); }}
.bar-fill {{ position: absolute; inset: 0 auto 0 0; opacity: .33; }}
.bar-fill.risk {{ background: var(--risk); }} .bar-fill.utility {{ background: var(--utility); }}
.bar strong {{ position: relative; display: block; padding: 5px 8px; font-weight: 500; }}
.status {{ display: inline-block; min-width: 52px; padding: 3px 7px; border-radius: 999px; text-align: center; font-size: 12px; font-weight: 500; border: 1px solid currentColor; }}
.status.pass {{ color: var(--pass); }} .status.fail {{ color: var(--fail); }}
.mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }}
.na, .muted {{ color: var(--muted); }}
.two {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 22px; }}
.note {{ padding: 16px 18px; border-left: 4px solid var(--accent); background: var(--accent-soft); border-radius: 0 10px 10px 0; }}
details {{ margin: 18px 0; }} summary {{ cursor: pointer; font-weight: 500; margin-bottom: 12px; }}
.artifacts {{ columns: 2; padding-left: 20px; }} .artifacts li {{ break-inside: avoid; margin: 7px 0; }}
footer {{ margin-top: 54px; padding-top: 20px; border-top: 1px solid var(--border); color: var(--muted); }}
@media (max-width: 760px) {{ main {{ padding: 24px 14px 56px; }} .two {{ grid-template-columns: 1fr; }} .meta {{ grid-template-columns: 1fr; gap: 3px; }} .artifacts {{ columns: 1; }} }}
@media print {{ :root {{ color-scheme: light; }} body {{ background: white; }} main {{ max-width: none; padding: 0; }} .card, .table-wrap {{ box-shadow: none; }} details {{ display: block; }} details > summary {{ display: none; }} }}
</style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">Experiment report · {_e(result['experiment_id'])}</div>
    <h1>{_e(research['title'])}</h1>
    <p class="lead">{_e(research['aim'])}</p>
    <div class="decision">{_e(decision_label)}</div>
  </header>

  <section aria-labelledby="overview">
    <h2 id="overview">Outcome at a glance</h2>
    <div class="grid">
      <div class="card"><div class="label">Completed pilot matrix</div><div class="value">{_e(result['rows'])} / {_e(result['expected_rows'])}</div></div>
      <div class="card"><div class="label">Prohibited synthetic outcomes</div><div class="value">{_e(result['target_triggered_n'])} / {_e(result['valid_adversarial_rows'])}</div></div>
      <div class="card"><div class="label">Technical failure rate</div><div class="value">{_pct(result['technical_failure_rate'])}</div></div>
      <div class="card"><div class="label">Primary handoff interaction</div><div class="value">{_number(result['primary_delta'])}</div></div>
    </div>
    <div class="note"><strong>Interpretation:</strong> The final decision is constrained by the qualification gate, matrix completeness, technical reliability, legitimate-task utility, and the prospectively configured practical-effect threshold.</div>
  </section>

  <section aria-labelledby="purpose">
    <h2 id="purpose">Purpose and scope</h2>
    <dl class="meta">
      <dt>Research question</dt><dd>{_e(research['research_question'])}</dd>
      <dt>Hypothesis</dt><dd>{_e(research['hypothesis'])}</dd>
      <dt>Domain</dt><dd>{_e(research['domain'])}</dd>
      <dt>Risk outcomes</dt><dd><div class="chips">{_chips(research['risk_outcomes'])}</div></dd>
      <dt>Tags</dt><dd><div class="chips">{_chips(research['tags'])}</div></dd>
      <dt>Parent experiment</dt><dd>{_e(parent)}</dd>
      <dt>Scenario</dt><dd>{_e(configuration['scenario'])}</dd>
      <dt>Languages</dt><dd><div class="chips">{_chips(configuration['languages'])}</div></dd>
      <dt>Pipelines</dt><dd><div class="chips">{_chips(configuration['pipelines'])}</div></dd>
      <dt>Attack frames</dt><dd><div class="chips">{_chips(configuration['frames'])}</div></dd>
      <dt>Policy properties</dt><dd><div class="chips">{_chips(configuration['policy_properties'])}</div></dd>
    </dl>
  </section>

  <section aria-labelledby="agents">
    <h2 id="agents">Agents and models</h2>
    <p>The configured model is recorded separately for each role. “Calls” shows whether and how often the role was actually used across the qualification gate and pilot.</p>
    {_table(['Role', 'Profile', 'Provider', 'Model', 'Digest', 'Prompt', 'Calls', 'Tool access'], agent_rows)}
  </section>

  <section aria-labelledby="execution">
    <h2 id="execution">Execution summary</h2>
    <div class="grid">
      <div class="card"><div class="label">Model calls</div><div class="value">{_e(execution['model_calls'])}</div><div class="muted">Gate {_e(execution.get('model_calls_by_phase', {}).get('gate', 0))} · pilot {_e(execution.get('model_calls_by_phase', {}).get('pilot', 0))}</div></div>
      <div class="card"><div class="label">Prompt tokens</div><div class="value">{_e(execution['prompt_tokens'])}</div></div>
      <div class="card"><div class="label">Completion tokens</div><div class="value">{_e(execution['completion_tokens'])}</div></div>
      <div class="card"><div class="label">Cumulative model duration</div><div class="value">{_seconds(execution['model_duration_seconds'])}</div></div>
      <div class="card"><div class="label">Cumulative case time</div><div class="value">{_seconds(execution['cumulative_case_seconds'])}</div></div>
    </div>
    <p class="muted">Cumulative times add recorded case or model durations. They are not wall-clock duration when shards run in parallel.</p>
  </section>

  <section aria-labelledby="gate">
    <h2 id="gate">Qualification gate</h2>
    <div class="grid">
      <div class="card"><div class="label">Gate result</div><div class="value">{'PASS' if gate.get('passed') else 'FAIL'}</div></div>
      <div class="card"><div class="label">Rows</div><div class="value">{_e(gate.get('rows'))} / {_e(gate.get('expected_rows'))}</div></div>
      <div class="card"><div class="label">Parse success</div><div class="value">{_pct(gate.get('parse_success_rate'))}</div></div>
      <div class="card"><div class="label">Legitimate-task utility</div><div class="value">{_pct(gate.get('utility_overall'))}</div></div>
      <div class="card"><div class="label">Repeat agreement</div><div class="value">{_pct(gate.get('deterministic_repeat_agreement'))}</div></div>
    </div>
    <div class="two">
      <div><h3>Gate checks</h3>{_table(['Check', 'Result'], gate_rows, compact=True)}</div>
      <div><h3>Pilot validity checks</h3>{_table(['Check', 'Result'], validity_rows, compact=True)}</div>
    </div>
  </section>

  <section aria-labelledby="risk">
    <h2 id="risk">Action-level risk by language and pipeline</h2>
    <p>Each bar is the proportion of valid prohibited cases that triggered the configured synthetic vulnerability. Technical failures are excluded and reported separately.</p>
    {_table(risk_headers, risk_rows)}
  </section>

  <section aria-labelledby="utility">
    <h2 id="utility">Legitimate-task utility</h2>
    <p>Utility measures whether matched legitimate requests completed the fixture-defined correct action.</p>
    {_table(['Language', 'Utility success'], utility_rows)}
  </section>

  <section aria-labelledby="contrasts">
    <h2 id="contrasts">Primary statistical contrasts</h2>
    <div class="grid">
      <div class="card"><div class="label">Primary interaction</div><div class="value">{_number(result['primary_delta'])}</div><div class="muted">95% CI [{_number(interval.get('lower'))}, {_number(interval.get('upper'))}]</div></div>
      <div class="card"><div class="label">Code-switch specificity</div><div class="value">{_number(result['code_switch_specific_gamma'])}</div></div>
      <div class="card"><div class="label">Trust-break contrast</div><div class="value">{_number(result['trust_break_contrast'])}</div></div>
      <div class="card"><div class="label">Officer compromise rows</div><div class="value">{_e(result['officer_compromise_rows'])}</div><div class="muted">Propagation {_e(result['propagation_count'])} · recovery {_e(result['recovery_count'])}</div></div>
    </div>
  </section>

  <section aria-labelledby="mechanism">
    <h2 id="mechanism">Handoff mechanism</h2>
    {_table(['Language', 'Pipeline', 'Valid', 'Officer compromised', 'Compromise rate', 'Propagated', 'Propagation rate', 'Recovered'], mechanism_rows)}
  </section>

  <section aria-labelledby="detail">
    <h2 id="detail">Detailed outcome tables</h2>
    <details>
      <summary>Action and property cells ({_e(len(cell_rows))} rows)</summary>
      {_table(['Language', 'Pipeline', 'Intent', 'Property', 'Planned', 'Valid', 'Technical failures', 'Triggered', 'Trigger rate', 'Utility successes', 'Utility rate', 'Mean steps'], cell_rows, compact=True)}
    </details>
    <details>
      <summary>Final action distribution ({_e(len(action_rows))} rows)</summary>
      {_table(['Language', 'Pipeline', 'Intent', 'Property', 'Final action', 'Count'], action_rows, compact=True)}
    </details>
  </section>

  <section aria-labelledby="provenance">
    <h2 id="provenance">Reproducibility and provenance</h2>
    <dl class="meta">
      <dt>Experiment ID</dt><dd class="mono">{_e(result['experiment_id'])}</dd>
      <dt>Package ID</dt><dd class="mono">{_e(package_id)}</dd>
      <dt>Frozen at</dt><dd>{_e(manifest.get('created_at_utc'))}</dd>
      <dt>Analysis completed at</dt><dd>{_e(result.get('completed_at_utc'))}</dd>
      <dt>Project commit</dt><dd class="mono">{_e(manifest.get('project_commit'))}</dd>
      <dt>FinVault commit</dt><dd class="mono">{_e(manifest.get('upstream_commit'))}</dd>
      <dt>Python</dt><dd>{_e(manifest.get('python_version'))}</dd>
      <dt>Plan size</dt><dd>Gate {_e(manifest.get('plans', {}).get('gate'))} · pilot {_e(manifest.get('plans', {}).get('pilot'))} · {_e(manifest.get('shards_per_phase'))} shard(s) per phase</dd>
    </dl>
    <div class="two">
      <div><h3>Python packages</h3>{_table(['Distribution', 'Version'], package_rows, compact=True)}</div>
      <div><h3>Frozen research inputs</h3>{_table(['File', 'SHA-256'], source_rows, compact=True)}</div>
    </div>
  </section>

  <section aria-labelledby="artifacts">
    <h2 id="artifacts">Evidence and downloadable artifacts</h2>
    <ul class="artifacts">{artifact_html}</ul>
    <div class="note">The HTML report contains aggregate evidence only. The collected trace may contain evaluation inputs and detailed model outputs, so it should remain local and access-controlled.</div>
  </section>

  <section aria-labelledby="boundary">
    <h2 id="boundary">Interpretation boundary</h2>
    <p>This result applies only to the frozen sandbox, cases, models, prompts, language forms, pipelines, thresholds, and software revisions identified above. It must not be generalized to real financial systems or to languages, models, domains, or outcomes that were not measured. Automated language construction also requires independent language review before making linguistic causal claims.</p>
  </section>

  <footer>Generated from the verified frozen experiment and collected action-level trace. No raw test cases are embedded in this report.</footer>
</main>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")
