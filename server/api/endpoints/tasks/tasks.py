################
# Default Imports
################
import sys
import os
import re
import asyncio
from datetime import datetime, timezone
from fastapi import HTTPException

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server.api import *
################

from server.task_management.task_management import celery
from server.api.endpoints.mates.ask_mate import ask_mate as ask_mate_processing
from server.api.endpoints.skills.books.translate import translate as book_translate_processing

from celery import shared_task
from datetime import datetime
from server.cms.cms import make_strapi_request, delete_file_from_strapi
from server.api.endpoints.skills.files.providers.openmates.delete import delete as openmates_delete
from server.api.endpoints.tasks.update import update as update_task


@celery.task(bind=True)
def ask_mate_task(self, team_slug, message, mate_username, task_info):
    # Add start time
    task_info['start_time'] = datetime.now()
    self.update_state(state='PROGRESS', meta={
        'meta': {
            'title': task_info['title'],
            'start_time': task_info['start_time']
        }
    })

    try:
        # Run the async function in an event loop
        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(ask_mate_processing(
            team_slug=team_slug,
            message=message,
            mate_username=mate_username
        ))
        response = response.model_dump()

        # Add end time and title
        task_info['end_time'] = datetime.now()
        task_info['title'] = task_info.get('title', 'Unknown')
        execution_time = (task_info['end_time'] - task_info['start_time']).total_seconds()
        self.update_state(state='SUCCESS', meta={
            'title': task_info['title'],
            'start_time': task_info['start_time'],
            'end_time': task_info['end_time'],
            'execution_time': round(execution_time, 3),
            'output': response
        })
    except Exception as e:
        task_info['end_time'] = datetime.now()
        task_info['title'] = task_info.get('title', 'Unknown')
        execution_time = (task_info['end_time'] - task_info['start_time']).total_seconds()
        self.update_state(state='FAILURE', meta={
            'title': task_info['title'],
            'start_time': task_info['start_time'],
            'end_time': task_info['end_time'],
            'execution_time': round(execution_time, 3),
            'exc_type': type(e).__name__,
            'exc_message': traceback.format_exc().split('\n')
        })

        # TODO: cannot access meta data here
        # TODO: implement task data storage in strapi (might be also a workaround)
        raise


@celery.task(bind=True)
def book_translate_task(self, task_id, team_slug, api_token, ebook_data, output_language, output_format):
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(update_task(
            task_id=task_id,
            status='in_progress'
        ))
        response = loop.run_until_complete(book_translate_processing(
            team_slug=team_slug,
            api_token=api_token,
            ebook_data=ebook_data,
            output_language=output_language,
            output_format=output_format,
            task_id=task_id
        ))
        response = response.model_dump()

        loop.run_until_complete(update_task(
            task_id=task_id,
            status='completed',
            progress=100,
            output=response,
            total_credits_cost_real=response.get('total_cost')
        ))

        # TODO: how to implement notifying user via chatbot about task completion, if the task was created in chat? (but don't notify if task was created via api call by default)
        # notify_user(
        #     team_slug=team_slug,
        #     user_id=task_info['user_id'],
        #     message='Task completed'
        # )

    # except InsufficientCreditsException as e:
    #     loop.run_until_complete(update_task(
    #         task_id=task_id,
    #         status='failed',
    #         error='Insufficient credits'
    #     ))
    #     notify_user(
    #         team_slug=team_slug,
    #         user_id=task_info['user_id'],
    #         message='Insufficient credits'
    #     )
    #     raise

    except Exception as e:
        loop.run_until_complete(update_task(
            task_id=task_id,
            status='failed',
            error=str(e)
        ))
        # notify_user(
        #     team_slug=team_slug,
        #     user_id=task_info['user_id'],
        #     message=str(e)
        # )
        raise


@shared_task
def delete_expired_files():
    add_to_log("Deleting expired files...")
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

    async def async_delete_expired_files():
        # Fetch expired files
        status_code, expired_files = await make_strapi_request(
            method='get',
            endpoint='uploaded-files',
            filters=[{'field': 'expiration_datetime', 'operator': '$lt', 'value': now}]
        )

        if status_code != 200:
            add_to_log(f"Failed to fetch expired files: {status_code}")
            return

        deleted_count = 0
        for file in expired_files['data']:
            file_id = file['attributes']['file_id']

            try:
                await openmates_delete(file_id)
                deleted_count += 1
            except HTTPException as e:
                # Log the error but continue with other files
                add_to_log(f"Failed to delete file {file_id}: {str(e)}")

        add_to_log(f"Deleted {deleted_count} expired files")

    loop = asyncio.get_event_loop()
    loop.run_until_complete(async_delete_expired_files())