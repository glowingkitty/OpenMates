from fastapi import FastAPI, HTTPException, Request
from playwright.async_api import async_playwright
from pydantic import BaseModel
import logging
import os
from read import read as read_processing
from playwright.async_api import BrowserContext
from context import new_context

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

        context: BrowserContext = await new_context(browser)

        return await read_processing(url=request.url, include_images=request.include_images, browser=context)
    except Exception as e:
        logger.exception("An error occurred while reading the web page")
        raise HTTPException(status_code=500, detail="An error occurred while reading the web page")