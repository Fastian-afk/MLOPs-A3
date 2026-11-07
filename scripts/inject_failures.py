"""Explicit fault demonstrations: actual Airflow gate, mocked Kubernetes selector."""

import argparse
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--real-airflow", action="store_true", help="Explicitly authorize two real DAG triggers"
    )
    args = parser.parse_args()
    subprocess.run([sys.executable, "scripts/kubernetes_fault_demo.py"], check=True)
    if args.real_airflow:
        for threshold, expected, output in [
            ("1.0", "failed", "evidence/failures/airflow_gate_failure.json"),
            ("0.8", "success", "evidence/failures/airflow_gate_recovery.json"),
        ]:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.verify_airflow",
                    "--confirm-trigger",
                    "--threshold",
                    threshold,
                    "--expect-state",
                    expected,
                    "--output",
                    output,
                ],
                check=True,
            )


if __name__ == "__main__":
    main()
