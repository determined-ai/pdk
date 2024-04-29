import argparse
import os
import git
import shutil
import time
from functools import partial

import yaml
from determined.common.experimental import ModelVersion
from google.cloud import storage
from kserve import (V1beta1InferenceService, V1beta1InferenceServiceSpec,
                    V1beta1PredictorSpec, V1beta1TorchServeSpec, constants)
from kubernetes import client
from kubernetes.client import V1ResourceRequirements, V1Toleration, V1Container, V1EnvVar

# =====================================================================================

csv_ = partial(str.split, sep=",")


def parse_args():
    parser = argparse.ArgumentParser(description="Deploy a model to KServe")
    parser.add_argument(
        "--deployment-name",
        type=str,
        help="Name of the resulting KServe InferenceService",
        required=True,
    )
    parser.add_argument(
        "--wait",
        type=bool,
        help="Wait for the inference service to be ready before exiting. Only availble for cloud models",
        default=False,
    )
    parser.add_argument(
        "--cloud-model-host",
        type=str,
        help="aws and gcp supported currently for storing model artifacts",
        default=None,
        choices=["gcp", "aws"],
    )
    parser.add_argument(
        "--cloud-model-bucket",
        type=str,
        help="Cloud Bucket name to use for storing model artifacts",
        default=None,
    )
    parser.add_argument(
        "--google-application-credentials",
        type=str,
        help="Path to Google Application Credentials file",
        default=None,
    )
    parser.add_argument(
        "--service-account-name",
        type=str,
        help="For non-cloud deploys, the Service Account Name for Pachyderm Access",
        default=None,
    )
    parser.add_argument(
        "--handler",
        type=str,
        help="Name of the custom TorchServe handler python file",
    )
    parser.add_argument(
        "--git-url",
        type=str,
        help="Git URL of the repository containing the model code",
    )
    parser.add_argument(
        "--git-ref",
        type=str,
        help="Git Commit/Tag/Branch to use",
    )
    parser.add_argument(
        "--sub-dir",
        type=str,
        help="Subfolder to handler file",
    )
    parser.add_argument(
        "--max-request-size",
        type=str,
        help="TorchServe max allowable REST request size in bytes",
        default=6553500,
    )
    parser.add_argument(
        "--max-response-size",
        type=str,
        help="TorchServe max allowable REST response size in bytes",
        default=6553500,
    )
    parser.add_argument(
        "--min-workers",
        type=str,
        help="TorchServe minimum number of worker threads",
        default=1,
    )
    parser.add_argument(
        "--max-workers",
        type=str,
        help="TorchServe maximum number of worker threads",
        default=5,
    )
    parser.add_argument(
        "--batch-size",
        type=str,
        help="TorchServe batch size for inference",
        default=1,
    )
    parser.add_argument(
        "--batch-delay",
        type=str,
        help="TorchServe maximum delay in ms for batch aggregation",
        default=5000,
    )
    parser.add_argument(
        "--response-timeout",
        type=str,
        help="TorchServe maximum response timeout in s for inference",
        default=240,
    )
    parser.add_argument(
        "--k8s-config-file",
        type=str,
        help="The path to the k8s config file",
        default=None,
    )
    parser.add_argument(
        "--tolerations",
        type=csv_,
        help="A comma separated list of tolerations to apply to the deployment in the format of key=value",
        default=None,
    )
    parser.add_argument(
        "--resource-requests",
        type=csv_,
        help="A comma separated list of resource requests to apply to the deployment in the format of key=value",
        default=None,
    )
    parser.add_argument(
        "--resource-limits",
        type=csv_,
        help="A comma separated list of resource limits to apply to the deployment in the format of key=value",
        default=None,
    )
    return parser.parse_args()


# =====================================================================================


def save_to_pfs(model_name, files):
    for file in files:
        if "config" in str(file):
            folder = "config"
        else:
            folder = "model-store"

        prefix = f"{model_name}/{folder}/"
        os.makedirs("/pfs/out/" + prefix, exist_ok=True)
        shutil.copyfile(file, f"/pfs/out/{prefix}{file}")
    print("Save to output repo complete.")


