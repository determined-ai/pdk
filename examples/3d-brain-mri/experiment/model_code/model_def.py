import os
from typing import Any, Dict, Sequence, Tuple, Union, cast

from vnet import VNet
from diceloss import GeneralizedDiceLoss

import data
import filelock
import torch
from data import download_pach_repo
from determined.pytorch import DataLoader, PyTorchTrial, PyTorchTrialContext
from utils import weights_init, tb_write_video

TorchData = Union[Dict[str, torch.Tensor], Sequence[torch.Tensor], torch.Tensor]

class MRIVnetTrial(PyTorchTrial):
    def __init__(self, context: PyTorchTrialContext):
        self.context = context

        self.data_config = self.context.get_data_config()
        training = os.environ.get("SERVING_MODE") != "true"
        full_dir = "/"
        self.writer = context.get_tensorboard_writer()
        print(self.writer.log_dir)
        
        if training:
            try:
                download_dir = self.data_config["download_directory"]
                data_dir = self.data_config["data_dir"]
                full_dir = os.path.join(full_dir, download_dir.strip("/"))
                lockfile = os.path.join(full_dir, "download.lock")

                # Avoid donwloading the data multiple times in distributed trainings
                with filelock.FileLock(lockfile):
                    if not os.path.exists(os.path.join(full_dir,data_dir.strip('/'))):
                        des = self.download_data(self.data_config, full_dir)
                        print("Download Directory = " + full_dir)

                self.train_dataset, self.val_dataset = data.get_train_val_datasets(
                    download_dir,
                    data_dir,
                    self.context
                )
                self.num_batches = len(self.train_dataset)//self.context.get_global_batch_size()
            except:
                pass
        
        if training:
            try:
                self.model = VNet(
                            in_channels=self.context.get_hparam("input_channels"),
                            classes=self.context.get_hparam("num_classes"),
                            dropout=self.context.get_hparam("dropout"),
                            elu=self.context.get_hparam("elu")
                )
                self.model.apply(weights_init)
                self.model = self.context.wrap_model(self.model)
                self.optimizer = self.context.wrap_optimizer(
                    torch.optim.Adam(
                        self.model.parameters(),
                        lr=self.context.get_hparam("learning_rate"),
                        weight_decay=self.context.get_hparam("weight_decay")
                    )
                )
                self.loss = GeneralizedDiceLoss(classes=self.context.get_hparam("num_classes"))
            except:
                pass
        else:
            self.model = VNet(
                        in_channels=self.context.get_hparam("input_channels"),
                        classes=self.context.get_hparam("num_classes"),
                        dropout=self.context.get_hparam("dropout"),
                        elu=self.context.get_hparam("elu")
            )
            self.model.apply(weights_init)
            self.model = self.context.wrap_model(self.model)
            self.loss = GeneralizedDiceLoss(classes=self.context.get_hparam("num_classes"))
    

    def train_batch(self, batch: TorchData, epoch_idx: int, batch_idx: int):
        imgs, masks = batch
        output = self.model(imgs)
        loss, dice_scores = self.loss(output, masks)
        self.context.backward(loss)
        self.context.step_optimizer(self.optimizer, auto_zero_grads=True)
        
        # Write 3D slice video to Tensorboard every n epochs
        tb_epochs = 2
        if ((batch_idx/self.num_batches % tb_epochs) == 0) and self.context.distributed.get_rank() == 0:
            tb_write_video(self.writer, 'train_collage', imgs, masks, output, epoch_idx)
        return {"loss": loss, "Dice": dice_scores[-1]}

    def evaluate_batch(self, batch: TorchData):
        imgs, masks = batch
        output = self.model(imgs)
        loss, dice_scores = self.loss(output, masks)
        return {"val_loss": loss, "val_Dice": dice_scores[-1]}

    def build_training_data_loader(self):
        return DataLoader(self.train_dataset, batch_size=self.context.get_per_slot_batch_size(), shuffle=True, num_workers=4)

    def build_validation_data_loader(self):
        return DataLoader(self.val_dataset, batch_size=2*self.context.get_per_slot_batch_size(), num_workers=4)

    def download_data(self, data_config, data_dir):

        files = download_pach_repo(
            data_config["pachyderm"]["host"],
            data_config["pachyderm"]["port"],
            data_config["pachyderm"]["repo"],
            data_config["pachyderm"]["branch"],
            data_dir,
            data_config["pachyderm"]["token"],
            data_config["pachyderm"]["project"]
        )
        print(f"Data dir set to : {data_dir}")
        return [des for src, des in files]
    # -------------------------------------------------------------------------