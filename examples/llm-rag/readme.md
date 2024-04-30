![alt text][hpe_logo]

[hpe_logo]: ../../deploy/images/hpe_logo.png "HPE Logo"

# PDK - Pachyderm | Determined | KServe
## LLM RAG Example
**Date/Revision:** February 23, 2024

This example is based on a new **Retrieval Augumented Generation** demo built by the AI At Scale SE team.<br/>

In this use case, a Vector Database (Chromadb) is used to store vectors from HPE Press Releases. A client application can then query the vectors based on the user's question and have a LLM (Mistral) generate a response. The dataset for this example is made of press releases from HPE, originally in XML format (later converted to CSV). The pre-trained model (Mistral) will run on a Service pipeline, using TitanML (which means KServe will not be used with this example). The client UI will run on a different Service pipeline. Keep in mind that this approach is done for demo purposes and should not be replicated in production environments.

To setup this PDK flow, start by following the instructions in the [Deployment](../../deploy/README.md#setup) page, to make sure the necessary components are in place and working properly. Do keep in mind, however, that this example follows a different structure: for instance, instead of deploying the model to KServe, it will instead run on a MLDM service pipeline.

Also, this example will include certain assets that must be accessible by both MLDM and MLDE, which means we will need to configure the MLDM pipelines to access the shared storage location used by MLDE.

Finally, the full RAG demo does include a Finetune step, where MLDE is used to finetune the LLM. However, an A100 GPU is required to run the finetune, and since we do not have one available in our cluster, this step will be skipped. To see an example notebook of this demo with a finetuning pipeline, please go to this [link](https://github.com/interactivetech/pdk-llm-rag-app/blob/main/Finetune%20and%20Deploy%20RAG%20with%20PDK.ipyn).

&nbsp;

The project name should be `pdk-llm-rag`, which will have 3 input repositories: `code`, `data`, and `model`:

```bash
pachctl connect ${MLDM_URL}

pachctl config set active-context ${MLDM_URL}

pachctl list project

pachctl create project pdk-llm-rag

pachctl config update context --project pdk-llm-rag

pachctl create repo data

pachctl create repo code

pachctl create repo model

pachctl list repo
```

&nbsp;

Since there will be no finetuning step, there is no need to create a MLDE Project, as no experiments will be created.

&nbsp;

To upload the initial files to MLDM, go to the `sample-data` folder and use these commands:

```bash
find . -name '.DS_Store' -type f -delete

pachctl put file data@master: -r -f ./HPE_press_releases/

pachctl put file data@master: -f ./HPE_2023_Press_Releases.csv

pachctl put file code@master: -r -f ./src/
```

&nbsp;

### Creating Pipelines

#### Model Download Pipeline

One of the pipelines will download the necessary models from HuggingFace. Before creating these pipelines, you will need a Huggingface token.

Go to [https://huggingface.co/](https://huggingface.co/) and login (or create an account), then go to `Settings`, `Access Tokens` and create a new token. Make a copy of the new token value, which should start with `hf_`.

The next step is to add the new token to the `pipeline-secret` secret, so it can be pulled by the pipeline at runtime. For this, we will need to retrieve the values currently in the secret, add the new token and update the secret. 

Use these commands to update the secret with the new token. Make sure to replace the token value in the first command:

```bash
export HF_TOKEN=hf_YOUR_TOKEN_GOES_HERE

export MLDE_HOST=$(kubectl get cm pdk-config -o=jsonpath='{.data.mlde_host}') && echo $MLDE_HOST

export MLDE_PORT=$(kubectl get cm pdk-config -o=jsonpath='{.data.mlde_port}') && echo $MLDE_PORT

export MLDE_ADMIN=$(kubectl get secret pipeline-secret -o jsonpath="{.data.det_user}" | base64 --decode) && echo $MLDE_ADMIN

export MLDE_PASSWORD=$(kubectl get secret pipeline-secret -o jsonpath="{.data.det_password}" | base64 --decode) && echo $MLDE_PASSWORD

export MLDM_HOST=$(kubectl get cm pdk-config -o=jsonpath='{.data.mldm_host}') && echo $MLDM_HOST

export MLDM_PORT=$(kubectl get cm pdk-config -o=jsonpath='{.data.mldm_port}') && echo $MLDM_PORT

export KSERVE_MODELS_NAMESPACE=$(kubectl get cm pdk-config -o=jsonpath='{.data.kserve_model_namespace}') && echo $KSERVE_MODELS_NAMESPACE

kubectl apply -f  - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: pipeline-secret
  namespace: default
stringData:
  det_master: "${MLDE_HOST}:${MLDE_PORT}"
  det_user: "${MLDE_ADMIN}"
  det_password: "${MLDE_PASSWORD}"
  pac_token: ""
  hf_token: "${HF_TOKEN}"
  pachd_lb_service_host: "${MLDM_HOST}"
  pachd_lb_service_port: "${MLDM_PORT}"
  kserve_namespace: "${KSERVE_MODELS_NAMESPACE}"
EOF
```

&nbsp;

Since the models will be saved to the shared storage, we'll need to configure the pipeline to mount the persistent volume claim as a shared folder that can be accessed by the python script. First, check the name of your PVCs:

```bash
kubectl get pvc

kubectl -n gpu-pool get pvc
```

Both should have the same name (`pdk-pvc`). If you see a different name, update the `model_download.json` pipeline file before proceeding. The `pod_patch` configuration will be at the end of the file.

Also, to prevent out-of-memory issues, this pipeline will run with more memory (24GBs), as defined by the `resourceRequests` setting, and on a T4 GPU, as defined by the `resourceLimits` and `tolerations` settings. Since `autoscaling` is set to true, the GPU and memory will not be used unless the pipeline is actually running.

If everythinng looks good, create the pipeline:
```bash
cd ../pipelines

pachctl create pipeline -f model_download.json
```

&nbsp;

This pipeline works by receiving a JSON file with a list of models that need to be downloaded. Each item in that list must contain the name of the model (to match Hugginface's catalog) and a shorter name to be used internally (to create a subfolder for this model in the storage).

Use the following commands to create the JSON file and upload it to the repo:
```bash
echo "[{\"model_id\" : \"mistralai/Mistral-7B-Instruct-v0.1\", \"model_name\" : \"mistral\"}]" > mistral.json

pachctl put file model@master:/mistral/models.json -f mistral.json
```

PS: In this case, we're downloading the `mistralai/Mistral-7B-Instruct-v0.1` model from HuggingFace. It will be saved in the `mistral` shared folder.

The pipeline will take several minutes to execute (it will also save the model to the output repo for this pipeline). If the pipeline fails with insufficient memory errors, you may need close other tasks that might be using GPUs, like notebooks or experiments. Wait until the pipeline status changes to `Success` before continuing. It will be slow at the end, as the pipeline will upload the model files to the storage bucket.

Once the step is completed, you should be able to find the model in the shared folder:

![alt text][example_llm_model]

[example_llm_model]: ../../deploy/images/example_llm_model.png "Saved Model"


&nbsp;

Next, download the model used to generate tokens for the Vector Database. This is a much smaller model, so the pipeline should execute faster than the previous one:

```bash
echo "[{\"model_id\" : \"sentence-transformers/all-MiniLM-L6-v2\", \"model_name\" : \"minilm\"}]" > minilm.json

pachctl put file model@master:/minilm/models.json -f minilm.json
```

&nbsp;

#### Process XML Pipeline

This step will read the XML files from the `data` repository and export them to CSV format.

```bash
pachctl create pipeline -f process_xml.json
```

&nbsp;

#### Vector DB Pipeline


This step will read the CSV data, split it and insert it into a Vector DB (chromadb), using the `MiniLM` model to generate the vectors. The database files will be saved to the shared storage location (under `shared_fs/rag_db`)

```bash
pachctl create pipeline -f vector_db.json
```

PS: If you look at the pipeline settings, you may notice these commands at the end of the `stdin` configuration:

```bash
echo \"$(openssl rand -base64 12)\" > /pfs/out/vector_db.txt
```

This is done because empty repositories don't trigger pipelines. Any pipelines that are pulling from this repo would never be executed, and because the next step will be connected to this one, since we do not want to serve the RAG application if the Vector DB was never created, we need to have some file in the output repo of this step; so these commands will generate a text file with a random string and save it to `/pfs/out`. 


&nbsp;

#### Titan ML Pipeline

The RAG application will search in the Vector Database for data that is similar to the question embeddings. Once if finds content, it will run the prompt and the Vector DB data through a LLM, so it can output a 'human-friendly' response.

This pipeline step will run the LLM in a service pipeline, using Titan ML as the inferencing component. Do be aware that this will require a T4 GPU, which will be allocated for as long as the pipeline is running (service pipelines do not downscale automatically, they run until they are deleted).

Titan ML requires some environment variables. A simple way to map them to the pipeline is by saving them as secrets. Use this command to create the secret with the necessary variables:

```bash
kubectl apply -f  - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: titanml-secret
  namespace: default
stringData:
  TAKEOFF_MODEL_NAME: "/run/determined/workdir/shared_fs/model/mistral"
  TAKEOFF_DEVICE: "cuda"
  API_PORT: "8080"
EOF
```

Next, create the pipeline:

```bash
pachctl create pipeline -f titan_ml.json
```

After about one minute, this service pipeline should have an IP (or DNS address) associated with it. Use the following command to grab the IP (or DNS):

```bash
export TITAN_HOST=$(pachctl inspect pipeline titan-ml --raw -o json | jq -r ."details.service.ip") && echo $TITAN_HOST
```

If you get an empty response, it means an address was not yet attached to this service (or the pipeline failed for some reason). Wait until you see an output value before continuing.

&nbsp;

#### Client UI Pipeline

In an actual production environment, service pipelines wouldn't be used for Titan ML or for the Client UI. The only reason we're using service pipelines here is that they make it easier to deploy and manage these services, for testing purposes. Be aware that this approach is **definitely not recommended** for production.

The client UI also needs a few environment variables, including the address for the Titan ML service. As before, we'll use a secret to store this data so it can be mapped to the pipeline:

```bash
kubectl apply -f  - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: clientui-secret
  namespace: default
stringData:
  API_HOST: "$TITAN_HOST"
  API_PORT: "8080"
  DB_PATH: "/run/determined/workdir/shared_fs/rag_db"
EOF
```

PS: If you restart the Titan ML pipeline, you will need to retrieve the new address and update the secret.

Finally, create the Client UI pipeline:

```bash
pachctl create pipeline -f ui-client.json
```

After a few minutes, the UI should be available. Use these commands to grab the URL:

```bash
export UI_HOST=$(pachctl inspect pipeline ui-client --raw -o json | jq -r ."details.service.ip") && echo $UI_HOST

export UI_URL="http://${UI_HOST}:8080"

echo $UI_URL
```

As before, wait until you have an address you can use.

At this time, you should be able to access the UI through the URL printed on the terminal. Try asking a question like *'What is HPE Greenlake for LLMs?'*

![alt text][example_llm_chatui]

[example_llm_chatui]: ../../deploy/images/example_llm_chatui.png "RAG Chat UI"



PS: If you get a connection error, make sure port 8080 is opened in your firewall. On AWS, this can be done by configuring the Security Groups. On GCP, you should create a firewall rule. The node groups have a `pdk` tag you can use when defining the scope of your firewall rule:

![alt text][example_llm_gcp_firewall]

[example_llm_gcp_firewall]: ../../deploy/images/example_llm_gcp_firewall.png "GCP Firewall Rule"


&nbsp;