def upload_model_to_s3(model_name, files, bucket_name):
    import boto3

    storage_client = boto3.client("s3")
    for file in files:
        if "config" in str(file):
            folder = "config"
        else:
            folder = "model-store"

        prefix = f"{model_name}/{folder}/"
        storage_client.upload_file("./" + file, bucket_name, prefix + file)

    print("Upload to S3 complete.")


def upload_model_to_gcs(model_name, files, bucket_name):
    storage_client = storage.Client()

    bucket = storage_client.get_bucket(bucket_name)

    for file in files:
        if "config" in str(file):
            folder = "config"
        else:
            folder = "model-store"
        blob = bucket.blob(model_name + "/" + folder + "/" + file)
        blob.upload_from_filename("./" + file)

    print("Upload to GCS complete.")


def upload_model(model_name, files, cloud_provider=None, bucket_name=None):
    if not cloud_provider:
        save_to_pfs(model_name, files)
        return
    print(
        f"Uploading model files to model repository to cloud provider {cloud_provider} in bucket {bucket_name}..."
    )
    if cloud_provider.lower() == "gcp":
        upload_model_to_gcs(model_name, files, bucket_name)
    elif cloud_provider.lower() == "aws":
        upload_model_to_s3(model_name, files, bucket_name)
    else:
        raise Exception(f"Invalid cloud provider {cloud_provider} specified")


# =====================================================================================


def wait_for_deployment(KServe, k8s_namespace, deployment_name, model_name):
    while not KServe.is_isvc_ready(deployment_name, namespace=k8s_namespace):
        print(
            f"Inference Service '{deployment_name}' is NOT READY. Waiting..."
        )
        time.sleep(5)
    print(
        f"Inference Service '{deployment_name}' in Namespace '{k8s_namespace}' is READY."
    )
    response = KServe.get(deployment_name, namespace=k8s_namespace)
    print(
        "Model "
        + model_name
        + " is "
        + str(response["status"]["modelStatus"]["states"]["targetModelState"])
        + " and available at "
        + str(response["status"]["address"]["url"])
        + " for predictions."
    )


# =====================================================================================


def get_version(client, model_name, model_version) -> ModelVersion:
    for version in client.get_model(model_name).get_versions():
        if version.name == model_version:
            return version

    raise AssertionError(
        f"Version '{model_version}' not found inside model '{model_name}'"
    )


# =====================================================================================


