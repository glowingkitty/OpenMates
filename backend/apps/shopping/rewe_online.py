import requests
import json
import time
import argparse
from pathlib import Path
import logging
from typing import List, Dict, Any, Optional

# TODO: It seems product details (nutrition, ingredients, etc.) are rendered in the HTML of the product detail page (detail_link).
# There might not be a separate API endpoint for this. Consider using BeautifulSoup (bs4) to parse the HTML if these details are needed.

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class REWEProductSearcher:
    BASE_DOMAIN = "https://shop.rewe.de" # Base domain for constructing detail URLs

    def __init__(self, market_code="240557"):
        self.base_url = f"{self.BASE_DOMAIN}/api/products"
        self.market_code = market_code
        # Using a common browser user agent
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36', # Slightly different UA
            'Accept': 'application/vnd.rewe.productlist+json',
            'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8', # Added english as fallback
            'Referer': f'{self.BASE_DOMAIN}/c/', # More generic referer
            'Origin': self.BASE_DOMAIN,
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'TE': 'trailers' # Sometimes helps
        }

    def _search_single_page(self, search_term: str, page: int = 1, objects_per_page: int = 80, service_type: str = "DELIVERY") -> Optional[Dict[str, Any]]:
        """Performs a product search for a single page"""
        params = {
            'objectsPerPage': objects_per_page,
            'page': page,
            'search': search_term,
            'serviceTypes': service_type,
            'market': self.market_code,
            'debug': 'false',
            'autoCorrect': 'true'
        }

        logger.info(f"Requesting page {page} for '{search_term}'...")

        try:
            response = requests.get(
                self.base_url,
                headers=self.headers,
                params=params,
                timeout=25 # Increased timeout slightly
            )
            logger.debug(f"Request URL: {response.url}") # Log the exact URL requested
            response.raise_for_status()  # Raise error for HTTP status code >= 400
            return response.json()
        except requests.exceptions.Timeout:
            logger.error(f"Timeout requesting page {page} for '{search_term}'")
            return None
        except requests.exceptions.HTTPError as e:
             logger.error(f"HTTP Error requesting page {page} for '{search_term}': {e.response.status_code} {e.response.reason}")
             logger.debug(f"Response text: {e.response.text[:500]}...") # Log response text on HTTP error
             return None
        except requests.exceptions.RequestException as e:
            logger.error(f"General Request Error requesting page {page} for '{search_term}': {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON Decode Error on page {page} for '{search_term}': {e}")
            logger.debug(f"Response text: {response.text[:500]}...") # Log response text on JSON error
            return None

    def extract_simplified_product_data(self, page_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extracts ONLY the desired fields (Name, Price, Category, Image, ID, Link)"""
        extracted_products = []
        products_raw = page_data.get('_embedded', {}).get('products', [])

        if not products_raw:
            # This is normal for later pages if total results aren't a multiple of objectsPerPage
            # logger.warning("No products found in '_embedded.products' for this page.")
            return extracted_products

        for product in products_raw:
            product_info = {}

            # 1. ID
            product_info['id'] = product.get('id')

            # 2. Name
            product_info['name'] = product.get('productName')

            # 3. Category Path
            # Sometimes categoryPath is directly under _embedded, sometimes under product._embedded
            category_path = product.get('_embedded', {}).get('categoryPath')
            if not category_path and '_embedded' in page_data: # Check top level if not in product
                 category_path = page_data.get('_embedded', {}).get('categoryPath') # Fallback, less likely useful
            product_info['category'] = category_path

            # 4. Image URL (taking the first image)
            images = product.get('media', {}).get('images', [])
            if images and isinstance(images, list) and len(images) > 0:
                 image_link = images[0].get('_links', {}).get('self', {}).get('href')
                 product_info['product_image'] = image_link
            else:
                 product_info['product_image'] = None

            # 5. Detail Link
            detail_link_path = product.get('_links', {}).get('detail', {}).get('href')
            if detail_link_path:
                product_info['detail_link'] = f"{self.BASE_DOMAIN}{detail_link_path}"
            else:
                product_info['detail_link'] = None

            

            # 6. Price (taking from the first article's listing)
            articles = product.get('_embedded', {}).get('articles', [])
            if articles and isinstance(articles, list) and len(articles) > 0:
                article = articles[0] # Assume first article
                listing = article.get('_embedded', {}).get('listing', {})
                pricing = listing.get('pricing', {})
                price_cents = pricing.get('currentRetailPrice')
                product_info['price'] = round(price_cents / 100.0, 2) if price_cents is not None else None
            else:
                product_info['price'] = None # Set price to None if no article/listing/pricing found

            # Only add if essential info is present (e.g., id and name)
            if product_info.get('id') and product_info.get('name'):
                extracted_products.append(product_info)
            else:
                logger.warning(f"Skipping product due to missing ID or Name: {product.get('id')}")


        return extracted_products

    def get_all_products(self, search_term: str, service_type: str = "DELIVERY", max_pages: Optional[int] = None, objects_per_page: int = 80) -> List[Dict[str, Any]]:
        """Fetches all products for a search term and extracts the simplified data"""
        all_products = []
        page = 1
        total_pages = 1 # Start with 1, update after first request
        processed_product_ids = set() # Keep track of IDs to avoid duplicates if API glitches

        while True:
            # Check if max_pages limit is reached
            if max_pages is not None and page > max_pages:
                logger.info(f"Max page limit ({max_pages}) reached.")
                break

            # Fetch data for the current page
            page_data = self._search_single_page(
                search_term,
                page=page,
                objects_per_page=objects_per_page,
                service_type=service_type
            )

            if not page_data:
                logger.warning(f"Failed to retrieve data for page {page}. Stopping pagination.")
                # Optionally: implement retries here
                break # Stop if a page fails

            # Update total_pages from the first successful response
            if page == 1:
                pagination_info = page_data.get('pagination', {})
                total_pages = pagination_info.get('totalPages', 1)
                total_results = pagination_info.get('totalResultCount', 'N/A')
                logger.info(f"API reports {total_results} total results across {total_pages} pages for '{search_term}'.")
                # Apply max_pages limit if provided
                if max_pages is not None:
                    total_pages = min(total_pages, max_pages)
                    logger.info(f"Will fetch a maximum of {total_pages} pages due to --max-pages limit.")


            # Extract simplified product data from the current page
            extracted = self.extract_simplified_product_data(page_data)
            new_products_added = 0
            if extracted:
                 for product in extracted:
                     # Avoid adding duplicates if the API returns the same product on multiple pages
                     if product.get('id') not in processed_product_ids:
                         all_products.append(product)
                         processed_product_ids.add(product.get('id'))
                         new_products_added += 1
                 logger.info(f"Extracted {new_products_added} new products from page {page}.")
            else:
                 # Check if products were expected based on pagination
                 current_page_num_api = page_data.get('pagination', {}).get('page', page)
                 if current_page_num_api <= total_pages and page_data.get('_embedded', {}).get('products'):
                     logger.warning(f"Products were present in API response for page {page}, but extraction yielded no results. Check extraction logic.")
                 elif current_page_num_api <= total_pages:
                     logger.info(f"No products found in API response for page {page} (may be expected for last page).")


            # Check if it was the last page according to API pagination
            current_page_num = page_data.get('pagination', {}).get('page', page)
            if current_page_num >= total_pages:
                logger.info(f"Reached the last page ({current_page_num}/{total_pages}).")
                break

            # Move to the next page and pause
            page += 1
            time.sleep(1.8) # Slightly longer politeness delay

        return all_products

def save_to_json(data: List[Dict[str, Any]], filename: Path):
    """Saves the data as a JSON file"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Data successfully saved to '{filename}'")
        return True
    except Exception as e:
        logger.error(f"Error saving data to '{filename}': {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="REWE Product Search - Simplified JSON Export")
    parser.add_argument("search_term", help="Search term for products")
    parser.add_argument("--output", "-o", help="Output file (JSON)", default="rewe_products_simple.json")
    parser.add_argument("--market", "-m", help="Market Code", default="240557")
    parser.add_argument("--service", "-s", help="Service Type (DELIVERY or PICKUP)", default="DELIVERY", choices=['DELIVERY', 'PICKUP'])
    parser.add_argument("--max-pages", "-p", type=int, help="Maximum number of pages to fetch")
    parser.add_argument("--per-page", type=int, default=80, help="Products per page (max 80 recommended)")

    args = parser.parse_args()

    # Validate objects per page
    if not 1 <= args.per_page <= 80:
        logger.warning("Products per page ('--per-page') should be between 1 and 80. Setting to 80.")
        args.per_page = 80

    # Ensure output path exists
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Initialize searcher and perform search
    searcher = REWEProductSearcher(market_code=args.market)
    products = searcher.get_all_products(
        args.search_term,
        service_type=args.service.upper(), # Ensure uppercase
        max_pages=args.max_pages,
        objects_per_page=args.per_page
    )

    # Save results and report count
    if products:
        if save_to_json(products, output_path):
            # This count should now be accurate based on the length of the final list
            logger.info(f"Successfully extracted and saved {len(products)} products.")
        else:
            logger.error("Failed to save the extracted products.")
    else:
        # This message appears if the final 'products' list is empty after all attempts
        logger.warning(f"No products were extracted for '{args.search_term}'. Check logs for errors or if the search term yields no results.")

if __name__ == "__main__":
    main()