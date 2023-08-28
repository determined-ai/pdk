import fiftyone as fo

# name = "xview-dataset"
# dataset_dir = "/Users/mendeza/data/xview/train_images_rgb/"
# ann_path = '/Users/mendeza/data/xview/train_rgb.json'
# # Create the dataset
# dataset = fo.Dataset.from_dir(
#     data_path=dataset_dir,
#     labels_path=ann_path,
#     dataset_type=fo.types.COCODetectionDataset,
#     name=name,
# )

# # View summary info about the dataset
# # print(dataset)

# # Print the first few samples in the dataset
# # print(dataset.head())

# session = fo.launch_app(dataset,port=5151)
# session.wait(-1)

# train_images_300_0
# train_300_0.json

name = "xview-dataset-sliced-train-no-neg2"
dataset_dir = "/Users/mendeza/data/xview/train_sliced_no_neg/train_images_300_02/"
ann_path = '/Users/mendeza/data/xview/train_sliced_no_neg/train_300_02.json'
# Create the dataset
dataset = fo.Dataset.from_dir(
    data_path=dataset_dir,
    labels_path=ann_path,
    dataset_type=fo.types.COCODetectionDataset,
    name=name,
)

# View summary info about the dataset
# print(dataset)

# Print the first few samples in the dataset
# print(dataset.head())

session = fo.launch_app(dataset,port=5151)
session.wait(-1)