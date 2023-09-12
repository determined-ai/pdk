import os
import shutil
from bisect import bisect
from typing import Dict, List, Tuple

import pachyderm_sdk
import torch
from pachyderm_sdk import Client
from pachyderm_sdk.api import pfs
from pachyderm_sdk.api.pfs import File, FileType
from PIL import Image
from skimage import io
from torch.utils.data import Dataset

# ======================================================================================================================

DEFAULT_PAGE_SIZE = 2 << 10


class CatDogDataset(Dataset):
    def __init__(
        self,
        client: Client,
        commit: pfs.Commit,
        path="/",
        transform=None,
        page_size: int = DEFAULT_PAGE_SIZE
    ):
        """A PyTorch Dataset for classifying images of dogs and cat where the data
        is all files of a `commit` within a pachyderm repo.

        The dataset size calculation and indexing happens at time of instantiation.
        Therefore, if the `current_commit` should be pinned to a specific commit and
        not relative to HEAD, else this Dataset might become corrupted.
        """
        self.client = client
        self.transform = transform
        self.root_file = pfs.File(commit=commit, path=path)

        # The PFS API doesn't provide a great method for indexing the "files" of a
        # commit, as FileInfo types are either a FILE or DIR. Therefore, we need to
        # construct our method for indexing. We could hold the entire list of files
        # in memory, but that solution would not scale well. Instead, we opt to create
        # a mapping of pagination markers to (theoretically) restrain lookup times.
        self.page_size = page_size
        self.pagination_markers: Dict[int, Tuple[int, pfs.File]] = dict()
        count = 0
        for info in self.client.pfs.walk_file(file=self.root_file):
            if info.file_type == pfs.FileType.FILE:
                if count % self.page_size == 0:
                    self.pagination_markers[count] = info.file
                count += 1
        self.len = count

    def __len__(self):
        return self.len

    def __getitem__(self, idx) -> Tuple["Image.Image", int]:
        # The pytorch documentation indicates to me that the below code isn't needed.
        # if torch.is_tensor(idx):
        #     idx = idx.tolist()
        if idx >= self.len:
            raise IndexError(f"{idx} > {self.len - 1}")

        file_index = idx - (idx % self.page_size)
        marker = self.pagination_markers[file_index]
        for info in self.client.pfs.walk_file(file=self.root_file, pagination_marker=marker):
            if info.file_type == pfs.FileType.FILE:
                if file_index == idx:
                    break
                file_index += 1
        else:
            # This shouldn't be reachable.
            raise IndexError(f"index {idx} not found.")

        with self.client.pfs.pfs_file(info.file) as image_file:
            print("reading file using sklearn")
            from tempfile import NamedTemporaryFile
            with NamedTemporaryFile("wb") as local_file:
                local_file.write(image_file.readall())
                image = Image.fromarray(io.imread(local_file.name))

        if self.transform:
            image = self.transform(image)

        # Create label for image based on file name (dog = 0, cat = 1)
        label = 0 if "dog" in info.file.path else 1
        return image, label


class CatDogDatasetCommitDiff(Dataset):
    """A PyTorch Dataset for classifying images of dogs and cat where the data
    is all files added to the pachyderm repo between `previous_commit` and
    `current_commit`.

    The dataset size calculation and indexing happens at time of instantiation.
    Therefore, if the `current_commit` should be pinned to a specific commit and
    not relative to HEAD, else this Dataset might become corrupted.
    """

    def __init__(
        self,
        client: Client,
        current_commit: pfs.Commit,
        previous_commit: pfs.Commit,
        path="/",
        transform=None,
    ):
        self.client = client
        self.transform = transform
        self.current_root_file = pfs.File(commit=current_commit, path=path)
        self.previous_root_file = pfs.File(commit=previous_commit, path=path)

        # The DiffFiles API does not support pagination, so we cannot chunk the
        # dataset in this manner for later indexing. Therefore, we track the index
        # of the directories so we can later perform shallow diffing during indexing.
        self.indices: List[int] = []  # Keep a list of indices
        self.dirs: Dict[int, pfs.File] = dict()
        count = 0
        for diff in self.client.pfs.diff_file(
                new_file=self.current_root_file, old_file=self.previous_root_file
        ):
            if diff.new_file.file_type == pfs.FileType.FILE:
                count += 1
            elif diff.new_file.file_type == pfs.FileType.DIR:
                if count not in self.dirs:
                    self.indices.append(count)
                self.dirs[count] = diff.new_file.file
        self.len = count

    def __len__(self):
        return self.len

    def __getitem__(self, idx) -> Tuple["Image.Image", int]:
        # The pytorch documentation indicates to me that the below code isn't needed.
        # if torch.is_tensor(idx):
        #     idx = idx.tolist()
        if idx >= self.len:
            raise IndexError(f"{idx} > {self.len - 1}")

        file_index = bisect(self.indices, idx) - 1
        dir_file = self.dirs[file_index]
        new_file = pfs.File(commit=self.current_root_file.commit, path=dir_file.path)
        old_file = pfs.File(commit=self.previous_root_file.commit, path=dir_file.path)
        for diff in self.client.pfs.diff_file(new_file=new_file, old_file=old_file, shallow=True):
            if diff.new_file.file_type == pfs.FileType.FILE:
                if file_index == idx:
                    info = diff.new_file
                    break
                file_index += 1
        else:
            # This shouldn't be reachable.
            raise IndexError(f"index {idx} not found.")

        with self.client.pfs.pfs_file(info.file) as image_file:
            print("reading file using sklearn")
            from tempfile import NamedTemporaryFile
            with NamedTemporaryFile("wb") as local_file:
                local_file.write(image_file.readall())
                image = Image.fromarray(io.imread(local_file.name))

        if self.transform:
            image = self.transform(image)

        # Create label for image based on file name (dog = 0, cat = 1)
        label = 0 if "dog" in info.file.path else 1
        return image, label


# ======================================================================================================================



def safe_open_wb(path):
    ''' Open "path" for writing, creating any parent directories as needed.
    '''
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return open(path, 'wb')


def download_pach_repo(
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

    client = pachyderm_sdk.Client(
        host=pachyderm_host, port=pachyderm_port, auth_token=token
    )
    files = []
    if previous_commit is not None:
        for diff in client.pfs.diff_file(new_file=File.from_uri(f"{project}/{repo}@{branch}"),
            old_file=File.from_uri(f"{project}/{repo}@{previous_commit}")
        ):
            src_path = diff.new_file.file.path
            des_path = os.path.join(root, src_path[1:])
            print(f"Got src='{src_path}', des='{des_path}'")

            if diff.new_file.file_type == FileType.FILE:
                if src_path != "":
                    files.append((src_path, des_path))
    else:
        for file_info in client.pfs.walk_file(file=File.from_uri(f"{project}/{repo}@{branch}")):
            src_path = file_info.file.path
            des_path = os.path.join(root, src_path[1:])
            print(f"Got src='{src_path}', des='{des_path}'")

            if file_info.file_type == FileType.FILE:
                if src_path != "":
                    files.append((src_path, des_path))

    for src_path, des_path in files:
        src_file = client.pfs.pfs_file(file=File.from_uri(f"{project}/{repo}@{branch}:{src_path}"))
        print(f"Downloading {src_path} to {des_path}")

        with safe_open_wb(des_path) as dest_file:
            shutil.copyfileobj(src_file, dest_file)

    print("Download operation ended")
    return files


# ========================================================================================================
