import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astra_ml.evaluation import evaluate, render_markdown  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate ASTRA on labelled synthetic scenarios")
    parser.add_argument("--seeds", type=int, default=200, help="random seeds per scenario and parameter")
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument("--out", default="docs/evaluation.md")
    args = parser.parse_args()

    stats = evaluate(args.seeds, args.seed_start)
    report = render_markdown(stats, args.seeds, args.seed_start)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
