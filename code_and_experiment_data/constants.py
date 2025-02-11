import os
import torch

from torchvision import transforms
from custom_pytorch_faster_rcnn import CustomPyTorchFasterRCNN

COCO_INSTANCE_CATEGORY_NAMES = [
    "__background__",
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "airplane",
    "bus",
    "train",
    "truck",
    "boat",
    "traffic light",
    "fire hydrant",
    "N/A",
    "stop sign",
    "parking meter",
    "bench",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
    "N/A",
    "backpack",
    "umbrella",
    "N/A",
    "N/A",
    "handbag",
    "tie",
    "suitcase",
    "frisbee",
    "skis",
    "snowboard",
    "sports ball",
    "kite",
    "baseball bat",
    "baseball glove",
    "skateboard",
    "surfboard",
    "tennis racket",
    "bottle",
    "N/A",
    "wine glass",
    "cup",
    "fork",
    "knife",
    "spoon",
    "bowl",
    "banana",
    "apple",
    "sandwich",
    "orange",
    "broccoli",
    "carrot",
    "hot dog",
    "pizza",
    "donut",
    "cake",
    "chair",
    "couch",
    "potted plant",
    "bed",
    "N/A",
    "dining table",
    "N/A",
    "N/A",
    "toilet",
    "N/A",
    "tv",
    "laptop",
    "mouse",
    "remote",
    "keyboard",
    "cell phone",
    "microwave",
    "oven",
    "toaster",
    "sink",
    "refrigerator",
    "N/A",
    "book",
    "clock",
    "vase",
    "scissors",
    "teddy bear",
    "hair drier",
    "toothbrush",
]

TRANSFORM = transforms.ToTensor()

FRCNN = CustomPyTorchFasterRCNN(
    clip_values=(0, 255),
    attack_losses=[
        "loss_classifier",
        "loss_box_reg",
        "loss_objectness",
        "loss_rpn_box_reg",
    ],
)

if torch.cuda.is_available():
    DEVICE = torch.device(f"cuda:{torch.cuda.current_device()}")
else:
    DEVICE = torch.device("cpu")

EPSILON = 1e-6

LIMIT_OF_PREDICTIONS_PER_IMAGE = 100

ROOT_DIRECTORY = os.path.dirname(os.path.realpath(__file__))

IMAGES_DIRECTORY = f"{ROOT_DIRECTORY}/plane_images"

ROOT_EXPERIMENT_DATA_DIRECTORY = f"{ROOT_DIRECTORY}/experiment_data"
