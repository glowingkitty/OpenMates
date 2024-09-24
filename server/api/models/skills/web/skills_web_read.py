from pydantic import BaseModel, Field
from typing import List, Optional

# GET /skill/web/read (read a web page)

class WebReadInput(BaseModel):
    """This is the model for the input of the web read skill"""
    url: str = Field(..., description="URL of the web page")
    include_images: bool = Field(True, description="Whether to include images in the output")

class WebReadOutput(BaseModel):
    """This is the model for the output of the web read skill"""
    url: str = Field(..., description="URL of the web page")
    title: str = Field(..., description="Title of the web page")
    content: str = Field(..., description="Content of the web page in markdown format")
    description: Optional[str] = Field(None, description="Description of the web page")
    keywords: Optional[List[str]] = Field(None, description="Keywords of the web page")
    authors: Optional[List[str]] = Field(None, description="Authors of the web page")
    publisher: Optional[str] = Field(None, description="Publisher of the web page")
    published_date: Optional[str] = Field(None, description="Published date of the web page")
    html: Optional[str] = Field(None, description="HTML content of the web page")

web_read_input_examples = [
    "https://www.digitalwaffle.co/job/product-designer-51",
    "https://machine-learning-made-simple.medium.com/openai-is-lying-about-o-1s-medical-diagnostic-capabilities-e5f4b4036eb8",
    "https://www.theverge.com/2024/9/20/24248356/iphone-16-camera-photographic-styles",
    "https://www.theverge.com/2024/9/20/24249856/battery-ev-renewable-energy-doe-funding",
    "https://www.tagesschau.de/inland/gesellschaft/fridays-for-future-254.html",
    "https://www.anthropic.com/news/claude-3-5-sonnet"
]

web_read_input_example = {
    "url": "https://www.anthropic.com/news/claude-3-5-sonnet",
    "include_images": True
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