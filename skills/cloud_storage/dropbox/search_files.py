

################

# Default Imports

################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *

################

import dropbox
import time
from skills.cloud_storage.dropbox.download_file import download_file
from skills.pdf.find_text_in_pdf import find_text_in_pdf

def search_files(
        query:str=None, 
        path:str=None, 
        max_results:int=100, 
        get_all: bool = False, 
        download: bool = False, 
        download_path: str = None,
        search_in_file_for_text: str = None
        ) -> list:
    try:
        add_to_log(module_name="Cloud storage | Dropbox", color="blue", state="start")
        add_to_log("Starting file search...")

        # Load Dropbox access token from secrets
        secrets = load_secrets()
        if not query:
            query = ""
        if not path:
            path = ""
        total_size = 0
        with dropbox.Dropbox(oauth2_refresh_token=secrets["DROPBOX_REFRESH_TOKEN"], app_key=secrets["DROPBOX_APP_KEY"]) as dbx:
            response = dbx.files_search(path, query)
            results = response.matches

            while response.more and (get_all or len(results) < max_results):  # If there are more results to retrieve
                response = dbx.files_search(path, query, start=len(results))
                results.extend(response.matches)
                add_to_log(f"Retrieving more results... (currently {len(results)} results)", module_name="Cloud storage | Dropbox")
                time.sleep(1)  # Add a delay to prevent hitting rate limits

        # Limit the results to the maximum number if get_all is False
        if not get_all:
            results = results[:max_results]

        # Extract the ids and paths from the results and calculate total size
        files = []
        total_size = 0
        for result in results:
            # if result is a file, add it to the list of files
            if isinstance(result.metadata, dropbox.files.FileMetadata):
                files.append({
                    'id': result.metadata.id,
                    'path': result.metadata.path_display,
                    'size_bytes': result.metadata.size
                })
                total_size += result.metadata.size

        total_size_mb = round(total_size / 1024 / 1024,2)  # Convert size to MB

        # Download files if download is True
        if download or search_in_file_for_text:
            if not download_path:
                download_path = f"{main_directory}temp_data/cloud_storage"
            for file in files:
                # Replace the leading slash with an empty string
                relative_path = file['path'].lstrip('/')
                target_file_path = os.path.join(download_path, relative_path)
                target_folder_path = os.path.dirname(target_file_path)
                if not os.path.exists(target_folder_path):  # Check if folder already exists
                    os.makedirs(target_folder_path)  # Create folder if it doesn't exist
                if not os.path.exists(target_file_path):  # Check if file already exists
                    download_file(filepath=file['path'], target_folder=target_folder_path)

        # if find_text_in_pdf is True, search for the query in the downloaded pdfs in the target folder
        if search_in_file_for_text:
            filtered_files = [
                file  # Keep the file
                for file in files  # For each file in the list of files
                if (
                    file['path'].lower().endswith('.pdf')  # If the file is a PDF
                    and find_text_in_pdf(  # And if the text is found in the PDF
                        filepath=os.path.join(download_path, os.path.basename(file['path'])),
                        search=search_in_file_for_text
                    )
                )
                or not file['path'].lower().endswith('.pdf')  # Or if the file is not a PDF
            ]

            # remove downloaded files
            for file in files:
                if not download or (download and file not in filtered_files):
                    os.remove(os.path.join(download_path, os.path.basename(file['path'])))

            files = filtered_files

        if path and query:
            add_to_log(f"Found {len(files)} files (Total size: {total_size_mb} MB) matching the query: {query} in path: {path}", state="success")
        elif path:
            add_to_log(f"Found {len(files)} files (Total size: {total_size_mb} MB) in path: {path}", state="success")
        elif query:
            add_to_log(f"Found {len(files)} files (Total size: {total_size_mb} MB) matching the query: {query}", state="success")
        return files
        

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to search for files", traceback=traceback.format_exc())
        return []


if __name__ == "__main__":
    search_files(path="/Documents/Finance/Vouchers",query=".pdf",max_results=10, download=True)
    # search_files(path="/Documents/Finance/Vouchers",query="amazon",get_all=True,search_in_file_for_text=["7,89"], download=True)