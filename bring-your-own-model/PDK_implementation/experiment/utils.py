import pandas as pd
import torch
import json

# Apply standard scaling to all numerical columns of df, using mean and std given in json file
def scale_data(df, json_numscale="numscale.json"):
    f = open(json_numscale)
    scale_dict = json.load(f)
    f.close()
    for col in scale_dict:
        df[col] = (df[col] - scale_dict[col]["mean"]) / scale_dict[col]["std"]
    
    return df

# One-hot encode all categorical features, assuming we know all values they may take
def encode_categories(df):
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

# Make sure not to pass a scaled "reference_df" as argument, since we use its values to scale df
def preprocess_dataframe(df, reference_df, numerical_cols):
    df = scale_data(df)
    df = encode_categories(df)
    return df
