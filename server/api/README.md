# How to add a new API endpoint

1. [`server/api/api.py`](api.py):
   - Add `async def` function for new endpoint, including router and limiter
2. [`server/api/models/{router}/`](models/):
   - Add `.py` file for new endpoint. This `.py` file is named similar to the endpoint function and contains the FastAPI models for this endpoint and doc examples:
     - Input
     - Output
     - examples for FastAPI docs
3. [`server/api/api.py`](api.py):
   - Add via `set_example()` each newly created example for the FastAPI docs
4. [`server/api/parameters.py`](parameters.py):
   - Add in `endpoint_metadata` the new endpoint
5. [`server/api/endpoints/{router}/`](endpoints/):
   - Add `.py` file for new endpoint, which does the actual processing of the request and which returns the response.