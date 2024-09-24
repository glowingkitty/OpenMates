from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin
from newspaper import Article, ArticleException
from markdownify import markdownify as md
import logging

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


def replace_relative_urls(html, base_url):
    return re.sub(r'src="(/[^"]+)"', lambda match: f'src="{urljoin(base_url, match.group(1))}"', html)


async def read(url, include_images, browser):
    article = Article(url)
    try:
        article.download()
        article.parse()
        logger.debug(f"Newspaper parsed the web page.")
    except ArticleException as e:
        logger.warning(f"Newspaper failed to parse the web page: {e}")
        article = None

    if article and article.authors:
        logger.debug("Article has authors, processing as news article.")
        full_content = process_content(article=article, base_url=url, include_images=include_images)
        return {
            "url": url,
            "title": article.title,
            "text": full_content,
            "description": article.meta_description,
            "keywords": article.keywords,
            "authors": article.authors,
            "publish_date": article.publish_date,
            "html": article.html
        }
    else:
        logger.debug("Article has no authors or failed to parse, processing as regular web page.")
        logger.debug("Loading web page with Playwright")
        page = await browser.new_page()
        await page.goto(url, wait_until='domcontentloaded', timeout=5000)
        content = await page.content()

        main_content = await page.query_selector("article")
        if not main_content:
            main_content = await page.query_selector("main")
        if not main_content:
            main_content = await page.query_selector("body")

        if main_content:
            main_html = await main_content.inner_html()
        else:
            main_html = content  # Fallback to the entire page content if no specific tag is found

        if not main_html.strip():
            raise Exception("Main content is empty")

        main_html = replace_relative_urls(main_html, url)
        await page.close()
        logger.debug("Playwright loaded the web page.")
        markdown_content = md(main_html)

        # Remove duplicate headlines and images
        markdown_content = remove_duplicates(markdown_content)

        return {
            "url": url,
            "title": article.title if article else "No Title",
            "text": markdown_content
        }

def remove_duplicates(content):
    lines = content.split('\n')
    seen = set()
    result = []
    for line in lines:
        if line.strip() and line not in seen:
            result.append(line)
            seen.add(line)
        elif not line.strip():
            result.append(line)
    # Remove excessive newlines
    result = '\n'.join(result)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()