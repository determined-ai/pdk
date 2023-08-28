from typing import Any, Dict, Union, Sequence

from data import Churn_Dataset, get_train_and_validation_datasets

import torch
from torch import nn
from torch import optim
from determined.pytorch import DataLoader, PyTorchTrial, PyTorchTrialContext

TorchData = Union[Dict[str, torch.Tensor], Sequence[torch.Tensor], torch.Tensor]

class ChurnTrial(PyTorchTrial):
    def __init__(self, context: PyTorchTrialContext):
        # Initialize the trial class and wrap the models, optimizers, and LR schedulers.
        
        # Store trial context for later use.
        self.context = context

        # Initialize the model and wrap it using self.context.wrap_model().
        self.model = nn.Sequential(
                                    nn.Linear(139, self.context.get_hparam("dense1")),
                                    nn.Linear(self.context.get_hparam("dense1"), 1),
                                    nn.Sigmoid()
                                )
        self.model = self.context.wrap_model(self.model)

        # Initialize the optimizer and wrap it using self.context.wrap_optimizer().
        self.optimizer = optim.Adam(self.model.parameters(), lr=self.context.get_hparam("lr"))
        self.optimizer = self.context.wrap_optimizer(self.optimizer)
        
        self.loss_function = nn.BCELoss()


    def train_batch(self, batch: TorchData, epoch_idx: int, batch_idx: int):
        # Run forward passes on the models and backward passes on the optimizers.
        
        X, y = batch
        
        # Define the training forward pass and calculate loss.
        output = self.model(X)
        loss = self.loss_function(output, y)
        
        # Define the training backward pass and step the optimizer.
        self.context.backward(loss)
        self.context.step_optimizer(self.optimizer)
        
        # Compute accuracy
        output[output < 0.5] = 0.0
        output[output >= 0.5] = 1.0
        acc = torch.sum(output == y) / len(y)
        
        return {"loss": loss, "acc": acc}

    def evaluate_batch(self, batch: TorchData):
        # Define how to evaluate the model by calculating loss and other metrics
        # for a batch of validation data.
        X, y = batch
        
        output = self.model(X)
        val_loss = self.loss_function(output, y)
        
        output[output < 0.5] = 0.0
        output[output >= 0.5] = 1.0
        val_acc = torch.sum(output == y) / len(y)
        
        return {"val_loss": val_loss, "val_acc": val_acc}

    def build_training_data_loader(self):
        # Create the training data loader.
        # This should return a determined.pytorch.Dataset.
        
        train_dataset, _ = get_train_and_validation_datasets(self.context.get_data_config().get("data_file"),
                                                            test_size=self.context.get_hparam("test_size"),
                                                            random_seed=self.context.get_hparam("random_seed"))
        
        return DataLoader(train_dataset, batch_size=self.context.get_per_slot_batch_size())

    def build_validation_data_loader(self):
        # Create the validation data loader.
        # This should return a determined.pytorch.Dataset.
        
        _, val_dataset = get_train_and_validation_datasets(self.context.get_data_config().get("data_file"),
                                                            test_size=self.context.get_hparam("test_size"),
                                                            random_seed=self.context.get_hparam("random_seed"))
        
        return DataLoader(val_dataset, batch_size=self.context.get_per_slot_batch_size())