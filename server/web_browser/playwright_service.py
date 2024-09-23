# playwright_service.py
from fastapi import FastAPI, HTTPException
from playwright.async_api import async_playwright
from pydantic import BaseModel
import logging


logger = logging.getLogger(__name__)

async def api_startup():
    global playwright, browser
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    logger.info("Playwright browser started")

async def api_shutdown():
    global playwright, browser
    if browser:
        await browser.close()


async def lifespan(app: FastAPI):
    await api_startup()
    yield
    await api_shutdown()

app = FastAPI(lifespan=lifespan)

class URLRequest(BaseModel):
    url: str

@app.post("/view")
async def view_page(request: URLRequest):
    try:
        # TODO implement secret key to make sure only restapi can call this
        page = await browser.new_page()
        await page.goto(request.url)
        content = await page.content()
        await page.close()
        return {"content": content}
    except Exception as e:
        logger.exception("An error occurred while viewing the web page")
        raise HTTPException(status_code=500, detail="An error occurred while viewing the web page")