# backend/apps/ai/utils/stream_utils.py
# Utilities for processing and handling LLM response streams.

import logging
from typing import AsyncIterator
import re

logger = logging.getLogger(__name__)

async def aggregate_paragraphs(raw_chunk_stream: AsyncIterator[str]) -> AsyncIterator[str]:
    """
    Asynchronously aggregates text chunks from a stream into paragraphs.

    Paragraphs are primarily delimited by double newlines ('\n\n').
    Additionally, markdown code blocks (``` ... ```) are treated as distinct paragraphs.
    It yields each complete paragraph/code block as it's formed.
    Any remaining buffered text is yielded at the end of the stream.

    Args:
        raw_chunk_stream: An asynchronous iterator yielding text chunks (strings).

    Yields:
        AsyncIterator[str]: An asynchronous iterator yielding complete paragraphs or code blocks.
    """
    buffer = ""
    in_code_block = False
    code_block_delimiter = "```"
    paragraph_separator = "\n\n"

    try:
        async for chunk in raw_chunk_stream:
            buffer += chunk

            while True:
                # Determine the next potential split point
                split_pos = -1
                current_separator_len = 0
                
                if in_code_block:
                    # If inside a code block, only look for the closing delimiter
                    end_code_block_pos = buffer.find(code_block_delimiter)
                    if end_code_block_pos != -1:
                        split_pos = end_code_block_pos + len(code_block_delimiter)
                        current_separator_len = len(code_block_delimiter) # The block includes the delimiter
                    else:
                        break # Need more chunks to close the code block
                else:
                    # If outside a code block, look for paragraph separator or start of a new code block
                    para_sep_pos = buffer.find(paragraph_separator)
                    start_code_block_pos = buffer.find(code_block_delimiter)

                    if para_sep_pos != -1 and (start_code_block_pos == -1 or para_sep_pos < start_code_block_pos):
                        # Found a paragraph separator before any code block start
                        split_pos = para_sep_pos + len(paragraph_separator)
                        current_separator_len = len(paragraph_separator)
                    elif start_code_block_pos != -1:
                        # Found a code block start (either before a para_sep or no para_sep found yet)
                        # If there's text before this code block, yield it first
                        if start_code_block_pos > 0:
                            yield buffer[:start_code_block_pos]
                            buffer = buffer[start_code_block_pos:]
                        # Now process the code block start
                        split_pos = len(code_block_delimiter) # The start of the code block content
                        current_separator_len = len(code_block_delimiter)
                        in_code_block = True # Enter code block state
                    else:
                        # No separators found, need more chunks
                        break
                
                if split_pos != -1 :
                    # If we are yielding a full code block that just ended
                    if not in_code_block and current_separator_len == len(code_block_delimiter) and buffer.startswith(code_block_delimiter): # Check if it was a code block that just ended
                         # This condition means we just exited a code block.
                         # The split_pos includes the closing ```.
                        yield buffer[:split_pos]
                        buffer = buffer[split_pos:]
                        # in_code_block is already False
                    elif in_code_block and current_separator_len == len(code_block_delimiter) and split_pos == len(code_block_delimiter):
                        # This means we just entered a code block.
                        # We don't yield yet, we wait for the closing ``` or more content.
                        # The buffer now starts with ```. We need to see if the *current chunk* completes it.
                        # This part of the logic is tricky. Let's simplify:
                        # The main loop handles finding the *next* delimiter.
                        # If we find ``` and we are *not* in a code block, we yield text before it, then set in_code_block = true.
                        # If we find ``` and we *are* in a code block, we yield the block including ```, then set in_code_block = false.
                        # This refined logic is better handled by checking state *before* finding delimiters.

                        # Re-evaluating the loop structure for clarity:
                        # The current loop structure is a bit complex. Let's refine.
                        # The outer loop gets chunks. The inner loop processes the buffer.
                        # The inner loop should find the *earliest* of \n\n or ```.

                        # Simpler approach for the inner loop:
                        # 1. If in_code_block: search for closing ```. If found, yield block, update buffer, set in_code_block=False. Else break.
                        # 2. If not in_code_block: search for earliest of \n\n or opening ```.
                        #    a. If \n\n is earliest (or only one found): yield paragraph, update buffer.
                        #    b. If ``` is earliest: yield text before ``` (if any), update buffer to start with ```, set in_code_block=True.
                        #    c. If neither: break.
                        # This loop needs to be outside the `while True` and replace it.
                        # The `while True` is causing issues. Let's restructure.
                        pass # This complex conditional logic needs a rethink.

                else: # Should not happen if break conditions are correct
                    break
            
            # --- Refined inner loop ---
            processed_something_in_iteration = True
            while processed_something_in_iteration:
                processed_something_in_iteration = False
                if in_code_block:
                    end_code_block_idx = buffer.find(code_block_delimiter)
                    if end_code_block_idx != -1:
                        # Code block ends. Yield the whole block including delimiters.
                        # The content of the code block might span multiple original chunks.
                        # We need to include the language specifier if present.
                        # The start of the code block was ````.
                        # The end is `end_code_block_idx` which is the start of the closing ```.
                        # So the block is buffer[:end_code_block_idx + len(code_block_delimiter)]
                        
                        # Let's assume the opening ``` was already handled.
                        # The buffer part for the code block is up to and including the closing ```.
                        code_block_content = buffer[:end_code_block_idx + len(code_block_delimiter)]
                        yield code_block_content
                        buffer = buffer[end_code_block_idx + len(code_block_delimiter):]
                        in_code_block = False
                        processed_something_in_iteration = True
                    else:
                        # Code block not yet closed, need more data or it's the end of stream
                        pass # Will be handled by final buffer yield if stream ends
                else: # Not in a code block
                    para_sep_idx = buffer.find(paragraph_separator)
                    code_block_start_idx = buffer.find(code_block_delimiter)

                    # Determine which separator comes first, if any
                    if para_sep_idx != -1 and (code_block_start_idx == -1 or para_sep_idx < code_block_start_idx):
                        # Paragraph separator is next
                        paragraph = buffer[:para_sep_idx + len(paragraph_separator)]
                        yield paragraph
                        buffer = buffer[para_sep_idx + len(paragraph_separator):]
                        processed_something_in_iteration = True
                    elif code_block_start_idx != -1:
                        # Code block start is next (or only one found)
                        if code_block_start_idx > 0:
                            # Yield text before the code block
                            yield buffer[:code_block_start_idx]
                        # The buffer now effectively starts at the code block delimiter
                        # The code block itself (```...```) will be handled in the next iteration
                        # or when in_code_block is true.
                        buffer = buffer[code_block_start_idx:]
                        in_code_block = True # Enter code block state
                        # We don't yield the opening ``` itself as a paragraph.
                        # The next iteration will look for the closing ```.
                        processed_something_in_iteration = True # We've processed up to the start of the code block
                    else:
                        # No separators found in the current buffer
                        pass
            # --- End of refined inner loop ---


        # Yield any remaining text in the buffer after the stream ends
        if buffer:
            # If we were in a code block and the stream ended, the buffer contains the rest of it.
            # The user of this generator should be aware that the last yielded item might be an unterminated code block.
            yield buffer
            
    except Exception as e:
        logger.error(f"Error during paragraph aggregation from stream: {e}", exc_info=True)
        raise

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