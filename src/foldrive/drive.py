from googleapiclient.http import MediaFileUpload

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"

def find_folder_by_name(service, name):
    escaped_name = name.replace("'","\\'")
    response = service.files().list(
        q=f"name = '{escaped_name}' and mimeType = '{FOLDER_MIME_TYPE}' and trashed = false",
        fields="files(id,name,parents)",
    ).execute()
    return response["files"]

def list_children(service, folder_id):
    all_children = []
    page_token = None
    while True:
        response = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id, name, mimeType, size, md5Checksum, modifiedTime)",
            pageSize=1000,
            pageToken=page_token,
        ).execute()
        all_children.extend(response["files"])
        page_token = response.get("nextPageToken")
        if page_token is None:
            return all_children


def create_folder(service, folder_name, parent_id=None):
    """Create a Drive folder (in My Drive root unless parent_id given); return its id."""
    folder_metadata = {"name": folder_name, "mimeType": FOLDER_MIME_TYPE}
    if parent_id is not None:
        folder_metadata["parents"] = [parent_id]
    created_folder = service.files().create(body=folder_metadata, fields="id").execute()
    return created_folder["id"]


def list_tree(service, folder_id):
    """Walk a Drive folder recursively"""

    files = {}
    folders = {}
    skipped_google_native = 0

    pending_folders = [(folder_id,"")]

    while pending_folders:
        current_folder_id, current_relative_path = pending_folders.pop()

        for child in list_children(service, current_folder_id):
            child_relative_path = (
                f"{current_relative_path}/{child['name']}" if current_relative_path else child['name']
            )

            if child["mimeType"] == FOLDER_MIME_TYPE:
                folders[child_relative_path] = child["id"]
                pending_folders.append((child["id"], child_relative_path))
                continue

            if child["mimeType"].startswith("application/vnd.google-apps"):
                skipped_google_native += 1
                continue 

            files[child_relative_path] = {
                "id": child["id"],
                "size": int(child.get("size", 0)),
                "md5": child.get("md5Checksum"),
                "modified": child.get("modifiedTime"),
            }

    return files, folders, skipped_google_native


def upload(service, local_path, parent_id, name):
    media =MediaFileUpload(str(local_path),resumable=True)
    return service.files().create(
        body={"name": name, "parents":[parent_id]},
        media_body=media,
        fields="id, md5Checksum, modifiedTime, size",
    ).execute()

def update(service,file_id,local_path):
    media=MediaFileUpload(str(local_path),resumable=True)
    return service.files().update(
        fileId=file_id,
        media_body=media,
        fields="id, md5Checksum, modifiedTime, size",
    ).execute()

def trash(service,file_id):
    service.files().update(
        fileId=file_id, body={"trashed":True}
    ).execute()