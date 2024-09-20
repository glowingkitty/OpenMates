from server.api.models.skills.web.skills_web_read import WebReadOutput
import logging
from fastapi import HTTPException
from newspaper import Article, ArticleException
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Set up logger
logger = logging.getLogger(__name__)

def process_content(article, base_url, include_images):
    # Parse the HTML content
    soup: BeautifulSoup = BeautifulSoup(article.html, 'html.parser')

    # Process the content to create a markdown structure
    markdown_content = []
    previous_element = None

    for element in soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'img']):
        current_content = None

        if element.name == 'p':
            current_content = f"\n{element.get_text().strip()}\n"
        elif element.name.startswith('h'):
            level = int(element.name[1])
            current_content = f"\n{'#' * level} {element.get_text().strip()}\n"
        elif element.name == 'img' and include_images:
            src = element.get('src', '')
            alt = element.get('alt', 'Image')

            # Skip SVGs and GIFs
            if 'svg' in src.lower():
                continue

            # Include all other images
            if src:
                full_src = urljoin(base_url, src)
                current_content = f"\n![{alt}]({full_src})\n"

        if current_content and current_content != previous_element:
            markdown_content.append(current_content)
            previous_element = current_content

    # Join the content and remove excessive newlines
    full_content = '\n'.join(markdown_content)
    full_content = re.sub(r'\n{3,}', '\n\n', full_content)

    return full_content.strip()

async def read(
        url: str,
        include_images: bool = True
    ) -> WebReadOutput:
    """
    Read a web page and return the content in markdown format.
    """
    try:
        logger.debug(f"Reading web page with URL: {url}")

        # Create an Article object
        article: Article = Article(url)

        # Download and parse the article
        article.download()
        article.parse()

        # Process the content with the base URL and include_images parameter
        full_content: str = process_content(article=article, base_url=url, include_images=include_images)

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

    except ArticleException:
        logger.exception(f"Newspaper3k couldn't parse the web page.")
        raise HTTPException(status_code=404, detail="Could not load the web page.")

    except Exception as e:
        logger.exception(f"An error occurred while reading the web page.")
        raise HTTPException(status_code=500, detail="An error occurred while reading the web page.")