# Backend Celery Tasks

This directory (`backend/core/api/app/tasks/`) contains Celery tasks used by the backend application. Celery is used for running background jobs asynchronously, which helps in offloading long-running operations from the main application thread, improving responsiveness and reliability.

## Overview

The tasks defined here cover various functionalities, including:

-   **Data Persistence**: Tasks related to saving, updating, and deleting data in the primary database (Directus) and cache. This includes operations for chats, messages, user drafts, etc. See [`persistence_tasks.py`](backend/core/api/app/tasks/persistence_tasks.py) for more details.
-   **Cache Management**: Tasks for managing cache entries, such as eviction policies. See [`cache_eviction.py`](backend/core/api/app/tasks/cache_eviction.py).
-   **User-Specific Operations**: Tasks that handle user-related background processes, like updating user metrics or managing user-specific cache entries. See [`user_cache_tasks.py`](backend/core/api/app/tasks/user_cache_tasks.py) and [`user_metrics.py`](backend/core/api/app/tasks/user_metrics.py).
-   **Email Notifications**: Asynchronous tasks for sending various types of emails to users (e.g., verification, notifications, password resets). These are typically organized in subdirectories like `email_tasks/`.

## Structure

-   **`celery_config.py`**: Configures the Celery application instance, including broker URL, result backend, and other settings.
-   **`base_task.py`**: May contain a base task class that other tasks can inherit from, providing common functionality or error handling.
-   **Individual Task Files (e.g., `persistence_tasks.py`, `email_tasks/...`):** Each file or module typically groups related tasks. For example, all tasks dealing with data persistence are in `persistence_tasks.py`.

## Usage

Tasks are typically invoked from other parts of the application (e.g., API route handlers, service layers) using Celery's `delay()` or `apply_async()` methods. This queues the task for execution by a Celery worker process.

## Logging and Monitoring

Tasks should implement robust logging to help in debugging and monitoring their execution. Celery integrates with monitoring tools, and logs from task executions are usually captured by the configured logging setup (see `app/utils/setup_logging.py`).

## Best Practices

-   **Idempotency**: Design tasks to be idempotent where possible, meaning running them multiple times with the same input produces the same result without unintended side effects.
-   **Error Handling**: Implement comprehensive error handling and retry mechanisms. Celery provides built-in support for retries.
-   **Atomicity**: Ensure that tasks perform operations atomically or have mechanisms to roll back changes in case of failure, especially for database operations.
-   **Task Granularity**: Keep tasks focused on a single, well-defined unit of work. Complex operations can be broken down into smaller, chained tasks.
-   **Asynchronous Nature**: Remember that tasks run asynchronously. Avoid relying on shared state that isn't managed through a distributed mechanism (like a database or cache).