"""Run the opt-in Inception discussion pilot from its source checkout."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tiberium_ai.inception_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
