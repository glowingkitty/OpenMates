# backend/tests/test_url_validator.py
# Tests for URL validation and extraction functionality.

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

# Add backend directory to Python path for imports
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from apps.ai.processing.url_validator import (
    extract_urls_from_markdown,
    check_url_status,
    validate_urls_in_paragraph
)


class TestExtractUrlsFromMarkdown:
    """Test URL extraction from markdown text"""
    
    @pytest.mark.asyncio
    async def test_extract_single_url(self):
        """Test extracting a single markdown link"""
        markdown = "Check out [Python docs](https://docs.python.org/) for more info."
        urls = await extract_urls_from_markdown(markdown)
        
        assert len(urls) == 1
        assert urls[0]['url'] == "https://docs.python.org/"
        assert urls[0]['text'] == "Python docs"
        assert urls[0]['full_match'] == "[Python docs](https://docs.python.org/)"
        assert urls[0]['start_pos'] == 10
        assert urls[0]['end_pos'] == 49  # match.end() returns position after last character
    
    @pytest.mark.asyncio
    async def test_extract_multiple_urls(self):
        """Test extracting multiple markdown links"""
        markdown = """
        See [Python docs](https://docs.python.org/) and 
        [FastAPI docs](https://fastapi.tiangolo.com/) for more information.
        """
        urls = await extract_urls_from_markdown(markdown)
        
        assert len(urls) == 2
        assert urls[0]['url'] == "https://docs.python.org/"
        assert urls[0]['text'] == "Python docs"
        assert urls[1]['url'] == "https://fastapi.tiangolo.com/"
        assert urls[1]['text'] == "FastAPI docs"
    
    @pytest.mark.asyncio
    async def test_extract_no_urls(self):
        """Test extracting from text with no URLs"""
        markdown = "This is just plain text with no links."
        urls = await extract_urls_from_markdown(markdown)
        
        assert len(urls) == 0
    
    @pytest.mark.asyncio
    async def test_extract_urls_with_special_characters(self):
        """Test extracting URLs with special characters in text"""
        markdown = "Check [Python 3.12 docs](https://docs.python.org/3.12/) here."
        urls = await extract_urls_from_markdown(markdown)
        
        assert len(urls) == 1
        assert urls[0]['url'] == "https://docs.python.org/3.12/"
        assert urls[0]['text'] == "Python 3.12 docs"
    
    @pytest.mark.asyncio
    async def test_extract_http_and_https(self):
        """Test extracting both HTTP and HTTPS URLs"""
        markdown = """
        [HTTP link](http://example.com) and 
        [HTTPS link](https://example.com)
        """
        urls = await extract_urls_from_markdown(markdown)
        
        assert len(urls) == 2
        assert urls[0]['url'] == "http://example.com"
        assert urls[1]['url'] == "https://example.com"


class TestCheckUrlStatus:
    """Test URL status checking"""
    
    @pytest.mark.asyncio
    async def test_valid_url_200(self):
        """Test checking a valid URL with 200 status"""
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.head = AsyncMock(return_value=mock_response)
            
            result = await check_url_status("https://example.com")
            
            assert result['is_valid'] is True
            assert result['status_code'] == 200
            assert result['error_type'] is None
            assert result['is_temporary'] is False
    
    @pytest.mark.asyncio
    async def test_broken_url_404(self):
        """Test checking a broken URL with 404 status"""
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_client.return_value.__aenter__.return_value.head = AsyncMock(return_value=mock_response)
            
            result = await check_url_status("https://example.com/not-found")
            
            assert result['is_valid'] is False
            assert result['status_code'] == 404
            assert result['error_type'] == '4xx'
            assert result['is_temporary'] is False
    
    @pytest.mark.asyncio
    async def test_broken_url_403(self):
        """Test checking a forbidden URL with 403 status"""
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_client.return_value.__aenter__.return_value.head = AsyncMock(return_value=mock_response)
            
            result = await check_url_status("https://example.com/forbidden")
            
            assert result['is_valid'] is False
            assert result['status_code'] == 403
            assert result['error_type'] == '4xx'
            assert result['is_temporary'] is False
    
    @pytest.mark.asyncio
    async def test_server_error_500(self):
        """Test checking a URL with 500 server error (temporary)"""
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_client.return_value.__aenter__.return_value.head = AsyncMock(return_value=mock_response)
            
            result = await check_url_status("https://example.com/error")
            
            assert result['is_valid'] is False
            assert result['status_code'] == 500
            assert result['error_type'] == '5xx'
            assert result['is_temporary'] is True
    
    @pytest.mark.asyncio
    async def test_timeout_error(self):
        """Test handling timeout errors"""
        with patch('apps.ai.processing.url_validator.httpx.AsyncClient') as mock_client:
            # Exception should be raised when entering the context manager
            mock_client.return_value.__aenter__ = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
            
            result = await check_url_status("https://example.com")
            
            assert result['is_valid'] is False
            assert result['status_code'] is None
            assert result['error_type'] == 'timeout'
            assert result['is_temporary'] is True
    
    @pytest.mark.asyncio
    async def test_connection_error(self):
        """Test handling connection errors"""
        with patch('apps.ai.processing.url_validator.httpx.AsyncClient') as mock_client:
            # Exception should be raised when entering the context manager
            mock_client.return_value.__aenter__ = AsyncMock(side_effect=httpx.ConnectError("Connection failed"))
            
            result = await check_url_status("https://example.com")
            
            assert result['is_valid'] is False
            assert result['status_code'] is None
            assert result['error_type'] == 'connection_error'
            assert result['is_temporary'] is True
    
    @pytest.mark.asyncio
    async def test_head_fallback_to_get(self):
        """Test fallback to GET when HEAD fails"""
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client_instance = mock_client.return_value.__aenter__.return_value
            mock_client_instance.head = AsyncMock(side_effect=httpx.HTTPError("HEAD failed"))
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            
            result = await check_url_status("https://example.com")
            
            assert result['is_valid'] is True
            assert result['status_code'] == 200
            # Verify GET was called as fallback
            mock_client_instance.get.assert_called_once()


