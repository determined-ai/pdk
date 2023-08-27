import torchvision
from utils.coco_eval import CocoEvaluator
import torch
from tqdm import tqdm
import time
import datetime

def convert_to_coco_api(ds):
    coco_ds = COCO()
    # annotation IDs need to start at 1, not 0, see torchvision issue #1530
    ann_id = 1
    dataset = {"images": [], "categories": [], "annotations": []}
    categories = set()
    for img_idx in range(len(ds)):
        # find better way to get target
        # targets = ds.get_annotations(img_idx)
        img, targets = ds[img_idx]
        image_id = targets["image_id"].item()
        img_dict = {}
        img_dict["id"] = image_id
        img_dict["height"] = img.shape[-2]
        img_dict["width"] = img.shape[-1]
        dataset["images"].append(img_dict)
        bboxes = targets["boxes"].clone()
        bboxes[:, 2:] -= bboxes[:, :2]
        bboxes = bboxes.tolist()
        labels = targets["labels"].tolist()
        areas = targets["area"].tolist()
        iscrowd = targets["iscrowd"].tolist()
        if "masks" in targets:
            masks = targets["masks"]
            # make masks Fortran contiguous for coco_mask
            masks = masks.permute(0, 2, 1).contiguous().permute(0, 2, 1)
        if "keypoints" in targets:
            keypoints = targets["keypoints"]
            keypoints = keypoints.reshape(keypoints.shape[0], -1).tolist()
        num_objs = len(bboxes)
        for i in range(num_objs):
            ann = {}
            ann["image_id"] = image_id
            ann["bbox"] = bboxes[i]
            ann["category_id"] = labels[i]
            categories.add(labels[i])
            ann["area"] = areas[i]
            ann["iscrowd"] = iscrowd[i]
            ann["id"] = ann_id
            if "masks" in targets:
                ann["segmentation"] = coco_mask.encode(masks[i].numpy())
            if "keypoints" in targets:
                ann["keypoints"] = keypoints[i]
                ann["num_keypoints"] = sum(k != 0 for k in keypoints[i][2::3])
            dataset["annotations"].append(ann)
            ann_id += 1
    dataset["categories"] = [{"id": i} for i in sorted(categories)]
    coco_ds.dataset = dataset
    coco_ds.createIndex()
    return coco_ds

def get_coco_api_from_dataset(dataset):
    for _ in range(10):
        if isinstance(dataset, torchvision.datasets.CocoDetection):
            break
        if isinstance(dataset, torch.utils.data.Subset):
            dataset = dataset.dataset
    if isinstance(dataset, torchvision.datasets.CocoDetection):
        return dataset.coco
    return convert_to_coco_api(dataset)
def train_and_eval(model,data_loader,data_loader_test,optimizer,scheduler,device,cpu_device,epochs = 1):
    '''
    '''
    losses = []
    it=0
    print("Epochs: {}".format(epochs))
    for e in range(epochs):
        print("Epoch #: {}".format(e))
        pbar = tqdm(enumerate(data_loader),total=len(data_loader))
        # Train Batch
        model.train()
        for ind, (images, targets) in pbar:
            batch_time_start = time.time()
            images = list(image.to(device,non_blocking=True) for image in images)
            targets = [{k: v.to(device,non_blocking=True) for k, v in t.items()} for t in targets]
            loss_dict = model(images, targets)
            losses_reduced = sum(loss for loss in loss_dict.values())
            
            # if ind %10 == 0:
            # print("loss: ",loss_value)
            # print("losses_reduced: ",losses_reduced)
            optimizer.zero_grad()
            losses_reduced.backward()
            optimizer.step()
            with torch.no_grad():
                # print(losses_reduced)
                loss_value = losses_reduced.item()
            total_batch_time = time.time() - batch_time_start
            total_batch_time_str = str(datetime.timedelta(seconds=int(total_batch_time)))
            # print(f"Training time {total_batch_time_str}")
            if it%10==0:
                losses.append(loss_value)
            it += 1
            loss_str = []
            loss_str.append("{}: {}".format("loss","{:.3f}".format(loss_value)))
            for name, val in loss_dict.items():
                loss_str.append(
                    "{}: {}".format(name, "{:.3f}".format(val) )
                )
                pbar.set_postfix({'loss': loss_str})
            # print(it, scheduler.get_last_lr())
            scheduler.step()
            # if ind>100:
            # break
            # break
            # break
        # lr_scheduler.step()

            # Eval
        if e%5==0:
            eval_model(model,data_loader_test,device,cpu_device)
    return losses,model
def eval_model(model,data_loader_test,device,cpu_device):
    '''
    '''
    coco = get_coco_api_from_dataset(data_loader_test.dataset)
    iou_types = ['bbox']
    coco_evaluator = CocoEvaluator(coco, iou_types)
    torch.save(model,'model.pth')
    model.eval()
    pbar = tqdm(enumerate(data_loader_test),total=len(data_loader_test))
    for ind, (images, targets) in pbar:
        with torch.no_grad():
            model_time = time.time()
            images = list(img.to(device) for img in images)
            targets = [{k: v.to(device) for k, v in t.items()} for t in targets]
            # loss_dict, outputs = model(images,targets)
            outputs = model(images)
            # losses_reduced = sum(loss for loss in loss_dict.values())
            # with torch.no_grad():
                # print("loss_dict: ",loss_dict)
                # print(" losses_reduced val: ",losses_reduced)
            # loss_value = losses_reduced.item()
            # outputs = model(images)

            # print(type(outputs[0]))
            # print(outputs)
#                 loss_str = []
#                 loss_str.append("{}: {}".format("loss","{:.3f}".format(loss_value)))

#                 for name, val in loss_dict.items():
#                     loss_str.append(
#                         "{}: {}".format(name, "{:.3f}".format(val) )
#                     )
#                     pbar.set_postfix({'loss': loss_str})
            outputss = []
            for t in outputs:
                outputss.append({k: v.to(cpu_device) for k, v in t.items()})
            model_time = time.time() - model_time
            res = {target["image_id"].item(): output for target, output in zip(targets, outputss)}
            model_time_str = str(datetime.timedelta(seconds=int(model_time)))
            # print("Model Time: ",model_time_str)

            evaluator_time = time.time()
            # print("data_loader_test.dataset.catIdtoCls: ",data_loader_test.dataset.clstoCatId)
            coco_evaluator.update(res,remap_dict=data_loader_test.dataset.clstoCatId)
            evaluator_time = time.time() - evaluator_time
            evaluator_time_str = str(datetime.timedelta(seconds=int(evaluator_time)))
            # print("COCO Eval Time: ",evaluator_time_str)
            # break
    # accumulate predictions from all images
    coco_evaluator.accumulate()
    coco_evaluator.summarize()