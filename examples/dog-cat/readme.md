![alt text][hpe_logo]

[hpe_logo]: ../../deploy/images/hpe_logo.png "HPE Logo"

# PDK - Pachyderm | Determined | KServe
## Dogs and Cats Example
**Date/Revision:** August 30, 2023

This example is based on the **Dogs vs Cats** Kaggle dataset, which can be found here:<br/>
https://www.kaggle.com/c/dogs-vs-cats/data?select=train.zip

The original dataset contains 25,000 images that can be used for model training. In the [sample-data](./sample-data/) folder, you will find a small subset of that ([dataset-dog-cat.zip](./sample-data/dataset-dog-cat.zip)), which will be used to train the model. Naturally, you can download the full dataset from Kaggle and use it instead.

To setup this PDK flow, please follow the instructions in the [Deployment](../../deploy/README.md#setup) page. Since those instructions are referring to this example, you can follow the steps exactly as documented.


&nbsp;

### In the [sample-data](./sample-data/) folder, you will also find a Jupyter Notebook example showing how to load images from a folder or from the sample .json files and generate predictions.