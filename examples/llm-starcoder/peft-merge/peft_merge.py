from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
import torch
import os
import sys
import argparse
from determined.experimental import Determined


def create_client():
    return Determined(
        master=os.getenv("DET_MASTER"),
        user=os.getenv("DET_USER"),
        password=os.getenv("DET_PASSWORD"),
    )

def find_file(start_dir='.',file='config.json'):
    for root, dirs, files in os.walk(start_dir):
        if file in files:
            return os.path.abspath(root)
    return None

def merge_peft_adapters(peft_chk_path, output_model_merged_path, model):

    base_model = AutoModelForCausalLM.from_pretrained(
        model,
        token=os.environ["HF_HOME"],
        return_dict=True,
        device_map="auto",
        torch_dtype=torch.float16
    )
    tokenizer = AutoTokenizer.from_pretrained(model)

    model = PeftModel.from_pretrained(base_model, peft_chk_path, device_map="auto")
    model = model.merge_and_unload()

    model.save_pretrained(f"{output_model_merged_path}")
    tokenizer.save_pretrained(f"{output_model_merged_path}")
    print(f"Model saved to {output_model_merged_path}")    

    return output_model_merged_path


def download_checkpoint(det, experiment_id):
    checkpoint = det.get_experiment(experiment_id).list_checkpoints(max_results=1)[0]
    path = checkpoint.download()
    for root, _, files in os.walk(path):
        print(f"Checking root:{root} _ {_} files:{files}")
        if 'config.json' in files:
            return root
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--experiment-num",
        type=int,
        help="Experiment ID",
        required=False,
    )
    parser.add_argument(
        "--input_path_peft",
        type=str,
        help="Local location of peft checkpoint",
        required=False,
    )    
    parser.add_argument(
        "--model",
        type=str,
        help="Model name or location",
        required=True,
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        help="Experiment ID",
        required=True,
    )
    args = parser.parse_args()
    client = create_client()
    if args.input_path_peft is not None:
        chk_path = find_file(args.input_path_peft, 'adapter_config.json')
    else:
        chk_path = download_checkpoint(client, args.experiment_num)
    if chk_path is None:
        print("Could not find a config.json")
        sys.exit(1)
    merge_peft_adapters(chk_path, args.output_dir, args.model)



if __name__ == "__main__":
    if "HF_HOME" not in os.environ or not os.environ:
        print(
            "Please set your Hugging Face API key in the HF_HOME environment variable."
        )
        sys.exit(1)
    main()
