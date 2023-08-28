import copy
import io
from contextlib import redirect_stdout

import numpy as np
import pycocotools.mask as mask_util
import torch
import utils
from pycocotools.coco import COCO
from pycocotools.cocoeval import COCOeval
import math
from terminaltables import AsciiTable
import itertools
class CocoEvaluator:
    def __init__(self, coco_gt, iou_types):
        if not isinstance(iou_types, (list, tuple)):
            raise TypeError(f"This constructor expects iou_types of type list or tuple, instead  got {type(iou_types)}")
        coco_gt = copy.deepcopy(coco_gt)
        self.coco_gt = coco_gt

        self.iou_types = iou_types
        self.coco_eval = {}
        for iou_type in iou_types:
            self.coco_eval[iou_type] = COCOeval(coco_gt, iouType=iou_type)

        self.img_ids = []
        self.eval_imgs = {k: [] for k in iou_types}

    def update(self, predictions,remap_dict=None):
        img_ids = list(np.unique(list(predictions.keys())))
        self.img_ids.extend(img_ids)

        for iou_type in self.iou_types:
            results = self.prepare(predictions, iou_type,remap_dict)
            with redirect_stdout(io.StringIO()):
                coco_dt = COCO.loadRes(self.coco_gt, results) if results else COCO()
            coco_eval = self.coco_eval[iou_type]

            coco_eval.cocoDt = coco_dt
            coco_eval.params.imgIds = list(img_ids)
            img_ids, eval_imgs = evaluate(coco_eval)

            self.eval_imgs[iou_type].append(eval_imgs)

    def synchronize_between_processes(self):
        for iou_type in self.iou_types:
            self.eval_imgs[iou_type] = np.concatenate(self.eval_imgs[iou_type], 2)
            create_common_coco_eval(self.coco_eval[iou_type], self.img_ids, self.eval_imgs[iou_type])

    def accumulate(self):
        for coco_eval in self.coco_eval.values():
            coco_eval.accumulate()

    def summarize(self):
        for iou_type, coco_eval in self.coco_eval.items():
            print(f"IoU metric: {iou_type}")
            coco_eval.summarize()
            # per class mAP metrics
        results_per_category = self.per_class_coco_ap(self.coco_gt, self.coco_eval['bbox'])
        results_per_category50 = self.per_class_coco_ap50(self.coco_gt, self.coco_eval['bbox'])
        self.print_per_class_metrics(results_per_category,results_per_category50)
    def print_per_class_metrics(self,results_per_category,results_per_category50):
            cls_names = []
            average = 0
            cnt = 0 # keep track of how many have a value (not nan)
            print("Per Class AP:")
            for i in results_per_category:
                    cls_name = i[0]
                    cls_names.append(i[0])
                    mAP_val = float(i[1])
                    if not math.isnan(mAP_val):
                        average+=mAP_val
                        cnt+=1
                    # print(cls_name,mAP_val)
                        num_columns = 2
            headers = ['category', 'AP']
            table_data = [headers]
            table_data+=results_per_category
            table = AsciiTable(table_data)
            print('\n' + table.table)
            average/=cnt
            print("mean coco AP: ",average)
            cls_names = []
            average = 0
            cnt = 0 # keep track of how many have a value (not nan)
            for i in results_per_category50:
                    cls_name = i[0]
                    cls_names.append(i[0])
                    mAP_val = float(i[1])
                    if not math.isnan(mAP_val):
                        average+=mAP_val
                        cnt+=1
                    # print(cls_name+"_50: ", mAP_val)
            num_columns = 2
            headers = ['category', 'AP@50']
            table_data = [headers]
            table_data+=results_per_category50
            table = AsciiTable(table_data)
            print('\n' + table.table)
            average/=cnt
            print("mean coco AP@50: ",average)
            # per class mAP50 metrics

    def per_class_coco_ap(self,coco,coco_eval):
      results_per_category=[]
      precisions = coco_eval.eval['precision']
      cats =  [i['id'] for i in coco.cats.values()]
      # print(cats)
      for idx, catId in enumerate(cats):
          # print(catId)
          # area range index 0: all area ranges
          # max dets index -1: typically 100 per image
          nm = coco.loadCats([catId])
          # print(nm[0]['name'])
          # print("precisions: ",precisions.shape)
          precision = precisions[:, :, idx, 0, -1]
          # print("precision:", precision.shape)
          # for ind, row in enumerate(precision):
              # print(ind,row)
          precision = precision[precision > -1]
          # print("precision, precision.size: ",precision,precision.size)
          if precision.size:
              ap = np.mean(precision)
          else:
              ap = float('nan')
          results_per_category.append(
              (f'{nm[0]["name"]}', f'{float(ap):0.6f}'))
      return results_per_category
    def per_class_coco_ap50(self, coco,coco_eval):
        results_per_category=[]
        cats =  [i['id'] for i in coco.cats.values()]
        def _get_thr_ind(coco_eval, thr):
            ind = np.where((coco_eval.params.iouThrs > thr - 1e-5) &
                           (coco_eval.params.iouThrs < thr + 1e-5))[0][0]
            iou_thr = coco_eval.params.iouThrs[ind]
            assert np.isclose(iou_thr, thr)
            return ind

        IoU_lo_thresh = 0.5
        IoU_hi_thresh = 0.5
        ind_lo = _get_thr_ind(coco_eval, IoU_lo_thresh)
        ind_hi = _get_thr_ind(coco_eval, IoU_hi_thresh)
        # precision has dims (iou, recall, cls, area range, max dets)
        # area range index 0: all area ranges
        # max dets index 2: 100 per image
        precision = coco_eval.eval['precision'][ind_lo:(ind_hi + 1), :, :, 0, 2]
        ap_default = np.mean(precision[precision > -1])
        print(
            '~~~~ Mean and per-category AP @ IoU=[{:.2f},{:.2f}] ~~~~'.format(
                IoU_lo_thresh, IoU_hi_thresh))
        print('{:.1f}'.format(100 * ap_default))
        for cls_ind, cls in enumerate(cats):
            if cls == '__background__':
                continue
            # minus 1 because of __background__
            nm = coco.loadCats([cls])
            # print(nm)
            precision = coco_eval.eval['precision'][
                ind_lo:(ind_hi + 1), :, cls_ind - 1, 0, 2]
            ap = precision[precision > -1]
            # print("ap, ap.size: ",ap,ap.size)
            ap = np.mean(precision[precision > -1])
            # print(cls,nm[0]['name'],cls_ind,ap)
            results_per_category.append(
                (f'{nm[0]["name"]}', f'{float(ap):0.6f}'))
        return results_per_category
    def prepare(self, predictions, iou_type,remap_dict=None):
            if iou_type == "bbox":
                return self.prepare_for_coco_detection(predictions,remap_dict)
            if iou_type == "segm":
                return self.prepare_for_coco_segmentation(predictions)
            if iou_type == "keypoints":
                return self.prepare_for_coco_keypoint(predictions)
            raise ValueError(f"Unknown iou type {iou_type}")
    def convert_label(self,label):
        if label== 0:
            return label
        else:
            return label-1
    def prepare_for_coco_detection(self, predictions,remap_dict=None):
        coco_results = []
        for original_id, prediction in predictions.items():
            if len(prediction) == 0:
                continue

            boxes = prediction["boxes"]
            boxes = convert_to_xywh(boxes).tolist()
            scores = prediction["scores"].tolist()
            labels = prediction["labels"].tolist()
            # print("labels: ",labels)

            coco_results.extend(
                [
                    {
                        "image_id": original_id,
                        "category_id": remap_dict[labels[k]],
                        "bbox": box,
                        "score": scores[k],
                    }
                    for k, box in enumerate(boxes)
                ]
            )
        return coco_results

    def prepare_for_coco_segmentation(self, predictions):
        coco_results = []
        for original_id, prediction in predictions.items():
            if len(prediction) == 0:
                continue

            scores = prediction["scores"]
            labels = prediction["labels"]
            masks = prediction["masks"]

            masks = masks > 0.5

            scores = prediction["scores"].tolist()
            labels = prediction["labels"].tolist()

            rles = [
                mask_util.encode(np.array(mask[0, :, :, np.newaxis], dtype=np.uint8, order="F"))[0] for mask in masks
            ]
            for rle in rles:
                rle["counts"] = rle["counts"].decode("utf-8")

            coco_results.extend(
                [
                    {
                        "image_id": original_id,
                        "category_id": labels[k],
                        "segmentation": rle,
                        "score": scores[k],
                    }
                    for k, rle in enumerate(rles)
                ]
            )
        return coco_results

    def prepare_for_coco_keypoint(self, predictions):
        coco_results = []
        for original_id, prediction in predictions.items():
            if len(prediction) == 0:
                continue

            boxes = prediction["boxes"]
            boxes = convert_to_xywh(boxes).tolist()
            scores = prediction["scores"].tolist()
            labels = prediction["labels"].tolist()
            keypoints = prediction["keypoints"]
            keypoints = keypoints.flatten(start_dim=1).tolist()

            coco_results.extend(
                [
                    {
                        "image_id": original_id,
                        "category_id": labels[k],
                        "keypoints": keypoint,
                        "score": scores[k],
                    }
                    for k, keypoint in enumerate(keypoints)
                ]
            )
        return coco_results


