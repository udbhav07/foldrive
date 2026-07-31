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
