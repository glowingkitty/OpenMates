import tiktoken
import logging

# Set up logger
logger = logging.getLogger(__name__)


def count_tokens(
        message: str, 
        model_name: str = "gpt-3.5-turbo") -> int:
    try:
        logger.debug("Counting the tokens ...")

        message = str(message)
        if model_name == "gpt-3.5":
            model_name = "gpt-3.5-turbo"
        encoding = tiktoken.encoding_for_model(model_name)
        tokens = len(encoding.encode(message))

        logger.debug(f"Successfully counted the tokens: {tokens}")

        return tokens

    except Exception:
        logger.exception("Failed to count the tokens.")
        return None


if __name__ == "__main__":
    count_tokens(message="Hello World")