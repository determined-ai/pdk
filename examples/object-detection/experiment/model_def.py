
from typing import Any, Dict, Sequence, Union
import torch
import copy
from collections import defaultdict
from attrdict import AttrDict
from utils.data import unwrap_collate_fn
#from utils.data import build_dataset, unwrap_collate_fn
from utils.group_by_aspect_ratio import create_aspect_ratio_groups, GroupedBatchSampler
import torchvision
from utils.coco_eval import CocoEvaluator
from pycocotools import mask as coco_mask
import time
import datetime
from pycocotools.coco import COCO
from torch.optim.lr_scheduler import MultiStepLR
from utils.data import build_xview_dataset, unwrap_collate_fn, build_xview_dataset_filtered, download_pretrained_model
from utils.model import build_frcnn_model,build_frcnn_model_finetune, finetune_ssd300_vgg16, finetune_ssdlite320_mobilenet_v3_large, create_resnet152_fasterrcnn_model, create_efficientnet_b4_fasterrcnn_model, create_convnext_large_fasterrcnn_model, create_convnext_small_fasterrcnn_model, resnet152_fpn_fasterrcnn
from utils.pach_download import download_full_pach_repo, get_pach_repo_folder

from lr_schedulers import WarmupWrapper
import os
import numpy as np
from determined.pytorch import (
    DataLoader,
    LRScheduler,
    PyTorchTrial,
    PyTorchTrialContext,
    MetricReducer,
)

TorchData = Union[Dict[str, torch.Tensor], Sequence[torch.Tensor], torch.Tensor]

def convert_to_coco_api(ds):
    coco_ds = COCO()
    # annotation IDs need to start at 1, not 0, see torchvision issue #1530
    ann_id = 1
    dataset = {"images": [], "categories": [], "annotations": []}
    categories = set()
    for img_idx in range(len(ds)):
        img, targets = ds[img_idx]
        image_id = targets["image_id"].item()
        img_dict = {}
        img_dict["id"] = image_id
        img_dict["height"] = img.shape[-2]
        img_dict["width"] = img.shape[-1]
        dataset["images"].append(img_dict)
        bboxes = targets["boxes"].clone()
        bboxes[:, 2:] -= bboxes[:, :2]
        bboxes = bboxes.tolist()
        labels = targets["labels"].tolist()
        areas = targets["area"].tolist()
        iscrowd = targets["iscrowd"].tolist()
        if "masks" in targets:
            masks = targets["masks"]
            # make masks Fortran contiguous for coco_mask
            masks = masks.permute(0, 2, 1).contiguous().permute(0, 2, 1)
        if "keypoints" in targets:
            keypoints = targets["keypoints"]
            keypoints = keypoints.reshape(keypoints.shape[0], -1).tolist()
        num_objs = len(bboxes)
        for i in range(num_objs):
            ann = {}
            ann["image_id"] = image_id
            ann["bbox"] = bboxes[i]
            ann["category_id"] = labels[i]
            categories.add(labels[i])
            ann["area"] = areas[i]
            ann["iscrowd"] = iscrowd[i]
            ann["id"] = ann_id
            if "masks" in targets:
                ann["segmentation"] = coco_mask.encode(masks[i].numpy())
            if "keypoints" in targets:
                ann["keypoints"] = keypoints[i]
                ann["num_keypoints"] = sum(k != 0 for k in keypoints[i][2::3])
            dataset["annotations"].append(ann)
            ann_id += 1
    dataset["categories"] = [{"id": i} for i in sorted(categories)]
    coco_ds.dataset = dataset
    coco_ds.createIndex()
    return coco_ds


def get_coco_api_from_dataset(dataset):
    for _ in range(10):
        if isinstance(dataset, torchvision.datasets.CocoDetection):
            break
        if isinstance(dataset, torch.utils.data.Subset):
            dataset = dataset.dataset
    if isinstance(dataset, torchvision.datasets.CocoDetection):
        return dataset.coco
    return convert_to_coco_api(dataset)


