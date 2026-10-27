"""Writer selection is scoped to Daily Inspirations, never account/chat routing."""
WRITER_MODEL = "inception/mercury-3"


def writer_model() -> str:
    """Use the sole background writer without account or environment overrides."""
    return WRITER_MODEL
