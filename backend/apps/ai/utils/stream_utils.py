# backend/apps/ai/utils/stream_utils.py
# Utilities for processing and handling LLM response streams.

import logging
from typing import AsyncIterator
logger = logging.getLogger(__name__)
# set logger to to DEBUG level for detailed output
# logger.setLevel(logging.DEBUG)

async def aggregate_paragraphs(
    raw_chunk_stream: AsyncIterator, *, early_prose: bool = False
) -> AsyncIterator:
    """
    Asynchronously aggregates text chunks from a stream into paragraphs,
    while passing through any non-string objects (like billing/usage data).

    Paragraphs are primarily delimited by double newlines ('\n\n').
    Additionally, markdown code blocks (``` ... ```) are treated as distinct paragraphs.
    It yields each complete paragraph/code block as it's formed.
    Any remaining buffered text is yielded at the end of the stream. When
    early_prose is enabled, the first ordinary text is released as soon as its
    suffix cannot become a paragraph separator, code fence, or tool-call XML
    marker. Later text retains paragraph boundaries for downstream line parsers.
    Complete and incomplete tool-call XML is suppressed in this mode.
    The default retains the paragraph contract for other callers.

    Args:
        raw_chunk_stream: An asynchronous iterator yielding text chunks (strings)
                          or other data objects.

    Yields:
        AsyncIterator: An asynchronous iterator yielding complete paragraphs,
                       code blocks, or the original non-string objects.
    """
    buffer = ""
    in_code_block = False
    code_block_delimiter = "```"
    paragraph_separator = "\n\n"
    tool_call_open = "<tool_call>"
    tool_call_close = "</tool_call>"
    in_tool_call = False
    early_release_done = False
    early_prose_min_chars = 8

    def held_marker_suffix(value: str) -> int:
        """Keep only suffixes that may complete a special opening token."""
        lowered = value.lower()
        markers = (
            paragraph_separator, code_block_delimiter, tool_call_open,
            "[error", "{thought}",
        )
        return max(
            (length for marker in markers for length in range(1, len(marker))
             if lowered.endswith(marker[:length])),
            default=0,
        )

    try:
        # Constants for buffer management
        MAX_BUFFER_SIZE = 32 * 1024  # Max buffer size before forced yield (e.g., 32KB)
        SCAN_PREFIX_LENGTH = 8 * 1024 # Scan only the beginning of the buffer (e.g., 8KB)
                                      # Must be smaller than MAX_BUFFER_SIZE

        async for chunk in raw_chunk_stream:
            # Pass non-string objects (like usage data) through immediately.
            if not isinstance(chunk, str):
                yield chunk
                continue

            logger.debug(f"Stream chunk received (length={len(chunk)})")
            buffer += chunk

            processed_in_outer_loop = True
            while processed_in_outer_loop: # Keep processing buffer as long as changes are made
                processed_in_outer_loop = False

                if in_tool_call:
                    # The consumer's per-chunk XML stripper cannot recognize a
                    # split block. Suppress it here before any text is published.
                    end_tool_call_idx = buffer.lower().find(tool_call_close)
                    if end_tool_call_idx != -1:
                        end = end_tool_call_idx + len(tool_call_close)
                        buffer = buffer[end:]
                        in_tool_call = False
                        processed_in_outer_loop = True
                    else:
                        if len(buffer) > MAX_BUFFER_SIZE:
                            # Keep only a possible prefix of the closing tag.
                            buffer = buffer[-(len(tool_call_close) - 1):]
                        break
                elif in_code_block:
                    # Look for closing code block delimiter
                    # Scan the whole buffer for closing delimiter as code blocks can be long
                    # When the buffered block still starts with its opening fence, skip
                    # that delimiter so it cannot be mistaken for the closing fence.
                    delimiter_search_start = (
                        len(code_block_delimiter)
                        if buffer.startswith(code_block_delimiter)
                        else 0
                    )
                    end_code_block_idx = buffer.find(
                        code_block_delimiter,
                        delimiter_search_start,
                    )
                    if end_code_block_idx != -1:
                        # Code block ends. Yield the whole block including delimiters.
                        code_block_content = buffer[:end_code_block_idx + len(code_block_delimiter)]
                        yield code_block_content
                        buffer = buffer[end_code_block_idx + len(code_block_delimiter):]
                        in_code_block = False
                        processed_in_outer_loop = True
                    elif len(buffer) > MAX_BUFFER_SIZE:
                        # Code block is too long without a closing delimiter, force yield part of it
                        # Try to break on a newline for cleaner output
                        forced_yield_len = MAX_BUFFER_SIZE - len(code_block_delimiter) # Leave space for potential delimiter later
                        last_newline = buffer.rfind('\n', 0, forced_yield_len)
                        if last_newline != -1 and last_newline > 0 : # Ensure it's not the very start
                            yield buffer[:last_newline + 1]
                            buffer = buffer[last_newline + 1:]
                        else: # No newline found, or it's at the start, yield fixed size
                            yield buffer[:forced_yield_len]
                            buffer = buffer[forced_yield_len:]
                        logger.warning(f"Forced yield from within a long code block. Current buffer size: {len(buffer)}")
                        processed_in_outer_loop = True # Buffer was modified
                    else:
                        # Code block not yet closed, and buffer not too large, need more data
                        break # Break inner while, wait for next chunk
                else: # Not in a code block
                    # Scan a prefix of the buffer for separators
                    # The fast path must inspect the entire provider chunk: a
                    # fence later in a large chunk must never be released as prose.
                    scan_area = buffer if early_prose else buffer[:SCAN_PREFIX_LENGTH]
                    para_sep_idx = scan_area.find(paragraph_separator)
                    code_block_start_idx = scan_area.find(code_block_delimiter)
                    tool_call_start_idx = (
                        scan_area.lower().find(tool_call_open) if early_prose else -1
                    )

                    if tool_call_start_idx != -1 and all(
                        idx == -1 or tool_call_start_idx < idx
                        for idx in (para_sep_idx, code_block_start_idx)
                    ):
                        if tool_call_start_idx > 0:
                            yield buffer[:tool_call_start_idx]
                        buffer = buffer[tool_call_start_idx:]
                        in_tool_call = True
                        processed_in_outer_loop = True

                    # Determine which separator comes first, if any, within the scan_area
                    elif para_sep_idx != -1 and (code_block_start_idx == -1 or para_sep_idx < code_block_start_idx):
                        # Paragraph separator is next
                        paragraph = buffer[:para_sep_idx + len(paragraph_separator)]
                        yield paragraph
                        buffer = buffer[para_sep_idx + len(paragraph_separator):]
                        processed_in_outer_loop = True
                    elif code_block_start_idx != -1:
                        # Code block start is next (or only one found in scan_area)
                        if code_block_start_idx > 0:
                            # Yield text before the code block
                            yield buffer[:code_block_start_idx]
                        buffer = buffer[code_block_start_idx:] # Buffer now starts with ```
                        in_code_block = True # Enter code block state
                        processed_in_outer_loop = True
                    else:
                        # No separators found in the scan_area
                        if early_prose and any(
                            buffer.lstrip().startswith(marker)
                            or marker.startswith(buffer.lstrip())
                            for marker in ("[ERROR", "{thought}")
                        ):
                            # The consumer recognizes these only at the start
                            # of a chunk; do not fragment a private error or
                            # leaked-reasoning marker before it sees it.
                            break
                        if early_prose and not early_release_done and (
                            not buffer.lstrip() or buffer.lstrip()[0] in "|-0123456789"
                        ):
                            # Table and numeric/garbled content needs the
                            # consumer's complete-line and chunk checks.
                            break
                        if early_prose and not early_release_done:
                            safe_len = len(buffer) - held_marker_suffix(buffer)
                            if safe_len >= early_prose_min_chars:
                                yield buffer[:safe_len]
                                buffer = buffer[safe_len:]
                                early_release_done = True
                        elif len(buffer) > MAX_BUFFER_SIZE:
                            # Buffer is too large without a separator, force yield part of it
                            # Try to break on a newline for cleaner output
                            forced_yield_len = SCAN_PREFIX_LENGTH # Yield up to where we scanned
                            last_newline = buffer.rfind('\n', 0, forced_yield_len)
                            if last_newline != -1 and last_newline > 0:
                                yield buffer[:last_newline + 1]
                                buffer = buffer[last_newline + 1:]
                            else: # No newline found, yield fixed size
                                yield buffer[:forced_yield_len]
                                buffer = buffer[forced_yield_len:]
                            logger.warning(f"Forced yield due to large buffer without separators. Current buffer size: {len(buffer)}")
                            processed_in_outer_loop = True # Buffer was modified
                        else:
                            # No separator in scan_area, buffer not yet too large, need more chunks
                            break # Break inner while, wait for next chunk
        
        # Yield any remaining text in the buffer after the stream ends
        if buffer and not in_tool_call:
            if in_code_block:
                logger.warning(f"Stream ended with an unterminated code block. Yielding remaining buffer. Size: {len(buffer)}")
            yield buffer
            
    except Exception as e:
        logger.error(f"Error during paragraph aggregation from stream: {e}", exc_info=True)
        # It's important to re-raise or handle appropriately so the caller knows.
        # For example, the caller might need to clean up resources or log the failure.
        raise # Re-raise the exception to be caught by the Celery task or other calling code.

if __name__ == '__main__':
    import asyncio

    async def mock_raw_stream_with_code() -> AsyncIterator[str]:
        yield "This is some introductory text.\n\n"
        yield "```python\n"
        yield "def hello():\n"
        yield "    print('Hello, world!')\n"
        yield "```\n\n"
        yield "This is some text after the code block."
        yield " It continues on the same logical paragraph."
        yield "\n\nAnother paragraph entirely.\n"
        yield "And a final fragment."
        yield "\n```javascript\nconsole.log('Streaming code');\n" # Unterminated code block
        yield "let x = 10;\n"


    async def test_aggregation():
        logger.info("Testing paragraph aggregation with code blocks:")
        paragraph_num = 1
        try:
            async for paragraph in aggregate_paragraphs(mock_raw_stream_with_code()):
                logger.info(f"--- Yielded Block {paragraph_num} ---")
                logger.info(f"{paragraph}") # No extra quotes to see exact output
                logger.info("-------------------------")
                paragraph_num += 1
        except Exception as e:
            logger.error(f"Test aggregation failed: {e}", exc_info=True)

    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_aggregation())
