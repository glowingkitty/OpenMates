################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from skills.intelligence.count_tokens import count_tokens
from skills.intelligence.get_costs_chat import get_costs_chat

import html2text
import requests
from io import BytesIO
from PyPDF2 import PdfReader
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup
import http.client



def get_website_title_and_description(url: str) -> dict:
    try:
        add_to_log(module_name="Web browsing", state="start", color="yellow")
        add_to_log("Getting the website title and description ...")

        config = load_config()

        # Retrieve the HTML content of the website
        headers = {'User-Agent': config["user_agent"]["official"]}
        req = Request(url, headers=headers)
        response = urlopen(req)
        html_content = response.read().decode('utf-8')

        # Parse the HTML content with BeautifulSoup
        soup = BeautifulSoup(html_content, 'html.parser')

        # Extract the title from the HTML content
        title = soup.title.string if soup.title else None

        # Extract the description from the HTML content
        description_tag = soup.find('meta', attrs={'name': 'description'})
        description = description_tag['content'] if description_tag else None

        add_to_log("Successfully got the website title and description", state="success")

    except Exception:
        title = None
        description = None
        process_error("Failed to get the website title and description", traceback=traceback.format_exc())

    return {'title': title, 'description': description}


def convert_website_and_pdf_to_text(url: str, print_costs: bool = False) -> str:
    try:
        add_to_log(module_name="Web browsing", state="start", color="yellow")
        add_to_log("Converting the website / PDF to text ...")

        # Get the content of the website with user agent
        config = load_config()
        headers = {'User-Agent': config["user_agent"]["official"]}

        response = requests.get(url, headers=headers)

        # Check if the page was loaded successfully
        if response.status_code != 200:
            return f"URL:{url}\n\nError:\n{response.status_code}: {http.client.responses[response.status_code]}"

        # Check if the content is a PDF file
        if "content-type" in response.headers and response.headers['content-type'] == 'application/pdf':
            # Extract text from the PDF file
            pdf_content = response.content
            pdf_reader = PdfReader(BytesIO(pdf_content))
            markdown_content = ''
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                markdown_content += page.extract_text()

        else:
            # Get the HTML content of the website
            html_content = response.content.decode('utf-8')

            # Convert the HTML content to Markdown
            add_to_log("Converting the HTML content to Markdown ...")
            markdown_content = html2text.html2text(html_content)
        
        if print_costs:
            # Get the number of tokens of the full markdown file
            num_tokens = count_tokens(markdown_content)

            # Get the costs of processing the Markdown file
            costs = get_costs_chat(num_tokens)
            add_to_log(f"Number of tokens: {num_tokens}")
            add_to_log(f"Costs: {costs}")

        details = get_website_title_and_description(url)
        title = details['title']
        description = details['description']

        output_string = f"URL:{url}\n\nTitle:\n{title}\n\nDescription:\n{description}\n\nContent:\nWEBSITE START\n{markdown_content}\nWEBSITE END"

        add_to_log("Successfully converted the website / PDF to text", state="success")

        return output_string
    
    except Exception:
        process_error("Failed to convert the website / PDF to text", traceback=traceback.format_exc())
        return ""

if __name__ == "__main__":
    url = "https://design.penpot.app/api/_doc"
    text = convert_website_and_pdf_to_text(url, print_costs=True)
    # save text to markdown file
    with open("test.md", "w") as f:
        f.write(text)

    print("Output saved to test.md")