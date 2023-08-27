import sys
# sys.path.insert(0,'/run/determined/workdir')
import torch
import torchvision

import os
try:
    from torchvision.models.detection import FCOS, fcos_resnet50_fpn, FasterRCNN
except ImportError as e:
    print("This version of Torchvision does not have FCOS!")
    print("Torchvision Version: ",torchvision.__version__)
    from torchvision.models.detection import FasterRCNN
    pass  # module doesn't exist, deal with it.

from torchvision.models.detection.anchor_utils import AnchorGenerator
from .mobileone_fpn import mobileone

from torch import nn, Tensor
from typing import Callable, Dict, List, Optional, Union

from torchvision.ops.feature_pyramid_network import ExtraFPNBlock, FeaturePyramidNetwork, LastLevelMaxPool
import torchsummary
import math
from torchvision.models.detection.faster_rcnn import FastRCNNPredictor

from functools import partial
from torchvision.models.detection import _utils as det_utils
from torchvision.models.detection.ssdlite import SSDLiteClassificationHead
from torchvision.models.detection.ssd import SSDClassificationHead
from torchvision.models.detection.rpn import RegionProposalNetwork, RPNHead
from torchvision.models.detection.backbone_utils import BackboneWithFPN,LastLevelMaxPool
try:
    from torchvision.models.detection.faster_rcnn import FastRCNNConvFCHead
except ImportError as e:
    print("This version of Torchvision: {torchvision.__version__} does not have FastRCNNConvFCHead")
    pass

print("TORCHVISION_VERSION: ",torchvision.__version__, torchvision.__file__)
print("TORCH_VERSION: ",torch.__version__, torch.__file__)

def _resnet_fpn_extractor(
    backbone,
    trainable_layers,
    returned_layers = None,
    extra_blocks = None,
    norm_layer = None,
):

    # select layers that wont be frozen
    if trainable_layers < 0 or trainable_layers > 5:
        raise ValueError(f"Trainable layers should be in the range [0,5], got {trainable_layers}")
    layers_to_train = ["layer4", "layer3", "layer2", "layer1", "conv1"][:trainable_layers]
    if trainable_layers == 5:
        layers_to_train.append("bn1")
    for name, parameter in backbone.named_parameters():
        if all([not name.startswith(layer) for layer in layers_to_train]):
            parameter.requires_grad_(False)

    if extra_blocks is None:
        extra_blocks = LastLevelMaxPool()

    if returned_layers is None:
        returned_layers = [1, 2, 3, 4]
    if min(returned_layers) <= 0 or max(returned_layers) >= 5:
        raise ValueError(f"Each returned layer should be in the range [1,4]. Got {returned_layers}")
    return_layers = {f"layer{k}": str(v) for v, k in enumerate(returned_layers)}

    in_channels_stage2 = backbone.inplanes // 8
    in_channels_list = [in_channels_stage2 * 2 ** (i - 1) for i in returned_layers]
    out_channels = 256
    return BackboneWithFPN(
        backbone, return_layers, in_channels_list, out_channels, extra_blocks=extra_blocks, norm_layer=norm_layer
    )
def _default_anchorgen():
    anchor_sizes = ((32,), (64,), (128,), (256,), (512,))
    aspect_ratios = ((0.5, 1.0, 2.0),) * len(anchor_sizes)
    return AnchorGenerator(anchor_sizes, aspect_ratios)

class Backbone_FPN(nn.Module):
    def __init__(self,backbone: nn.Module,fpn: FeaturePyramidNetwork):
        super().__init__()
        self.backbone = backbone
        self.fpn = fpn

    def forward(self, x: Tensor)-> Dict[str, Tensor]:
        y = self.backbone(x)
        x = self.fpn(y)
        return x


def get_mobileone_s4_fpn_fcos(num_classes, ckpt_path=None):
    backbone = mobileone(variant='s4', inference_mode=True)
    # ckpt = 'mobileone_s4.pth.tar'
    if ckpt_path is not None:
        checkpoint = torch.load(ckpt_path)
        backbone.load_state_dict(checkpoint,strict=False)
        print("mobileone_s4.pth.tar loaded!")

    # fpn = FeaturePyramidNetwork([ 64,192, 448],256)
    # fpn = FeaturePyramidNetwork([ 64,192, 448,896],256)
    fpn = FeaturePyramidNetwork([ 64,192, 448,896,2048],256)


    b_fpn = Backbone_FPN(backbone,fpn)
    b_fpn.out_channels = 256
    # anchor_sizes = ( (16,), (32,), (64,))

    # anchor_sizes = ( (16,), (32,), (64,), (128,))
    anchor_sizes = ( (16,), (32,), (64,), (128,),(256,))

    anchor_generator = AnchorGenerator(
    sizes=anchor_sizes,
    aspect_ratios=((1.0,),)* len(anchor_sizes) 
    )   
    model = FCOS(
    b_fpn,
    num_classes=num_classes,
    anchor_generator=anchor_generator,
    )
    return model

