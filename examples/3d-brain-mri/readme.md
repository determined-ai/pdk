![alt text][hpe_logo]

[hpe_logo]: ../../deploy/images/hpe_logo.png "HPE Logo"

# PDK - Pachyderm | Determined | KServe
## 3D Brain MRI Example
**Date/Revision:** April 30, 2024

This example is based on the **UCSF-PDGM: The University of California San Francisco Preoperative Diffuse Glioma MRI** research dataset, which can be found here:<br/>
https://www.cancerimagingarchive.net/collection/ucsf-pdgm/

The original dataset contains data from 495 unique subjects. The dataset is formed by taking several MRI scans for each patient, “skull stripping” the scan (leaving just the brain image), and de-identifying the patient. The result is 4 MRI volumes per subject, as well as a target segmentation mask. In the [sample-data](./sample-data/) folder, you will find a small subset of the data from 87 subjects ([dataset-3d-brain.zip](./sample-data/dataset-3d-brain.zip)), which will be used to train the model. Given the size of the subset data being 1.1 GiB, the data is stores using git large file storage (`git lfs`). To download the data, use the following commands from within the repo after cloning it:

```bash
git lfs install
git lfs pull
```

To setup this PDK flow, please follow the instructions in the [Deployment](../../deploy/README.md#setup) page. Since that page is referring to the [Dogs vs Cats](../dog-cat/readme.md) example, you should make the following changes:

Create the following folder structure in the storage bucket (can be skipped for vanilla kubernetes deployments):

```bash
pdk-3d-brain-mri
pdk-3d-brain-mri/config
pdk-3d-brain-mri/model-store
```

&nbsp;

The project name should be `pdk-3d-brain-mri`, and the input repository should be called `3d-brain-mri-data`:

```bash
pachctl connect ${MLDM_URL}

pachctl config set active-context ${MLDM_URL}

pachctl create project pdk-3d-brain-mri

pachctl config update context --project pdk-3d-brain-mri

pachctl create repo 3d-brain-mri-data

pachctl list repo
```

&nbsp;

**MLDE Experiment Project:**

By default, the MLDE experiment will use the `pdk-3d-brain-mri` Project inside the `PDK Demos` workspace. Make sure to create that project before uploading files to the MLDM repo.

```bash
det p create "PDK Demos" pdk-3d-brain-mri
```

&nbsp;

**Creating Pipelines**
Review the pipeline files to make sure the input arguments are correct, especially the bucket name and platform (aws/gcs).
```bash
pachctl create pipeline -f training-pipeline.json

pachctl create pipeline -f deployment-pipeline.json
```

&nbsp;

To upload files to MLDM, go to the `sample-data` folder, [download the dataset (`dataset-3d-brain.zip`) and sample json (`3d-brain.json`) payload](https://drive.google.com/drive/folders/1du5eHMRE6VOzUkYRmLdfCdmHRaoBryyy?usp=drive_link), and unzip the dataset and use the `put file` command to upload:

```bash
unzip dataset-3d-brain.zip -d data

find ./data/ -name '.DS_Store' -type f -delete

pachctl put file 3d-brain-mri-data@master:/data -f ./data -r
```

&nbsp;

Finally, to test the inference service, look for the `pdk-3d-brain-mri-deploy` service hostname, and use the `3d-brain.json` file located in the [sample-data](./sample-data/) folder:

```bash
export INGRESS_HOST=$(kubectl -n istio-system get service istio-ingressgateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

export INGRESS_PORT=$(kubectl -n istio-system get service istio-ingressgateway -o jsonpath='{.spec.ports[?(@.name=="http2")].port}')

export SERVICE_HOSTNAME=$(kubectl get inferenceservice pdk-3d-brain-mri-deploy -n ${KSERVE_MODELS_NAMESPACE} -o jsonpath='{.status.url}' | cut -d "/" -f 3)

echo $INGRESS_HOST

echo $INGRESS_PORT

echo $SERVICE_HOSTNAME


curl -v \
-H "Content-Type: application/json" \
-H "Host: ${SERVICE_HOSTNAME}" \
http://${INGRESS_HOST}:${INGRESS_PORT}/v2/models/brain-mri/infer \
-d @./3d-brain.json
```

PS: Depending on your load balancer, you may need to use `.status.loadBalancer.ingress[0].hostname` instead of `.status.loadBalancer.ingress[0].ip` for the `INGRESS_HOST` variable.


The return response should be JSON block with a very long list of values.

&nbsp;

### In the [sample-data](./sample-data/) folder, you will also find a Jupyter Notebook example showing how to load images from a folder or from the sample .json file and generate predictions.
