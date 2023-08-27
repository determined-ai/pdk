
from sahi.utils.coco import Coco, CocoAnnotation, CocoImage, create_coco_dict
from pprint import pprint
from sahi.utils.file import load_json, save_json
if __name__ == '__main__':
     # read coco file
    coco_dict = load_json('/Users/mendeza/data/xview/train_rgb.json')
    # /Users/mendeza/data/xview/train_sliced_no_neg/train_300_02.json
    coco_dict = load_json('/Users/mendeza/data/xview/train_sliced_no_neg/train_300_02.json')
    # create image_id_to_annotation_list mapping
    coco = Coco.from_coco_dict_or_path(coco_dict)
    coco.calculate_stats()
    pprint(coco._stats)
    # pprint(res)