#!/usr/bin/env python3
import json
from pathlib import Path

def load_finvault_data(base_path="FinVault"):
    """
    Load all FinVault datasets with correct nested structure
    """
    base = Path(base_path)
    data = {
        "attack_cases": [],
        "benign_cases": [],
        "synthesis_attacks": {},  # Organized by attack type
        "scenarios": []
    }
    
    # 1. Load base attack datasets (flat structure)
    attack_path = base / "sandbox" / "attack_datasets"
    if attack_path.exists():
        for json_file in attack_path.glob("scenario_*_attacks.json"):
            with open(json_file) as f:
                cases = json.load(f)
                data["attack_cases"].extend(cases)
                print(f"Loaded {len(cases)} from {json_file.name}")
    
    # 2. Load synthesis attack datasets (nested by attack type)
    synthesis_path = base / "sandbox" / "attack_datasets_synthesis"
    if synthesis_path.exists():
        for attack_type_dir in synthesis_path.iterdir():
            if attack_type_dir.is_dir():
                type_name = attack_type_dir.name
                data["synthesis_attacks"][type_name] = []
                
                for json_file in attack_type_dir.glob("scenario_*_attacks.json"):
                    with open(json_file) as f:
                        cases = json.load(f)
                        data["synthesis_attacks"][type_name].extend(cases)
                        print(f"Loaded {len(cases)} {type_name} attacks from {json_file.name}")
                
                # Also add to flat attack_cases list
                data["attack_cases"].extend(data["synthesis_attacks"][type_name])
    
    # 3. Load normal/benign datasets
    normal_path = base / "sandbox" / "normal_datasets"
    if normal_path.exists():
        for json_file in normal_path.glob("scenario_*_normal.json"):
            with open(json_file) as f:
                cases = json.load(f)
                data["benign_cases"].extend(cases)
                print(f"Loaded {len(cases)} benign cases from {json_file.name}")
    
    # 4. Load scenario configs (if they exist elsewhere)
    # Check for scenario configs in various locations
    for scenario_dir in [base / "scenarios", base / "sandbox" / "scenarios"]:
        if scenario_dir.exists():
            for json_file in scenario_dir.glob("*.json"):
                with open(json_file) as f:
                    data["scenarios"].append(json.load(f))
    
    return data

def main():
    # Load the data
    finvault = load_finvault_data("./FinVault")
    
    # Print comprehensive statistics
    print("\n" + "="*50)
    print("FINVAULT DATASET STATISTICS")
    print("="*50)
    
    # Base attacks
    print(f"\nBase Attack Cases: {len(finvault['attack_cases'])}")
    
    # Breakdown by synthesis type
    print("\nAttack Types (Synthesis):")
    for attack_type, cases in finvault['synthesis_attacks'].items():
        print(f"  - {attack_type}: {len(cases)} cases")
    
    # Benign cases
    print(f"\nBenign/Normal Cases: {len(finvault['benign_cases'])}")
    
    # Scenarios
    print(f"Scenario Configs: {len(finvault['scenarios'])}")
    
    # Show sample structure
    if finvault['attack_cases']:
        print("\n" + "="*50)
        print("SAMPLE ATTACK CASE STRUCTURE")
        print("="*50)
        sample = finvault['attack_cases'][0]
        print(json.dumps(sample, indent=2)[:1500])
        print("...")
    
    # Show sample benign case
    if finvault['benign_cases']:
        print("\n" + "="*50)
        print("SAMPLE BENIGN CASE STRUCTURE")
        print("="*50)
        sample = finvault['benign_cases'][0]
        print(json.dumps(sample, indent=2)[:1500])
        print("...")
    
    return finvault

if __name__ == "__main__":
    data = main()