def convert_to_xywh(boxes):
    xmin, ymin, xmax, ymax = boxes.unbind(1)
    return torch.stack((xmin, ymin, xmax - xmin, ymax - ymin), dim=1)


def merge(img_ids, eval_imgs):
    all_img_ids = utils.all_gather(img_ids)
    all_eval_imgs = utils.all_gather(eval_imgs)

    merged_img_ids = []
    for p in all_img_ids:
        merged_img_ids.extend(p)

    merged_eval_imgs = []
    for p in all_eval_imgs:
        merged_eval_imgs.append(p)

    merged_img_ids = np.array(merged_img_ids)
    merged_eval_imgs = np.concatenate(merged_eval_imgs, 2)

    # keep only unique (and in sorted order) images
    merged_img_ids, idx = np.unique(merged_img_ids, return_index=True)
    merged_eval_imgs = merged_eval_imgs[..., idx]

    return merged_img_ids, merged_eval_imgs


def create_common_coco_eval(coco_eval, img_ids, eval_imgs):
    img_ids, eval_imgs = merge(img_ids, eval_imgs)
    img_ids = list(img_ids)
    eval_imgs = list(eval_imgs.flatten())

    coco_eval.evalImgs = eval_imgs
    coco_eval.params.imgIds = img_ids
    coco_eval._paramsEval = copy.deepcopy(coco_eval.params)


def evaluate(imgs):
    with redirect_stdout(io.StringIO()):
        imgs.evaluate()
    return imgs.params.imgIds, np.asarray(imgs.evalImgs).reshape(-1, len(imgs.params.areaRng), len(imgs.params.imgIds))