![alt text][hpe_logo]

[hpe_logo]: ../../deploy/images/hpe_logo.png "HPE Logo"

# PDK - Pachyderm | Determined | KServe
## Object Detection Example
**Date/Revision:** August 30, 2023

This example is based on the **xVIEW** dataset, which can be found here:<br/>
http://xviewdataset.org/

It is one of the largest publicly available datasets of overhead imagery, containing images from complex scenes around the world, annotated using bounding boxes. In the [sample-data](./sample-data/) folder, you will find a small subset of that ([dataset-object-detection.zip](./sample-data/dataset-object-detection.zip)), which will be used to train the model. Naturally, you can download the full dataset from the web site listed above and use it instead.

To setup this PDK flow, please follow the instructions in the [Deployment](../../deploy/README.md#setup) page. Since that page is referring to the [Dogs vs Cats](../dog-cat/readme.md) example, you should make the following changes:

Create the following folder structure in the storage bucket (can be skipped for vanilla kubernetes deployments):

```bash
object-detection
object-detection/config
object-detection/model-store
```

&nbsp;

The project name should be `pdk-object-detection`, and the input repository should be called `object-detection-data`:

```bash
pachctl connect ${MLDM_URL}

pachctl config set active-context ${MLDM_URL}

pachctl create project pdk-object-detection

pachctl config update context --project pdk-object-detection

pachctl create repo object-detection-data

pachctl list repo
```

&nbsp;

**MLDE Experiment Project:**

By default, the MLDE experiment will use the `pdk-object-detection` Project inside the `PDK Demos` workspace. Make sure to create that project before uploading files to the MLDM repo.

&nbsp;

When uploading files to MLDM, make sure to use the correct repository name:

```bash
find ./data/ -name '.DS_Store' -type f -delete

pachctl put file object-detection-data@master:/data1 -f ./data -r
```

&nbsp;

Finally, to test the inference service, look for the `detection-deploy` service hostname, and use the `object_detection.json` file located in the [sample-data](./sample-data/) folder:

```bash
export INGRESS_HOST=$(kubectl -n istio-system get service istio-ingressgateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

export INGRESS_PORT=$(kubectl -n istio-system get service istio-ingressgateway -o jsonpath='{.spec.ports[?(@.name=="http2")].port}')

export SERVICE_HOSTNAME=$(kubectl get inferenceservice detection-deploy -n ${KSERVE_MODELS_NAMESPACE} -o jsonpath='{.status.url}' | cut -d "/" -f 3)

echo $INGRESS_HOST

echo $INGRESS_PORT

echo $SERVICE_HOSTNAME


curl -v -H "Host: ${SERVICE_HOSTNAME}" http://${INGRESS_HOST}:${INGRESS_PORT}/v1/models/object-detection:predict -d @./object_detection.json
```

PS: Depending on your load balancer, you may need to use `.status.loadBalancer.ingress[0].hostname` instead of `.status.loadBalancer.ingress[0].ip` for the `INGRESS_HOST` variable.


The return response should be JSON block with a very long list of values.

&nbsp;

### In the [sample-data](./sample-data/) folder, you will also find a Jupyter Notebook example showing how to load images from a folder or from the sample .json file and generate predictions.