class COCOReducer(MetricReducer):
    def __init__(self, base_ds, iou_types, cat_ids=[],remapping_dict=None):
        self.base_ds = base_ds
        self.iou_types = iou_types
        self.cat_ids = cat_ids
        self.remapping_dict = remapping_dict
        self.reset()

    def reset(self):
        self.results = []

    def update(self, result):
        self.results.extend(result)

    def per_slot_reduce(self):
        return self.results

    def cross_slot_reduce(self, per_slot_metrics):
        coco_evaluator = CocoEvaluator(self.base_ds, self.iou_types)
        if len(self.cat_ids):
            for iou_type in self.iou_types:
                coco_evaluator.coco_eval[iou_type].params.catIds = self.cat_ids
        for results in per_slot_metrics:
            results_dict = {r[0]: r[1] for r in results}
            coco_evaluator.update(results_dict,self.remapping_dict)

        for iou_type in coco_evaluator.iou_types:
            coco_eval = coco_evaluator.coco_eval[iou_type]
            coco_evaluator.eval_imgs[iou_type] = np.concatenate(
                coco_evaluator.eval_imgs[iou_type], 2
            )
            coco_eval.evalImgs = list(coco_evaluator.eval_imgs[iou_type].flatten())
            coco_eval.params.imgIds = list(coco_evaluator.img_ids)
            # We need to perform a deepcopy here since this dictionary can be modified in a
            # custom accumulate call and we don't want that to change coco_eval.params.
            # See https://github.com/cocodataset/cocoapi/blob/master/PythonAPI/pycocotools/cocoeval.py#L315.
            coco_eval._paramsEval = copy.deepcopy(coco_eval.params)
        coco_evaluator.accumulate()
        coco_evaluator.summarize()

        coco_stats = coco_evaluator.coco_eval["bbox"].stats.tolist()

        loss_dict = {}
        loss_dict["mAP"] = coco_stats[0]
        loss_dict["mAP_50"] = coco_stats[1]
        loss_dict["mAP_75"] = coco_stats[2]
        loss_dict["mAP_small"] = coco_stats[3]
        loss_dict["mAP_medium"] = coco_stats[4]
        loss_dict["mAP_large"] = coco_stats[5]
        return loss_dict



