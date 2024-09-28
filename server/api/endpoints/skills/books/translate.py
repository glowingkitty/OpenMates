import os
import re
import zipfile
import xml.etree.ElementTree as ET
import tempfile
import asyncio
from server.api.endpoints.tasks.update import update as update_task
import time
from server.api.endpoints.skills.ai.estimate_cost import estimate_cost, count_tokens
from typing import List, Literal
from server.api.models.skills.ai.skills_ai_estimate_cost import AiEstimateCostOutput
from server.api.models.skills.files.skills_files_upload import FilesUploadOutput
from server.api.endpoints.skills.files.upload import upload
from server.api.endpoints.skills.ai.ask import ask
from server.api.models.skills.ai.skills_ai_ask import AiAskInput, AiAskOutput
from datetime import datetime, timedelta
from ebooklib import epub
from urllib.parse import quote
import tempfile
from datetime import datetime, timedelta

import logging

logger = logging.getLogger(__name__)

# TODO add estimated finish time and estimated costs and total costs to the task
# TODO add PDF output support

translation_provider = { "name": "chatgpt", "model": "gpt-4o-mini" }

async def translate_text(
        user_api_token: str,
        team_slug: str,
        text: str,
        output_language: str
) -> str:
    logger.debug(f"Translating text to {output_language}")
    response: AiAskOutput = await ask(
        user_api_token=user_api_token,
        team_slug=team_slug,
        input=AiAskInput(
            system=f"You are an expert translator. Translate the given text to {output_language} and output nothing else except the translation output (and make sure to keep the original formatting/html structure).",
            message=text,
            provider=translation_provider,
            temperature=0
        )
    )
    if response.content:
        translated_text = response.content[0].text
    else:
        raise ValueError("No content in the response")
    logger.debug(f"Translation complete")
    return translated_text

def split_into_chunks(content: str) -> list:
    logger.debug("Splitting content into chunks")
    # Find the body content
    body_match = re.search(r'<body.*?>(.*)</body>', content, re.DOTALL)
    if not body_match:
        logger.debug("No body tag found, returning entire content as one chunk")
        return [content]  # If no body tag, return the entire content as one chunk

    body_content = body_match.group(1)

    # Split by heading tags
    chunks = re.split(r'(<h[1-6].*?>)', body_content)

    # Combine headings with their content
    combined_chunks = []
    for i in range(0, len(chunks), 2):
        if i + 1 < len(chunks):
            combined_chunks.append(chunks[i] + chunks[i+1])
        else:
            combined_chunks.append(chunks[i])

    logger.debug(f"Split into {len(combined_chunks)} chunks")
    return combined_chunks if combined_chunks else [body_content]

async def translate_xhtml_file(
        user_api_token: str,
        team_slug: str,
        file_path: str,
        output_language: str,
        total_chars: int,
        task_id: str,
        start_time: float,
        chunk_lengths: List[int]
) -> int:
    logger.debug(f"Translating XHTML file: {file_path}")
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()

    # Extract content outside the body
    pre_body = re.search(r'^.*?<body.*?>', content, re.DOTALL)
    post_body = re.search(r'</body>.*?$', content, re.DOTALL)

    chunks = split_into_chunks(content)

    async def translate_chunk(chunk, i):
        logger.debug(f"Translating chunk {i+1}/{len(chunks)}")
        # Replace processing instructions with placeholders
        pi_placeholders = {}
        for j, pi in enumerate(re.findall(r'<\?.*?\?>', chunk)):
            placeholder = f'__PI_PLACEHOLDER_{j}__'
            pi_placeholders[placeholder] = pi
            chunk = chunk.replace(pi, placeholder)

        translated_chunk = await translate_text(
            user_api_token=user_api_token,
            team_slug=team_slug,
            text=chunk,
            output_language=output_language
        )

        # Restore processing instructions
        for placeholder, pi in pi_placeholders.items():
            translated_chunk = translated_chunk.replace(placeholder, pi)

        # Update progress
        progress = round((sum(chunk_lengths[:i+1]) / total_chars) * 100)
        elapsed_time = time.time() - start_time
        remaining_time = (elapsed_time / progress) * (100 - progress) if progress > 0 else None
        if remaining_time is not None:
            estimated_completion_time = datetime.now() + timedelta(seconds=remaining_time)
            time_estimated_completion = estimated_completion_time.isoformat()
        else:
            time_estimated_completion = None
        await update_task(task_id, progress=progress, time_estimated_completion=time_estimated_completion)
        logger.debug(f"Chunk {i+1} translated, progress: {progress}%")

        return translated_chunk, len(translated_chunk)

    # Translate chunks concurrently
    tasks = [translate_chunk(chunk, i) for i, chunk in enumerate(chunks)]
    results = await asyncio.gather(*tasks)

    translated_chunks, translated_chars_list = zip(*results)
    translated_body = "".join(translated_chunks)
    translated_chars = sum(translated_chars_list)

    # Translate title if it exists
    title_match = re.search(r'<title>(.*?)</title>', content)
    if title_match:
        original_title = title_match.group(1)
        logger.debug(f"Translating title.")
        translated_title = await translate_text(
            user_api_token=user_api_token,
            team_slug=team_slug,
            text=original_title,
            output_language=output_language
        )
        content = content.replace(f'<title>{original_title}</title>', f'<title>{translated_title}</title>')

    # Reconstruct the full content
    translated_content = (
        (pre_body.group(0) if pre_body else '') +
        f'<body>{translated_body}</body>' +
        (post_body.group(0) if post_body else '')
    )

    # Write the translated content back to the file
    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(translated_content)
    logger.debug(f"File {file_path} translation complete")

    return translated_chars

