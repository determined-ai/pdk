import os
import random
import numpy as np
import nibabel as nib
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from IPython.display import clear_output
plt.rcParams['animation.html'] = 'jshtml'
plt.rcParams['animation.embed_limit'] = 2**128


def load_patient_volume(dir_path, idx=None):

    all_patient_paths = set(nifti_file.parent for nifti_file in Path(dir_path).rglob('*.nii*'))
    if idx is None or idx < len(all_patient_paths):
        patient_path = random.choice(list(all_patient_paths))
    else:
        patient_path = list(all_patient_paths)[idx]
    vol_FLAIR = nib.load(next(patient_path.rglob('*FLAIR.nii*'))).get_fdata(dtype=np.float32).T
    vol_T1c = nib.load(next(patient_path.rglob('*T1c.nii*'))).get_fdata(dtype=np.float32).T
    vol_T2 = nib.load(next(patient_path.rglob('*T2.nii*'))).get_fdata(dtype=np.float32).T
    vol_SWI = nib.load(next(patient_path.rglob('*SWI.nii*'))).get_fdata(dtype=np.float32).T
    vol_mask = nib.load(next(patient_path.rglob('*tumor*.nii*'))).get_fdata(dtype=np.float32).T

    multimodal_vol = np.stack([vol_FLAIR,vol_T1c,vol_T2,vol_SWI])

    return multimodal_vol, vol_mask


def plot_masked_volumes(mri_vol, mri_mask, figsize=(20,4), save=False, norm=0.4):
    
    modalities, (min_slice,mid_slice,max_slice) = preprocess_volumes(mri_vol,mri_mask)
    norm_mri_mask = (mri_mask/mri_mask.max())*norm
    fig, ax = plt.subplots(1,len(modalities), figsize=figsize)

    ims = []
    for n, (vol,name) in enumerate(modalities):
        # Set the initial image
        ims += [ax[n].imshow(vol[mid_slice,...] + norm_mri_mask[mid_slice,...], aspect='auto', animated=True)]
        ax[n].set_title(name)
        ax[n].set_axis_off()

    def update(i):
        for n, (vol,_) in enumerate(modalities):
            ims[n].set_data(vol[min_slice:max_slice,...][i] + norm_mri_mask[min_slice:max_slice,...][i])
        return ims

    clear_output()

    # Create the animation object
    animation_fig = animation.FuncAnimation(fig, update, frames=max_slice-min_slice, interval=100, blit=True, repeat_delay=10)

    # Show the animation
    animation_fig
    if save:
        animation_fig.save('./img/all_mri_mask.gif', writer='pillow')

    # Show the animation
    return animation_fig

def plot_mask_vs_preds(mri_preds, mri_mask, figsize=(10,4), save=False):
    
    multimodal_mri = np.stack([mri_preds,mri_preds,mri_preds,mri_preds])
    modalities, (min_slice,mid_slice,max_slice) = preprocess_volumes(multimodal_mri,mri_mask)
    fig, ax = plt.subplots(1,2,figsize=figsize)

    vol,_ = modalities[0]
    ims = []
    # Set the initial image
    ims = [ax[0].imshow(vol[mid_slice,...], aspect='auto', animated=True),
           ax[1].imshow(mri_mask[mid_slice,...], aspect='auto', animated=True)]
    ax[0].set_title(f'Predicted')
    ax[1].set_title(f'Mask')
    ax[0].set_axis_off()
    ax[1].set_axis_off()
        
    def update(i):
        ims[0].set_data(vol[min_slice:max_slice,...][i])
        ims[1].set_data(mri_mask[min_slice:max_slice,...][i])
        return ims

    clear_output()

    # Create the animation object
    animation_fig = animation.FuncAnimation(fig, update, frames=max_slice-min_slice, interval=100, blit=True, repeat_delay=10)

    if save:
        animation_fig.save('./img/mri_preds_vs_mask.gif', writer='pillow')

    # Show the animation
    return animation_fig


def preprocess_volumes(mri_vol, mri_mask):
    
    norm_mri_vol = mri_vol/mri_vol.max(axis=(1,2,3)).reshape(4,1,1,1)
    modalities = [(norm_mri_vol[0,...], 'FLAIR'), (norm_mri_vol[1,...], 'T1c'), (norm_mri_vol[2,...], 'T2'), (norm_mri_vol[3,...], 'SWI')]

    min_mask_slice = np.argwhere(mri_mask)[:,0].min()
    max_mask_slice = np.argwhere(mri_mask)[:,0].max()
    min_vol_slice = np.argwhere(mri_vol[0,...])[:,0].min()
    max_vol_slice = np.argwhere(mri_vol[0,...])[:,0].max()
    min_slice = min_vol_slice + abs(min_mask_slice - min_vol_slice)//2
    max_slice = max_vol_slice - abs(max_vol_slice - max_mask_slice)//2
    mid_slice = min_slice + (max_slice - min_slice)//2

    return modalities, (min_slice,mid_slice,max_slice)