class ObjectDetectionTrial(PyTorchTrial):
    def __init__(self, context: PyTorchTrialContext) -> None:
        self.context = context
        self.hparams = AttrDict(self.context.get_hparams())
        print(self.hparams)
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

        print("Download Dataset from Pachyderm...")
        self.download_directory = (f"/tmp/data-rank{self.context.distributed.get_rank()}")

        data_config = self.context.get_data_config()

        if len(data_config.keys()) > 0:
            data_dir = self.download_data()
            print("===> DATA DIR: ", data_dir)

        repo_folder = get_pach_repo_folder(
            data_config["pachyderm"]["host"],
            data_config["pachyderm"]["port"],
            data_config["pachyderm"]["repo"],
            data_config["pachyderm"]["branch"],
            data_config["pachyderm"]["token"],
            data_config["pachyderm"]["project"])

        self.curr_folder = repo_folder


        # define model
        print("self.hparams[model]: ",self.hparams['model'] )
        if self.hparams['model'] == 'fasterrcnn_resnet50_fpn':
            pretrained_model = download_pretrained_model(self.hparams['pretrained_model'], "frcnn_xview.pth")
            model = build_frcnn_model_finetune(3,ckpt=pretrained_model)

        model = torch.nn.SyncBatchNorm.convert_sync_batchnorm(model)
        print("Converted all BatchNorm*D layers in the model to torch.nn.SyncBatchNorm layers.")

        # Load Previous Checkpoint
        # if self.hparams['finetune_ckpt'] != None:
        #     checkpoint = torch.load(self.hparams['finetune_ckpt'], map_location='cpu')
        #     model.load_state_dict(checkpoint['model'])

        # wrap model
        self.model = self.context.wrap_model(model)

        # wrap optimizer
        optimizer = torch.optim.SGD(
            self.model.parameters(),
            lr=self.hparams.lr,
            momentum=self.hparams.momentum,
            weight_decay=self.hparams.weight_decay
        )

        self.optimizer = self.context.wrap_optimizer(optimizer)

        scheduler_cls = WarmupWrapper(MultiStepLR)
        print("self.hparams[warmup]:",self.hparams["warmup"])
        print("self.hparams[warmup_iters]:",self.hparams["warmup_iters"])
        print("self.hparams[warmup_ratio]:",self.hparams["warmup_ratio"])
        print("self.hparams[step1]:",self.hparams["step1"])
        print("self.hparams[step2]:",self.hparams["step2"])
        scheduler = scheduler_cls(
            self.hparams["warmup"],  # warmup schedule
            self.hparams["warmup_iters"],  # warmup_iters
            self.hparams["warmup_ratio"],  # warmup_ratio
            self.optimizer,
            [self.hparams["step1"], self.hparams["step2"]],  # milestones
            self.hparams["gamma"],  # gamma
        )
        self.scheduler = self.context.wrap_lr_scheduler(
            scheduler, step_mode=LRScheduler.StepMode.MANUAL_STEP
        )


    def download_data(self):
        data_config = self.context.get_data_config()
        if len(data_config.keys()) > 0:
            data_dir = os.path.join(self.download_directory, "")
            print("--> Downloading to Data Dir: ", data_dir)
        else:
            data_dir = self.hparams['data_dir']
        if data_config is not None:
            data_dir = download_full_pach_repo(
                data_config["pachyderm"]["host"],
                data_config["pachyderm"]["port"],
                data_config["pachyderm"]["repo"],
                data_config["pachyderm"]["branch"],
                data_dir,
                data_config["pachyderm"]["token"],
                data_config["pachyderm"]["project"],
                data_config["pachyderm"]["previous_commit"],
            )
            print(f"Data dir set to : {data_dir}")

        return data_dir

    def build_training_data_loader(self) -> DataLoader:
        data_config = self.context.get_data_config()
        print("data_config: ",data_config)
        if len(data_config.keys()) > 0:
            data_dir = os.path.join(self.download_directory, self.curr_folder)
        else:
            data_dir = self.hparams['data_dir']
        dataset, num_classes = build_xview_dataset_filtered(image_set='train',args=AttrDict({
                                                'data_dir':data_dir,
                                                'backend':'local',
                                                'masks': None,
                                                }))
        print("--num_classes: ",num_classes)

        train_sampler = torch.utils.data.RandomSampler(dataset)

        data_loader = DataLoader(
                                 dataset,
                                 batch_sampler=None,
                                 shuffle=True,
                                 num_workers=self.hparams.num_workers,
                                 collate_fn=unwrap_collate_fn)
        print("NUMBER OF BATCHES IN COCO: ",len(data_loader))# 59143, 7392 for mini coco
        return data_loader


    def build_validation_data_loader(self) -> DataLoader:
        data_config = self.context.get_data_config()
        if len(data_config.keys())> 0:
            data_dir = os.path.join(self.download_directory, self.curr_folder)
        else:
            data_dir = self.hparams['data_dir']
        dataset_test, _ = build_xview_dataset_filtered(image_set='val',args=AttrDict({
                                                'data_dir':data_dir,
                                                'backend':'local',
                                                'masks': None,
                                                }))
        self.dataset_test = dataset_test
        self.base_ds = get_coco_api_from_dataset(dataset_test)

        self.reducer = self.context.wrap_reducer(
            COCOReducer(self.base_ds,['bbox'],[],remapping_dict=self.dataset_test.clstoCatId),
            for_training=False,
            for_validation=True,

        )
        test_sampler = torch.utils.data.SequentialSampler(dataset_test)
        data_loader_test = DataLoader(
                            dataset_test,
                            batch_size=self.context.get_per_slot_batch_size(),
                            sampler=test_sampler,
                            num_workers=self.hparams.num_workers,
                            collate_fn=unwrap_collate_fn)
        self.test_length = len(data_loader_test)# batch size of 2
        print("Length of Test Dataset: ",len(data_loader_test))

        return data_loader_test


    def train_batch(self, batch: TorchData, epoch_idx: int, batch_idx: int) -> Dict[str, torch.Tensor]:
        batch_time_start = time.time()
        images, targets = batch
        images = list(image.to(self.device ,non_blocking=True) for image in images)
        targets = [{k: v.to(self.device ,non_blocking=True) for k, v in t.items()} for t in targets]
        loss_dict = self.model(images, targets)
        losses_reduced = sum(loss for loss in loss_dict.values())
        loss_value = losses_reduced.item()
        self.context.backward(losses_reduced)
        self.context.step_optimizer(self.optimizer)
        self.scheduler.step()
        total_batch_time = time.time() - batch_time_start
        loss_dict['lr'] = self.scheduler.get_lr()[0]
        loss_dict['tr_time'] = total_batch_time
        return loss_dict

    def evaluate_batch(self, batch: TorchData,batch_idx: int) -> Dict[str, Any]:
        images, targets = batch
        model_time_start = time.time()
        loss_dict = {}
        loss_dict['eval_loss']=0.0
        outputs = self.model(images, targets)

        model_time = time.time() - model_time_start
        losses_reduced = sum(loss for loss in loss_dict.values())
        outputs = [{k: v.to('cpu') for k, v in t.items()} for t in outputs]

        result = [
            (target["image_id"].item(), output) for target, output in zip(targets, outputs)
        ]
        self.reducer.update(result)

        # Run after losses_reduced run:
        loss_dict['model_time'] = model_time
        loss_dict['lr'] = self.scheduler.get_lr()[0]

        return loss_dict
