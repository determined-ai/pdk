import pandas as pd
import numpy as np

from utils import preprocess_dataframe

from sklearn.model_selection import train_test_split

import torch
from torch.utils.data import Dataset, DataLoader

class Churn_Dataset(Dataset):
 
  def __init__(self, df, training_cols, label_col):
 
    self.X = torch.tensor(df[training_cols].values.astype(np.float32), dtype=torch.float32)
    self.y = torch.tensor(df[label_col].values.astype(np.float32), dtype=torch.float32).unsqueeze(-1)
 
  def __len__(self):
    return len(self.y)
  
  def __getitem__(self,idx):
    return self.X[idx], self.y[idx]

def get_train_and_validation_datasets(data_file, test_size=0.2, random_seed=42):
    
    full_df = pd.read_csv(data_file)
    
    train_df, val_df = train_test_split(full_df, test_size=test_size, random_state=random_seed)
    train_df.reset_index(drop=True, inplace=True)
    val_df.reset_index(drop=True, inplace=True)
    
    object_cols = list(train_df.columns[train_df.dtypes.values == "object"])
    int_cols = list(train_df.columns[train_df.dtypes.values == "int"])
    float_cols = list(train_df.columns[train_df.dtypes.values == "float"])

    # Churn will be the label, no need to preprocess it
    int_cols.remove("churn")

    numerical_cols = int_cols+float_cols
    
    # Keep an unscaled version of train_df for scaling all dataframes
    unscaled_train_df = train_df.copy()

    train_df = preprocess_dataframe(train_df, unscaled_train_df, numerical_cols)
    val_df = preprocess_dataframe(val_df, unscaled_train_df, numerical_cols)
    
    training_cols = list(train_df.columns)
    label_col = "churn"
    training_cols.remove(label_col)
    
    train_dataset = Churn_Dataset(train_df, training_cols, label_col)
    val_dataset = Churn_Dataset(val_df, training_cols, label_col)
    
    return train_dataset, val_dataset