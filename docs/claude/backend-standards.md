# Backend Standards (Python/FastAPI)

Standards for modifying Python code in `backend/` - FastAPI routes, Pydantic models, database patterns, and security.

---

## Python Code Style

- Follow PEP 8 style guidelines
- Use type hints for all function parameters and return values
- Use `logger.debug()` or `logger.info()` instead of `print()` statements
- Add comprehensive docstrings for all functions and classes

---

## FastAPI Best Practices

- Use dependency injection for database connections and services
- Implement proper request/response models with Pydantic
- Use async/await for I/O operations
- Implement proper error handling with HTTPException
- Use background tasks for non-critical operations

---

## Error Handling (CRITICAL)

- **NEVER use fallback values to hide errors** - all errors must be visible
- **NO silent failures** - if an operation fails, log it and raise an exception
- Always use proper exception handling with logging
- Never catch exceptions without logging them

```python
# ❌ WRONG - hides errors
try:
    data = read_file()
except:
    data = None

# ✅ CORRECT - errors are visible
try:
    data = read_file()
except Exception as e:
    logger.error(f"Failed to read file: {e}", exc_info=True)
    raise
```

---

## Database Patterns

- Use repository pattern for data access
- Implement proper connection pooling
- Use transactions for multi-step operations
- Follow database naming conventions (snake_case)
- Define Directus models in YAML files under `backend/core/directus/schemas/`

---

## Security Best Practices

- Validate all input data
- Use environment variables for sensitive configuration
- Implement proper authentication and authorization
- Sanitize user inputs
- Implement rate limiting where appropriate