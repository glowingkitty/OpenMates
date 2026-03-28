# backend/apps/home/providers/__init__.py
# Provider modules for German housing search platforms.
#
# Each provider exports an async search_listings(city, listing_type, max_results)
# function that returns normalized listing dicts with a consistent schema.