def make_custom_object_detection_model_fcos(num_classes):
    model = fcos_resnet50_fpn(pretrained=True)  # load an object detection model pre-trained on COCO
    model.score_thresh = 0.05
    model.nms_thresh = 0.4
    model.detections_per_img = 300
    model.topk_candidates = 300
    num_anchors = model.head.classification_head.num_anchors
    model.head.classification_head.num_classes = num_classes
    print("FOCS num_classes: ",model.head.classification_head.num_classes)

    out_channels = model.head.classification_head.conv[9].out_channels
    cls_logits = torch.nn.Conv2d(out_channels, num_anchors * num_classes, kernel_size=3, stride=1, padding=1)
    torch.nn.init.normal_(cls_logits.weight, std=0.01)
    torch.nn.init.constant_(cls_logits.bias, -math.log((1 - 0.01) / 0.01))

    model.head.classification_head.cls_logits = cls_logits
    return model
def load_model_ddp(loaded_model,model_state_dict):
    '''
    '''
    try:
        loaded_model.load_state_dict(model_state_dict)
    except Exception:
        # If the checkpointed model is non-DDP and the current model is DDP, append
        # module prefix to the checkpointed data
        if isinstance(loaded_model, torch.nn.parallel.DistributedDataParallel):
            print("Loading non-DDP checkpoint into a DDP model.")
            self._add_prefix_in_state_dict_if_not_present(model_state_dict, "module.")
        else:
            # If the checkpointed model is DDP and if we are currently running in
            # single-slot mode, remove the module prefix from checkpointed data
            print("Loading DDP checkpoint into a non-DDP model.")
            torch.nn.modules.utils.consume_prefix_in_state_dict_if_present(
                model_state_dict, "module."
            )
        loaded_model.load_state_dict(model_state_dict)
    return loaded_model
def build_frcnn_model(num_classes):
    print("Loading pretrained model...")
    # load an detection model pre-trained on COCO
    model = torchvision.models.detection.fasterrcnn_resnet50_fpn(pretrained=True)
    
    # get the number of input features for the classifier
    in_features = model.roi_heads.box_predictor.cls_score.in_features
    # replace the pre-trained head with a new one
    model.roi_heads.box_predictor = FastRCNNPredictor(in_features, num_classes)
    model.min_size=800
    model.max_size=1333
    # RPN parameters
    model.rpn_pre_nms_top_n_train=2000
    model.rpn_pre_nms_top_n_test=1000
    model.rpn_post_nms_top_n_train=2000
    model.rpn_post_nms_top_n_test=1000
    model.rpn_nms_thresh=0.7
    model.rpn_fg_iou_thresh=0.7
    model.rpn_bg_iou_thresh=0.3
    model.rpn_batch_size_per_image=256
    model.rpn_positive_fraction=0.5
    model.rpn_score_thresh=0.05
    # Box parameters
    model.box_score_thresh=0.0
    model.box_nms_thresh=0.5
    model.box_detections_per_img=300
    model.box_fg_iou_thresh=0.5
    model.box_bg_iou_thresh=0.5
    model.box_batch_size_per_image=512
    model.box_positive_fraction=0.25
    return model
