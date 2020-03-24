from experiments import BaseExperiment
from experiments.parser import create_objects_from_config
import pytorch_lightning as pl
import torch
from sacred import Experiment
from configs.simple_sampling_config import configuration
import copy
from utils.logger import Logger
import os
import torch.utils.data


class SimpleSamplingExperiment(pl.LightningModule, BaseExperiment):

    def __init__(self, configuration_dict, _run):
        super().__init__()

        self.configuration_dict = copy.deepcopy(configuration_dict)
        self.objects = create_objects_from_config(configuration_dict)

        if not os.path.exists(self.configuration_dict['log_path']):
            os.mkdir(self.configuration_dict['log_path'])

        self.trainer = self.objects['trainer']

        if self.objects.get('deterministic'):
            torch.backends.cudnn.deterministic = True
            torch.backends.cudnn.benchmark = False

        self.auto_encoder_model = self.objects['auto_encoder_model']
        self.prior = self.objects['prior']
        self.reconstruction = self.objects['reconstruction']

        self.inf_complement_training_iterator = iter(
            self.get_infinite_data_loader(
                torch.utils.data.DataLoader(
                    self.objects['training_data_set'].get_complement_data_set(),
                    batch_size=self.objects['batch_size'],
                    shuffle=True,
                    num_workers=self.objects['num_workers']
                )
            )
        )

        self.logger_ = Logger(_run, self, self.configuration_dict, self.objects)
        self.epoch = -1
        self.step = 0
        self.result = None

    def get_infinite_data_loader(self, dl):
        device = "cuda:{}".format(self.trainer.root_gpu)
        while True:
            for batch in iter(dl):
                for key in batch:
                    if type(batch[key]) is torch.Tensor:
                        batch[key] = batch[key].to(device)
                yield batch

    def forward(self, batch):
        batch['epoch'] = self.epoch
        batch = self.auto_encoder_model(batch)
        return batch

    def training_step(self, batch_normal, batch_num, optimizer_idx=0):

        if batch_num == 0 and optimizer_idx == 0:
            self.epoch += 1

        if optimizer_idx == 0:
            batch_normal = self(batch_normal)
            batch_abnormal = self(next(self.inf_complement_training_iterator))
            reconstruction_loss = self.objects['reconstruction'].loss(batch_normal, batch_abnormal)
            prior_loss = self.objects['prior'].loss(batch_normal) + self.objects['prior'].loss(batch_abnormal)

            batch_normal['reconstruction_loss'] = reconstruction_loss
            batch_normal['prior_loss'] = prior_loss
            batch_normal['loss'] = reconstruction_loss + prior_loss

            self.logger_.log_training_step(batch_normal, self.step)

            self.step += 1

        else:
            raise AttributeError

        return {
            'loss': batch_normal['loss'],
            'tqdm': {'loss': batch_normal['loss']},
        }

    def validation_step(self, batch, batch_num):
        self(batch)
        return {
            'targets': batch['targets'],
            'scores': batch['scores'],
            'machine_types': batch['machine_types'],
            'machine_ids': batch['machine_ids'],
            'part_numbers': batch['part_numbers'],
            'file_ids': batch['file_ids']
        }

    def validation_end(self, outputs):
        self.logger_.log_validation(outputs, self.step, self.epoch)
        return {}

    def test_step(self, batch, batch_num, *args):
        self(batch)
        return {
            'targets': batch['targets'],
            'scores': batch['scores'],
            'machine_types': batch['machine_types'],
            'machine_ids': batch['machine_ids'],
            'part_numbers': batch['part_numbers'],
            'file_ids': batch['file_ids']
        }

    def test_end(self, outputs):
        self.result = self.logger_.log_testing(outputs)
        self.logger_.close()
        return self.result

    def configure_optimizers(self):
        optimizers = [
            self.objects['optimizer']
        ]

        lr_schedulers = [
            self.objects['lr_scheduler']
        ]

        return optimizers, lr_schedulers

    def train_dataloader(self):
        dl = torch.utils.data.DataLoader(
            self.objects['training_data_set'],
            batch_size=self.objects['batch_size'],
            shuffle=True,
            num_workers=self.objects['num_workers']
        )
        return dl

    def val_dataloader(self):
        dl = torch.utils.data.DataLoader(
            self.objects['validation_data_set'],
            batch_size=self.objects['batch_size'],
            shuffle=False,
            num_workers=self.objects['num_workers']
        )
        return dl

    def test_dataloader(self):
        dl = torch.utils.data.DataLoader(
            self.objects['validation_data_set'],
            batch_size=self.objects['batch_size'],
            shuffle=False,
            num_workers=self.objects['num_workers']
        )
        return dl

    def run(self):
        self.trainer.fit(self)
        self.trainer.test(self)
        return self.result


ex = Experiment('dcase2020_task2_simple_sampling')
cfg = ex.config(configuration)


@ex.automain
def run(_config, _run):
    experiment = SimpleSamplingExperiment(_config, _run)
    return experiment.run()