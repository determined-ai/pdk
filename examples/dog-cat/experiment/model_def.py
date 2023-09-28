import logging
import os
from typing import Any, Callable, Dict, List, Sequence, Tuple, Union, cast

import numpy as np
import pachyderm_sdk
import torch
from pachyderm_sdk.api import pfs
from determined import InvalidHP
from determined.pytorch import DataLoader, PyTorchTrial
from PIL import Image
from torch import Tensor
from torch.utils.data import random_split, Dataset
from torch.utils.data.datapipes.map import Mapper
from torchvision import models, transforms

from data import PfsFileDataPipe

DogCatItem = Tuple['Image.Image', int]
TorchData = Union[Dict[str, Tensor], Sequence[Tensor], Tensor]

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)


# =============================================================================


class DogCatModel(PyTorchTrial):
    def __init__(self, context):
        self.context = context
        self.download_directory = (
            f"/tmp/data-rank{self.context.distributed.get_rank()}"
        )

        load_weights = os.environ.get("SERVING_MODE") != "true"
        logging.info(f"Loading weights : {load_weights}")

        if load_weights:
            self.train_ds, self.val_ds = self.create_datasets()
            if len(self.train_ds) == 0:
                print("No data. Aborting training.")
                raise InvalidHP("No data")

        model = models.resnet50(pretrained=load_weights)
        model.fc = torch.nn.Linear(2048, 2)
        optimizer = torch.optim.SGD(
            model.parameters(),
            lr=float(self.context.get_hparam("learning_rate")),
            momentum=0.9,
            weight_decay=float(self.context.get_hparam("weight_decay")),
            nesterov=self.context.get_hparam("nesterov"),
        )

        self.model = self.context.wrap_model(model)
        self.optimizer = self.context.wrap_optimizer(optimizer)
        self.labels = ["dog", "cat"]

    # -------------------------------------------------------------------------

    def train_batch(
        self, batch: TorchData, epoch_idx: int, batch_idx: int
    ) -> Union[Tensor, Dict[str, Any]]:
        batch = cast(Tuple[Tensor, Tensor], batch)
        data, labels = batch

        output = self.model(data)
        loss = torch.nn.functional.cross_entropy(output, labels)

        self.context.backward(loss)
        self.context.step_optimizer(self.optimizer)

        return {"loss": loss}

    # -------------------------------------------------------------------------

    def evaluate_batch(
        self, batch: TorchData, batch_idx: int
    ) -> Dict[str, Any]:
        """
        Calculate validation metrics for a batch and return them as a dictionary.
        This method is not necessary if the user overwrites evaluate_full_dataset().
        """
        batch = cast(Tuple[Tensor, Tensor], batch)
        data, labels = batch
        output = self.model(data)

        pred = output.argmax(dim=1, keepdim=True)
        accuracy = pred.eq(labels.view_as(pred)).sum().item() / len(data)
        return {"accuracy": accuracy}

    # -------------------------------------------------------------------------

    def build_training_data_loader(self) -> DataLoader:
        return DataLoader(
            self.train_ds, batch_size=self.context.get_per_slot_batch_size()
        )

    # -------------------------------------------------------------------------

    def build_validation_data_loader(self) -> DataLoader:
        return DataLoader(
            self.val_ds, batch_size=self.context.get_per_slot_batch_size()
        )

    # -------------------------------------------------------------------------

    def create_datasets(self) -> Tuple[Dataset, Dataset]:
        data_config = self.context.get_data_config()
        pach_config = data_config["pachyderm"]
        client = pachyderm_sdk.Client(
            host=pach_config["host"],
            port=pach_config["port"],
            auth_token=pach_config["token"],
        )
        project = pach_config['project'] or 'default'
        repo, branch = pach_config['repo'], pach_config['branch']
        commit = pfs.Commit.from_uri(f"{project}/{repo}@{branch}")
        previous_commit = None
        if pach_config['previous_commit']:
            previous_commit = pfs.Commit.from_uri(f"{project}/{repo}@{pach_config['previous_commit']}")

        # Create the DataPipe and convert the output to (Image, Label).
        datapipe = PfsFileDataPipe(client, commit, previous_commit=previous_commit).map(
            lambda item: (Image.open(item['file']), 0 if "dog" in item['info'].file.path else 1)
        ).with_cache()

        print(f"Creating datasets from {len(datapipe)} input files")
        train_size = round(0.81 * len(datapipe))
        val_size = len(datapipe) - train_size
        train, validate = random_split(datapipe, [train_size, val_size])

        print("setting transform for training dataset")
        train = Mapper(train, self.get_test_transforms())
        validate = Mapper(validate, self.get_train_transforms())

        print(f"Datasets created: train_size={train_size}, val_size={val_size}")
        return train, validate

    # -------------------------------------------------------------------------

    def get_train_transforms(self) -> Callable[[DogCatItem], DogCatItem]:
        transform = transforms.Compose(
            [
                transforms.Resize(240),
                transforms.RandomCrop(224),
                transforms.RandomHorizontalFlip(),
                transforms.ToTensor(),
                transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
            ]
        )

        def wrapper(image_label: DogCatItem) -> DogCatItem:
            image, label = image_label
            return transform(image), label
        return wrapper

    # -------------------------------------------------------------------------

    def get_test_transforms(self) -> Callable[[DogCatItem], DogCatItem]:
        transform = transforms.Compose(
            [
                transforms.Resize(240),
                transforms.CenterCrop(224),
                transforms.ToTensor(),
                transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
            ]
        )

        def wrapper(image_label: DogCatItem) -> DogCatItem:
            image, label = image_label
            return transform(image), label
        return wrapper

    # -------------------------------------------------------------------------

    def predict(
        self, X: np.ndarray, names, meta
    ) -> Union[np.ndarray, List, str, bytes, Dict]:
        image = Image.fromarray(X.astype(np.uint8))
        logging.info(f"Image size : {image.size}")

        image = self.get_test_transforms()(image)
        image = image.unsqueeze(0)

        with torch.no_grad():
            output = self.model(image)[0]
            pred = np.argmax(output)
            logging.info(f"Prediction is : {pred}")

        return [self.labels[pred]]

# =============================================================================
