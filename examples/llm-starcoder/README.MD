# LLM Starcoder Example


This example allows you to fine tune the [StarCoder](https://huggingface.co/bigcode/starcoder) model from huggingface using the [Stack Exchange Q&A Pairs.](https://github.com/bigcode-project/starcoder?tab=readme-ov-file#stack-exchange-se)

### Prerequisites
* A HuggingFace account and api key
* Agree to the license on both the [StarCoder](https://huggingface.co/bigcode/starcoder) and [Stack Exchange Instruction](https://huggingface.co/datasets/ArmelR/stack-exchange-instruction) Repos.
* Pachyderm and Determined Installed and setup following the PDK Guides.


### Setup
1) First, create a project in Pachyderm to deploy this example. 
    ```
    pachctl create project starcoder
    pachctl config update context --project starcoder
    ``` 
1) We're going to use the [HF Downloader](https://github.com/tybritten/hf-dataset-downloader) to download both the model and dataset from HuggingFace. We will need to create a secret with your huggingface key to access the model and data. Put your key in the code snipped below and run:
    ```bash
    cat <<EOF > "hf-secret.json"
    {
        "apiVersion": "v1",
        "StringData": {
            "HF_HOME": "<your HF key here>"
        },
        "kind": "Secret",
        "metadata": {
            "name": "hf-download-key"
        },
        "type": "Opaque"
    }
    EOF
    pachctl create secret --file hf-secret.json

    ```
1) Now that the secret is there, lets create the two pipelines. Lets start with the model downloader:
    ```bash
    pachctl create pipeline --jsonnet https://raw.githubusercontent.com/tybritten/hf-dataset-downloader/main/dataset-downloader.jsonnet \
        --arg name="hf-download-starcoder-model" \
        --arg hf_name="bigcode/starcoder" --arg type="model" \
        --arg secretName=hf-download-key
    ```
1) Now lets create the dataset downloader:
    ```bash
    pachctl create pipeline --jsonnet https://raw.githubusercontent.com/tybritten/hf-dataset-downloader/main/dataset-downloader.jsonnet \
        --arg name="hf-download-stack-exchange" \
        --arg dataset_name="ArmelR/stack-exchange-instruction" \
        --arg secretName=hf-download-key
    ```
1) Now it's time to create the training pipeline. You'll need to have your `pipeline-secret` already created like the other PDK examples:
    ```
    pachctl create pipeline -f pipelines/training.pipeline.json
    ```
1) We're using PEFT (parameter efficient fine tuning), so the output of the training needs to be merged with the source model to get the new fine-tuned model. So we're create the peft_merge pipeline:
    ```
    pachctl create pipeline -f pipelines/peft_merge.pipeline.json
    ```
1) Finally, we'll create a service pipeline to use titanML to host the model for testing:
    ```
    pachctl create pipeline -f pipelines/serving.pipeline.json
    ```
