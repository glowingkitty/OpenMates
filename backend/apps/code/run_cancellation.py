"""The stop flag for a Code Run outlives concurrent progress updates."""


def code_run_cancel_key(execution_id: str) -> str:
    return f"code_run_cancel_requested:{execution_id}"
