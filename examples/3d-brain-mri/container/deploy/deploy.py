import os
import time

import torch
from common import (DeterminedInfo, KServeInfo, ModelInfo, check_existence,
                    create_inference_service, get_version, parse_args,
                    upload_model, wait_for_deployment, clone_code)
from determined.common.experimental import ModelVersion
from determined.experimental import Determined
from determined.pytorch import load_trial_from_checkpoint_path
from google.cloud import storage
from kserve import KServeClient

# =====================================================================================


def create_scriptmodule(det_master, det_user, det_pw, model_name, pach_id):
    print(
        f"Loading model version '{model_name}/{pach_id}' from master at '{det_master}...'"
    )

    if os.environ["HOME"] == "/":
        os.environ["HOME"] = "/app"

    os.environ["SERVING_MODE"] = "true"

    start = time.time()
    det_client = Determined(master=det_master, user=det_user, password=det_pw)
    version = get_version(det_client, model_name, pach_id)
    checkpoint = version.checkpoint
    checkpoint_dir = checkpoint.download()
    trial = load_trial_from_checkpoint_path(
        checkpoint_dir, map_location=torch.device("cpu")
    )
    end = time.time()
    delta = end - start
    print(f"Checkpoint loaded in {delta} seconds.")

    print("Creating ScriptModule from Determined checkpoint...")

    # Create ScriptModule
    m = torch.jit.script(trial.model)

    # Save ScriptModule to file
    torch.jit.save(m, "scriptmodule.pt")
    print(f"ScriptModule created successfully.")


# =====================================================================================


def create_mar_file(model_name, model_version, handler_file):
    print(f"Creating .mar file for model '{model_name}'...")
    os.system(
        "torch-model-archiver --model-name %s --version %s --serialized-file ./scriptmodule.pt --handler %s --force"
        % (model_name, model_version, handler_file)
    )
    print(f"Created .mar file successfully.")


# =====================================================================================


def create_properties_file(model_name, model_version, args):
    config_properties = """inference_address=http://0.0.0.0:8085
management_address=http://0.0.0.0:8083
metrics_address=http://0.0.0.0:8082
grpc_inference_port=7070
grpc_management_port=7071
enable_envvars_config=true
install_py_dep_per_model=true
enable_metrics_api=true
metrics_format=prometheus
number_of_netty_threads=4
job_queue_size=10
model_store=/mnt/models/model-store
max_request_size=%s
max_response_size=%s
model_snapshot={"name":"startup.cfg","modelCount":1,"models":{"%s":{"%s":{"defaultVersion":true,"marName":"%s.mar","minWorkers":%s,"maxWorkers":%s,"batchSize":%s,"maxBatchDelay":%s,"responseTimeout":120}}}}""" % (
        args.max_request_size,
        args.max_response_size,
        model_name,
        model_version,
        model_name,
        args.min_workers,
        args.max_workers,
        args.batch_size,
        args.batch_delay
    )

    conf_prop = open("config.properties", "w")
    n = conf_prop.write(config_properties)
    conf_prop.close()

    model_files = ["config.properties", str(model_name) + ".mar"]

    return model_files


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

    # Pull Determined.AI Checkpoint, load it, and create ScriptModule (TorchScript)
    create_scriptmodule(
        det.master, det.username, det.password, model.name, model.version
    )

    # --- Download code repository

    local_repo = os.path.join(os.getcwd(), "code-repository")
    clone_code(args.git_url, args.git_ref, local_repo)

    # --- Points to the correct subfolder inside the cloned repo

    if args.sub_dir:
        workdir = os.path.join(local_repo, args.sub_dir)
    else:
        workdir = local_repo

    handler_file = os.path.join(workdir, args.handler)

    # Create .mar file from ScriptModule
    create_mar_file(model.name, model.version, handler_file)

    # Create config.properties for .mar file, return files to upload to GCS bucket
    model_files = create_properties_file(model.name, model.version, args)

    # Upload model artifacts to Cloud  bucket in the format for TorchServe
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
        resource_requirements["requests"] = dict([i.split("=") for i in args.resource_requests])
    if args.resource_limits:
        resource_requirements["limits"] = dict([i.split("=") for i in args.resource_limits])
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
        args.service_account_name
    )
    if args.wait and args.cloud_model_host:
        # Wait for InferenceService to be ready for predictions
        wait_for_deployment(kclient, ksrv.namespace, args.deployment_name, model.name)

    print(
        f"Ending pipeline: deploy-name='{args.deployment_name}', model='{model.name}', version='{model.version}'"
    )


# =====================================================================================


if __name__ == "__main__":
    main()
