# Delete Users Without Chats Script

This script identifies and deletes users who do not have any chats created in the system.

## Overview

The script performs the following operations:

1. **Fetches all users** from Directus (excluding admin users)
2. **Checks each user** for chats by:
   - Hashing the user's ID using SHA-256 (same method used throughout the codebase)
   - Querying the `chats` collection for any chats with matching `hashed_user_id`
3. **Collects users without chats** into a deletion list
4. **Asks for confirmation** before proceeding with deletion
5. **Deletes the identified users** using the DirectusService `delete_user` method

## Prerequisites

- Docker and Docker Compose must be running
- The `api` service container must be running
- Environment variables must be properly configured in `.env` file:
  - `CMS_URL`
  - `ADMIN_EMAIL`
  - `ADMIN_PASSWORD`
  - `DIRECTUS_TOKEN`

## Usage

### Running the Script

Execute the script inside the Docker container:

```bash
docker exec -it api python /app/backend/scripts/delete_users_without_chats.py
```

### What to Expect

1. **Initial Phase**: The script will fetch all users and check each one for chats. This may take some time depending on the number of users.

2. **Confirmation Prompt**: Before deletion, you'll see:
   - The number of users to be deleted
   - A preview of user IDs (first 10, truncated for privacy)
   - A warning that the action cannot be undone
   - A prompt asking for confirmation (type `yes` or `no`)

3. **Deletion Phase**: If confirmed, the script will delete each user and show progress.

4. **Summary**: At the end, you'll see a summary showing:
   - Number of successfully deleted users
   - Number of failed deletions (if any)

### Example Output

```
2025-01-XX XX:XX:XX - INFO - Starting user deletion script...
2025-01-XX XX:XX:XX - INFO - Fetching all users from Directus...
2025-01-XX XX:XX:XX - INFO - Total users fetched: 150
2025-01-XX XX:XX:XX - INFO - Finding users without chats...
2025-01-XX XX:XX:XX - INFO - Checking user abc12345... (1/150)
...
2025-01-XX XX:XX:XX - INFO - Found 25 users without chats out of 150 total users

================================================================================
WARNING: About to delete 25 users who have no chats.
================================================================================

Users to be deleted:
  1. abc12345...xyz1
  2. def67890...uvw2
  ... and 15 more users

================================================================================
This action CANNOT be undone!
================================================================================

Do you want to proceed with deletion? (yes/no): yes

2025-01-XX XX:XX:XX - INFO - Proceeding with deletion of 25 users...
...
================================================================================
DELETION SUMMARY
================================================================================
Successfully deleted: 25 users
Failed to delete: 0 users
================================================================================
```

## Safety Features

1. **Admin Protection**: Admin users are automatically skipped and will never be deleted
2. **Confirmation Required**: The script requires explicit user confirmation before deletion
3. **Error Handling**: If a user cannot be checked for chats (due to errors), the script assumes they have chats to prevent accidental deletion
4. **Logging**: All operations are logged for audit purposes
5. **Compliance Logging**: User deletions are logged via the ComplianceService for compliance tracking

## Technical Details

### User ID Hashing

User IDs are hashed using SHA-256 before querying chats:
```python
hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
```

This matches the method used throughout the codebase for privacy and security.

### Chat Query

The script queries the `chats` collection with:
```python
filter[hashed_user_id][_eq] = <hashed_user_id>
```

Only the existence of chats is checked (limit=1) for efficiency.

### Deletion Method

Users are deleted using the `DirectusService.delete_user()` method, which:
- Logs the deletion for compliance purposes
- Uses admin authentication
- Handles errors gracefully

## Troubleshooting

### Script Fails to Start

- **Check Docker**: Ensure the `api` container is running: `docker ps | grep api`
- **Check Environment**: Verify `.env` file has all required variables
- **Check Logs**: Review container logs: `docker logs api`

### No Users Found

- This is normal if all users have chats
- The script will exit gracefully with a message

### Deletion Failures

- Check Directus logs for specific error messages
- Verify admin credentials are correct
- Ensure Directus service is healthy: `docker logs cms`

### Permission Errors

- Ensure the script is run inside the Docker container (not on host)
- Verify admin token can be obtained (check `ADMIN_EMAIL` and `ADMIN_PASSWORD`)

## Important Notes

⚠️ **WARNING**: This script permanently deletes users. The action cannot be undone.

- Always review the list of users before confirming deletion
- Consider backing up the database before running this script
- Test in a development environment first
- Monitor the deletion process for any errors

## Related Files

- Script: `/backend/scripts/delete_users_without_chats.py`
- User deletion service: `/backend/core/api/app/services/directus/user/delete_user.py`
- Directus service: `/backend/core/api/app/services/directus/directus.py`
- Chat schema: `/backend/core/directus/schemas/chats.yml`

