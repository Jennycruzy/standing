"""Allow ``python -m standing`` to execute the product CLI."""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
