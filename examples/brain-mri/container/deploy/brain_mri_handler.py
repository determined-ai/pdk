import torch
import numpy as np
from torchvision import transforms
from ts.torch_handler.image_classifier import ImageClassifier
from torch.profiler import ProfilerActivity


class BrainHandler(ImageClassifier):
    """
    BrainHandler handler class. This handler extends class ImageClassifier from image_classifier.py, a
    default handler. This handler takes an image from the reqeust body (shape and values) and returns a mask as a tensor, stored in a list of dicts.

    Here method postprocess() and preprocess() have been overridden while others are reused from parent class.
    
    Author: Cyrill Hug / 01.17.2023
    Based on: https://github.dev/pytorch/serve/blob/master/examples/image_classifier/mnist/mnist_handler.py#L1 
    """

    #image_processing = transforms.Compose([
    #    transforms.ToTensor(),
    #])

    def __init__(self):
        super(BrainHandler, self).__init__()
        self.profiler_args = {
            "activities" : [ProfilerActivity.CPU],
            "record_shapes": True,
        }

        
        
    def preprocess(self, data):
        """Preprocess the data, fetches the image from the request body and converts to torch tensor.
        Args:
            data (list): Image to be sent to the model for inference.
        Returns:
            tensor: A torch tensor in correct format for brain mri unet model
        """
        
        tensor_data = data[0]["data"]
        tensor_shape = data[0]["shape"]
        output = torch.FloatTensor(np.array(tensor_data).reshape(tensor_shape))

        input_img = output.unsqueeze(0)
        
        return input_img
        

    def postprocess(self, data):
        """The post process of BrainHandler stores the predicted mask in a list.

        Args:
            data (tensor): The predicted output from the Inference is passed
            to the post-process function
        Returns:
            list : A list with a tensor for the mask is returned
        """
        return data.tolist()
