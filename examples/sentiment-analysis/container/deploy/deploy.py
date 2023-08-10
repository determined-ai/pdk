import argparse
import os
import random
import time

import numpy as np
import torch
import torch.optim as optim
import yaml
from determined.common.experimental import ModelVersion
from determined.experimental import Determined
from determined.pytorch import load_trial_from_checkpoint_path
from google.cloud import storage
from kserve import (
    KServeClient,
    V1beta1InferenceService,
    V1beta1InferenceServiceSpec,
    V1beta1PredictorSpec,
    V1beta1TorchServeSpec,
    constants,
    utils,
)
from kubernetes import client
from torch import nn
from torch.utils.data import DataLoader, Dataset

from common import (
    upload_model,
    get_version,
    DeterminedInfo,
    KServeInfo,
    ModelInfo,
    check_existence,
    create_inference_service,
    wait_for_deployment,
    parse_args,
)


# =====================================================================================


def create_state_dict(det_master, det_user, det_pw, model_name, pach_id):
    print(
        f"Loading model version '{model_name}/{pach_id}' from master at '{det_master}...'"
    )

    if os.environ["HOME"] == "/":
        os.environ["HOME"] = "/app"

    os.environ["SERVING_MODE"] = "true"

    start = time.time()
    client = Determined(master=det_master, user=det_user, password=det_pw)
    version = get_version(client, model_name, pach_id)
    checkpoint = version.checkpoint
    checkpoint_dir = checkpoint.download()
    trial = load_trial_from_checkpoint_path(
        checkpoint_dir, map_location=torch.device("cpu")
    )
    end = time.time()
    delta = end - start
    print(f"Checkpoint loaded in {delta} seconds.")

    print(f"Creating state_dict from Determined checkpoint...")

    # Define Model
    model = trial.model

    # Save model state_dict
    torch.save(model.state_dict(), "./state_dict.pth")

    print(f"state_dict created successfully.")


# =====================================================================================


def create_mar_file(model_name, model_version):
    print(f"Creating .mar file for model '{model_name}'...")
    os.system(
        "torch-model-archiver --model-name %s --version %s --serialized-file ./state_dict.pth --handler ./finbert_handler_grpc.py --force"
        % (model_name, model_version)
    )
    print(f"Created .mar file successfully.")


# =====================================================================================


def create_properties_file(model_name, model_version):
    config_properties = """inference_address=http://0.0.0.0:8085
management_address=http://0.0.0.0:8081
metrics_address=http://0.0.0.0:8082
grpc_inference_port=7070
grpc_management_port=7071
enable_envvars_config=true
install_py_dep_per_model=true
enable_metrics_api=true
metrics_format=prometheus
NUM_WORKERS=1
number_of_netty_threads=4
job_queue_size=10
model_store=/mnt/models/model-store
model_snapshot={"name":"startup.cfg","modelCount":1,"models":{"%s":{"%s":{"defaultVersion":true,"marName":"%s.mar","minWorkers":1,"maxWorkers":5,"batchSize":1,"maxBatchDelay":5000,"responseTimeout":120}}}}""" % (
        model_name,
        model_version,
        model_name,
    )

    conf_prop = open("config.properties", "w")
    n = conf_prop.write(config_properties)
    conf_prop.close()

    model_files = ["config.properties", str(model_name) + ".mar"]

    return model_files


# =====================================================================================


def main():
    args = parse_args()
    det = DeterminedInfo()
    ksrv = KServeInfo()
    model = ModelInfo("/pfs/data/model-info.yaml")

    if args.google_application_credentials:
        os.environ[
            "GOOGLE_APPLICATION_CREDENTIALS"
        ] = args.google_application_credentials

    print(
        f"Starting pipeline: deploy-name='{args.deployment_name}', model='{model.name}', version='{model.version}'"
    )

    # Pull Determined.AI Checkpoint, load it, and create State_Dict from det checkpoint
    create_state_dict(
        det.master, det.username, det.password, model.name, model.version
    )

    # Create .mar file from State_Dict and handler
    create_mar_file(model.name, model.version)

    # Create config.properties for .mar file, return files to upload to GCS bucket
    model_files = create_properties_file(model.name, model.version)

    # Upload model artifacts to GCS bucket in the format for TorchServe
    upload_model(
        model.name, model_files, args.cloud_model_host, args.cloud_model_bucket
    )

    # Instantiate KServe Client using kubeconfig
    if args.k8s_config_file:
        print(f"Using Configured K8s Config File at {args.k8s_config_file}")
        kclient = KServeClient(config_file=args.k8s_config_file)
    else:
        kclient = KServeClient()

    # Check if a previous version of the InferenceService exists (return true/false)
    replace = check_existence(kclient, args.deployment_name, ksrv.namespace)

    resource_requirements = {"requests": {}, "limits": {}}
    if args.resource_requests:
        resource_requirements["requests"] = dict(
            [i.split("=") for i in args.resource_requests]
        )
    if args.resource_limits:
        resource_requirements["limits"] = dict(
            [i.split("=") for i in args.resource_limits]
        )
    # Create or replace inference service
    create_inference_service(
        kclient,
        ksrv.namespace,
        model.name,
        args.deployment_name,
        model.version,
        replace,
        args.cloud_model_host,
        args.cloud_model_bucket,
        args.tolerations,
        resource_requirements,
        args.service_account_name,
    )
    if args.wait and args.cloud_model_host:
        # Wait for InferenceService to be ready for predictions
        wait_for_deployment(
            kclient, ksrv.namespace, args.deployment_name, model.name
        )

    print(
        f"Ending pipeline: deploy-name='{args.deployment_name}', model='{model.name}', version='{model.version}'"
    )


# =====================================================================================


if __name__ == "__main__":
    main()
