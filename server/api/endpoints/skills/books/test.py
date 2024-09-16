import zipfile
import re
import os
import json
from bs4 import BeautifulSoup
import tiktoken

def extract_html_files(epub_path: str, extract_to: str) -> list:
    with zipfile.ZipFile(epub_path, 'r') as epub:
        epub.extractall(extract_to)
    
    html_files = []
    for root, _, files in os.walk(extract_to):
        for file in files:
            if file.endswith('.html') or file.endswith('.xhtml'):
                html_files.append(os.path.join(root, file))
    return html_files

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

def write_chunks_to_markdown(chunks: list, output_path: str):
    with open(output_path, 'w', encoding='utf-8') as md_file:
        for i, chunk in enumerate(chunks):
            md_file.write(f"### Chunk {i+1}\n")
            md_file.write(chunk)
            md_file.write("\n\n---\n\n")

def count_tokens(text: str) -> int:
    enc = tiktoken.encoding_for_model("gpt-4o")
    return len(enc.encode(text))

def create_json_overview(chunks: list, json_output_path: str):
    chunk_info = []
    token_counts = []

    for i, chunk in enumerate(chunks):
        token_count = count_tokens(chunk)
        chunk_info.append({
            "chunk": f"Chunk {i+1}",
            "token_count": token_count
        })
        token_counts.append(token_count)

    overview = {
        "total_chunks": len(chunks),
        "largest_chunk_count": max(token_counts),
        "smallest_chunk_count": min(token_counts),
        "chunks": chunk_info
    }

    with open(json_output_path, 'w', encoding='utf-8') as json_file:
        json.dump(overview, json_file, indent=4)

def process_epub_to_markdown(epub_path: str, output_file: str, temp_dir: str, json_output_path: str):
    html_files = extract_html_files(epub_path, temp_dir)
    all_chunks = []

    for html_file in html_files:
        print(f"Processing file: {html_file}")  # Debugging information
        body_content = extract_body_content(html_file)
        if body_content:
            chunks = split_into_chunks(body_content)
            all_chunks.extend(chunks)
        else:
            print(f"No body content found in {html_file}")

    if all_chunks:
        write_chunks_to_markdown(all_chunks, output_file)
        create_json_overview(all_chunks, json_output_path)
        print(f"Chunks have been written to {output_file}")
        print(f"Overview JSON has been written to {json_output_path}")
    else:
        print("No chunks were created. The resulting markdown file is empty.")

if __name__ == "__main__":
    epub_path = "tests/paid/api/endpoints/skills/books/test_ebook.epub"
    output_file = "tests/paid/api/endpoints/skills/books/test_ebook.md"
    json_output_path = "tests/paid/api/endpoints/skills/books/test_ebook.json"
    temp_dir = "tests/paid/api/endpoints/skills/books/test_ebook"
    process_epub_to_markdown(epub_path, output_file, temp_dir, json_output_path)