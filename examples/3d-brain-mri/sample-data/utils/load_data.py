# General modules
import os
import shutil
import random
import numpy as np

# Torch modules
import torch
from torch import nn
import torch.optim as optim
from torch.utils.data import Dataset
from torch.utils.data import DataLoader
from torchvision import models, transforms

# Image modules
from PIL import Image
from skimage import io
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

# Import MLDM packages
import pachyderm_sdk
from pachyderm_sdk.api import pfs
from pachyderm_sdk.api.pfs import File, FileType


def download_data(mldm_client, repo, branch, project, download_dir):
    
    files = download_pach_repo(mldm_client, repo, branch, project, download_dir)
    
    # Return list local destination path for each file
    return [des for src, des in files ]

def safe_open_wb(path):
    ''' Open "path" for writing, creating any parent directories as needed.
    '''
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return open(path, 'wb')

def download_pach_repo(mldm_client, repo, branch, project, download_dir, previous_commit=None):
    
    print(f"Starting to download dataset: {repo}@{branch} --> {download_dir}")

    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    files = []
    if previous_commit is not None:
        for diff in mldm_client.pfs.diff_file(new_file=File.from_uri(f"{project}/{repo}@{branch}"),
                                              old_file=File.from_uri(f"{project}/{repo}@{previous_commit}")):
            src_path = diff.new_file.file.path
            des_path = os.path.join(download_dir, src_path[1:])

            if diff.new_file.file_type == FileType.FILE:
                if src_path != "":
                    files.append((src_path, des_path))
    else:
        for file_info in mldm_client.pfs.walk_file(file=File.from_uri(f"{project}/{repo}@{branch}")):
            src_path = file_info.file.path
            des_path = os.path.join(download_dir, src_path[1:])

            if file_info.file_type == FileType.FILE:
                if src_path != "":
                    files.append((src_path, des_path))

    for src_path, des_path in files:
        src_file = mldm_client.pfs.pfs_file(file=File.from_uri(f"{project}/{repo}@{branch}:{src_path}"))
        print(f"Downloading {src_path} to {des_path}")

        with safe_open_wb(des_path) as dest_file:
            shutil.copyfileobj(src_file, dest_file)

    print("Download operation ended")
    return files



# Create transforms for data (resize, crop, flip, noramlize)
def get_train_transforms():
    return transforms.Compose([
        transforms.Resize(240),
        transforms.RandomCrop(224),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
    ])