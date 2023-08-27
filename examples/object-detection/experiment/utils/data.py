"""
COCO dataset which returns image_id for evaluation.
Mostly copy-paste from https://github.com/pytorch/vision/blob/13b35ff/references/detection/coco_utils.py
"""
import os
from io import BytesIO
import boto3
import requests
from tqdm import tqdm
from google.cloud import storage
from determined.util import download_gcs_blob_with_backoff
import os
import torch
import torchvision
from PIL import Image
from attrdict import AttrDict
# from misc import nested_tensor_from_tensor_list
from utils.coco import ConvertCocoPolysToMask, make_coco_transforms
from pathlib import Path
from time import time

def unwrap_collate_fn(batch):
    batch = list(zip(*batch))
    return tuple(batch)


class S3Backend:
    def __init__(self, bucket_name):
        self._storage_client  = boto3.client('s3', aws_access_key_id='', aws_secret_access_key='')
        self._storage_client ._request_signer.sign = (lambda *args, **kwargs: None)
        self._bucket = bucket_name

    def convert_filepath(self, filepath):
        '''
        assumption of filepath: determined-ai-coco-dataset/data/coco/train2017/000000000009.jpg
        expected key: data/coco/train2017/000000000009.jpg
        '''
        p = Path(filepath)
        # print(p.parent.parent.parent.name, p.parent.parent.name,p.parent.name,p.name)
        return str(Path(p.parent.parent.parent.name, p.parent.parent.name,p.parent.name,p.name))

    def get(self, filepath):
        # print("self._bucket: ",self._bucket)
        # print("filepath: ",filepath)
        filepath = self.convert_filepath(filepath)
        # print("filepath: ",filepath)

        obj = self._storage_client.get_object(Bucket=self._bucket, Key=filepath)
        img_str = obj["Body"].read()
        return img_str

class S3Backend2:
    def __init__(self, bucket_name):
        self._storage_client  = boto3.client('s3', aws_access_key_id='', aws_secret_access_key='')
        self._storage_client ._request_signer.sign = (lambda *args, **kwargs: None)
        self._bucket = bucket_name

        self._bucket = bucket_name

    def convert_filepath(self, bucket,filepath):
        '''
        assumption of filepath: determined-ai-coco-dataset/data/coco/train2017/000000000009.jpg
        expected key: data/coco/train2017/000000000009.jpg
        get bucket root dir name
        get filepath
        '''
        p = Path(filepath)
        # print(p.parts[1:])
        return str(Path(p.parts[0])), str(Path(*p.parts[1:]))

    def get(self, filepath):
        # print("self._bucket: ",self._bucket)
        # print("filepath: ",filepath)
        bucket, filepath = self.convert_filepath(self._bucket,filepath)
        # print("filepath: ",filepath)
        # print(f"Bucket=self._bucket: {bucket}, Key=filepath {filepath}")
        obj = self._storage_client.get_object(Bucket=bucket, Key=filepath)
        img_str = obj["Body"].read()
        return img_str


class GCSBackend:
    def __init__(self, bucket_name):
        self._storage_client = storage.Client()
        self._bucket = self._storage_client.bucket(bucket_name)

    def convert_filepath(self, filepath):
        tokens = filepath.split("/")
        directory = tokens[-2]
        filename = tokens[-1]
        return "{}/{}".format(directory, filename)

    def get(self, filepath):
        filepath = self.convert_filepath(filepath)
        blob = self._bucket.blob(filepath)
        img_str = download_gcs_blob_with_backoff(blob)
        return img_str


class FakeBackend:
    def __init__(self):
        self.data = None

    def get(self, filepath):
        # We will return train_curves.png image regardless of the COCO image requested.
        if self.data is None:
            with open("imgs/train_curves.png", "rb") as f:
                img_str = f.read()
            self.data = img_str
        return self.data


class LocalBackend:
    """
    This class will load data from harddrive.
    COCO dataset will be downloaded from source in model_def.py if
    local backend is specified.
    """

    def __init__(self, outdir):
        assert os.path.isdir(outdir)
        self.outdir = outdir

    def get(self, filepath):
        with open(os.path.join(self.outdir, filepath), "rb") as f:
            img_str = f.read()
        return img_str


