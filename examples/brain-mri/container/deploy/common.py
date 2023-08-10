import argparse
import os
import shutil
import time
from functools import partial

import yaml
from determined.common.experimental import ModelVersion
from google.cloud import storage
from kserve import (
    V1beta1InferenceService,
    V1beta1InferenceServiceSpec,
    V1beta1PredictorSpec,
    V1beta1TorchServeSpec,
    constants,
)
from kubernetes import client
from kubernetes.client import V1ResourceRequirements, V1Toleration

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
        "--k8s-config-file",
        type=str,
        help="The path to the k8s config file",
        default=None,
    )
    parser.add_argument(
        "--tolerations",
        type=csv_,
        help="a comma separated list of tolerations to apply to the deployment in the format of key=value",
        default=None,
    )
    parser.add_argument(
        "--resource-requests",
        type=csv_,
        help="",
        default=None,
    )
    parser.add_argument(
        "--resource-limits",
        type=csv_,
        help="",
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
            pytorch=(
                V1beta1TorchServeSpec(
                    protocol_version="v2",
                    storage_uri=f"gs://{bucket_name}/{model_name}",
                    resources=(
                        V1ResourceRequirements(
                            requests=resource_requirements["requests"],
                            limits=resource_requirements["limits"],
                        )
                    ),
                )
            ),
        )
    elif cloud_provider == "aws":
        predictor_spec = V1beta1PredictorSpec(
            tolerations=tol,
            pytorch=(
                V1beta1TorchServeSpec(
                    protocol_version="v2",
                    storage_uri=f"s3://{bucket_name}/{model_name}",
                    resources=(
                        V1ResourceRequirements(
                            requests=resource_requirements["requests"],
                            limits=resource_requirements["limits"],
                        )
                    ),
                )
            ),
        )
    else:
        predictor_spec = V1beta1PredictorSpec(
            tolerations=tol,
            pytorch=(
                V1beta1TorchServeSpec(
                    protocol_version="v2",
                    storage_uri=f"s3://{commit}.master.{repo}.{project}/{model_name}",
                    resources=(
                        V1ResourceRequirements(
                            requests=resource_requirements["requests"],
                            limits=resource_requirements["limits"],
                        )
                    ),
                )
            ),
            service_account_name=sa,
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
