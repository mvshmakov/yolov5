import dvclive
import numpy as np
import torch


class DVCLogger():
    def __init__(self, path) -> None:
        dvclive.init(path)
        self.log_dict = {}
    
    def process_data(self, name, val):
        name = name.replace('/', '_')
        name = name.replace(':', '_')
        if isinstance(val, torch.Tensor):
            val = val.numpy()
        if isinstance(val, np.ndarray):
            val = val.tolist()
        if hasattr(val, "len") and len(val) == 1:
            val = val[0]
        return name, val
    
    def log(self, name, val):
        name, val = self.process_data(name, val)
        self.log_dict[name] = val

    def next_step(self):
        # NOTE: we save this here because this is how it's done with W&B integration
        # I guess, the idea is to store all metrics together when the epoch is completed
        # If we ^CTRL+C the process we could end up with some metric stored, while others
        # still aren't calculated. This approach reduces the chance of that happening.
        # TODO: W&B saves some kind of artefact - need to investigate
        for name, val in self.log_dict.items():
            dvclive.log(name, val)
        dvclive.next_step()
        self.log_dict = {}
