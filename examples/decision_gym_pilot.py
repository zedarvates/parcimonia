"""Write a bounded offline fixture benchmark into a new runs directory."""
import argparse
from pathlib import Path

from tiberium_ai.decision_gym import generate_episodes, run_benchmark
from tiberium_ai.decision_json import canonical_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "runs"
    destination = args.output_dir.resolve()
    destination.relative_to(root.resolve())
    destination.mkdir(parents=True, exist_ok=False)
    episodes = generate_episodes(args.seed)
    (destination / "episodes.json").write_text(canonical_json(episodes), encoding="utf-8")
    report = run_benchmark(episodes)
    (destination / "report.json").write_text(canonical_json(report), encoding="utf-8")
    for name, arm in report["arms"].items():
        print(name, arm.get("by_split", arm["status"]))


if __name__ == "__main__":
    main()