class TestValidateUrlsInParagraph:
    """Test URL validation in paragraphs"""
    
    @pytest.mark.asyncio
    async def test_validate_paragraph_with_valid_urls(self):
        """Test validating a paragraph with valid URLs"""
        paragraph = "Check [Python docs](https://docs.python.org/) and [FastAPI](https://fastapi.tiangolo.com/)"
        
        with patch('apps.ai.processing.url_validator.check_url_status') as mock_check:
            mock_check.side_effect = [
                {'is_valid': True, 'status_code': 200, 'error_type': None, 'is_temporary': False},
                {'is_valid': True, 'status_code': 200, 'error_type': None, 'is_temporary': False}
            ]
            
            results = await validate_urls_in_paragraph(paragraph, "test_task_123")
            
            assert len(results) == 2
            assert all(r['is_valid'] for r in results)
            assert results[0]['url'] == "https://docs.python.org/"
            assert results[1]['url'] == "https://fastapi.tiangolo.com/"
    
    @pytest.mark.asyncio
    async def test_validate_paragraph_with_broken_urls(self):
        """Test validating a paragraph with broken URLs"""
        paragraph = "Check [Broken link](https://example.com/404) and [Another broken](https://example.com/not-found)"
        
        with patch('apps.ai.processing.url_validator.check_url_status') as mock_check:
            mock_check.side_effect = [
                {'is_valid': False, 'status_code': 404, 'error_type': '4xx', 'is_temporary': False},
                {'is_valid': False, 'status_code': 404, 'error_type': '4xx', 'is_temporary': False}
            ]
            
            results = await validate_urls_in_paragraph(paragraph, "test_task_123")
            
            assert len(results) == 2
            assert all(not r['is_valid'] for r in results)
            assert all(not r['is_temporary'] for r in results)
            assert all(r['error_type'] == '4xx' for r in results)
    
    @pytest.mark.asyncio
    async def test_validate_paragraph_mixed_urls(self):
        """Test validating a paragraph with both valid and broken URLs"""
        paragraph = "Check [Valid link](https://docs.python.org/) and [Broken link](https://example.com/404)"
        
        with patch('apps.ai.processing.url_validator.check_url_status') as mock_check:
            mock_check.side_effect = [
                {'is_valid': True, 'status_code': 200, 'error_type': None, 'is_temporary': False},
                {'is_valid': False, 'status_code': 404, 'error_type': '4xx', 'is_temporary': False}
            ]
            
            results = await validate_urls_in_paragraph(paragraph, "test_task_123")
            
            assert len(results) == 2
            assert results[0]['is_valid'] is True
            assert results[1]['is_valid'] is False
    
    @pytest.mark.asyncio
    async def test_validate_paragraph_no_urls(self):
        """Test validating a paragraph with no URLs"""
        paragraph = "This is just plain text with no links."
        
        results = await validate_urls_in_paragraph(paragraph, "test_task_123")
        
        assert len(results) == 0
    
    @pytest.mark.asyncio
    async def test_validate_paragraph_temporary_errors(self):
        """Test that temporary errors (5xx) are marked as temporary"""
        paragraph = "Check [Server error](https://example.com/error)"
        
        with patch('apps.ai.processing.url_validator.check_url_status') as mock_check:
            mock_check.return_value = {
                'is_valid': False,
                'status_code': 500,
                'error_type': '5xx',
                'is_temporary': True
            }
            
            results = await validate_urls_in_paragraph(paragraph, "test_task_123")
            
            assert len(results) == 1
            assert results[0]['is_valid'] is False
            assert results[0]['is_temporary'] is True
            assert results[0]['error_type'] == '5xx'
    
    @pytest.mark.asyncio
    async def test_validate_paragraph_exception_handling(self):
        """Test handling exceptions during URL validation"""
        paragraph = "Check [URL](https://example.com)"
        
        with patch('apps.ai.processing.url_validator.check_url_status') as mock_check:
            mock_check.side_effect = Exception("Unexpected error")
            
            results = await validate_urls_in_paragraph(paragraph, "test_task_123")
            
            assert len(results) == 1
            assert results[0]['is_valid'] is False
            assert results[0]['error_type'] == 'exception'
            assert results[0]['is_temporary'] is True
            assert 'error' in results[0]


