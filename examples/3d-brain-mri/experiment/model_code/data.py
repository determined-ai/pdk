import os
import shutil
import pachyderm_sdk
import numpy as np
import pandas as pd
import nibabel as nib
from model_code import utils
from torchvision import transforms
from pachyderm_sdk.api.pfs import File, FileType
from pathlib import Path
from torch.utils.data import Dataset
from sklearn.model_selection import train_test_split


class MRI_Dataset(Dataset):
    def __init__(self, path_df, data_dir, transform=None):
        self.path_df = path_df
        self.transform = transform
        self.data_dir = data_dir
        
    def __len__(self):
        return self.path_df.index.unique().shape[0]
    
    def __getitem__(self, idx):
        patient = self.path_df.index[idx]
        mask = self.path_df.loc[patient, 'masks'].strip('/')
        volumes = self.path_df.loc[patient, 'volumes']
        vol_paths = [os.path.join(self.data_dir, patient, volume.strip('/')) for volume in volumes]
        mask_path = os.path.join(self.data_dir, patient, mask)
        vol_FLAIR = nib.load(vol_paths[0]).get_fdata(dtype=np.float32).T
        vol_T1c = nib.load(vol_paths[1]).get_fdata(dtype=np.float32).T
        vol_T2 = nib.load(vol_paths[2]).get_fdata(dtype=np.float32).T
        vol_SWI = nib.load(vol_paths[3]).get_fdata(dtype=np.float32).T
        vol_mask = nib.load(mask_path).get_fdata(dtype=np.float32).T.astype(bool).astype(int)
        multimodal_vol = np.stack([vol_FLAIR,vol_T1c,vol_T2,vol_SWI])
        
        sample = (multimodal_vol, vol_mask)
              
        if self.transform:
            sample = self.transform(sample)
        
        return sample
    
   
def get_train_val_datasets(download_dir, data_dir, trial_context):
    
    patients, volumes, masks = [], [], []

    full_dir = "/"
    full_dir = os.path.join(full_dir, download_dir.strip("/"), data_dir.strip("/"))
    
    print("full_dir = " + full_dir)

    all_patients = set(nifti_file.parent for nifti_file in Path(full_dir).rglob('*.nii*'))
    for patient_dir in all_patients:
        patients.append(patient_dir.name)
        volumes.append((next(patient_dir.rglob('*FLAIR.nii*')).name,
                        next(patient_dir.rglob('*T1c.nii*')).name,
                        next(patient_dir.rglob('*T2.nii*')).name,
                        next(patient_dir.rglob('*SWI.nii*')).name))
        masks.append(next(patient_dir.rglob('*tumor*.nii*')).name)

    PathDF = pd.DataFrame({'patients': patients,
                        'volumes': volumes,
                        'masks': masks})

    PathDF = PathDF.set_index('patients')
    PathDF
    
    train_patients, val_patients = train_test_split(PathDF.index.unique(), random_state = trial_context.get_hparam("split_seed"),
                                     test_size = trial_context.get_hparam("validation_ratio"))
    
    train_transforms = transforms.Compose([                       
        utils.PairedToTensor(),
        utils.PairedCrop(),
        utils.PairedNormalize(trial_context.get_hparam("normalization")),
        utils.PairedRandomAffine(degrees=(trial_context.get_hparam("affine_degrees_min"), trial_context.get_hparam("affine_degrees_max")),
                           translate=(trial_context.get_hparam("affine_translate_min"), trial_context.get_hparam("affine_translate_max")),
                           scale_ranges=(trial_context.get_hparam("affine_scale_min"), trial_context.get_hparam("affine_scale_max"))),
        utils.PairedRandomHorizontalFlip(trial_context.get_hparam("hflip_pct")),
    ])
    eval_transforms = transforms.Compose([
        utils.PairedToTensor(),
        utils.PairedCrop(),
        utils.PairedNormalize(trial_context.get_hparam("normalization"))
    ])


    train_data = MRI_Dataset(PathDF.loc[train_patients], full_dir, transform=train_transforms)
    valid_data = MRI_Dataset(PathDF.loc[val_patients], full_dir, transform=eval_transforms)
    
    return train_data, valid_data



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

    print(f'pachyderm_host = {pachyderm_host}')
    print(f'pachyderm_port = {pachyderm_port}')
    print(f'repo = {repo}')
    print(f'branch = {branch}')
    print(f'root = {root}')
    print(f'token = {token}')
    print(f'project = {project}')
    print(f'previous_commit = {previous_commit}')
    
    print(f'DIR: {os.path.realpath("./")}')
    print(f'CWD: {os.getcwd()}')
    print(f'{root} -> {os.path.exists(root)}')

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