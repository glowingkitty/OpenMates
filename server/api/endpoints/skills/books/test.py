################
# Default Imports
################
import sys
import os
import re
import zipfile
import xml.etree.ElementTree as ET
import tempfile
import asyncio
import time
import shutil

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server.api import *
################

from typing import List, Dict, Any
from fastapi import HTTPException
from datetime import datetime, timedelta
from ebooklib import epub
from urllib.parse import quote
import tempfile
import json


async def translate_text(
        user_api_token: str,
        team_slug: str,
        text: str, 
        output_language: str
) -> str:
    return f"This is the translated text for '{text}' into '{output_language}'"

def split_into_chunks(content: str) -> list:
    # Find the body content
    body_match = re.search(r'<body.*?>(.*)</body>', content, re.DOTALL)
    if not body_match:
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
    
    return combined_chunks if combined_chunks else [body_content]

async def translate_xhtml_file(
        user_api_token: str,
        team_slug: str,
        file_path: str,
        output_language: str,
        total_chars: int,
        translated_chars: int,
        task_id: str,
        start_time: float
) -> int:
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
    
    # Extract content outside the body
    pre_body = re.search(r'^.*?<body.*?>', content, re.DOTALL)
    post_body = re.search(r'</body>.*?$', content, re.DOTALL)
    
    chunks = split_into_chunks(content)
    
    translated_chunks = []
    for chunk in chunks:
        # Replace processing instructions with placeholders
        pi_placeholders = {}
        for i, pi in enumerate(re.findall(r'<\?.*?\?>', chunk)):
            placeholder = f'__PI_PLACEHOLDER_{i}__'
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
        
        translated_chunks.append(translated_chunk)
    
    translated_body = "".join(translated_chunks)
    
    # Translate title if it exists
    title_match = re.search(r'<title>(.*?)</title>', content)
    if title_match:
        original_title = title_match.group(1)
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
    
    translated_chars = len(translated_content)
    
    # Update progress
    if total_chars:
        progress = (translated_chars / total_chars) * 100
    else:
        progress = 0
    elapsed_time = time.time() - start_time
    remaining_time = (elapsed_time / progress) * (100 - progress) if progress > 0 else None
    
    # Write the translated content back to the file
    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(translated_content)
    
    return translated_chars

def count_translatable_chars(file_path: str) -> int:
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
    # Remove all HTML tags and count remaining characters
    text_content = re.sub(r'<.*?>', '', content)
    return len(text_content)

async def translate(
    team_slug: str,
    api_token: str,
    input_epub_path: str,  # Change this to accept a file path
    output_language: str,
    task_id: str
):
    global translation_counter
    translation_counter = 0  # Reset the counter at the start

    # Create a temporary directory to work with the EPUB
    with tempfile.TemporaryDirectory() as temp_dir:
        # Extract the EPUB file
        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(input_epub_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)

        # Create a directory for original HTML files
        original_html_dir = os.path.join(os.path.dirname(input_epub_path), "original_html")
        os.makedirs(original_html_dir, exist_ok=True)

        # Find and process all XHTML files
        total_chars = 0
        xhtml_files = []
        all_chunks = []
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                if file.endswith('.xhtml') or file.endswith('.html'):
                    file_path = os.path.join(root, file)
                    xhtml_files.append(file_path)
                    total_chars += count_translatable_chars(file_path)
                    
                    # Save original HTML file
                    shutil.copy2(file_path, original_html_dir)
                    
                    # Extract chunks and add to all_chunks
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    chunks = split_into_chunks(content)
                    all_chunks.extend(chunks)

        # Save all chunks to a single Markdown file
        chunks_md_path = os.path.join(os.path.dirname(input_epub_path), "all_chunks.md")
        with open(chunks_md_path, 'w', encoding='utf-8') as f:
            for chunk in all_chunks:
                f.write(f"{chunk}\n\n---\n\n")

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
                translated_chars=translated_chars,
                task_id=task_id,
                start_time=start_time
            ) for file_path in xhtml_files
        ]
        results = await asyncio.gather(*tasks)
        translated_chars = sum(results)

        # Create a new EPUB file with translated content
        output_epub = os.path.join(os.path.dirname(input_epub_path), "output.epub")
        with zipfile.ZipFile(output_epub, 'w') as zip_ref:
            for root, dirs, files in os.walk(extract_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, extract_dir)
                    zip_ref.write(file_path, arcname)

        # Get the book title for the file name
        book = epub.read_epub(input_epub_path)
        title = book.get_metadata('DC', 'title')[0][0] if book.get_metadata('DC', 'title') else "Untitled"
        file_name = f"{quote(title)}_translated_{output_language}.epub"

    print(f"Translated EPUB saved as: {output_epub}")
    print(f"Original HTML files saved in: {original_html_dir}")
    print(f"All chunks saved in: {chunks_md_path}")

if __name__ == "__main__":
    asyncio.run(translate(
        team_slug="test",
        api_token="test",
        input_epub_path="tests/paid/api/endpoints/skills/books/test_ebook.epub",
        output_language="german",
        task_id="test"
    ))