class TestUrlValidatorIntegration:
    """Integration tests with real URLs and actual HTTP requests
    
    These tests require network access. They will be skipped if network is unavailable.
    """
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_url_validation_mixed(self):
        """Test validating a paragraph with real URLs (both valid and broken)"""
        # Using real The Verge URLs: one valid, one broken
        paragraph = """
        Check out this article about [Nvidia's Digits supercomputer](https://www.theverge.com/2025/1/6/24337530/nvidia-ces-digits-super-computer-ai) 
        from The Verge. Unfortunately, [this broken link](https://www.theverge.com/2025/1/6/2433731) doesn't exist.
        """
        
        results = await validate_urls_in_paragraph(paragraph, "integration_test_123")
        
        # Should find 2 URLs
        assert len(results) == 2
        
        # Extract URLs for easier checking
        url_results = {r['url']: r for r in results}
        
        # Valid The Verge article should be valid
        valid_url = 'https://www.theverge.com/2025/1/6/24337530/nvidia-ces-digits-super-computer-ai'
        assert valid_url in url_results
        valid_result = url_results[valid_url]
        assert valid_result['text'] == "Nvidia's Digits supercomputer"
        
        # Network MUST be available for integration tests - fail if not
        assert valid_result['is_valid'] is True, \
            f"Network unavailable or URL validation failed. Result: {valid_result}"
        assert valid_result['status_code'] in [200, 301, 302], \
            f"Expected 2xx or 3xx for valid URL, got {valid_result['status_code']}"
        assert valid_result['error_type'] is None
        assert valid_result['is_temporary'] is False
        
        # Broken The Verge link should be invalid (404)
        broken_url = 'https://www.theverge.com/2025/1/6/2433731'
        assert broken_url in url_results
        broken_result = url_results[broken_url]
        assert broken_result['is_valid'] is False, f"Expected broken URL but got: {broken_result}"
        assert broken_result['text'] == 'this broken link'
        
        # Network MUST be available - fail if we can't get status code
        assert broken_result['status_code'] is not None, \
            f"Network unavailable - cannot verify broken URL. Result: {broken_result}"
        assert broken_result['status_code'] >= 400, \
            f"Expected 4xx or 5xx for broken URL, got {broken_result['status_code']}"
        assert broken_result['error_type'] in ['4xx', '5xx'], \
            f"Expected 4xx or 5xx error type, got {broken_result['error_type']}"
        assert broken_result['is_temporary'] is False, \
            "Broken URLs (4xx) should not be marked as temporary"
        
        # Verify broken URLs are correctly identified (non-temporary errors)
        broken_urls = [r for r in results if not r.get('is_valid') and not r.get('is_temporary')]
        assert len(broken_urls) >= 1, \
            f"Expected at least 1 broken URL (non-temporary), found {len(broken_urls)}"
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_url_extraction_complex_paragraph(self):
        """Test extracting URLs from a complex paragraph with multiple links"""
        paragraph = """
        Here are some useful resources:
        - [Python 3.12 docs](https://docs.python.org/3.12/)
        - [FastAPI tutorial](https://fastapi.tiangolo.com/tutorial/)
        - [MDN Web Docs](https://developer.mozilla.org/)
        - [GitHub](https://github.com/)
        
        You can also check out [this article](https://example.com/nonexistent-article-99999) 
        and [another resource](http://httpstat.us/404) for more info.
        """
        
        urls = await extract_urls_from_markdown(paragraph)
        
        # Should extract 6 URLs (there are 6 links in the paragraph)
        assert len(urls) == 6
        
        # Verify all URLs are extracted correctly
        url_texts = {url['url']: url['text'] for url in urls}
        
        assert 'https://docs.python.org/3.12/' in url_texts
        assert url_texts['https://docs.python.org/3.12/'] == 'Python 3.12 docs'
        
        assert 'https://fastapi.tiangolo.com/tutorial/' in url_texts
        assert url_texts['https://fastapi.tiangolo.com/tutorial/'] == 'FastAPI tutorial'
        
        assert 'https://developer.mozilla.org/' in url_texts
        assert url_texts['https://developer.mozilla.org/'] == 'MDN Web Docs'
        
        assert 'https://github.com/' in url_texts
        assert url_texts['https://github.com/'] == 'GitHub'
        
        assert 'https://example.com/nonexistent-article-99999' in url_texts
        assert url_texts['https://example.com/nonexistent-article-99999'] == 'this article'
        
        assert 'http://httpstat.us/404' in url_texts
        assert url_texts['http://httpstat.us/404'] == 'another resource'
        
        # Now validate them
        results = await validate_urls_in_paragraph(paragraph, "integration_test_complex")
        
        assert len(results) == 6
        
        # Verify all URLs were processed
        assert len(results) == 6, f"Expected 6 URLs to be processed, found {len(results)}"
        
        # Network MUST be available for integration tests
        # Check that real URLs are valid
        valid_urls = [r for r in results if r.get('is_valid')]
        assert len(valid_urls) >= 2, \
            f"Network unavailable or validation failed - expected at least 2 valid URLs, " \
            f"found {len(valid_urls)}. Results: {results}"
        
        # Check that broken URLs are detected (non-temporary errors)
        broken_urls = [r for r in results if not r.get('is_valid') and not r.get('is_temporary')]
        # At least the example.com should be broken (404)
        assert len(broken_urls) >= 1, \
            f"Network unavailable or validation failed - expected at least 1 broken URL " \
            f"(non-temporary), found {len(broken_urls)}. Results: {results}"
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_url_status_check_valid(self):
        """Test checking status of a real valid URL from The Verge
        
        Requires network access. Test will fail if network is unavailable.
        """
        result = await check_url_status("https://www.theverge.com/2025/1/6/24337530/nvidia-ces-digits-super-computer-ai")
        
        # Network MUST be available for integration tests
        assert result['is_valid'] is True, \
            f"Network unavailable or URL validation failed. Result: {result}"
        assert result['status_code'] in [200, 301, 302], \
            f"Expected 2xx or 3xx for valid URL, got {result['status_code']}"
        assert result['error_type'] is None
        assert result['is_temporary'] is False
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_url_status_check_404(self):
        """Test checking status of a real broken URL from The Verge
        
        Requires network access. Test will fail if network is unavailable.
        """
        result = await check_url_status("https://www.theverge.com/2025/1/6/2433731")
        
        assert result['is_valid'] is False, f"Expected broken URL but got: {result}"
        
        # Network MUST be available - fail if we can't get status code
        assert result['status_code'] is not None, \
            f"Network unavailable - cannot verify broken URL. Result: {result}"
        assert result['status_code'] >= 400, \
            f"Expected 4xx or 5xx for broken URL, got {result['status_code']}"
        assert result['error_type'] in ['4xx', '5xx'], \
            f"Expected 4xx or 5xx error type, got {result['error_type']}"
        assert result['is_temporary'] is False, \
            "Broken URLs (4xx) should not be marked as temporary"
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_url_status_check_httpstat_404(self):
        """Test checking status of httpstat.us 404 (predictable test service)"""
        # Using httpstat.us which provides predictable HTTP status codes
        result = await check_url_status("http://httpstat.us/404")
        
        # httpstat.us might be down or have connection issues, so be flexible
        if result['status_code'] is not None:
            assert result['is_valid'] is False
            assert result['status_code'] == 404
            assert result['error_type'] == '4xx'
            assert result['is_temporary'] is False
        else:
            # If connection fails, that's also acceptable for this test
            assert result['is_valid'] is False
            assert result['error_type'] in ['timeout', 'connection_error', 'unknown_error']
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_url_status_check_httpstat_500(self):
        """Test checking status of httpstat.us 500 (predictable test service)"""
        # Using httpstat.us which provides predictable HTTP status codes
        result = await check_url_status("http://httpstat.us/500")
        
        # httpstat.us might be down or have connection issues, so be flexible
        if result['status_code'] is not None:
            assert result['is_valid'] is False
            assert result['status_code'] == 500
            assert result['error_type'] == '5xx'
            assert result['is_temporary'] is True
        else:
            # If connection fails, that's also acceptable for this test
            assert result['is_valid'] is False
            assert result['error_type'] in ['timeout', 'connection_error', 'unknown_error']

