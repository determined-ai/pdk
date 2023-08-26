import torch
import logging
import os
import json

import pandas as pd

from ts.torch_handler.base_handler import BaseHandler
from torch.profiler import ProfilerActivity

logger = logging.getLogger(__name__)

class CustomerChurnHandler(BaseHandler):
    """
    CustomerChurnHandler handler class. This handler extends class BaseHandler from base_handler.py, a
    default handler. This handler takes a dictionary of feature values (list of values for each feature) from the request body
    and returns a list of binary predictions (churn - 1, no churn - 0), stored in a list.

    Here method preprocess() and inference() have been overridden while others are reused from parent class.
    We also reused scale_data() and encode_categories() functions previously used in Determined experiment's utils.py to preprocess the request data.
    (We do not expect persons requesting inference to have scaled and encoded their data, instead they can just convert their original pandas DataFrame
    to JSON and submit it as it is)
    """

    def __init__(self):
        super(CustomerChurnHandler, self).__init__()
        
        f = open("numscale.json")
        self.scale_dict = json.load(f)
        f.close()

    def scale_data(self, df):
        for col in self.scale_dict:
            df[col] = (df[col] - self.scale_dict[col]["mean"]) / self.scale_dict[col]["std"]
        
        return df
    
    def encode_categories(self, df):
        expected_categories = {}
        expected_categories["new_cell"] = ['U','Y','N']
        expected_categories["asl_flag"] = ['N','Y']
        expected_categories["area"] = ['NORTHWEST/ROCKY MOUNTAIN AREA','GREAT LAKES AREA','CHICAGO AREA',
         'NEW ENGLAND AREA','DALLAS AREA','CENTRAL/SOUTH TEXAS AREA',
         'TENNESSEE AREA','MIDWEST AREA','PHILADELPHIA AREA','OHIO AREA',
         'HOUSTON AREA','SOUTHWEST AREA','NEW YORK CITY AREA',
         'ATLANTIC SOUTH AREA','SOUTH FLORIDA AREA','CALIFORNIA NORTH AREA',
         'DC/MARYLAND/VIRGINIA AREA','NORTH FLORIDA AREA','LOS ANGELES AREA']
        expected_categories["dualband"] = ['Y','N','T']
        expected_categories["refurb_new"] = ['N','R']
        expected_categories["hnd_webcap"] = ['WCMB','UNKW','WC']
        expected_categories["marital"] = ['S','M','A','U','B']
        expected_categories["ethnic"] = ['N','U','I','S','F','J','Z','M','H','G','D','O','R','B','P','X','C']
        expected_categories["kid0_2"] = ['U','Y']
        expected_categories["kid3_5"] = ['U','Y']
        expected_categories["kid6_10"] = ['U','Y']
        expected_categories["kid11_15"] = ['U','Y']
        expected_categories["kid16_17"] = ['U','Y']
        expected_categories["creditcd"] = ['Y','N']
        
        for col in expected_categories:
            categorical_col = pd.Categorical(df[col], categories=expected_categories[col], ordered=False)
            one_hot_cols = pd.get_dummies(categorical_col, prefix=col)
            df.drop(col, axis=1, inplace=True)
            df = pd.concat([df, one_hot_cols], axis=1)
        
        return df

    def preprocess(self, requests):
        """
        Get the data from the JSON request in a dictionary, convert it to a pandas DataFrame.
        Then scale its numerical features using values from numscale.json, encode its categorical features,
        remove the label column if present in the request and return values from the resulting DataFrame as a tensor.

        Args:
            requests: A list containing a dictionary, might be in the form
            of [{'body': json_file}] or [{'data': json_file}]
        """

        # unpack the data
        data = requests[0].get('body')
        if data is None:
            data = requests[0].get('data')
            
        df = pd.DataFrame.from_dict(data).reset_index(drop=True)
        logger.info('Successfully converted json/dict back to pandas DataFrame')                             
        
        df = self.scale_data(df)
        logger.info('Numerical features successfully scaled')
        
        df = self.encode_categories(df)
        logger.info('Categorical features successfully encoded')
        
        feature_cols = list(df.columns)
        label_col = "churn"
        if label_col in feature_cols:
            feature_cols.remove(label_col)
        
        input_tensor = torch.Tensor(df[feature_cols].values)
        logger.info('Dataframe successfully converted to tensor')

        return input_tensor


    def inference(self, inputs):
        """
        Apply a threshold to predicted values.
        We could have overridden the postprocess function instead.
        """
        output = self.model(inputs.to(self.device))
        output[output < 0.5] = 0
        output[output >= 0.5] = 1
        logger.info('Predictions successfully obtained.')

        return output
