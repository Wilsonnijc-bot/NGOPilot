"""CareFlow managed worker."""

from .base import run_worker


def main() -> None:
    run_worker(
        "careflow",
        {
            "careflow_paper_forms_to_excel",
            "careflow_meeting_notes",
            "careflow_government_forms",
        },
    )


if __name__ == "__main__":
    main()
