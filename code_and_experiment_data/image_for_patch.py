import numpy as np

from dataclasses import InitVar, dataclass, field
from torch.functional import Tensor
from typing import Tuple
from utils import (
    file_handler,
    plot_predictions,
    get_lab_diff,
    open_image_as_rgb_np_array,
)
from constants import IMAGES_DIRECTORY, TRANSFORM

from main import (
    initial_predictions_images_directory,
    training_loss_printouts_directory,
)


@dataclass(repr=False, eq=False)
class Image_For_Patch:
    name: str
    file_type: InitVar[str]
    object_detector: InitVar[None]
    image_as_np_array: np.ndarray = field(init=False)
    patch_shape: Tuple[int, int, int] = field(init=False)
    patch_location: Tuple[int, int] = field(init=False)
    patch_section_of_image: np.ndarray = field(init=False)
    image_rgb_diff: Tensor = field(init=False)

    def __post_init__(self, file_type, object_detector) -> None:
        self.image_as_np_array = open_image_as_rgb_np_array(
            path=f"{IMAGES_DIRECTORY}/{self.name}.{file_type}"
        )

        (
            predictions_class,
            predictions_boxes,
            predictions_score,
        ) = plot_predictions(
            object_detector,
            self.image_as_np_array,
            threshold=0.5,
            path=f"{initial_predictions_images_directory}/{self.name}.{file_type}",
        )

        self.append_to_training_progress_file(
            f"\n--- Initial Predictions for {self.name} ---"
            + f"\npredicted classes: {str(predictions_class)}"
            + f"\npredicted score: {str(predictions_score)}"
        )

        # Customise patch location to centre of prediction box
        # and patch to ratio of prediction box
        (
            self.patch_shape,
            self.patch_location,
        ) = self.cal_custom_patch_shape_and_location(predictions_boxes[0])

        self.patch_section_of_image = self.image_as_np_array[0][
            self.patch_location[0] : self.patch_location[0]
            + self.patch_shape[0],
            self.patch_location[1] : self.patch_location[1]
            + self.patch_shape[1],
            ...,
        ]

        self.image_rgb_diff = get_lab_diff(
            TRANSFORM(self.patch_section_of_image.astype(np.uint8))
        )

    def cal_custom_patch_shape_and_location(self, prediction_box):
        prediction_box_width_height = (
            prediction_box[1][0] - prediction_box[0][0],
            prediction_box[1][1] - prediction_box[0][1],
        )

        prediction_box_centre_points = (
            int(prediction_box[1][0] - (prediction_box_width_height[0] / 2)),
            int(prediction_box[1][1] - (prediction_box_width_height[1] / 2)),
        )

        # in the format (height, width, nb_channels) to meet Dpatch Requirements
        patch_shape = (
            int(1 / 3 * prediction_box_width_height[1]),
            int(1 / 3 * prediction_box_width_height[0]),
            3,
        )

        patch_location = self.cal_custom_patch_location(
            prediction_box_centre_points, patch_shape
        )

        return patch_shape, patch_location

    def cal_custom_patch_location(self, prediction_centre_points, patch_shape):
        # in format y,x to fit Dpatch requirements
        return (
            int(prediction_centre_points[1] - (patch_shape[0] / 2)),
            int(prediction_centre_points[0] - (patch_shape[1] / 2)),
        )

    def append_to_training_progress_file(self, string):
        file_handler(
            path=f"{training_loss_printouts_directory}/loss_prinouts_for_{self.name}.txt",
            mode="a",
            func=lambda f: f.write("\n" + string),
        )
