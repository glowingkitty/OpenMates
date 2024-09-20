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
    "https://www.theverge.com/2024/9/20/24248356/iphone-16-camera-photographic-styles"
]

web_read_input_example = {
    "url": "https://www.theverge.com/2024/9/20/24248356/iphone-16-camera-photographic-styles"
}

web_read_output_example = {
    "url": "https://www.theverge.com/2024/9/20/24248356/iphone-16-camera-photographic-styles",
    "title": "The iPhone camera is more confusing than ever",
    "content": "The iPhone camera is more confusing than ever ...",
    "description": "What is a camera? Its personal, it turns out.",
    "keywords": ["camera", "iPhone", "photography"],
    "authors": ["Allison Johnson"],
    "publisher": "The Verge",
    "published_date": "2024-09-20"
}