def build_frcnn_model_finetune(num_classes,ckpt=None):
    print("Loading pretrained model from {}...".format(ckpt))
    # load an detection model pre-trained on COCO
    model = torchvision.models.detection.fasterrcnn_resnet50_fpn(pretrained=True)
    try:
        in_features = model.roi_heads.box_predictor.cls_score.in_features
        # replace the pre-trained head with a new one
        model.roi_heads.box_predictor = FastRCNNPredictor(in_features, 61)
        path = os.path.join(ckpt)
        model=load_model_ddp(model,torch.load(path,map_location=torch.device('cpu')))
    except Exception as e:
        print(e)
        pass
    # get the number of input features for the classifier
    in_features = model.roi_heads.box_predictor.cls_score.in_features
    # replace the pre-trained head with a new one
    model.roi_heads.box_predictor = FastRCNNPredictor(in_features, num_classes)
    model.min_size=800
    model.max_size=1333
    # RPN parameters
    model.rpn_pre_nms_top_n_train=2000
    model.rpn_pre_nms_top_n_test=1000
    model.rpn_post_nms_top_n_train=2000
    model.rpn_post_nms_top_n_test=1000
    model.rpn_nms_thresh=0.7
    model.rpn_fg_iou_thresh=0.7
    model.rpn_bg_iou_thresh=0.3
    model.rpn_batch_size_per_image=256
    model.rpn_positive_fraction=0.5
    model.rpn_score_thresh=0.05
    # Box parameters
    model.box_score_thresh=0.0
    model.box_nms_thresh=0.5
    model.box_detections_per_img=300
    model.box_fg_iou_thresh=0.5
    model.box_bg_iou_thresh=0.5
    model.box_batch_size_per_image=512
    model.box_positive_fraction=0.25
    return model
def finetune_ssd300_vgg16(num_classes):
    # model = torchvision.models.detection.ssdlite320_mobilenet_v3_large(pretrained=True)
    model = torchvision.models.detection.ssd300_vgg16(pretrained=True)

    in_channels = det_utils.retrieve_out_channels(model.backbone, (320, 320))
    num_anchors = model.anchor_generator.num_anchors_per_location()
    # norm_layer  = partial(nn.BatchNorm2d, eps=0.001, momentum=0.03)
    # num_classes = 2
    model.head.classification_head = SSDClassificationHead(in_channels, num_anchors, num_classes)
    return model
def finetune_ssdlite320_mobilenet_v3_large(num_classes):
    model = torchvision.models.detection.ssdlite320_mobilenet_v3_large(pretrained=True)
    in_channels = det_utils.retrieve_out_channels(model.backbone, (320, 320))
    num_anchors = model.anchor_generator.num_anchors_per_location()
    norm_layer  = partial(nn.BatchNorm2d, eps=0.001, momentum=0.03)
    model.head.classification_head = SSDLiteClassificationHead(in_channels, num_anchors, num_classes,norm_layer)
    return model

def create_convnext_small_fasterrcnn_model(num_classes=81, pretrained=True, coco_model=False):
    # Load the pretrained features.
    if pretrained:
        backbone = torchvision.models.convnext_small(weights='DEFAULT').features
    else:
        backbone = torchvision.models.convnext_small().features

    # We need the output channels of the last convolutional layers from
    # the features for the Faster RCNN model.
    backbone.out_channels = 768

    # Generate anchors using the RPN. Here, we are using 5x3 anchors.
    # Meaning, anchors with 5 different sizes and 3 different aspect 
    # ratios.
    anchor_generator = AnchorGenerator(
        sizes=((32, 64, 128, 256, 512),),
        aspect_ratios=((0.5, 1.0, 2.0),)
    )

    # Feature maps to perform RoI cropping.
    # If backbone returns a Tensor, `featmap_names` is expected to
    # be [0]. We can choose which feature maps to use.
    roi_pooler = torchvision.ops.MultiScaleRoIAlign(
        featmap_names=['0'],
        output_size=7,
        sampling_ratio=2
    )

    # Final Faster RCNN model.
    model = FasterRCNN(
        backbone=backbone,
        num_classes=num_classes,
        rpn_anchor_generator=anchor_generator,
        box_roi_pool=roi_pooler
    )

    return model
def create_convnext_large_fasterrcnn_model(num_classes=81, pretrained=True, coco_model=False):
    # Load the pretrained features.
    if pretrained:
        backbone = torchvision.models.convnext_large(weights='DEFAULT').features
    else:
        backbone = torchvision.models.convnext_large().features

    # We need the output channels of the last convolutional layers from
    # the features for the Faster RCNN model.
    backbone.out_channels = 1536

    # Generate anchors using the RPN. Here, we are using 5x3 anchors.
    # Meaning, anchors with 5 different sizes and 3 different aspect 
    # ratios.
    anchor_generator = AnchorGenerator(
        sizes=((32, 64, 128, 256, 512),),
        aspect_ratios=((0.5, 1.0, 2.0),)
    )

    # Feature maps to perform RoI cropping.
    # If backbone returns a Tensor, `featmap_names` is expected to
    # be [0]. We can choose which feature maps to use.
    roi_pooler = torchvision.ops.MultiScaleRoIAlign(
        featmap_names=['0'],
        output_size=7,
        sampling_ratio=2
    )

    # Final Faster RCNN model.
    model = FasterRCNN(
        backbone=backbone,
        num_classes=num_classes,
        rpn_anchor_generator=anchor_generator,
        box_roi_pool=roi_pooler
    )

    return model
