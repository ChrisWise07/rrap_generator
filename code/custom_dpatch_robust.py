# MIT License
#
# Copyright (C) The Adversarial Robustness Toolbox (ART) Authors 2020
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
# Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
# WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""
This module implements a variation of the adversarial patch attack `DPatch` for object detectors.
It follows Lee & Kolter (2019) in using sign gradients with expectations over transformations.
The particular transformations supported in this implementation are cropping, rotations by multiples of 90 degrees,
and changes in the brightness of the image.

| Paper link (original DPatch): https://arxiv.org/abs/1806.02299v4
| Paper link (physical-world patch from Lee & Kolter): https://arxiv.org/abs/1906.11897
"""
import logging
import math
import random
from re import I
from typing import Dict, List, Optional, Tuple, Union, TYPE_CHECKING
import numpy as np
from math import pi, cos

from tqdm.auto import trange
from art.attacks.attack import EvasionAttack
from art.estimators.estimator import BaseEstimator, LossGradientsMixin
from art.estimators.object_detection.object_detector import ObjectDetectorMixin
from art import config
from utils import calculate_patch_perceptibility_gradients, save_image_from_np_array, calculate_patch_perceptibility_gradients_no_trans
from image_for_patch import Image_For_Patch
from loss_tracker import Loss_Tracker
from main import args
from constants import ROOT_DIRECTORY

if TYPE_CHECKING:
    from art.utils import OBJECT_DETECTOR_TYPE

logger = logging.getLogger(__name__)

class RobustDPatch(EvasionAttack):
    """
    Implementation of a particular variation of the DPatch attack.
    It follows Lee & Kolter (2019) in using sign gradients with expectations over transformations.
    The particular transformations supported in this implementation are cropping, rotations by multiples of 90 degrees,
    and changes in the brightness of the image.

    | Paper link (original DPatch): https://arxiv.org/abs/1806.02299v4
    | Paper link (physical-world patch from Lee & Kolter): https://arxiv.org/abs/1906.11897
    """

    attack_params = EvasionAttack.attack_params + [
        "patch_shape",
        "learning_rate",
        "max_iter",
        "batch_size",
        "patch_location",
        "crop_range",
        "brightness_range",
        "rotation_weights",
        "sample_size",
        "targeted",
        "verbose",
    ]

    _estimator_requirements = (BaseEstimator, LossGradientsMixin, ObjectDetectorMixin)

    def __init__(
        self,
        estimator: "OBJECT_DETECTOR_TYPE",
        patch_shape: Tuple[int, int, int] = (40, 40, 3),
        patch_location: Tuple[int, int] = (0, 0),
        crop_range: Tuple[int, int] = (0, 0),
        brightness_range: Tuple[float, float] = (1.0, 1.0),
        rotation_weights: Union[Tuple[float, float, float, float], Tuple[int, int, int, int]] = (1, 0, 0, 0),
        sample_size: int = 1,
        max_iter: int = 500,
        batch_size: int = 16,
        targeted: bool = False,
        verbose: bool = True,
        dec_decay_rate: float = 0.95,
        percep_decay_rate: float = 0.95,
        detection_momentum = 0.9, 
        perceptibility_momentum = 0.9,
        perceptibility_learning_rate: float = 5.0,
        detection_learning_rate: float = 0.01,
        image_to_patch: Image_For_Patch = None,
        training_data_path: str = None,
        previous_training_data: dict = None
        

    ):
        """
        Create an instance of the :class:`.RobustDPatch`.

        :param estimator: A trained object detector.
        :param patch_shape: The shape of the adversarial patch as a tuple of shape (height, width, nb_channels).
        :param patch_location: The location of the adversarial patch as a tuple of shape (upper left x, upper left y).
        :param crop_range: By how much the images may be cropped as a tuple of shape (height, width).
        :param brightness_range: Range for randomly adjusting the brightness of the image.
        :param rotation_weights: Sampling weights for random image rotations by (0, 90, 180, 270) degrees clockwise.
        :param sample_size: Number of samples to be used in expectations over transformation.
        :param learning_rate: The learning rate of the optimization.
        :param max_iter: The number of optimization steps.
        :param batch_size: The size of the training batch.
        :param targeted: Indicates whether the attack is targeted (True) or untargeted (False).
        :param verbose: Show progress bars.
        """

        super().__init__(estimator=estimator)

        self.image_to_patch = image_to_patch
        self.patch_shape = self.image_to_patch.patch_shape
        self.patch_location = self.image_to_patch.patch_location
        self.crop_range = crop_range
        self.brightness_range = brightness_range
        self.rotation_weights = rotation_weights
        self.sample_size = sample_size
        self.max_iter = max_iter
        self.batch_size = batch_size
        self._targeted = targeted
        self.verbose = verbose
        self.dec_decay_rate = dec_decay_rate
        self.percep_decay_rate = percep_decay_rate
        self.detection_momentum =  detection_momentum 
        self.perceptibility_momentum = perceptibility_momentum
        self.training_data_path = training_data_path

        if previous_training_data:
            self.detection_learning_rate = previous_training_data["detection_learning_rate"]
            self.perceptibility_learning_rate = previous_training_data["perceptibility_learning_rate"]
            self.loss_tracker = Loss_Tracker(rolling_perceptibility_loss = previous_training_data["loss_data"]["perceptibility_loss"], 
                                             rolling_detection_loss = previous_training_data["loss_data"]["detection_loss"])
            self._patch = np.array(previous_training_data["patch_np_array"]).astype(config.ART_NUMPY_DTYPE)
            self._old_patch_detection_update = np.array(previous_training_data["old_patch_detection_update"])
            self._old_patch_perceptibility_update = np.array(previous_training_data["old_patch_perceptibility_update"])
        else:
            self.detection_learning_rate = detection_learning_rate
            self.perceptibility_learning_rate = perceptibility_learning_rate
            self.loss_tracker = Loss_Tracker()
            self._patch = self.configure_starting_patch(args.patch_config)
            self._old_patch_detection_update = np.zeros_like(self._patch)
            self._old_patch_perceptibility_update = np.zeros_like(self._patch)
            
        self._check_params()

    def apply_patch(self, x: np.ndarray, patch_external: Optional[np.ndarray] = None) -> np.ndarray:
        """
        Apply the adversarial patch to images.

        :param x: Images to be patched.
        :param patch_external: External patch to apply to images `x`. If None the attacks patch will be applied.
        :return: The patched images.
        """

        x_patch = x.copy()

        if patch_external is not None:
            patch_local = patch_external.copy()
        else:
            patch_local = self._patch.copy()

        if self.estimator.channels_first:
            x_patch = np.transpose(x_patch, (0, 2, 3, 1))
            patch_local = np.transpose(patch_local, (1, 2, 0))

        # Apply patch:
        x_1, y_1 = self.patch_location
        x_2, y_2 = x_1 + patch_local.shape[0], y_1 + patch_local.shape[1]

        if x_2 > x_patch.shape[1] or y_2 > x_patch.shape[2]:
            raise ValueError("The patch (partially) lies outside the image.")

        x_patch[:, x_1:x_2, y_1:y_2, :] = patch_local

        if self.estimator.channels_first:
            x_patch = np.transpose(x_patch, (0, 3, 1, 2))

        return x_patch

    def generate(
        self, 
        x: np.ndarray, 
        print_nth_num: int,
        y: Optional[List[Dict[str, np.ndarray]]] = None, 
        **kwargs) -> np.ndarray:
        """
        Generate RobustDPatch.

        :param x: Sample images.
        :param y: Target labels for object detector.
        :return: Adversarial patch.
        """
        channel_index = 1 if self.estimator.channels_first else x.ndim - 1
        if x.shape[channel_index] != self.patch_shape[channel_index - 1]:
            raise ValueError("The color channel index of the images and the patch have to be identical.")
        if y is None and self.targeted:
            raise ValueError("The targeted version of RobustDPatch attack requires target labels provided to `y`.")
        if y is not None and not self.targeted:
            raise ValueError("The RobustDPatch attack does not use target labels.")
        if x.ndim != 4:
            raise ValueError("The adversarial patch can only be applied to images.")

        # Check whether patch fits into the cropped images:
        if self.estimator.channels_first:
            image_height, image_width = x.shape[2:4]
        else:
            image_height, image_width = x.shape[1:3]

        if not self.estimator.native_label_is_pytorch_format and y is not None:
            from art.estimators.object_detection.utils import convert_tf_to_pt

            y = convert_tf_to_pt(y=y, height=x.shape[1], width=x.shape[2])

        if y is not None:
            for i_image in range(x.shape[0]):
                y_i = y[i_image]["boxes"]
                for i_box in range(y_i.shape[0]):
                    x_1, y_1, x_2, y_2 = y_i[i_box]
                    if (
                        x_1 < self.crop_range[1]
                        or y_1 < self.crop_range[0]
                        or x_2 > image_width - self.crop_range[1] + 1
                        or y_2 > image_height - self.crop_range[0] + 1
                    ):
                        raise ValueError("Cropping is intersecting with at least one box, reduce `crop_range`.")

        if (
            self.patch_location[0] + self.patch_shape[0] > image_height - self.crop_range[0]
            or self.patch_location[1] + self.patch_shape[1] > image_width - self.crop_range[1]
        ):
            raise ValueError("The patch (partially) lies outside the cropped image.")
        
        num_batches = math.ceil(x.shape[0]/self.batch_size)
        min_perceptibility_learning_rate = self.perceptibility_learning_rate / 10
    
        for i_step in trange(self.max_iter, desc="RobustDPatch iteration", disable=not self.verbose):
            cosine_perceptibility_learning_rate = min_perceptibility_learning_rate + (0.5 * (self.perceptibility_learning_rate - min_perceptibility_learning_rate)) * (1 + cos((i_step / self.max_iter) * pi))
            
            if (i_step % args.dec_update_freq == 0):
                patch_gradients_old = np.zeros_like(self._patch)

                for i_batch in range(num_batches):
                    i_batch_start = i_batch * self.batch_size
                    i_batch_end = min((i_batch + 1) * self.batch_size, x.shape[0])

                    if y is None:
                        y_batch = y
                    else:
                        y_batch = y[i_batch_start:i_batch_end]

                    # Sample and apply the random transformations:
                    patched_images, patch_target, transforms = self._augment_images_with_patch(
                        x[i_batch_start:i_batch_end], y_batch, self._patch, channels_first=self.estimator.channels_first
                    )

                    gradients, loss = self.estimator.loss_gradient(
                        x=patched_images,
                        y=patch_target,
                        standardise_output=True,
                    )

                    self.loss_tracker.update_detection_loss(loss)

                    gradients = self._untransform_gradients(
                        gradients, transforms, channels_first=self.estimator.channels_first
                    )

                    patch_gradients_old += np.sum(gradients, axis=0)

                #update patch based on detection
                current_patch_detection_update = np.sign(patch_gradients_old) * (1 - 2 * int(self.targeted)) * self.detection_learning_rate
                self._old_patch_detection_update = np.add((self.detection_momentum * self._old_patch_detection_update), ((1 - self.detection_momentum) * current_patch_detection_update))
                self._patch += self._old_patch_detection_update

            #update based on perceptibility
            perc_patch_gradients = calculate_patch_perceptibility_gradients_no_trans(
                self._patch, self.image_to_patch.image_rgb_diff, self.loss_tracker
            )

            current_patch_perceptibility_update = perc_patch_gradients * -(cosine_perceptibility_learning_rate)
            self._old_patch_perceptibility_update = np.add((self.perceptibility_momentum * self._old_patch_perceptibility_update), ((1 - self.perceptibility_momentum) * current_patch_perceptibility_update))
            self._patch += self._old_patch_perceptibility_update

            if self.estimator.clip_values is not None:
                self._patch = np.clip(self._patch, a_min=self.estimator.clip_values[0], a_max=self.estimator.clip_values[1])

            if (i_step + 1) % print_nth_num == 0:
                self.loss_tracker.print_losses(self.image_to_patch, num_iter=i_step+1)

        return self._patch

    def _augment_images_with_patch(
        self, x: np.ndarray, y: Optional[List[Dict[str, np.ndarray]]], patch: np.ndarray, channels_first: bool
    ) -> Tuple[np.ndarray, List[Dict[str, np.ndarray]], Dict[str, Union[int, float]]]:
        """
        Augment images with patch.

        :param x: Sample images.
        :param y: Target labels.
        :param patch: The patch to be applied.
        :param channels_first: Set channels first or last.
        """

        transformations: Dict[str, Union[float, int]] = dict()
        x_copy = x.copy()
        patch_copy = patch.copy()
        x_patch = x.copy()

        if channels_first:
            x_copy = np.transpose(x_copy, (0, 2, 3, 1))
            x_patch = np.transpose(x_patch, (0, 2, 3, 1))
            patch_copy = np.transpose(patch_copy, (1, 2, 0))

        # Apply patch:
        x_1, y_1 = self.patch_location
        x_2, y_2 = x_1 + patch_copy.shape[0], y_1 + patch_copy.shape[1]
        x_patch[:, x_1:x_2, y_1:y_2, :] = patch_copy

        # 1) crop images:
        crop_x = random.randint(0, self.crop_range[0])
        crop_y = random.randint(0, self.crop_range[1])
        x_1, y_1 = crop_x, crop_y
        x_2, y_2 = x_copy.shape[1] - crop_x + 1, x_copy.shape[2] - crop_y + 1
        x_copy = x_copy[:, x_1:x_2, y_1:y_2, :]
        x_patch = x_patch[:, x_1:x_2, y_1:y_2, :]

        transformations.update({"crop_x": crop_x, "crop_y": crop_y})

        # 2) rotate images:
        rot90 = random.choices([0, 1, 2, 3], weights=self.rotation_weights)[0]

        x_copy = np.rot90(x_copy, rot90, (1, 2))
        x_patch = np.rot90(x_patch, rot90, (1, 2))

        transformations.update({"rot90": rot90})

        if y is not None:

            y_copy: List[Dict[str, np.ndarray]] = list()

            for i_image in range(x_copy.shape[0]):
                y_b = y[i_image]["boxes"].copy()
                image_width = x.shape[2]
                image_height = x.shape[1]
                x_1_arr = y_b[:, 0]
                y_1_arr = y_b[:, 1]
                x_2_arr = y_b[:, 2]
                y_2_arr = y_b[:, 3]
                box_width = x_2_arr - x_1_arr
                box_height = y_2_arr - y_1_arr

                if rot90 == 0:
                    x_1_new = x_1_arr
                    y_1_new = y_1_arr
                    x_2_new = x_2_arr
                    y_2_new = y_2_arr

                if rot90 == 1:
                    x_1_new = y_1_arr
                    y_1_new = image_width - x_1_arr - box_width
                    x_2_new = y_1_arr + box_height
                    y_2_new = image_width - x_1_arr

                if rot90 == 2:
                    x_1_new = image_width - x_2_arr
                    y_1_new = image_height - y_2_arr
                    x_2_new = x_1_new + box_width
                    y_2_new = y_1_new + box_height

                if rot90 == 3:
                    x_1_new = image_height - y_1_arr - box_height
                    y_1_new = x_1_arr
                    x_2_new = image_height - y_1_arr
                    y_2_new = x_1_arr + box_width

                y_i = dict()
                y_i["boxes"] = np.zeros_like(y[i_image]["boxes"])
                y_i["boxes"][:, 0] = x_1_new
                y_i["boxes"][:, 1] = y_1_new
                y_i["boxes"][:, 2] = x_2_new
                y_i["boxes"][:, 3] = y_2_new

                y_i["labels"] = y[i_image]["labels"]
                y_i["scores"] = y[i_image]["scores"]

                y_copy.append(y_i)

        # 3) adjust brightness:
        brightness = random.uniform(*self.brightness_range)
        x_copy = np.round(brightness * x_copy / self.detection_learning_rate) * self.detection_learning_rate
        x_patch = np.round(brightness * x_patch / self.detection_learning_rate) * self.detection_learning_rate

        transformations.update({"brightness": brightness})

        logger.debug("Transformations: %s", str(transformations))

        patch_target: List[Dict[str, np.ndarray]] = list()

        if self.targeted:
            predictions = y_copy
        else:
            predictions = self.estimator.predict(x=x_copy, standardise_output=True)

        for i_image in range(x_copy.shape[0]):
            target_dict = dict()
            target_dict["boxes"] = predictions[i_image]["boxes"]
            target_dict["labels"] = predictions[i_image]["labels"]
            target_dict["scores"] = predictions[i_image]["scores"]

            patch_target.append(target_dict)

        if channels_first:
            x_patch = np.transpose(x_patch, (0, 3, 1, 2))

        return x_patch, patch_target, transformations

    def _untransform_gradients(
        self,
        gradients: np.ndarray,
        transforms: Dict[str, Union[int, float]],
        channels_first: bool,
    ) -> np.ndarray:
        """
        Revert transformation on gradients.

        :param gradients: The gradients to be reverse transformed.
        :param transforms: The transformations in forward direction.
        :param channels_first: Set channels first or last.
        """

        if channels_first:
            gradients = np.transpose(gradients, (0, 2, 3, 1))

        # Account for brightness adjustment:
        gradients = transforms["brightness"] * gradients

        # Undo rotations:
        rot90 = (4 - transforms["rot90"]) % 4
        gradients = np.rot90(gradients, rot90, (1, 2))

        # Account for cropping when considering the upper left point of the patch:
        x_1 = self.patch_location[0] - int(transforms["crop_x"])
        y_1 = self.patch_location[1] - int(transforms["crop_y"])
        x_2 = x_1 + self.patch_shape[0]
        y_2 = y_1 + self.patch_shape[1]
        gradients = gradients[:, x_1:x_2, y_1:y_2, :]

        if channels_first:
            gradients = np.transpose(gradients, (0, 3, 1, 2))

        return gradients

    def _check_params(self) -> None:
        if not isinstance(self.patch_shape, (tuple, list)) or not all(isinstance(s, int) for s in self.patch_shape):
            raise ValueError("The patch shape must be either a tuple or list of integers.")
        if len(self.patch_shape) != 3:
            raise ValueError("The length of patch shape must be 3.")

        if not isinstance(self.detection_learning_rate, float):
            raise ValueError("The learning rate must be of type float.")
        if self.detection_learning_rate <= 0.0:
            raise ValueError("The learning rate must be greater than 0.0.")

        if not isinstance(self.max_iter, int):
            raise ValueError("The number of optimization steps must be of type int.")
        if self.max_iter <= 0:
            raise ValueError("The number of optimization steps must be greater than 0.")

        if not isinstance(self.batch_size, int):
            raise ValueError("The batch size must be of type int.")
        if self.batch_size <= 0:
            raise ValueError("The batch size must be greater than 0.")

        if not isinstance(self.verbose, bool):
            raise ValueError("The argument `verbose` has to be of type bool.")

        if not isinstance(self.patch_location, (tuple, list)) or not all(
            isinstance(s, int) for s in self.patch_location
        ):
            raise ValueError("The patch location must be either a tuple or list of integers.")
        if len(self.patch_location) != 2:
            raise ValueError("The length of patch location must be 2.")

        if not isinstance(self.crop_range, (tuple, list)) or not all(isinstance(s, int) for s in self.crop_range):
            raise ValueError("The crop range must be either a tuple or list of integers.")
        if len(self.crop_range) != 2:
            raise ValueError("The length of crop range must be 2.")

        if self.crop_range[0] > self.crop_range[1]:
            raise ValueError("The first element of the crop range must be less or equal to the second one.")

        if self.patch_location[0] < self.crop_range[0] or self.patch_location[1] < self.crop_range[1]:
            raise ValueError("The patch location must be outside the crop range.")

        if not isinstance(self.brightness_range, (tuple, list)) or not all(
            isinstance(s, float) for s in self.brightness_range
        ):
            raise ValueError("The brightness range must be either a tuple or list of floats.")
        if len(self.brightness_range) != 2:
            raise ValueError("The length of brightness range must be 2.")

        if self.brightness_range[0] < 0.0:
            raise ValueError("The brightness range must be >= 0.0.")

        if self.brightness_range[0] > self.brightness_range[1]:
            raise ValueError("The first element of the brightness range must be less or equal to the second one.")

        if not isinstance(self.rotation_weights, (tuple, list)) or not all(
            isinstance(s, (float, int)) for s in self.rotation_weights
        ):
            raise ValueError("The rotation sampling weights must be provided as tuple or list of float or int values.")
        if len(self.rotation_weights) != 4:
            raise ValueError("The number of rotation sampling weights must be 4.")

        if not all(s >= 0.0 for s in self.rotation_weights):
            raise ValueError("The rotation sampling weights must be non-negative.")

        if all(s == 0.0 for s in self.rotation_weights):
            raise ValueError("At least one of the rotation sampling weights must be strictly greater than zero.")

        if not isinstance(self.sample_size, int):
            raise ValueError("The EOT sample size must be of type int.")
        if self.sample_size <= 0:
            raise ValueError("The EOT sample size must be greater than 0.")

        if not isinstance(self.targeted, bool):
            raise ValueError("The argument `targeted` has to be of type bool.")
 
    def get_patch_shape(self):
        return self.patch_shape

    def decay_detection_learning_rate(self):
        self.detection_learning_rate *= self.dec_decay_rate
    
    def get_detection_learning_rate(self):
        return self.detection_learning_rate
 
    def decay_perceptibility_learning_rate(self):
        self.perceptibility_learning_rate *= self.percep_decay_rate
    
    def get_perceptibility_learning_rate(self):
        return self.perceptibility_learning_rate

    def get_patch(self):
        return self._patch
    
    def get_loss_tracker(self):
        return self.loss_tracker

    def get_old_patch_detection_update(self):
        return self._old_patch_detection_update

    def get_old_patch_perceptibility_update(self):
        return self._old_patch_perceptibility_update

    def get_image_to_patch(self):
        return self.image_to_patch 
    
    def get_training_data_path(self) -> str:
        return self.training_data_path

    def random_patch(self) -> np.ndarray:
        if self.estimator.clip_values is None:
            return np.zeros(shape=self.patch_shape, dtype=config.ART_NUMPY_DTYPE)
        else:
            np.random.seed(0)
            return (
                np.random.randint(0, 255, size=self.patch_shape)
                / 255
                * (self.estimator.clip_values[1] - self.estimator.clip_values[0])
                + self.estimator.clip_values[0]
            ).astype(config.ART_NUMPY_DTYPE)

    def configure_starting_patch(self, config_flag: str) -> np.ndarray:
        return {
            'is': self.image_to_patch.patch_section_of_image,
            'b': np.full(shape=self.patch_shape, fill_value = 0, dtype=config.ART_NUMPY_DTYPE),
            'w': np.full(shape=self.patch_shape, fill_value = 255, dtype=config.ART_NUMPY_DTYPE),
            'r': self.random_patch(),
            'hybrid': self.image_to_patch.patch_section_of_image + self.random_patch()
        }[config_flag]