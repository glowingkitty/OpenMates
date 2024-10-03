from server.cms.cms import make_strapi_request
import uuid
import logging

logger = logging.getLogger(__name__)
import logging

async def generate_file_id() -> str:
    """
    Generate a unique file ID
    """
    while True:
        file_id = uuid.uuid4().hex[:10]
        status_code, response = await make_strapi_request(
            method='get',
            endpoint='uploaded-files',
            filters=[{
                'field': 'file_id',
                'operator': '$eq',
                'value': file_id
            }]
        )
        if status_code == 200 and not response['data']:
            logger.info(f'Generated file ID: {file_id}')
            # If no files are found with this ID, return it
            return file_id
        else:
            logger.info(f'File ID {file_id} already exists')