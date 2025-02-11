from dataclasses import dataclass


@dataclass(repr=False, eq=False)
class Loss_Tracker:
    rolling_perceptibility_loss: float = 0.0
    current_perceptibility_loss: float = 0.0

    rolling_detection_loss: float = 0.0
    current_detection_loss: float = 0.0

    def update_perceptibility_loss(self, loss):
        self.current_perceptibility_loss = loss

        if self.rolling_perceptibility_loss:
            self.rolling_perceptibility_loss = (
                self.rolling_perceptibility_loss * 0.99
            ) + (loss * 0.01)
        else:
            self.rolling_perceptibility_loss = loss

    def update_detection_loss(self, loss):
        self.current_detection_loss = loss

        if self.rolling_detection_loss:
            self.rolling_detection_loss = (
                self.rolling_detection_loss * 0.99
            ) + (loss * 0.01)
        else:
            self.rolling_detection_loss = loss

    def print_losses(self, image, num_iter):
        losses_string = (
            f"\n--- Iteration Number {num_iter} losses --- \n"
            + f"Current detection loss: {self.current_detection_loss:7f} \n"
            + f"Exponential rolling average detection loss: {self.rolling_detection_loss:7f} \n\n"
            + f"Current perceptibility loss: {self.current_perceptibility_loss:7f} \n"
            + f"Exponential rolling average perceptibility loss: {self.rolling_perceptibility_loss:7f} \n"
        )
        image.append_to_training_progress_file(losses_string)
        print(losses_string)

    def return_all_losses(self):
        return [
            self.current_detection_loss,
            self.rolling_detection_loss,
            self.current_perceptibility_loss,
            self.rolling_perceptibility_loss,
        ]
