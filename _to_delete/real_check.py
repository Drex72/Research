"""Stdlib-only. Runs the new logic against the REAL vendored FinVault data."""
import sys, pathlib, traceback
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

failures, checks = [], 0
def check(label, fn):
    global checks
    checks += 1
    try:
        result = fn()
        print(f"  PASS  {label}" + (f"  -> {result}" if result else ""))
    except Exception as exc:
        failures.append((label, exc))
        print(f"  FAIL  {label}: {type(exc).__name__}: {exc}")

print("=" * 70)
print("1. CATALOG: does the real catalog resolve?")
print("=" * 70)
from csrt_mas.finvault_dynamic.catalog import FinVaultCatalog
cat = FinVaultCatalog(ROOT / "vendor" / "FinVault", ROOT / "scenarios" / "finvault")
check("scenario_ids", lambda: f"{len(cat.scenario_ids)} scenarios: {cat.scenario_ids[:5]}...")
check("synthesis_families", lambda: f"{len(cat.synthesis_families)}: {cat.synthesis_families}")

print()
print("=" * 70)
print("2. CORPUS: build from the REAL attack_datasets_synthesis, all 8 families")
print("=" * 70)
from csrt_mas.matrix.corpus import build_corpus, corpus_coverage, matrix_size, sample_balanced

rows = None
def build():
    global rows
    rows = build_corpus(cat, dataset="attack_datasets_synthesis", scenarios=["00"],
                        families=list(cat.synthesis_families), include_normal_controls=False)
    return f"{len(rows)} rows"
check("build_corpus attack-only, scenario 00, 8 families", build)

if rows:
    cov = corpus_coverage(rows)
    print(f"\n  adversarial rows      : {cov['adversarial_rows']}")
    print(f"  INDEPENDENT CLUSTERS  : {cov['independent_clusters']}   <-- what the interval must use")
    print(f"  variants per cluster  : {cov['variants_per_cluster']:.2f}")
    print(f"  by family             : {cov['by_family']}")
    print(f"  by property           : {cov['by_property']}")
    check("clustering actually collapses variants",
          lambda: f"{cov['adversarial_rows']} rows -> {cov['independent_clusters']} clusters"
          if cov['independent_clusters'] < cov['adversarial_rows'] else (_ for _ in ()).throw(
              AssertionError("no collapse: clustering is not working")))
    size = matrix_size(rows, ["EN","KO","YO","ES","CS-EN-KO","CS-EN-YO","CS-EN-ES"], ["single","summary-relay"])
    print(f"\n  7 surfaces x 2 pipelines -> {size['units']} run units")
    print(f"  adversarial per cell: {size['adversarial_units_per_cell']}, independent clusters per cell: {size['independent_clusters_per_cell']}")

print()
print("=" * 70)
print("3. CORPUS: multi-scenario (00 + 13) from the real catalog")
print("=" * 70)
def multi():
    r = build_corpus(cat, dataset="attack_datasets_synthesis", scenarios=["00","13"],
                     families=["authority_impersonation"], include_normal_controls=False)
    c = corpus_coverage(r)
    assert set(c["by_scenario"]) == {"00","13"}, c["by_scenario"]
    return f"{c['by_scenario']}"
check("corpus spans two scenarios", multi)

print()
print("=" * 70)
print("4. CORPUS: with real benign controls (pairing)")
print("=" * 70)
def paired():
    r = build_corpus(cat, dataset="attack_datasets_synthesis", scenarios=["00"],
                     families=["authority_impersonation"], include_normal_controls=True)
    c = corpus_coverage(r)
    return f"pairs={c['matched_pairs']} unmatched={c['unmatched_adversarial']} benign={c['benign_rows']}"
check("benign controls pair by property", paired)

print()
print("=" * 70)
print("5. SURFACES: load the shipped language profiles")
print("=" * 70)
from csrt_mas.matrix.surfaces import load_detectors, load_surface_specs, validate_surface_text
det = load_detectors(ROOT / "languages" / "_detectors.json")
refs = {p.stem: f"languages/{p.name}" for p in sorted((ROOT/"languages").glob("*.json")) if not p.name.startswith("_")}
check("load all surfaces", lambda: f"{sorted(refs)}")
specs = load_surface_specs(refs, ROOT, det)

print()
print("=" * 70)
print("6. SURFACES: run detection over a REAL attack prompt from the dataset")
print("=" * 70)
cases = cat.load_cases("attack_datasets_synthesis", "00", family="authority_impersonation")
real_prompt = cases[0].prompt
print(f"  real case id : {cases[0].case_id}")
print(f"  prompt chars : {len(real_prompt)}")
check("English detected in the real English prompt",
      lambda: f"English tokens={det.require('English').hits(real_prompt)}"
      if det.require('English').hits(real_prompt) >= 3 else (_ for _ in ()).throw(AssertionError("English not detected")))
check("Korean absent from the real English prompt",
      lambda: "0 Korean tokens" if det.require('Korean').hits(real_prompt) == 0
      else (_ for _ in ()).throw(AssertionError("false Korean positive")))
check("real prompt REJECTED as a code-switched surface (it is monolingual)",
      lambda: f"{len(validate_surface_text(specs['CS-EN-KO'], real_prompt, det, source_text=real_prompt))} problems"
      if validate_surface_text(specs['CS-EN-KO'], real_prompt, det, source_text=real_prompt)
      else (_ for _ in ()).throw(AssertionError("monolingual text wrongly accepted as code-switched")))

print()
print("=" * 70)
print(f"RESULT: {checks - len(failures)}/{checks} checks passed")
if failures:
    print("FAILURES:")
    for label, exc in failures:
        print(f"  - {label}: {exc}")
    sys.exit(1)
