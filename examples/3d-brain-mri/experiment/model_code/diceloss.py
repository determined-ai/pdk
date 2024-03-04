import torch
from torch import nn
# Code was adapted and modified from the following files:
# https://github.com/black0017/MedicalZooPytorch/blob/master/lib/losses3D/basic.py
# https://github.com/black0017/MedicalZooPytorch/blob/master/lib/losses3D/BaseClass.py
# https://github.com/black0017/MedicalZooPytorch/blob/master/lib/losses3D/generalized_dice.py


class GeneralizedDiceLoss(nn.Module):
    """Computes Generalized Dice Loss (GDL) as described in https://arxiv.org/pdf/1707.03237.pdf.
    """

    def __init__(self, classes=4, sigmoid_normalization=True, epsilon=1e-9):
        super().__init__()
        self.epsilon = epsilon
        self.classes = classes
        # The output from the network during training is assumed to be un-normalized probabilities and we would
        # like to normalize the logits. Since Dice (or soft Dice in this case) is usually used for binary data,
        # normalizing the channels with Sigmoid is the default choice even for multi-class segmentation problems.
        # However if one would like to apply Softmax in order to get the proper probability distribution from the
        # output, just specify sigmoid_normalization=False.
        if sigmoid_normalization:
            self.normalization = nn.Sigmoid()
        else:
            self.normalization = nn.Softmax(dim=1)

    def dice(self, input_arr, target):
        assert input_arr.size() == target.size()
        input_arr = self.flatten(input_arr)
        target = self.flatten(target)
        target = target.float()

        if input_arr.size(1) == 1:
            # for GDL to make sense we need at least 2 channels (see https://arxiv.org/pdf/1707.03237.pdf)
            # put foreground and background voxels in separate channels
            input_arr = torch.cat((1 - input_arr, input_arr), dim=1)
            target = torch.cat((1 - target, target), dim=1)

        # GDL weighting: the contribution of each label is corrected by the inverse of its volume
        w_l = target.sum(-1)
        w_l = 1 / (w_l * w_l).clamp(min=1e-9)
        w_l.requires_grad = False

        intersect = (input_arr * target).sum(-1)
        intersect = intersect * w_l

        denominator = (input_arr + target).sum(-1)
        denominator = (denominator * w_l).clamp(min=1e-9)

        per_channel_volume_dice = 2 * (intersect/denominator)
        per_channel_dice = 2 * (intersect.sum(0)/denominator.sum(0))
        per_volume_dice = 2 * (intersect.sum(-1)/denominator.sum(-1))
        total_dice = 2 * (intersect.sum()/denominator.sum())
        return per_channel_volume_dice, per_channel_dice, per_volume_dice, total_dice

    def forward(self, input_arr, target):
        """
        Expand to one hot added extra for consistency reasons
        """
        if self.classes > 1:
            target = self.expand_as_one_hot(target.long(), self.classes)

        assert input_arr.dim() == target.dim() == 5, "'input_arr' and 'target' have different number of dims"

        assert input_arr.size() == target.size(), "'input_arr' and 'target' must have the same shape"
        # get probabilities from logits
        input_arr = nn.Sigmoid()(input_arr)

        # compute per volume, per channel  and total Dice coefficients
        (per_channel_volume_dice, per_channel_dice, per_volume_dice, total_dice) = self.dice(input_arr, target)

        loss = (1. - total_dice)
        per_channel_volume_dice = per_channel_volume_dice.detach().cpu().numpy()
        per_channel_dice = per_channel_dice.detach().cpu().numpy()
        per_volume_dice = per_volume_dice.detach().cpu().numpy()
        total_dice = total_dice.detach().cpu().numpy()

        # average Dice score across all channels/self.classes
        return loss, (per_channel_volume_dice, per_channel_dice, per_volume_dice, total_dice)

    def expand_as_one_hot(self, input_arr, C, ignore_index=None):
        """
        Converts Nx1xDxHxW label image to NxCxDxHxW, where each label gets converted to its corresponding one-hot vector
        :param input_arr: 5D input_arr image (Nx1xDxHxW)
        :param C: number of channels/labels
        :return: 5D output image (NxCxDxHxW)
        """

        # create result tensor shape (NxCxDxHxW)
        shape = list(input_arr.size())
        shape[1] = C
        
        # scatter to get the one-hot tensor
        return torch.zeros(shape).to(input_arr.device).scatter_(1, input_arr, 1)


    def flatten(self, tensor):
        """Flattens a given tensor such that the channel axis is first.
        The shapes are transformed as follows:
        (N, C, D, H, W) -> (N, C, D * H * W)
        """
        # number of volumes
        N = tensor.size(0)
        # number of channels
        C = tensor.size(1)
        # Flatten: (N, C, D, H, W) -> (N, C, D * H * W)
        return tensor.contiguous().view(N, C, -1)