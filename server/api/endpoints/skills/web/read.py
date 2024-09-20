from server.api.models.skills.web.skills_web_read import WebReadOutput
import logging
from fastapi import HTTPException
from newspaper import Article
import re
from bs4 import BeautifulSoup

# Set up logger
logger = logging.getLogger(__name__)

def process_content(article):
    # Parse the HTML content
    soup = BeautifulSoup(article.html, 'html.parser')

    # Process the content to create a markdown structure
    markdown_content = []

    for element in soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'img']):
        if element.name == 'p':
            markdown_content.append(f"\n{element.get_text().strip()}\n")
        elif element.name.startswith('h'):
            level = int(element.name[1])
            markdown_content.append(f"\n{'#' * level} {element.get_text().strip()}\n")
        elif element.name == 'img':
            src = element.get('src', '')
            alt = element.get('alt', 'Image')
            if src:
                markdown_content.append(f"\n![{alt}]({src})\n")

    # Join the content and remove excessive newlines
    full_content = '\n'.join(markdown_content)
    full_content = re.sub(r'\n{3,}', '\n\n', full_content)

    return full_content.strip()

async def read(url: str) -> WebReadOutput:
    try:
        logger.debug(f"Reading web page with URL: {url}")

        # Create an Article object
        article = Article(url)

        # Download and parse the article
        article.download()
        article.parse()

        # Process the content
        full_content = process_content(article)

        web_read_output: WebReadOutput = WebReadOutput(
            url=url,
            title=article.title,
            content=full_content,
            description=article.meta_description,
            keywords=article.keywords,
            authors=article.authors,
            publisher=article.source_url,
            published_date=article.publish_date.isoformat() if article.publish_date else None
        )

        logger.debug(f"Successfully read web page with URL: {url}")

        return web_read_output

    except Exception as e:
        logger.exception(f"An error occurred while reading the web page: {str(e)}")
        raise HTTPException(status_code=500, detail="An error occurred while reading the web page.")