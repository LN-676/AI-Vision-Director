"""Thin command entry point; object construction lives in ``bootstrap``."""

from autocamtracker.bootstrap import run


def main() -> None:
    run()


if __name__ == "__main__":
    main()