def create_inference_service(
    kclient,
    k8s_namespace,
    model_name,
    deployment_name,
    pach_id,
    replace: bool,
    cloud_provider=None,
    bucket_name=None,
    tolerations=None,
    resource_requirements={"requests": {}, "limits": {}},
    sa=None,
):
    repo = os.environ["PPS_PIPELINE_NAME"]
    project = os.environ["PPS_PROJECT_NAME"]
    commit = os.environ["PACH_JOB_ID"]
    kserve_version = "v1beta1"
    api_version = constants.KSERVE_GROUP + "/" + kserve_version
    tol = []
    if tolerations:
        for toleration in tolerations:
            key, value = toleration.split("=")
            tol.append(
                V1Toleration(
                    effect="NoSchedule",
                    key=key,
                    value=value,
                    operator="Equal",
                )
            )
    if cloud_provider == "gcp":
        predictor_spec = V1beta1PredictorSpec(
            tolerations=tol,
            containers=[
                V1Container(
                    name='kserve-container',
                    args=[ 'torchserve', '--start', '--model-store=/mnt/models/model-store', '--ts-config=/mnt/models/config/config.properties'],
                    image='pytorch/torchserve-kfs:0.9.0-gpu',
                    env=[V1EnvVar(name='STORAGE_URI',value=f"gs://{bucket_name}/{model_name}"),
                         V1EnvVar(name='TS_SERVICE_ENVELOPE',value='kservev2'),
                         V1EnvVar(name='PROTOCOL_VERSION',value='v2')],
                    resources=(
                        V1ResourceRequirements(
                            requests=resource_requirements["requests"],
                            limits=resource_requirements["limits"],
                        )
                    )
                )
            ]
        )
    elif cloud_provider == "aws":
        predictor_spec = V1beta1PredictorSpec(
            tolerations=tol,
            containers=[
                V1Container(
                    name='kserve-container',
                    args=[ 'torchserve', '--start', '--model-store=/mnt/models/model-store', '--ts-config=/mnt/models/config/config.properties'],
                    image='pytorch/torchserve-kfs:0.9.0-gpu',
                    env=[V1EnvVar(name='STORAGE_URI',value=f"aws://{bucket_name}/{model_name}"),
                         V1EnvVar(name='TS_SERVICE_ENVELOPE',value='kservev2'),
                         V1EnvVar(name='PROTOCOL_VERSION',value='v2')],
                    resources=(
                        V1ResourceRequirements(
                            requests=resource_requirements["requests"],
                            limits=resource_requirements["limits"],
                        )
                    )
                )
            ]
        )
    else:
        predictor_spec = V1beta1PredictorSpec(
            tolerations=tol,
            containers=[
                V1Container(
                    name='kserve-container',
                    args=[ 'torchserve', '--start', '--model-store=/mnt/models/model-store', '--ts-config=/mnt/models/config/config.properties'],
                    image='pytorch/torchserve-kfs:0.9.0-gpu',
                    env=[V1EnvVar(name='STORAGE_URI',value=f"s3://{commit}.master.{repo}.{project}/{model_name}"),
                         V1EnvVar(name='TS_SERVICE_ENVELOPE',value='kservev2'),
                         V1EnvVar(name='PROTOCOL_VERSION',value='v2')],
                    resources=(
                        V1ResourceRequirements(
                            requests=resource_requirements["requests"],
                            limits=resource_requirements["limits"],
                        )
                    )
                )
            ],
            service_account_name=sa
        )
    isvc = V1beta1InferenceService(
        api_version=api_version,
        kind=constants.KSERVE_KIND,
        metadata=client.V1ObjectMeta(
            name=deployment_name,
            namespace=k8s_namespace,
            annotations={
                "sidecar.istio.io/inject": "false",
                "pach_id": pach_id,
            },
        ),
        spec=V1beta1InferenceServiceSpec(predictor=predictor_spec),
    )

    if replace:
        print("Replacing InferenceService with new version...")
        kclient.replace(deployment_name, isvc)
        print(f"InferenceService replaced with new version '{pach_id}'.")
    else:
        print(f"Creating KServe InferenceService for model '{model_name}'.")
        kclient.create(isvc)
        print(f"Inference Service '{deployment_name}' created.")


# =====================================================================================


def check_existence(kclient, deployment_name, k8s_namespace):
    print(
        f"Checking if previous version of InferenceService '{deployment_name}' exists..."
    )

    try:
        kclient.get(deployment_name, namespace=k8s_namespace)
        exists = True
        print(
            f"Previous version of InferenceService '{deployment_name}' exists."
        )
    except RuntimeError:
        exists = False
        print(
            f"Previous version of InferenceService '{deployment_name}' does not exist."
        )

    return exists


# =====================================================================================


def clone_code(repo_url, ref, dir):
    if os.path.isdir(dir):
        print(f"Directory {dir} already exists. Fetching latest code...")
        repo = git.Repo(dir)
        ret = repo.remotes.origin.fetch()
        if ret[0].flags == 4:
            print("No new code to fetch.")
        else:
            print("New code fetched.")
    else:
        print(f"Cloning code from: {repo_url}@{ref} --> {dir}")
        repo = git.Repo.clone_from(repo_url, dir)
    repo.git.checkout(ref)


# =====================================================================================


class DeterminedInfo:
    def __init__(self):
        self.master = os.getenv("DET_MASTER")
        self.username = os.getenv("DET_USER")
        self.password = os.getenv("DET_PASSWORD")


# =====================================================================================


class KServeInfo:
    def __init__(self):
        self.namespace = os.getenv("KSERVE_NAMESPACE")


# =====================================================================================


class ModelInfo:
    def __init__(self, file):
        print(f"Reading model info file: {file}")
        info = {}
        with open(file, "r") as stream:
            try:
                info = yaml.safe_load(stream)

                self.name = info["name"]
                self.version = info["version"]
                self.pipeline = info["pipeline"]
                self.repository = info["repo"]

                print(
                    f"Loaded model info: name='{self.name}', version='{self.version}', pipeline='{self.pipeline}', repo='{self.repository}'"
                )
            except yaml.YAMLError as exc:
                print(exc)


# =====================================================================================
