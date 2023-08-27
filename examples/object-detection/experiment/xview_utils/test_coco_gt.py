import torch
from torchvision.datasets import CocoDetection
import cv2
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageDraw
if __name__ == '__main__':
    ds = CocoDetection(root='/Users/mendeza/data/xview/train_images/',annFile='/Users/mendeza/data/xview/train.json')
    img, anns = ds[0]
    draw = ImageDraw.Draw(img)
    print("img: ",img)
    bboxes = np.array([a['bbox'] for a in anns])
    print(bboxes.shape)
    cats = np.array([a['category_id'] for a in anns])
    for b,c in zip(bboxes, cats):
        x,y,w,h = b
        x2 = x+w
        y2 = y+h
        draw.rectangle([x,y,x2,y2],fill=None,width=10,outline=(255,0,0))
    plt.imshow(img)
    plt.show()