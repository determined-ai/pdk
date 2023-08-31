![alt text][hpe_logo]

[hpe_logo]: ../deploy/images/hpe_logo.png "HPE Logo"

# PDK - Pachyderm | Determined | KServe
## Bringing Your Model to PDK
**Date/Revision:** August 30, 2023

In this section, we will train and deploy a simple customer churn model on PDK.

This example starts from files defining a MLDE experiment independent any from MLDM integration. It will go through the steps that need to be followed to integrate this experiment to the MLDM training pipeline and then to deploy the resulting model with KServe.

The dataset used for this example is an edited and simplified version of this [dataset](https://www.kaggle.com/datasets/abhinav89/telecom-customer) from Kaggle. The base MLDE experiment will train a very simple binary classification model on this dataset to predict whether a customer will churn (1) or not (0).

**Important notes:**
* This is just one implementation example of a training and a deployment pipeline in MLDM using a MLDE experiment, similar results can be achieved with  with other proper use of MLDM.
* This example is based on a MLDE experiment using the **PyTorch Trial API**, some additional changes will be required if the starting MLDE experiment is based on CoreAPI or TFKeras Trial API. For example, when using CoreAPI, checkpoints cannot be loaded using _load_trial_from_checkpoint_path_ as currently done in **deploy.py**, and if the model hasn't been trained using PyTorch, other significant changes will have to be made in **deploy.py**.

&nbsp;
# Prerequisites

* MLDM + MLDE + KServe environment properly set up and tested (see [setup](../deploy/README.md) page for instructions).
* Git, as changes to the experiment config files will most likely be required
* Docker to create new train/deploy images, push them to Docker Hub and use them to define your training and deployment pipelines.

&nbsp;

# Files

**base_experiment** contains files used to start a regular experiment on the MLDE platform, training a small dense neural network with the PyTorchTrial API.

**PDK_implementation** contains three folders:
  * **container** contains all the necessary files to create the two images used in training and deployment pipelines.
  * **experiment** contains files to run the experiment when the training pipeline is triggered. These are adapted from the files in the **base_experiment** folder.
  * **pipelines** contains the JSON files used to create both the training and the deployment pipelines on MLDM.

**sample-data** subfolder contains three files:
  * **data_part1.csv** containing 31009 samples, used in the base experiment. This is the first dataset you should commit to your MLDM repository.
  * **data_part2.csv** containing 31000 samples, used to to trigger the training pipeline a second time after commiting to the same MLDM repository. This allows to test model retraining.
  * **customer_churn_sample.csv** containing 10 samples, to test model inference.

&nbsp;

  Keep in mind that the syntax to upload a single file to MLDM is different than the one used in the deployment pages:
  ```bash
  pachctl put file customer-churn-data@master:data_part1.csv -f ./data/data_part1.csv
  ```

&nbsp;

# Porting a model from a regular MLDE experiment to PDK

## Step 1: Adapting the original experiment files

Be sure to check the difference between the original, base MLDE experiment files under **base_experiment** and their version adapted to PDK, under **PDK_implementation/experiment**.

For convenience, most additions to the base experiment files are preceded by "# New" comments.

### Step 1-1: Changes to the original experiment config file
* Data used to train the model will come from a MLDM repository that may be regularly updated with new data. Therefore, data files or data paths hardcoded in the experiment config file should be removed. Instead, add all the MLDM keys with empty values to the config file, as shown in **const.yaml**:
```
data:
  pachyderm:
    host:
    port:
    repo:
    branch:
    token:
    previous_commit:
```

&nbsp;
* Additionally, if the original experiment had a training length specified in number of epochs, it may be convenient to **define training length in number of batches instead** (the same applies for **min_validation_period**).
  * Indeed, the number of samples in the training set will now vary as new data gets committed to the MLDM repository, and knowing that number of samples is mandatory to define training length in number of epochs.
  * Note that the training pipeline image could be modified to deal with that issue, but specifying the training length in batches is a simple solution.
* Depending on the organization of the MLDE cluster where these automatically triggered experiments are expected to run, it may also be a good idea to **edit the workspace and project fields accordingly**.

&nbsp;

### Step 1-2: Add code to download data from MLDM
* In **startup-hook.sh**, install python-pachyderm.
* In **data.py**, add the imports (_os_, _shutil_, _python-pachyderm_) that are required to define the two new functions to add: _safe_open_wb_, and _download_pach_repo_. The later one being used to download data from the MLDM repository.
  * **Note:** In this example, _download_pach_repo_ will only download files corresponding to the difference between current and last commit on the MLDM repository. It won't redownload and retrain on the initial *data_part1* if *data_part2* has been committed afterwards. You can change that behaviour by editing the _download_pach_repo_ function.
* In **model_def.py**:
  * Add _os_, _logging_ and _download_pach_repo_ as imports
  * In \_\__init___, check if the model is expected to be trained (which would require downloading data from the MLDM repository, building the training set and building the validation sets) or not.
  * Add the _download_data_ function, that will call the _download_pach_repo_ function to download files from the MLDM repository and return the list of those files.
		
### Step 1-3: Make sure the code handles the output of the _download_data_ function

The original code may not handle a list of files, as output by the _download_data_ function. In this example, in the base experiment, a single csv data file was expected, while a list of files can be expected with the PDK experiment. Depending on your original code, and how you expect your data to be committed to MLDM, this may or may not require changes.

In this example, the _get_train_and_validation_datasets_ function from **data.py** has been changed to concatenate a list of csv files into a single pandas DataFrame.

## Step 2: Preparing MLDM and MLDE

### Step 2-1: Create MLDM Project and Repository

Run these commands to create the project and repository in your MLDM instance:
```bash
pachctl connect ${MLDM_URL}

pachctl create project pdk-customer-churn

pachctl config update context --project pdk-customer-churn

pachctl create repo customer-churn-data
```

### Step 2-2: Create MLDE Project in the PDK Demos Workspace

By default, we are using the same Workspace that was created in the deployment tutorial (PDK Demos) and a new project called `pdk-customer-churn`. Go to the MLDE UI and create this project in the `PDK Demos` workspace.


&nbsp;
## Step 3: Create the training pipeline

As noted in the [deployment](../deploy/README.md) page, the pipeline configuration will be slightly different for environments that use shared folders, when compared to environments that use storage buckets. Read the instructions in the deployment page and inspect the `_on_prem_` version of the pipeline files to understand the differences.

### Step 3-1: Select or create an image to define the training pipeline

The process of automatically starting a MLDE experiment when new data is committed to the MLDM repository will unlikely change much. As such, the image currently in use in **training-pipeline.json** probably fits your needs.

In case this is not the case or if you want to dig deeper into the details, all the files used to create this image are available in the **container/train** folder. These files can be edited and then used to build alternate images for a custom training pipeline.
	
### Step 3-2: Define training-pipeline.json

* Name this MLDM pipeline by changing the _pipeline.name_.
* Make sure the input repo matches the MLDM repository where data is expected to be committed.
* Under _transform_:
  * Define the image to be used. The current image corresponds to files in the **container/train** folder and should work well as it is.
  * _stdin_ command will be run when the pipeline is triggered. Make sure to change all the relevant options, in particular:
    * _--git-url_ to point to the Git URL containing the model code, since you probably want to change details in the experiment files.
    * _--sub-dir_ if the file structure of your git repository is different to this one.
    * _--repo_ should match your initial MLDM repository.
    * _--model_ will be the name of the model on the MLDE cluster (in the model registry).
    * _--project_ should match the MLDM project containing the repo you are working with.
  * Assuming the PDK environment has been properly set up, Kubernetes pipeline secrets have already been created and no change should be required under _secrets_.
  * The *pod_patch* entry is needed for environments that leverage shared folders (instead of storage buckets). In this case, use the *_on_prem_* version of the pipeline files and adjust the *pod_patch* entry according to your environment.

## Step 4: Create the deployment pipeline

### Step 4-1: Select or create an image to define the deployment pipeline

The image used in the deployment pipeline is entirely defined by the files under **container/deploy**. To run this example as it is, no change is needed to this image, currently referred in **deployment-pipeline.json**.

However, several changes to this image are expected to deploy another model:
* The PyTorch handler, currently **customer_churn_handler.py** extends the _BaseHandler_ class from **base_handler.py**, which is a default handler. Depending on the model to deploy, another handler might be more relevant to extend, such as _ImageClassifier_ or _TextClassifier_ handlers. Those default handlers are defined [here](https://github.com/pytorch/serve/tree/master/ts/torch_handler)
* We overwrote the following methods from the default _BaseHandler_:
  * \_\__init___, in which we read a json file to define a dictionary of values that are used to properly scale numerical features from the data we expect to read.
  * _preprocess_, in which we read the json request and convert it to an input that is properly scaled, encoded and that can be processed by the model.
  * _inference_, to apply a threshold to the model predictions.
* We also included new methods to this handler, to scale numerical features of the input, as well as to encode its categorical features. These methods have been copied from **utils.py** that was used in Determined experiment.
* Depending on the model to deploy and its expected data, vastly different processing operations can potentially be defined in this handler file.
* To import specific libraries to perform the operations defined in the handler file, the same libraries should be added in **requirements.txt**.
* To add new files to this image, the **Dockerfile** should also be updated accordingly.
* Finally, in **deploy.py**, in the _create_mar_file_ function:
  * The name of the python file where the handler is defined has to be changed, as it currently points to **customer_churn_handler.py**
  * If the handler file relies on additional files, those should be listed as _--extra-files_.

### Step 4-2: Define deployment-pipeline.json

* Similarly to **training-pipeline.json**, name this Pachyderm pipeline by changing _pipeline.name_ and make sure the input repo matches the Pachyderm repo that corresponding to the training pipeline.
* Under _transform_:
  * Define the image to be used. If not running this exact customer churn example, editing this image will be mandatory, as explained in step 3-1.
  * _stdin_ command will be run when the pipeline is triggered. Make sure to change all the relevant options, in particular:
    * _--deployment-name_, which will be the name of the KServe InferenceService
    * _--service-account-name_, which is the name of the Service Account for Pachyderm access if not deploying in the cloud
    * _--tolerations_, --resource-requests and --resource-limits, to specify resources to be used by the deployment
    * If deploying in the cloud, make sure to check the full list of arguments in **common.py**
  * Assuming the Pachyderm/MLDM + Determined/MLDE + KServe environment has properly been set up, Kubernetes pipeline secrets have already been created and no change should be required under _secrets_.
  * As mentioned before, the *pod_patch* entry is needed for environments that leverage shared folders. In this case, use the *_on_prem_* version of the pipeline files and adjust the *pod_patch* entry according to your environment.

For a detailed walkthrough of the PDK deployment steps, please check the [deployment](../deploy/README.md) page.


&nbsp;

## Step 5: Test the Inference Service

To generate a prediction with the `customer_churn_sample.json` file provided in the [sample-data](./sample-data/) folder, run the following code on a Jupyter Notebook:

```python
import glob
import json
import requests

ingress_host="198.162.1.2"
ingress_port=80
model_name="customer-churn"
service_hostname="customer-churn.models.example.com"

sample_file = "./customer_churn_sample.json"
f = open(sample_file)
sample_data = json.load(f)
f.close()

request = {
  "instances":[
    {
      "data": sample_data
    }
  ]
}

url = str("http://") + str(ingress_host) + ":" + str(ingress_port) + "/v1/models/" + str(model_name) + ":predict"
headers = {'Host': service_hostname}
payload = json.dumps(request)

response = requests.post(url, data=payload, headers=headers)
output = response.json()
print(output)

for i in range(len(output['predictions'])):
    sample_result = int(output['predictions'][i][0])
    ground_truth = sample_data['churn'][str(i)]
    print("Ground truth/Predicted: " + str(ground_truth) + "/" + str(sample_result))
```

PS: Make sure the value of `ingress_host` matches your environment.

The output should be similar to this:
```
Ground truth/Predicted: 1/0
Ground truth/Predicted: 0/0
Ground truth/Predicted: 1/0
Ground truth/Predicted: 0/0
Ground truth/Predicted: 0/0
Ground truth/Predicted: 1/0
Ground truth/Predicted: 1/1
Ground truth/Predicted: 1/1
Ground truth/Predicted: 0/0
Ground truth/Predicted: 1/1
```
