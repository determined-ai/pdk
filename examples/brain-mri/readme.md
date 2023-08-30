![alt text][hpe_logo]

[hpe_logo]: ../../deploy/images/hpe_logo.png "HPE Logo"

# PDK - Pachyderm | Determined | KServe
## Brain MRI Example
**Date/Revision:** August 30, 2023

This example is based on the **Brain MRI Segmentation** Kaggle dataset, which can be found here:<br/>
https://www.kaggle.com/datasets/mateuszbuda/lgg-mri-segmentation

The original dataset contains images from 110 patients that can be used for model training. In the [sample-data](./sample-data/) folder, you will find a small subset of that ([dataset-brain.zip](./sample-data/dataset-brain.zip)), which will be used to train the model. Naturally, you can download the full dataset from Kaggle and use it instead.

To setup this PDK flow, please follow the instructions in the [Deployment](../../deploy/README.md#setup) page. Since that page is referring to the [Dogs vs Cats](../dog-cat/readme.md) example, you should make the following changes:

Create the following folder structure in the storage bucket (can be skipped for vanilla kubernetes deployments):

```bash
brain-mri
brain-mri/config
brain-mri/model-store
```

&nbsp;

The project name should be `pdk-brain-mri`, and the input repository should be called `brain-mri-data`:

```bash
pachctl connect ${MLDM_URL}

pachctl config set active-context ${MLDM_URL}

pachctl create project pdk-brain-mri

pachctl config update context --project pdk-brain-mri

pachctl create repo brain-mri-data

pachctl list repo
```

&nbsp;

**MLDE Experiment Project:**

By default, the MLDE experiment will use the `pdk-brain-mri` Project inside the `PDK Demos` workspace. Make sure to create that project before uploading files to the MLDM repo.

&nbsp;

When uploading files to MLDM, make sure to use the correct repository name:

```bash
find ./brain/ -name '.DS_Store' -type f -delete

pachctl put file brain-mri-data@master:/data1 -f ./brain -r
```

&nbsp;

Finally, to test the inference service, look for the `brain-mri-deploy` service hostname, and use the `brain.json` file located in the [sample-data](./sample-data/) folder:

```bash
export INGRESS_HOST=$(kubectl -n istio-system get service istio-ingressgateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

export INGRESS_PORT=$(kubectl -n istio-system get service istio-ingressgateway -o jsonpath='{.spec.ports[?(@.name=="http2")].port}')

export SERVICE_HOSTNAME=$(kubectl get inferenceservice brain-mri-deploy -n ${KSERVE_MODELS_NAMESPACE} -o jsonpath='{.status.url}' | cut -d "/" -f 3)

echo $INGRESS_HOST

echo $INGRESS_PORT

echo $SERVICE_HOSTNAME


curl -v -H "Host: ${SERVICE_HOSTNAME}" http://${INGRESS_HOST}:${INGRESS_PORT}/v1/models/brain-mri:predict -d @./brain.json
```

PS: Depending on your load balancer, you may need to use `.status.loadBalancer.ingress[0].hostname` instead of `.status.loadBalancer.ingress[0].ip` for the `INGRESS_HOST` variable.


The return response should be JSON block with a very long list of values.

&nbsp;

### In the [sample-data](./sample-data/) folder, you will also find a Jupyter Notebook example showing how to load images from a folder or from the sample .json file and generate predictions.
