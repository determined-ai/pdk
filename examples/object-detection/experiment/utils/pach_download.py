
import os
import shutil

import python_pachyderm

from python_pachyderm.pfs import Commit
from python_pachyderm.proto.v2.pfs.pfs_pb2 import FileType


def safe_open_wb(path):
    ''' Open "path" for writing, creating any parent directories as needed.
    '''
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return open(path, 'wb')

def get_pach_repo_folder(
    pachyderm_host,
    pachyderm_port,
    repo,
    branch,
    token,
    project="default"
):
    folder_name = ""

    print(f"Starting to download dataset: {repo}@{branch}")

    client = python_pachyderm.Client(
        host=pachyderm_host, port=pachyderm_port, auth_token=token
    )

    for file_info in client.walk_file(
            Commit(repo=repo, id=branch, project=project), "/"):
            src_path = file_info.file.path

            if file_info.file_type != FileType.FILE:
                if src_path != "/":
                    folder_name  = src_path
                    break;
    print("Repository Folder: ", folder_name)
    return folder_name.replace("/","")


def download_full_pach_repo(
    pachyderm_host,
    pachyderm_port,
    repo,
    branch,
    root,
    token,
    project="default",
    previous_commit=None,
):
    print(f"Starting to download dataset: {repo}@{branch} --> {root}")

    if not os.path.exists(root):
        os.makedirs(root)

    client = python_pachyderm.Client(
        host=pachyderm_host, port=pachyderm_port, auth_token=token
    )

    for file_info in client.walk_file(
            Commit(repo=repo, id=branch, project=project), "/"):
            src_path = file_info.file.path
            des_path = os.path.join(root, src_path[1:])
            print(f"Saving File: '{des_path}'")

            if file_info.file_type == FileType.FILE:
                if src_path != "":
                    # get file
                    src_file = client.get_file(
                        Commit(repo=repo, id=branch, project=project), src_path
                    )
                    # copy file to folder
                    with safe_open_wb(des_path) as dest_file:
                        shutil.copyfileobj(src_file, dest_file)
                    # files.append((src_path, des_path))
    print("Download operation ended")
    return root
