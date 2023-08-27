from determined.common.experimental.experiment import ExperimentState
from determined.common.experimental import experiment
from determined.experimental import Determined

import os
import git
import argparse
import yaml

# =====================================================================================

class DeterminedClient(Determined):
    def __init__(self, master, user, password):
        super().__init__(master=master, user=user, password=password)

    def continue_experiment(self, config, parent_id, checkpoint_uuid):
        config["searcher"]["source_checkpoint_uuid"] = checkpoint_uuid

        resp = self._session.post(
            "/api/v1/experiments",
            json={
                "activate": True,
                "config": yaml.safe_dump(config),
                "parentId": parent_id,
            },
        )

        exp_id = resp.json()["experiment"]["id"]
        exp = experiment.ExperimentReference(exp_id, self._session)

        return exp

# =====================================================================================

def parse_args():
    parser = argparse.ArgumentParser(description="Determined AI Experiment Runner")

    parser.add_argument(
        "--config",
        type=str,
        help="Determined's experiment configuration file",
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
        help="Subfolder to experiment files",
    )

    parser.add_argument(
        "--repo",
        type=str,
        help="Name of the Pachyderm's repository containing the dataset",
    )

    parser.add_argument(
        "--model",
        type=str,
        help="Name of the model on DeterminedAI to create/update",
    )

    return parser.parse_args()

# =====================================================================================

def clone_code(repo_url, ref, dir):
    print(f"Cloning code from: {repo_url}@{ref} --> {dir}")
    if os.path.isdir(dir):
        repo = git.Repo(dir)
        repo.remotes.origin.fetch()
    else:
        repo = git.Repo.clone_from(repo_url, dir)
    repo.git.checkout(ref)

# =====================================================================================

def read_config(conf_file):
    print(f"Reading experiment config file: {conf_file}")
    config = {}
    with open(conf_file, "r") as stream:
        try:
            config = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            print(exc)
    return config

# =====================================================================================

def setup_config(config_file, repo, pipeline, job_id):
    config = read_config(config_file)
    config["data"]["pachyderm"]["host"]   = os.getenv("PACHD_LB_SERVICE_HOST")
    config["data"]["pachyderm"]["port"]   = os.getenv("PACHD_LB_SERVICE_PORT")
    config["data"]["pachyderm"]["repo"]   = repo
    config["data"]["pachyderm"]["branch"] = job_id
    config["data"]["pachyderm"]["token"]  = os.getenv("PAC_TOKEN")

    config["labels"] = [ repo, job_id, pipeline ]

    return config

# =====================================================================================

def create_client():
    return DeterminedClient(
        master  = os.getenv("DET_MASTER"),
        user    = os.getenv("DET_USER"),
        password= os.getenv("DET_PASSWORD"),
    )

# =====================================================================================

def execute_experiment(client, configfile, code_path, parent_id):
    try:
        if parent_id is None:
            exp = client.create_experiment(configfile, code_path)
        else:
            print(parent_id)
            print(client)
            print(configfile)
            print(code_path)
            exp = client.continue_experiment(configfile, parent_id, parent_id.uuid, trial_id=157)

        print(f"Created experiment with id='{exp.id}' (parent_id='{parent_id}'). Waiting for its completion...")

        #state = exp.wait()["experiment"]["state"]
        state = exp.wait()
        print(f"Experiment with id='{exp.id}' ended with the following state: {state}")

        if state == ExperimentState.COMPLETED:
            return exp
        else:
            return None
    except AssertionError:
        print("Experiment exited with abnormal state")
        return None



# =====================================================================================

def run_experiment(client, configfile, code_path):
    print("Creating a new experiment on DeterminedAI...")
    return execute_experiment(client, configfile, code_path, None)
    
# =====================================================================================

def get_checkpoint(exp):
    try:
        return exp.top_checkpoint()
    except AssertionError:
        return None

# =====================================================================================

def get_or_create_model(client, model_name, pipeline, repo):

    models = client.get_models(name=model_name)

    if len(models) > 0:
        print(f"Model already present. Updating it : {model_name}")
        model = client.get_models(name=model_name)[0]
    else:
        print(f"Creating a new model : {model_name}")
        model = client.create_model(name=model_name, labels=[ pipeline, repo], metadata={
            "pipeline": pipeline,
            "repository": repo
        })

    return model

# =====================================================================================

def register_checkpoint(checkpoint, model, job_id):
    print(f"Registering checkpoint on model : {model.name}")
    version = model.register_version(checkpoint.uuid)
    version.set_name(job_id)
    version.set_notes("Job_id/commit_id = " + job_id)

    checkpoint.download("/pfs/out/checkpoint")
    print("Checkpoint registered and downloaded to output repository")

# =====================================================================================

def write_model_info(file, model_name, model_version, pipeline, repo):
    print(f"Writing model information to file: {file}")

    model = dict()
    model["name"]     = model_name
    model["version"]  = model_version
    model["pipeline"] = pipeline
    model["repo"]     = repo

    with open(file, "w") as stream:
        try:
            yaml.safe_dump(model, stream)
        except yaml.YAMLError as exc:
            print(exc)

# =====================================================================================

def main():
    # --- Retrieve useful info from environment

    #config_file = os.path.join(os.getcwd(), "../../use-case/image-classification/experiment/")
    #print(config_file)

#    exp    = run_experiment(client, config_file, os.getcwd())

    # --- Get best checkpoint from experiment. It may not exist if the experiment did not succeed
    
    #exp = client.create_experiment(os.path.join(config_file,"const.yaml"), config_file)


    client = create_client()    
    
    
#    try:
#        exp = client.create_experiment("/Users/j9s/git/determined-examples/examples/computer_vision/iris_tf_keras/distributed.yaml", "/Users/j9s/git/determined-examples/examples/computer_vision/iris_tf_keras/")
#        state = exp.wait()
#        if state == ExperimentState.COMPLETED:
#            print(exp)
#            checkpoint = get_checkpoint(exp)
#            print(checkpoint)
            
#    except AssertionError:
#        return None

    exp = client.get_experiment(73)
    checkpoint = get_checkpoint(exp)
    print(exp)
    print(checkpoint)
    print(exp.id)

    model = client.get_model("brain-mri UNET")
    print(model)
    print(type(model))
    print(model.name)
    print(model.model_id)

    # --- Now, register checkpoint on model and download it

# =====================================================================================


if __name__ == "__main__":
    main()
