import os
from typing import Any, Dict, Sequence, Tuple, Union, cast

import data
import filelock
import torch
import torch.nn as nn
from data import download_pach_repo
from determined.pytorch import DataLoader, PyTorchTrial, PyTorchTrialContext
from torch import optim

TorchData = Union[Dict[str, torch.Tensor], Sequence[torch.Tensor], torch.Tensor]


class MRIUnetTrial(PyTorchTrial):
    def __init__(self, context: PyTorchTrialContext):
        self.context = context

        self.data_config = self.context.get_data_config()
        training = os.environ.get("SERVING_MODE") != "true"
        full_dir = "/"

        if training:
            try:
                download_dir = self.data_config["download_directory"]
                data_dir = self.data_config["data_dir"]
                full_dir = os.path.join(full_dir, download_dir.strip("/"), data_dir.strip("/"))

                des = self.download_data(self.data_config, full_dir)

                print("Download Directory = " + full_dir)

                self.train_dataset, self.val_dataset = data.get_train_val_datasets(
                    download_dir,
                    data_dir,
                    self.context.get_hparam("split_seed"),
                    self.context.get_hparam("validation_ratio"),
                )
            except:
                pass

        if training:
            try:
                if not os.path.exists(full_dir):
                    os.makedirs(full_dir)

                with filelock.FileLock(os.path.join(full_dir, "download.lock")):
                    model = torch.hub.load(
                        self.data_config["repo"],
                        self.data_config["model"],
                        in_channels=self.context.get_hparam("input_channels"),
                        out_channels=self.context.get_hparam("output_channels"),
                        init_features=self.context.get_hparam("init_features"),
                        pretrained=self.context.get_hparam("pretrained"),
                    )

                self.model = self.context.wrap_model(model)
                self.optimizer = self.context.wrap_optimizer(
                    optim.Adam(
                        self.model.parameters(),
                        lr=self.context.get_hparam("learning_rate"),
                        weight_decay=self.context.get_hparam("weight_decay"),
                    )
                )
            except:
                pass
        else:
            model = torch.hub.load(
                self.data_config["repo"],
                self.data_config["model"],
                in_channels=self.context.get_hparam("input_channels"),
                out_channels=self.context.get_hparam("output_channels"),
                init_features=self.context.get_hparam("init_features"),
                pretrained=self.context.get_hparam("pretrained"),
            )
            self.model = self.context.wrap_model(model)

    def iou(self, pred, label):
        intersection = (pred * label).sum()
        union = pred.sum() + label.sum() - intersection
        if pred.sum() == 0 and label.sum() == 0:
            return 1
        return intersection / union

    def train_batch(self, batch: TorchData, epoch_idx: int, batch_idx: int):
        imgs, masks = batch
        output = self.model(imgs)
        loss = torch.nn.functional.binary_cross_entropy(output, masks)
        self.context.backward(loss)
        self.context.step_optimizer(self.optimizer)
        iou = self.iou((output > 0.5).int(), masks)
        return {"loss": loss, "IoU": iou}

    def evaluate_batch(self, batch: TorchData):
        imgs, masks = batch
        output = self.model(imgs)
        loss = torch.nn.functional.binary_cross_entropy(output, masks)
        iou = self.iou((output > 0.5).int(), masks)
        return {"val_loss": loss, "val_IoU": iou}

    def build_training_data_loader(self):
        return DataLoader(self.train_dataset, batch_size=self.context.get_per_slot_batch_size(), shuffle=True)

    def build_validation_data_loader(self):
        return DataLoader(self.val_dataset, batch_size=self.context.get_per_slot_batch_size())

    def download_data(self, data_config, data_dir):

        files = download_pach_repo(
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
        return [des for src, des in files]

    # -------------------------------------------------------------------------
