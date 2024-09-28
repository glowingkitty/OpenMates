from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin
from newspaper import Article, ArticleException
from markdownify import markdownify as md
import logging
from playwright.async_api import Browser, Page, ElementHandle, BrowserContext

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
    full_content = re.sub(r'\n +', '\n', full_content)  # Replace lines with only spaces with a single newline
    full_content = re.sub(r'\n{2,}', '\n', full_content)  # Replace multiple empty lines with a single empty line
    full_content = re.sub(r' +', ' ', full_content)  # Replace multiple spaces with a single space
    full_content = re.sub(r' *\n', '\n', full_content)  # Remove trailing spaces at the end of lines

    return full_content.strip()


def replace_relative_urls(html, base_url):
    return re.sub(r'src="(/[^"]+)"', lambda match: f'src="{urljoin(base_url, match.group(1))}"', html)


async def read(url: str, include_images: bool, browser: BrowserContext):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            article: Article = Article(url)
            try:
                article.download()
                article.parse()
                logger.debug(f"Newspaper parsed the web page.")
            except ArticleException as e:
                logger.warning(f"Newspaper failed to parse the web page.")
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

                # Open the page
                logger.debug("Loading web page with Playwright")
                page: Page = await browser.new_page()

                response = await page.goto(url, wait_until='domcontentloaded', timeout=15000)

                # Check if the final URL is different from the initial URL (indicating a redirect)
                if response.url != url:
                    logger.debug(f"Redirected to: {response.url}")

                # Wait for a specific element to ensure the page is fully loaded
                await page.wait_for_selector("body", state="attached")

                content: str = await page.content()
                logger.debug("Playwright loaded the web page.")

                if content.strip() == "":
                    logger.warning(f"Page is empty")
                    raise Exception("Page is empty")
                else:
                    logger.debug(f"Page is not empty")

                main_content: ElementHandle = await page.query_selector("article")
                if main_content:
                    text_content = await main_content.inner_text()
                    if not text_content.strip():
                        main_content = None
                    else:
                        logger.debug("Article tag found")

                if not main_content:
                    logger.debug("No article tag found or it is empty, trying main")
                    main_content: ElementHandle = await page.query_selector("main")
                    if main_content:
                        text_content = await main_content.inner_text()
                        if not text_content.strip():
                            main_content = None
                        else:
                            logger.debug("Main tag found")

                if main_content:
                    main_html: str = await main_content.inner_html()
                else:
                    logger.debug("No main tag found, using the entire page content")
                    main_html: str = content  # Fallback to the entire page content if no specific tag is found

                main_html: str = replace_relative_urls(main_html, url)
                await page.close()
                logger.debug("Playwright closed the web page.")
                markdown_content: str = md(main_html)

                # Remove duplicate headlines and images
                markdown_content: str = remove_duplicates(markdown_content)

                if not include_images:
                    markdown_content = re.sub(r'!\[.*?\]\(.*?\)', '', markdown_content)

                # Replace multiple empty lines with a single empty line
                markdown_content = re.sub(r'\n{3,}', '\n\n', markdown_content)
                markdown_content = re.sub(r'\n{2,}', '\n', markdown_content)
                markdown_content = re.sub(r'\n +', '\n', markdown_content)  # Replace lines with only spaces with a single newline
                markdown_content = re.sub(r' +', ' ', markdown_content)  # Replace multiple spaces with a single space
                markdown_content = re.sub(r' *\n', '\n', markdown_content)  # Remove trailing spaces at the end of lines

                return {
                    "url": url,
                    "title": article.title if article else "No Title",
                    "text": markdown_content,
                    "html": content
                }
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                raise
            else:
                logger.info(f"Retrying... ({attempt + 1}/{max_retries})")
                await asyncio.sleep(2)  # Optional: wait before retrying


def remove_duplicates(content: str) -> str:
    lines: list[str] = content.split('\n')
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        if line.strip() and line not in seen:
            result.append(line)
            seen.add(line)
        elif not line.strip():
            result.append(line)
    # Remove excessive newlines
    result = '\n'.join(result)
    result: str = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()