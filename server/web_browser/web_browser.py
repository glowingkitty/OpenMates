# playwright_service.py
from fastapi import FastAPI, HTTPException, Request
from playwright.async_api import async_playwright
from pydantic import BaseModel
import logging
from newspaper import Article, ArticleException
import os
from read import process_content
from markdownify import markdownify as md

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

WEB_BROWSER_SECRET_KEY = os.getenv("WEB_BROWSER_SECRET_KEY")

async def api_startup():
    global playwright, browser
    logger.info("Starting Playwright...")
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    logger.info("Playwright browser started")

async def api_shutdown():
    global playwright, browser
    if browser:
        logger.info("Closing Playwright browser...")
        await browser.close()
        logger.info("Playwright browser closed")


async def lifespan(app: FastAPI):
    await api_startup()
    yield
    await api_shutdown()

app = FastAPI(lifespan=lifespan)

class URLRequest(BaseModel):
    url: str
    include_images: bool = True

@app.post("/view")
async def view_page(request: URLRequest, req: Request):
    try:
        logger.debug(f"Received request to view page: {request.url}")
        auth_header = req.headers.get("Authorization")
        if auth_header != f"Bearer {WEB_BROWSER_SECRET_KEY}":
            logger.warning("Unauthorized access attempt")
            raise HTTPException(status_code=403, detail="Forbidden")

        # TODO check if url is harmful

        page = None
        try:
            page = await browser.new_page()
            logger.debug(f"Navigating to URL: {request.url}")
            await page.goto(request.url)
            logger.debug("Page loaded")
            content = await page.content()
            title = await page.title()
            logger.debug(f"Page title: {title}")
        finally:
            if page:
                await page.close()
                logger.debug("Page closed")

        return {
            "url": request.url,
            "title": title
        }
    except Exception as e:
        logger.exception("An error occurred while viewing the web page")
        raise HTTPException(status_code=500, detail="An error occurred while viewing the web page")


@app.post("/read")
async def read_page(request: URLRequest, req: Request):
    try:
        logger.debug(f"Received request to read page.")
        auth_header = req.headers.get("Authorization")
        if auth_header != f"Bearer {WEB_BROWSER_SECRET_KEY}":
            logger.warning("Unauthorized access attempt")
            raise HTTPException(status_code=403, detail="Forbidden")

        # TODO check if url is harmful

        article = Article(request.url)
        try:
            article.download()
            article.parse()
            logger.debug(f"Newspaper parsed the web page.")
        except ArticleException as e:
            logger.warning(f"Newspaper failed to parse the web page: {e}")
            article = None

        if article and article.authors:
            logger.debug("Article has authors, processing as news article.")
            full_content = process_content(article=article, base_url=request.url, include_images=request.include_images)
            return {
                "url": request.url,
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
            await page.goto(request.url, wait_until='networkidle')
            content = await page.content()
            main_content = await page.query_selector("main")
            if main_content:
                main_html = await main_content.inner_html()
            else:
                main_html = await page.inner_html("body")
            await page.close()
            logger.debug("Playwright loaded the web page.")
            markdown_content = md(main_html)
            return {
                "url": request.url,
                "title": article.title if article else "No Title",
                "text": markdown_content,
                "html": content
            }
    except Exception as e:
        logger.exception("An error occurred while reading the web page")
        raise HTTPException(status_code=500, detail="An error occurred while reading the web page")