# Sample Python file for E2E attachment testing
# This file is used by file-attachment-flow.spec.ts


def greet(name: str) -> str:
    """Return a greeting for the given name."""
    return f"Hello, {name}!"


def main() -> None:
    """Entry point."""
    print(greet("World"))


if __name__ == "__main__":
    main()
