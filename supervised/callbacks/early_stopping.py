import logging
import numpy as np
import pandas as pd

from supervised.callbacks.callback import Callback
from supervised.utils.metric import Metric
from supervised.utils.config import LOG_LEVEL

logger = logging.getLogger(__name__)
logger.setLevel(LOG_LEVEL)

class EarlyStopping(Callback):
    def __init__(self, params):
        super(EarlyStopping, self).__init__(params)
        self.name = params.get("name", "early_stopping")
        self.metric = Metric(params.get("metric"))
        self.max_no_improvement_cnt = params.get("max_no_improvement_cnt", 5)

        self.keep_best_model = params.get("keep_best_model", True)
        self.best_iter = {}
        self.best_loss = {}
        self.loss_values = {}
        self.best_models = {}
        self.best_y_predicted = {}
        self.best_y_oof = (
            None
        )  # predictions computed on out of folds or on validation set
        self.final_loss = (
            None
        )  # final score computed on combined predictions from all learners
        # path to best model local copy, only used if cannot deep copy
        self.best_model_paths = {}
        self.multiple_target = False
        self.target_columns = None

    def add_and_set_learner(self, learner):
        self.learners += [learner]
        self.learner = learner
        self.best_iter[learner.uid] = None
        self.best_loss[learner.uid] = self.metric.worst_value()
        self.loss_values[learner.uid] = {"train": [], "validation": [], "iters": []}
        self.best_models[learner.uid] = None
        self.best_model_paths[learner.uid] = None
        self.best_y_predicted[learner.uid] = None

    def on_learner_train_start(self, logs):
        self.no_improvement_cnt = 0

    def on_framework_train_end(self, logs):
        # aggregate predictions from all learners
        # it has two columns: 'prediction', 'target'
        logger.debug("early stopping on framework train end")
        print(self.multiple_target)
        print(self.target_columns)

        self.best_y_oof = pd.concat(list(self.best_y_predicted.values()))
        self.best_y_oof.sort_index(inplace=True)

        if "prediction" in self.best_y_oof:
            self.final_loss = self.metric(
                self.best_y_oof[self.target_columns], self.best_y_oof["prediction"]
            )
        else:
            prediction_cols = [c for c in self.best_y_oof.columns if "prediction" in c]            
            self.final_loss = self.metric(
                self.best_y_oof[self.target_columns], self.best_y_oof[prediction_cols]
            )

    def on_iteration_end(self, logs, predictions):
        
        train_loss = self.metric(
            predictions.get("y_train_true"), predictions.get("y_train_predicted")
        )
        validation_loss = self.metric(
            predictions.get("y_validation_true"),
            predictions.get("y_validation_predicted"),
        )
        self.loss_values[self.learner.uid]["train"] += [train_loss]
        self.loss_values[self.learner.uid]["validation"] += [validation_loss]
        self.loss_values[self.learner.uid]["iters"] += [logs.get("iter_cnt")]

        if self.metric.improvement(
            previous=self.best_loss[self.learner.uid], current=validation_loss
        ):

            y_validation_true = predictions.get("y_validation_true")
            self.no_improvement_cnt = 0
            self.best_iter[self.learner.uid] = logs.get("iter_cnt")
            self.best_loss[self.learner.uid] = validation_loss

            
            
            if len(y_validation_true.shape) == 1 or y_validation_true.shape[1] == 1:
                self.best_y_predicted[self.learner.uid] = pd.DataFrame(
                    {
                        "target": y_validation_true.values.reshape(
                            y_validation_true.shape[0]
                        )
                    },
                    index=predictions.get("validation_index"),
                )
                self.multiple_target = False
                self.target_columns = "target"
            else:
                self.best_y_predicted[self.learner.uid] = pd.DataFrame(
                    y_validation_true,
                    index=predictions.get("validation_index"),
                )
                self.multiple_target = True
                self.target_columns = y_validation_true.columns

            y_validation_predicted = predictions.get("y_validation_predicted")

            if len(y_validation_predicted.shape) == 1:
                # only one prediction column (binary classification or regression)
                self.best_y_predicted[self.learner.uid][
                    "prediction"
                ] = y_validation_predicted
            else:
                # several columns (multiclass classification)
                for i_col in range(y_validation_predicted.shape[1]):
                    self.best_y_predicted[self.learner.uid][
                        "prediction_{}".format(i_col)
                    ] = y_validation_predicted[:, i_col]

            self.best_models[self.learner.uid] = self.learner.copy()

            # if local copy is not available, save model and keep path
            if self.best_models[self.learner.uid] is None:
                self.best_model_paths[self.learner.uid] = self.learner.save()
        else:
            self.no_improvement_cnt += 1

        if self.no_improvement_cnt > self.max_no_improvement_cnt:
            self.learner.stop_training = True

        logger.info(
            "EarlyStopping.on_iteration_end, train loss: {}, validation loss: {}, "
            "no improvement cnt {}, iters {}".format(
                train_loss,
                validation_loss,
                self.no_improvement_cnt,
                len(self.loss_values[self.learner.uid]["iters"]),
            )
        )

    def get_status(self):
        return "Train loss: {}, Validation loss: {} @ iteration {}".format(
            self.loss_values[self.learner.uid]["train"][-1],
            self.loss_values[self.learner.uid]["validation"][-1],
            len(self.loss_values[self.learner.uid]["iters"]),
        )