class CocoDetection(torchvision.datasets.CocoDetection):
    def __init__(
        self,
        backend,
        root_dir,
        img_folder,
        ann_file,
        transforms,
        return_masks,
        catIds=[],
    ):
        super(CocoDetection, self).__init__(img_folder, ann_file)
        self.img_folder = img_folder
        self._transforms = transforms
        self.prepare = ConvertCocoPolysToMask(return_masks)
        if backend == "fake":
            self.backend = FakeBackend()
        elif backend == "local":
            self.backend = LocalBackend(root_dir)
        elif backend == "gcs":
            self.backend = GCSBackend(root_dir)
        elif backend == "aws":
            self.backend = S3Backend2(root_dir)
        elif backend == "aws1":
            self.backend = S3Backend(root_dir)
        else:
            raise NotImplementedError

        self.catIds = catIds
        # print(self.coco)
        # print(self.catIds )
        # self.catIdtoCls=None
        # filtering based on id will result in examples that contain certain class(i.e. [21] images with only cow annotations)
        # if len(catIds):# if catIds is empty, return examples with all categories
        self.catIds = self.coco.getCatIds()
        # print("self.ids: ",self.ids)
        '''
        Remapping to set background class to zero, so can support FasterRCNN models
        '''
        self.catIdtoCls = {
            catId: i+1 for i, catId in zip(range(len(self.catIds)), self.catIds)
        }
        self.clstoCatId = {
            v:k for k,v in self.catIdtoCls.items()
        }
        print("self.catIdtoCls: ",self.catIdtoCls)
        # if len(self.catIds) == 0:
        #     cat_ids = sorted(self.coco.getCatIds())
        #     # print("cat_ids: ",cat_ids)
        #     self.num_classes = len(self.coco.getCatIds())+1
        # else:
        #     self.num_classes = len(self.catIds)
        # print("self.catIdtoCls: ",self.catIdtoCls)
        self.num_classes = len(list(self.catIdtoCls.values()))+1

    def __getitem__(self, idx):
        coco = self.coco
        img_id = self.ids[idx]
        ann_ids = coco.getAnnIds(imgIds=img_id, catIds=self.catIds)
        target = coco.loadAnns(ann_ids)
        path = coco.loadImgs(img_id)[0]["file_name"]
        img_bytes = BytesIO(self.backend.get(os.path.join(self.img_folder, path)))

        img = Image.open(img_bytes).convert("RGB")
        # img.save('test.png')
        image_id = self.ids[idx]
        target = {"image_id": image_id, "annotations": target}
        img, target = self.prepare(img, target)
        if self._transforms is not None:
            img, target = self._transforms(img, target)
        # print(target["labels"])
        target["labels"] = torch.tensor(
                [self.catIdtoCls[l.item()] for l in target["labels"]], dtype=torch.int64
            )
        # print(target["labels"])
        # if len(self.catIds):
        #     target["labels"] = torch.tensor(
        #         [self.catIdtoCls[l.item()] for l in target["labels"]], dtype=torch.int64
        #     )
        return img, target

    def __len__(self):
        # If using fake data, we'll limit the dataset to 1000 examples.
        if isinstance(self.backend, FakeBackend):
            return 1000
        return len(self.ids)

def download_pretrained_model(model_url, filename):
    print('--> Download Pre-trained Model')
    os.mkdir('pretrained')

    r = requests.get(model_url) # create HTTP response object

    filepath = f"./pretrained/{filename}"

    with open(filepath,'wb') as f:
        f.write(r.content)

    print('--> Finished Downloading Pre-trained Model to: ', filepath)
    return filepath



def build_xview_dataset(image_set, args):
    root = args.data_dir
    mode = "instances"
    PATHS = {
        "train": (os.path.join(root), os.path.join('/tmp/train_sliced_no_neg/',"train_300_02.json")),
        "val": (os.path.join(root), os.path.join('/tmp/val_sliced_no_neg/',"val_300_02.json")),
    }
    print("PATHS: ",PATHS)
    catIds = [] if "cat_ids" not in args else args.cat_ids

    img_folder, ann_file = PATHS[image_set]
    dataset = CocoDetection(
        args.backend,
        args.data_dir,
        img_folder,
        ann_file,
        transforms=make_coco_transforms(image_set),
        return_masks=args.masks,
        catIds=catIds,
    )
    return dataset, dataset.num_classes

def build_xview_dataset_filtered(image_set, args):
    root = args.data_dir
    mode = "instances"
    PATHS = {
        "train": ("train_images_rgb_no_neg_filt_32/train_images_640_02_filt_32", 'train_images_rgb_no_neg_filt_32/train_640_02_filtered_32.json'),
        "val": ("val_images_rgb_no_neg_filt_32/val_images_640_02_filt_32", 'val_images_rgb_no_neg_filt_32/val_640_02_filtered_32.json'),
    }
    print("PATHS: ",PATHS)

    catIds = [] if "cat_ids" not in args else args.cat_ids
    img_folder, ann_file = PATHS[image_set]
    dataset = CocoDetection(
        args.backend,
        args.data_dir,
        img_folder,
        os.path.join(args.data_dir,ann_file),
        transforms=make_coco_transforms(image_set),
        return_masks=args.masks,
        catIds=catIds,
    )
    return dataset, dataset.num_classes

if __name__ == '__main__':
    DATA_DIR='determined-ai-xview-coco-dataset/train_sliced_no_neg/train_images_300_02/'
    data, n_classes = build_xview_dataset(image_set='train',args=AttrDict({
                                                'data_dir':DATA_DIR,
                                                'backend':'aws',
                                                'masks': None,
                                                }))
    for im, ann in tqdm(data):
            print(im.shape)
            print(len(ann))
            print(ann)
            break
    DATA_DIR='determined-ai-xview-coco-dataset/val_sliced_no_neg/val_images_300_02/'
    data, n_classes = build_xview_dataset(image_set='val',args=AttrDict({
                                                'data_dir':DATA_DIR,
                                                'backend':'aws',
                                                'masks': None,
                                                }))
    for im, ann in tqdm(data):
            print(im.shape)
            print(len(ann))
            print(ann)
            break