def create_efficientnet_b4_fasterrcnn_model(num_classes, pretrained=True, coco_model=False):
    # Load the pretrained EfficientNetB0 large features.
    backbone = torchvision.models.efficientnet_b4(pretrained=pretrained).features

    # We need the output channels of the last convolutional layers from
    # the features for the Faster RCNN model.
    backbone.out_channels = 1792

    # Generate anchors using the RPN. Here, we are using 5x3 anchors.
    # Meaning, anchors with 5 different sizes and 3 different aspect 
    # ratios.
    anchor_generator = AnchorGenerator(
        sizes=((32, 64, 128, 256, 512),),
        aspect_ratios=((0.5, 1.0, 2.0),)
    )

    # Feature maps to perform RoI cropping.
    # If backbone returns a Tensor, `featmap_names` is expected to
    # be [0]. We can choose which feature maps to use.
    roi_pooler = torchvision.ops.MultiScaleRoIAlign(
        featmap_names=['0'],
        output_size=7,
        sampling_ratio=2
    )

    # Final Faster RCNN model.
    model = FasterRCNN(
        backbone=backbone,
        num_classes=num_classes,
        rpn_anchor_generator=anchor_generator,
        box_roi_pool=roi_pooler
    )

    return model
def create_resnet152_fasterrcnn_model(num_classes=81, pretrained=True, coco_model=False):
    model_backbone = torchvision.models.resnet152(weights='DEFAULT')

    conv1 = model_backbone.conv1
    bn1 = model_backbone.bn1
    relu = model_backbone.relu
    max_pool = model_backbone.maxpool
    layer1 = model_backbone.layer1
    layer2 = model_backbone.layer2
    layer3 = model_backbone.layer3
    layer4 = model_backbone.layer4

    backbone = nn.Sequential(
        conv1, bn1, relu, max_pool, 
        layer1, layer2, layer3, layer4
    )
    # We need the output channels of the last convolutional layers from
    # the features for the Faster RCNN model.
    # It is 960 for MobileNetV3.
    backbone.out_channels = 2048

    # Generate anchors using the RPN. Here, we are using 5x3 anchors.
    # Meaning, anchors with 5 different sizes and 3 different aspect 
    # ratios.
    anchor_generator = AnchorGenerator(
        sizes=((32, 64, 128, 256, 512),),
        aspect_ratios=((0.5, 1.0, 2.0),)
    )

    # Feature maps to perform RoI cropping.
    # If backbone returns a Tensor, `featmap_names` is expected to
    # be [0]. We can choose which feature maps to use.
    roi_pooler = torchvision.ops.MultiScaleRoIAlign(
        featmap_names=['0'],
        output_size=7,
        sampling_ratio=2
    )

    # Final Faster RCNN model.
    model = FasterRCNN(
        backbone=backbone,
        num_classes=num_classes,
        rpn_anchor_generator=anchor_generator,
        box_roi_pool=roi_pooler
    )

    return model
def resnet152_fpn_fasterrcnn(num_classes):
    '''
    '''
    backbone = torchvision.models.resnet152(pretrained=True)
    backbone.out_channels = 256
    # print(b.conv1)
    # layers_to_train = ["layer4", "layer3", "layer2", "layer1", "conv1"]
    layers_to_train = 3
    rpn = _resnet_fpn_extractor(backbone,0,norm_layer=nn.BatchNorm2d)
    # print([i for i in rpn])
    rpn_anchor_generator = _default_anchorgen()
    rpn_head = RPNHead(backbone.out_channels, rpn_anchor_generator.num_anchors_per_location()[0], conv_depth=2)
    box_head = FastRCNNConvFCHead(
        (backbone.out_channels, 7, 7), [256, 256, 256, 256], [1024], norm_layer=nn.BatchNorm2d
    )
    model = FasterRCNN(
        rpn,
        num_classes=num_classes,
        rpn_anchor_generator=rpn_anchor_generator,
        rpn_head=rpn_head,
        box_head=box_head)
    return model

if __name__ == '__main__':
    model = get_mobileone_s4_fpn_fcos(91,ckpt_path='/tmp/mobileone_s4.pth.tar')
    # model = build_frcnn_model(61)
    # model.eval()
    torchsummary.summary(model,input_size=(3,256,256),device='cpu')