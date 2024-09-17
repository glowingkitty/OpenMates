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
from server.api.endpoints.tasks.update import update as update_task
import time

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server.api import *
################

from typing import List, Dict, Any
from fastapi import HTTPException
from server.api.models.skills.files.skills_files_upload import FilesUploadOutput
from server.api.endpoints.skills.files.upload import upload
from server.api.endpoints.skills.ai.ask import ask
from datetime import datetime, timedelta
from ebooklib import epub
from urllib.parse import quote
import tempfile
import json
from bs4 import BeautifulSoup, NavigableString, Tag

# Global counter for translations
translation_counter = 0
TRANSLATION_LIMIT = 30

async def translate_text(
        user_api_token: str,
        team_slug: str,
        text: str, 
        output_language: str
) -> str:
    global translation_counter
    if translation_counter >= TRANSLATION_LIMIT:
        return text  # Return original text if limit is reached

    response = await ask(
        user_api_token=user_api_token,
        team_slug=team_slug,
        system=f"You are an expert translator. Translate the given text to {output_language} and output nothing else except the translation output.",
        message=text,
        provider={ "name": "chatgpt","model": "gpt-4o-mini" },
        temperature=0.5
    )
    translated_text = response["content"][0]["text"]
    translation_counter += 1  # Increment the counter
    return translated_text

def extract_body_content(file_path: str) -> str:
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return ""

    soup = BeautifulSoup(content, 'html.parser')
    body = soup.find('body')
    return str(body) if body else ""

def split_into_chunks(body_content: str) -> list:
    soup = BeautifulSoup(body_content, 'html.parser')
    chunks = []

    for tag in soup.find_all(['div', re.compile('^h[1-6]$'), 'p', 'section', 'a']):
        if tag.has_attr('class'):
            nested_divs = tag.find_all('div', class_=True)
            nested_headings = tag.find_all(re.compile('^h[1-6]$'), class_=True)
            if not nested_divs and not nested_headings:
                chunks.append(str(tag))
        else:
            chunks.append(str(tag))

    if not chunks:
        chunks.append(str(soup))

    return chunks

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

    soup = BeautifulSoup(content, 'html.parser')

    async def translate_node(node):
        if isinstance(node, NavigableString) and node.strip():
            return await translate_text(
                user_api_token=user_api_token,
                team_slug=team_slug,
                text=str(node),
                output_language=output_language
            )
        elif isinstance(node, Tag):
            for child in node.contents:
                translated_child = await translate_node(child)
                if translated_child:
                    child.replace_with(translated_child)
        return node

    # Translate title
    title_tag = soup.find('title')
    if title_tag:
        title_tag.string = await translate_text(
            user_api_token=user_api_token,
            team_slug=team_slug,
            text=title_tag.string,
            output_language=output_language
        )

    # Translate body content
    body_tag = soup.find('body')
    if body_tag:
        await translate_node(body_tag)

    translated_content = str(soup)
    translated_chars = len(translated_content)

    # Update progress
    if total_chars:
        progress = (translated_chars / total_chars) * 100
    else:
        progress = 0
    elapsed_time = time.time() - start_time
    remaining_time = (elapsed_time / progress) * (100 - progress) if progress > 0 else None
    await update_task(task_id, progress=progress, estimated_completion_time=remaining_time)

    # Write the translated content back to the file
    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(translated_content)

    return translated_chars

def count_translatable_chars(file_path: str) -> int:
    body_content = extract_body_content(file_path)
    chunks = split_into_chunks(body_content)
    return sum(len(chunk) for chunk in chunks)

async def translate(
    team_slug: str,
    api_token: str,
    ebook_data: bytes,
    output_language: str,
    task_id: str
) -> FilesUploadOutput:
    global translation_counter
    translation_counter = 0  # Reset the counter at the start

    await update_task(task_id, status="in_progress", progress=0)

    # Create a temporary directory to work with the EPUB
    with tempfile.TemporaryDirectory() as temp_dir:
        # Save the input EPUB to a temporary file
        input_epub = os.path.join(temp_dir, "input.epub")
        with open(input_epub, "wb") as f:
            f.write(ebook_data)

        # Extract the EPUB file
        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(input_epub, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)

        # Find and process all XHTML files
        total_chars = 0
        xhtml_files = []
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                if file.endswith('.xhtml') or file.endswith('.html'):
                    file_path = os.path.join(root, file)
                    xhtml_files.append(file_path)
                    total_chars += count_translatable_chars(file_path)

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
        output_epub = os.path.join(temp_dir, "output.epub")
        with zipfile.ZipFile(output_epub, 'w') as zip_ref:
            for root, dirs, files in os.walk(extract_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, extract_dir)
                    zip_ref.write(file_path, arcname)

        # Read the translated EPUB data
        with open(output_epub, "rb") as f:
            translated_epub_data = f.read()

        # Get the book title for the file name
        book = epub.read_epub(input_epub)
        title = book.get_metadata('DC', 'title')[0][0] if book.get_metadata('DC', 'title') else "Untitled"
        file_name = f"{quote(title)}_translated_{output_language}.epub"

    # Upload the translated EPUB
    expiration_datetime = datetime.now() + timedelta(days=1)
    file_info = await upload(
        team_slug=team_slug,
        api_token=api_token,
        provider="books",
        file_name=file_name,
        file_data=translated_epub_data,
        expiration_datetime=expiration_datetime.isoformat(),
        access_public=False,
        folder_path="books"
    )

    return file_info