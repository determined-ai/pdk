import torch
import random
import numpy as np
import matplotlib.pyplot as plt
from torchvision import transforms


# Get the color map by name:
cmap_conv = plt.get_cmap('viridis')

# Sigmoid function
sigmoid = torch.nn.Sigmoid()

def weights_init(m):
    classname = m.__class__.__name__
    if classname.find('Conv3d') != -1:
        torch.nn.init.kaiming_normal_(m.weight)
        m.bias.data.zero_()

def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def tb_write_video(writer, name, imgs, masks, output, batch_idx):
    imgs_cmap = cmap_conv(imgs[0,0,...].detach().unsqueeze(0).cpu())
    output_cmap = cmap_conv(output[0,0,...].detach().unsqueeze(0).cpu())
    masks_cmap = cmap_conv(masks[0,0,...].detach().unsqueeze(0).cpu())
    img_collage = np.concatenate([imgs_cmap, output_cmap, masks_cmap],-2)
    img_collage = np.moveaxis(img_collage,-1,2)
    writer.add_video(name, img_collage, global_step=batch_idx)
    writer.flush()

class PairedRandomHorizontalFlip():
    """Custom transform for horizontal flipping"""
    def __init__(self, prob=0.5):
        self.prob = prob   

    def __call__(self, sample):
        """
        Randomly flips both of the images

        Arguments:
        sample - tuple, image and segmentation mask
    
        Returns:
        (img, mask) - tuple, transformed sample
        """
        img, mask = sample
        if np.random.random() < self.prob:
            img, mask = torch.flip(img, [-1]), torch.flip(mask, [-1])
        return img, mask

    
class PairedRandomAffine():
    """
    Randomly applies affine transformation
    on both of the images
    """
    def __init__(self, degrees=None, translate=None, scale_ranges=None, shears=None):

        self.params = {
            'degrees': degrees,
            'translate': translate,
            'scale_ranges': scale_ranges,
            'shears': shears
        }

    def __call__(self, sample):
        img, mask = sample
        n, c, w, h = img.size()
        # extract parameters from transforms.RandomAffine
        angle, translations, scale, shear = transforms.RandomAffine.get_params(self.params['degrees'],
                                                                               self.params['translate'],
                                                                               self.params['scale_ranges'],
                                                                               self.params['shears'],
                                                                               (n,c,w,h))
        # apply TF.affine using fixed parameters
        img = transforms.functional.affine(img, angle, translations, scale, shear)
        mask = transforms.functional.affine(mask, angle, translations, scale, shear)
        return img, mask
    
class PairedToTensor():
    """
    Convert ndarrays in sample to Tensors.
    """
    def __call__(self, sample):
        imgs, masks = sample
        if len(masks.shape) == 3:
            masks = np.expand_dims(masks, -1)
            masks = np.moveaxis(masks, -1, 0)
        imgs, masks = torch.FloatTensor(imgs), torch.FloatTensor(masks)
        return imgs, masks

class PairedCrop():
    """
    Crop Tensors to correct dimension without interpolating.
    """
    def __call__(self, sample):
        imgs, masks = sample
        # Depth should be divisible by 16 due to VNet architecture
        depth = imgs.shape[-3]
        factor = 16
        residual = depth%factor
        if residual != 0:
            crop_left = (residual)//2
            crop_right = depth - ((residual)-crop_left)
            imgs = imgs[...,crop_left:crop_right,:,:]
            masks = masks[...,crop_left:crop_right,:,:]

        return imgs, masks

class PairedNormalize():
    """
    Normalize voxel intensity by volume z-score, percentiles or max-min
    """
    def __init__(self, normalization='percentile'):
        self.normalization = normalization

    def __call__(self, sample):
        imgs, masks = sample

        if self.normalization == 'zscore':
            mean_vals = imgs.mean(axis=(1,2,3)).reshape(4,1,1,1)
            std_vals = imgs.std(axis=(1,2,3)).reshape(4,1,1,1)
            imgs_norm = (imgs - mean_vals)/std_vals
        elif self.normalization == 'min-max':
            min_vals = imgs.amin(axis=(1,2,3)).reshape(4,1,1,1)
            max_vals = imgs.amax(axis=(1,2,3)).reshape(4,1,1,1)
            imgs_norm = (imgs - min_vals)/(max_vals-min_vals)
        else:
            if self.normalization != 'percentile':
                print('Defaulting to 1st and 99th percentile normalization')
            imgs_min, imgs_max = torch.quantile(imgs.view(4,-1), torch.tensor([0.1,0.99]), dim=-1)
            imgs_min, imgs_max = imgs_min.reshape(4,1,1,1), imgs_max.reshape(4,1,1,1)
            imgs_norm = ((imgs - imgs_min)/(imgs_max - imgs_min)).clip(min=0, max=1)
        
        return imgs_norm, masks