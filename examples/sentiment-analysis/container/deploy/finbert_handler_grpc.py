import logging
import os

import numpy as np
import torch
import transformers
from torch.profiler import ProfilerActivity
from ts.torch_handler.text_classifier import TextClassifier

logger = logging.getLogger(__name__)


class FinbertHandler(TextClassifier):
    """
    FinbertHandler handler class. This handler extends class TextClassifier from text_classifier.py, a
    default TorchServe handler. This handler takes a string from the reqeust body (JSON) and returns a class.

    Based on : https://medium.com/analytics-vidhya/deploy-huggingface-s-bert-to-production-with-pytorch-serve-27b068026d18

    Author: Cyrill Hug / 01.27.2023
    """

    def __init__(self):
        super(FinbertHandler, self).__init__()
        self.initialized = False

    def initialize(self, ctx):
        self.manifest = ctx.manifest

        properties = ctx.system_properties
        model_dir = properties.get("model_dir")
        serialized_file = self.manifest["model"]["serializedFile"]

        model_pt_path = os.path.join(model_dir, serialized_file)

        logger.debug("Path for model state_dict is {0}".format(model_pt_path))

        self.device = torch.device(
            "cuda:" + str(properties.get("gpu_id"))
            if torch.cuda.is_available()
            else "cpu"
        )

        logger.debug("Device is set to {0}".format(self.device))

        tokenizer_class = transformers.BertTokenizer
        model_class = transformers.BertForSequenceClassification
        model_name = "bert-base-uncased"

        self.tokenizer = tokenizer_class.from_pretrained(
            model_name, do_lower_case=True, cache_dir=None
        )

        logger.debug("Tokenizer has been defined successfully")

        num_labels = len(["positive", "negative", "neutral"])

        self.model = model_class.from_pretrained(
            model_name,
            num_labels=num_labels,
            cache_dir="/tmp/serve-cache-dir",
        )

        logger.debug("Model has been defined successfully")

        self.model.load_state_dict(torch.load(model_pt_path))

        self.model.to(self.device)
        self.model.eval()

        logger.debug(
            "Transformer model from path {0} loaded successfully".format(
                model_dir
            )
        )

        # Read the mapping file, index to object name
        mapping_file_path = os.path.join(model_dir, "index_to_name.json")

        if os.path.isfile(mapping_file_path):
            with open(mapping_file_path) as f:
                self.mapping = json.load(f)
        else:
            logger.warning(
                "Missing the index_to_name.json file. Inference output will not include class name."
            )

        self.initialized = True

    def preprocess(self, data):
        """Very basic preprocessing code - only tokenizes.
        Extend with your own preprocessing steps as needed.
        """

        logger.debug("Received data: '%s'", data)

        text = data[0].get("data")
        if text is None:
            text = data[0].get("body")

        logger.info("Received text: '%s'", text)

        inputs = self.tokenizer.encode_plus(
            text, add_special_tokens=True, return_tensors="pt"
        )

        logger.info("Input for model: '%s'", inputs)

        return inputs

    def postprocess(self, inference_output):
        return inference_output

    def inference(self, inputs):
        """
        Predict the class of a text using a trained transformer model.
        """
        # NOTE: This makes the assumption that your model expects text to be tokenized
        # with "input_ids" and "token_type_ids" - which is true for some popular transformer models, e.g. bert.
        # If your transformer model expects different tokenization, adapt this code to suit
        # its expected input format.
        prediction = (
            self.model(
                inputs["input_ids"].to(self.device),
                token_type_ids=inputs["token_type_ids"].to(self.device),
            )[0]
            .argmax()
            .item()
        )
        logger.info("Model predicted: '%s'", prediction)

        if self.mapping:
            prediction = self.mapping[str(prediction)]

        return [prediction]


_service = FinbertHandler()


def handle(data, context):
    try:
        if not _service.initialized:
            _service.initialize(context)

        if data is None:
            return None

        data = _service.preprocess(data)
        data = _service.inference(data)
        data = _service.postprocess(data)

        return data
    except Exception as e:
        raise e
