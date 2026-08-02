"""RosterCopiilot managed worker."""

from .base import run_worker


def main() -> None:
    run_worker("rostercopiilot", {"roster_copilot"})


if __name__ == "__main__":
    main()