def count_translatable_chars(file_path: str) -> int:
    logger.debug(f"Counting translatable characters in file: {file_path}")
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
    # Remove all HTML tags and count remaining characters
    text_content = re.sub(r'<.*?>', '', content)
    char_count = len(text_content)
    logger.debug(f"File {file_path} has {char_count} translatable characters")
    return char_count

async def translate(
    team_slug: str,
    api_token: str,
    ebook_data: bytes,
    output_language: str,
    task_id: str,
    output_format: Literal["epub", "pdf"] = 'epub'
) -> FilesUploadOutput:
    logger.debug("Starting translation process")
    # Create a temporary directory to work with the EPUB
    with tempfile.TemporaryDirectory() as temp_dir:
        # Save the input EPUB to a temporary file
        input_epub = os.path.join(temp_dir, "input.epub")
        with open(input_epub, "wb") as f:
            f.write(ebook_data)
        logger.debug(f"EPUB saved to temporary file: {input_epub}")

        # Extract the EPUB file
        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(input_epub, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        logger.debug(f"EPUB extracted to directory: {extract_dir}")

        # Find and process all XHTML files
        total_chars = 0
        xhtml_files = []
        chunk_lengths = []
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                if file.endswith('.xhtml') or file.endswith('.html'):
                    file_path = os.path.join(root, file)
                    xhtml_files.append(file_path)
                    total_chars += count_translatable_chars(file_path)

                    # Extract chunks and their lengths
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    chunks = split_into_chunks(content)
                    for chunk in chunks:
                        tokens = count_tokens(chunk)
                        chunk_lengths.append(tokens)
        logger.debug(f"Found {len(xhtml_files)} XHTML files with a total of {total_chars} characters")

        # Estimate total cost
        total_credits_cost_estimated: AiEstimateCostOutput = estimate_cost(
            token_count=sum(chunk_lengths),
            provider=translation_provider
        )
        logger.debug(f"Estimated total cost: {total_credits_cost_estimated.total_credits_cost_estimated.credits_for_input_tokens * 2.1}")

        # TODO check if the user has enough credits to perform the translation, else cancel the task and return an error
        expected_total_cost = round(total_credits_cost_estimated.total_credits_cost_estimated.credits_for_input_tokens * 2.1)
        # if get_balance(api_token=api_token, team_slug=team_slug) < expected_total_cost:
        #     raise InsufficientCreditsException

        await update_task(
            task_id=task_id,
            total_credits_cost_estimated=expected_total_cost
        )

        translated_chars = 0
        start_time = time.time()

        # Process all files concurrently
        tasks = [
            translate_xhtml_file(
                user_api_token=api_token,
                team_slug=team_slug,
                file_path=file_path,
                output_language=output_language,
                total_chars=total_chars,
                task_id=task_id,
                start_time=start_time,
                chunk_lengths=chunk_lengths
            ) for file_path in xhtml_files
        ]
        results = await asyncio.gather(*tasks)
        translated_chars = sum(results)

        # Get the book title for the file name
        book = epub.read_epub(input_epub)
        title = book.get_metadata('DC', 'title')[0][0] if book.get_metadata('DC', 'title') else "Untitled"

        if output_format.lower() == 'pdf':
            logger.info("PDF conversion not implemented yet")
            # Placeholder for PDF conversion
            # pdf_data = convert_file(input_format='epub', output_format='pdf')
            # file_name = f"{quote(title)}_translated_{output_language}.pdf"
            # file_info = await upload(
            #     team_slug=team_slug,
            #     api_token=api_token,
            #     provider="books",
            #     file_name=file_name,
            #     file_data=pdf_data,
            #     expiration_datetime=(datetime.now() + timedelta(days=1)).isoformat(),
            #     access_public=False,
            #     folder_path="books"
            # )
        else:
            # Existing EPUB processing
            # Create a new EPUB file with translated content
            output_epub = os.path.join(temp_dir, "output_translated.epub")
            with zipfile.ZipFile(output_epub, 'w') as zip_ref:
                for root, dirs, files in os.walk(extract_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, extract_dir)
                        zip_ref.write(file_path, arcname)

            # Read the translated EPUB data
            with open(output_epub, "rb") as f:
                translated_epub_data = f.read()

            # Define the EPUB file name
            file_name = f"{quote(title)}_translated_{output_language}.epub"

            # Upload the translated EPUB
            file_info = await upload(
                team_slug=team_slug,
                api_token=api_token,
                provider="books",
                file_name=file_name,
                file_data=translated_epub_data,
                expiration_datetime=(datetime.now() + timedelta(days=1)).isoformat(),
                access_public=False,
                folder_path="books"
            )

        return file_info