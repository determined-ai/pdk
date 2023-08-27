from pathlib import Path
from PIL import Image
import os
from tqdm import tqdm
if __name__ == '__main__':
    OUT_DIR = '/Users/mendeza/data/xview/train_images_rgb/'
    if not os.path.exists(OUT_DIR):
        os.makedirs(OUT_DIR)
    fnames = list(Path('/Users/mendeza/data/xview/train_images/').glob("*.tif"))
    for f in tqdm(fnames):
        # print(f.name)
        img = Image.open(f).convert('RGB')
        p = Path(f.name)
        # print(p.with_suffix('.png'))
        img.save(os.path.join(OUT_DIR,p.with_suffix('.png')) )
        # break