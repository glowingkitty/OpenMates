################
# Default Imports
################
import sys
import os
import re

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
from server.api.endpoints.skills.ai.ask import ask as ask_ai
from datetime import datetime, timedelta
from ebooklib import epub
from urllib.parse import quote
import tempfile
from bs4 import BeautifulSoup
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def inspect_epub(epub_path: str):
    book = epub.read_epub(epub_path)
    
    # Log metadata
    logger.info("EPUB Metadata:")
    for metadata_type, values in book.metadata.items():
        for value in values:
            logger.info(f"  {metadata_type}: {value}")
    
    # Log spine
    logger.info("\nEPUB Spine:")
    for item in book.spine:
        logger.info(f"  {item}")
    
    # Log table of contents
    logger.info("\nEPUB Table of Contents:")
    def log_toc(toc, level=0):
        for item in toc:
            if isinstance(item, epub.Link):
                logger.info(f"{'  ' * level}- {item.title} ({item.href})")
            elif isinstance(item, epub.Section):
                logger.info(f"{'  ' * level}+ {item.title}")
                log_toc(item, level + 1)
    log_toc(book.toc)
    
    # Log all items
    logger.info("\nEPUB Items:")
    for item in book.get_items():
        logger.info(f"\nItem: {item.get_name()} (Type: {type(item)})")
        logger.info(f"  File Name: {item.file_name}")
        logger.info(f"  Media Type: {item.media_type}")
        
        if isinstance(item, epub.EpubHtml):
            logger.info("  Content (HTML):")
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            logger.info(f"    Title: {soup.title.string if soup.title else 'No title'}")
            logger.info(f"    Text snippet: {soup.get_text()[:200]}...")
        elif isinstance(item, epub.EpubNcx):
            logger.info("  Content (NCX):")
            soup = BeautifulSoup(item.get_content(), 'xml')
            logger.info(f"    NavMap items: {len(soup.find_all('navPoint'))}")
        elif isinstance(item, epub.EpubNav):
            logger.info("  Content (Nav):")
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            logger.info(f"    Nav items: {len(soup.find_all('li'))}")
        elif item.media_type.startswith('image/'):
            logger.info(f"  Image file: {item.file_name}")
        else:
            logger.info(f"  Content snippet: {item.get_content()[:200]}...")

async def translate(
    team_slug: str,
    api_token: str,
    ebook_data: bytes,
    output_language: str
) -> FilesUploadOutput:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as temp_file:
        temp_file.write(ebook_data)
        temp_file_path = temp_file.name

    try:
        book = epub.read_epub(temp_file_path)

        # Translate title
        original_title = book.get_metadata('DC', 'title')[0][0]
        translated_title = example_translate(original_title, output_language)
        book.set_title(translated_title)

        # Translate content
        for item in book.get_items():
            if isinstance(item, epub.EpubHtml):
                logger.info(f"Translating HTML content: {item.get_name()}")
                content = item.get_content().decode('utf-8')
                translated_content = translate_html_content(content, output_language)
                item.set_content(translated_content.encode('utf-8'))
            elif isinstance(item, epub.EpubNcx):
                logger.info(f"Updating NCX: {item.get_name()}")
                soup = BeautifulSoup(item.content, 'xml')
                for text in soup.find_all('text'):
                    text.string = example_translate(text.string, output_language)
                item.content = str(soup)
            elif isinstance(item, epub.EpubNav):
                logger.info(f"Updating Nav: {item.get_name()}")
                content = item.get_content().decode('utf-8')
                translated_content = translate_html_content(content, output_language)
                item.set_content(translated_content.encode('utf-8'))

        # Update TOC
        new_toc = []
        for toc_item in book.toc:
            if isinstance(toc_item, epub.Link):
                toc_item.title = example_translate(toc_item.title, output_language)
            new_toc.append(toc_item)
        book.toc = new_toc

        # Save the translated epub
        translated_epub_path = tempfile.mktemp(suffix=".epub")
        epub.write_epub(translated_epub_path, book)

        with open(translated_epub_path, 'rb') as f:
            translated_epub_data = f.read()

        # Upload the translated file
        expiration_datetime = datetime.now() + timedelta(days=1)
        file_info = await upload(
            team_slug=team_slug,
            api_token=api_token,
            provider="books",
            file_name=f"{quote(translated_title)}.epub",
            file_data=translated_epub_data,
            expiration_datetime=expiration_datetime.isoformat(),
            access_public=False,
            folder_path="books"
        )

        return file_info

    except Exception as e:
        logger.error(f"Error during translation: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error processing EPUB file: {str(e)}")
    finally:
        os.remove(temp_file_path)
        if os.path.exists(translated_epub_path):
            os.remove(translated_epub_path)

def example_translate(text: str, target_language: str) -> str:
    return f"Here would be the translation of '{text}' to {target_language}"

def translate_html_content(content: str, target_language: str) -> str:
    soup = BeautifulSoup(content, 'html.parser')
    for tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p']):
        if tag.string:
            tag.string = example_translate(tag.string, target_language)
    return str(soup)