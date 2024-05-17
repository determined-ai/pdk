![alt text][hpe_logo]

[hpe_logo]: ../../deploy/images/hpe_logo.png "HPE Logo"

# PDK - Pachyderm | Determined | KServe
## Object Detection Example
**Date/Revision:** February 23, 2024

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

# Step 1: Prepare Environment (Fresh Install)

You will prepare the demo environment by using a JupyterLab config in your deployed MLDE cluster.
The below 


FO

```yaml
bind_mounts: null
debug: false
description: andrew-test
entrypoint: null
environment:
  add_capabilities: null
  drop_capabilities: null
  environment_variables: {}
  force_pull_image: false
  image:
    cpu: mendeza/sat-obj-det-demo:0.0.3
    cuda: mendeza/sat-obj-det-demo:0.0.3
    rocm: mendeza/sat-obj-det-demo:0.0.3
  pod_spec:
    apiVersion: v1
    kind: Pod
    metadata:
      creationTimestamp: null
    spec:
      containers:
        - name: determined-container
          resources: {}
          volumeMounts:
            - mountPath: /run/determined/workdir/shared_fs
              name: shared-fs
      nodeSelector:
        nvidia.com/gpu.product: NVIDIA-A100-PCIE-40GB
      runtimeClassName: nvidia
      volumes:
        - name: shared-fs
          persistentVolumeClaim:
            claimName: shared-fs
    status: {}
  ports: null
  proxy_ports: null
idle_timeout: null
notebook_idle_type: kernels_or_terminals
pbs: {}
resources:
  devices: null
  is_single_node: null
  resource_pool: default
  slots: 1
  weight: 1
slurm: {}
work_dir: /run/determined/workdir/shared_fs

```

# Step 1: Prepare Environment (Returning user)
RETURNING USER: Select `` template and open terminal


# Step 2. 
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

```bash
det p create "PDK Demos" pdk-object-detection
```

**Creating Pipelines**
Review the pipeline files to make sure the input arguments are correct, especially the bucket name and platform (aws/gcs).
```bash
pachctl create pipeline -f pipelines/training-pipeline.json

pachctl create pipeline -f pipelines/_on_prem_deployment-pipeline.json
```

&nbsp;
&nbsp;

To upload files to MLDM, go to the `sample-data` folder, unzip the dataset and use the `put file` command to upload:

```bash
apt-get update && apt-get install unzip
unzip dataset-object-detection.zip

find ./data/ -name '.DS_Store' -type f -delete

pachctl put file object-detection-data@master:/data1 -f ./data -r
```

&nbsp;

Finally, to test the inference service, look for the `detection-deploy` service hostname, and use the `object_detection.json` file located in the [sample-data](./sample-data/) folder:

```bash
export INGRESS_HOST=$(k -n istio-system get service istio-ingressgateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

export INGRESS_PORT=$(k -n istio-system get service istio-ingressgateway -o jsonpath='{.spec.ports[?(@.name=="http2")].port}')

export SERVICE_HOSTNAME=$(k get inferenceservice detection-deploy -n ${KSERVE_MODELS_NAMESPACE} -o jsonpath='{.status.url}' | cut -d "/" -f 3)

echo $INGRESS_HOST

echo $INGRESS_PORT

echo $SERVICE_HOSTNAME

curl -v \
-H "Content-Type: application/json" \
-H "Host: ${SERVICE_HOSTNAME}" \
http://${INGRESS_HOST}:${INGRESS_PORT}/v1/models/object-detection

curl -v -H Content-Type: application/json -H Host: detection-deploy.pdk.192.168.11.103.sslip.io http://192.168.11.103:80/v1/models/object-detection


curl -v \
-H "Content-Type: application/json" \
-H "Host: ${SERVICE_HOSTNAME}" \
http://${INGRESS_HOST}:${INGRESS_PORT}/v1/models/object-detection:predict \
-d @./object_detection.json
```

PS: Depending on your load balancer, you may need to use `.status.loadBalancer.ingress[0].hostname` instead of `.status.loadBalancer.ingress[0].ip` for the `INGRESS_HOST` variable.


The return response should be JSON block with a very long list of values.

&nbsp;

### In the [sample-data](./sample-data/) folder, you will also find a Jupyter Notebook example showing how to load images from a folder or from the sample .json file and generate predictions.
