import argparse
from pathlib import Path

from .app import LcarsDash


def main() -> None:
    ap = argparse.ArgumentParser(description="LCARS repo activity dashboard")
    ap.add_argument("--root", type=Path, action="append",
                    help="folder containing cloned repos (repeatable); default: roots in ~/.lcars_dash.json")
    LcarsDash(ap.parse_args().root).run()


main()
