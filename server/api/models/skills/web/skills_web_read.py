from pydantic import BaseModel, Field
from typing import List, Optional

# GET /skill/web/read (read a web page)

class WebReadInput(BaseModel):
    """This is the model for the input of the web read skill"""
    url: str = Field(..., description="URL of the web page")

class WebReadOutput(BaseModel):
    """This is the model for the output of the web read skill"""
    url: str = Field(..., description="URL of the web page")
    title: str = Field(..., description="Title of the web page")
    content: str = Field(..., description="Content of the web page")
    description: Optional[str] = Field(..., description="Description of the web page")
    keywords: Optional[List[str]] = Field(..., description="Keywords of the web page")
    authors: Optional[List[str]] = Field(..., description="Authors of the web page")
    publisher: Optional[str] = Field(..., description="Publisher of the web page")
    published_date: Optional[str] = Field(..., description="Published date of the web page")


web_read_input_examples = [
    "https://www.theverge.com/2024/9/20/24248356/iphone-16-camera-photographic-styles",
    "https://www.theverge.com/2024/9/20/24249856/battery-ev-renewable-energy-doe-funding",
    "https://www.tagesschau.de/inland/gesellschaft/fridays-for-future-254.html",
    "https://www.anthropic.com/news/claude-3-5-sonnet"
]

web_read_input_example = {
    "url": "https://www.anthropic.com/news/claude-3-5-sonnet"
}

web_read_output_example = {
    "url": "https://www.anthropic.com/news/claude-3-5-sonnet",
    "title": "Introducing Claude 3.5 Sonnet",
    "content": "# Claude 3.5 Sonnet\n\n![Claude head illustration](https://www.anthropic.com/_next/image?url=htt...",
    "description": "Introducing Claude 3.5 Sonnet—our most intelligent model yet. Sonnet now outperforms competitor models and Claude 3 Opus on key evaluations, at twice the speed.",
    "keywords": [],
    "authors": [],
    "publisher": "https://www.anthropic.com",
    "published_date": None
}