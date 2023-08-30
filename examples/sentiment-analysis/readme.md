![alt text][hpe_logo]

[hpe_logo]: ../../deploy/images/hpe_logo.png "HPE Logo"

# PDK - Pachyderm | Determined | KServe
## Sentiment Analysis - Finbert Example
**Date/Revision:** August 30, 2023

This example is based on the **Financial PhraseBank from Malo et al. (2014)** example, which can be found here:<br/>
https://www.researchgate.net/publication/251231364_FinancialPhraseBank-v10

The [sample-data](./sample-data/) folder contains a pre-processed dataset ([dataset-brain.zip](./sample-data/dataset-brain.zip)), which will be used to train the model.

To setup this PDK flow, please follow the instructions in the [Deployment](../../deploy/README.md#setup) page. Since that page is referring to the [Dogs vs Cats](../dog-cat/readme.md) example, you should make the following changes:

Create the following folder structure in the storage bucket (can be skipped for vanilla kubernetes deployments):

```bash
finbert
finbert/config
finbert/model-store
```


The project name should be `pdk-finbert`, and the input repository should be called `finbert-data`:

```bash
pachctl connect ${MLDM_URL}

pachctl config set active-context ${MLDM_URL}

pachctl create project pdk-finbert

pachctl config update context --project pdk-finbert

pachctl create repo finbert-data

pachctl list repo
```

&nbsp;

**MLDE Experiment Project:**

By default, the MLDE experiment will use the `pdk-finbert` Project inside the `PDK Demos` workspace. Make sure to create that project before uploading files to the MLDM repo.

&nbsp;


**MLDM Pipelines:**

This use case has an additional pipeline to prepare the data. Make sure to create the `prep` pipeline, then the `train` and `deploy`:
```bash
pachctl create pipeline -f prep-pipeline.json

pachctl create pipeline -f training-pipeline.json

pachctl create pipeline -f deployment-pipeline.json
```

&nbsp;


When uploading files to MLDM, make sure to use the correct repository name:

```bash
find ./finbert/ -name '.DS_Store' -type f -delete

pachctl put file finbert-data@master:/data1 -f ./finbert -r
```

&nbsp;

Finally, to test the inference service, look for the `finbert-deploy` service hostname, and use the `finbert_n.json` files located in the [sample-data](./sample-data/) folder:

```bash
export INGRESS_HOST=$(kubectl -n istio-system get service istio-ingressgateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

export INGRESS_PORT=$(kubectl -n istio-system get service istio-ingressgateway -o jsonpath='{.spec.ports[?(@.name=="http2")].port}')

export SERVICE_HOSTNAME=$(kubectl get inferenceservice finbert-deploy -n ${KSERVE_MODELS_NAMESPACE} -o jsonpath='{.status.url}' | cut -d "/" -f 3)

echo $INGRESS_HOST

echo $INGRESS_PORT

echo $SERVICE_HOSTNAME


curl -v -H "Host: ${SERVICE_HOSTNAME}" http://${INGRESS_HOST}:${INGRESS_PORT}/v1/models/finbert:predict -d @./finbert_0.json
```

PS: Depending on your load balancer, you may need to use `.status.loadBalancer.ingress[0].hostname` instead of `.status.loadBalancer.ingress[0].ip` for the `INGRESS_HOST` variable.


&nbsp;

### In the [sample-data](./sample-data/) folder, you will also find a Jupyter Notebook example showing how to load text inputs from the sample .json files, or just create new inputs in the notebook and generate predictions.