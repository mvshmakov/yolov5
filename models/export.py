"""Exports a YOLOv5 *.pt model to TorchScript, ONNX, CoreML formats

Usage:
    $ python path/to/models/export.py --weights yolov5s.pt --img 640 --batch 1
"""

import argparse
import sys
import time
from pathlib import Path
import yaml

sys.path.append(Path(__file__).parent.parent.absolute().__str__())  # to run '$ python *.py' files in subdirectories

import torch
import torch.nn as nn
from torch.utils.mobile_optimizer import optimize_for_mobile

import models
from models.experimental import attempt_load
from utils.activations import Hardswish, SiLU
from utils.general import colorstr, check_img_size, check_requirements, file_size, set_logging
from utils.torch_utils import select_device

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--params', type=str, default='params.yaml', help='params.yaml path')
    cli_opt = parser.parse_args()
    with open(cli_opt.params) as f:
        params = yaml.safe_load(f)["export"]
    # TODO: avoid using Namespace and switch to dict usage, probably
    opt = argparse.Namespace()
    opt.__dict__ = params

    opt.img_size *= 2 if len(opt.img_size) == 1 else 1  # expand
    opt.include = [x.lower() for x in opt.include]
    print(opt)
    set_logging()
    t = time.time()

    # Create folder to store models
    save_dir = Path(opt.project)
    save_dir.mkdir(exist_ok=True)

    # Load PyTorch model
    device = select_device(opt.device)
    model = attempt_load(opt.weights, map_location=device)  # load FP32 model
    model_filename = str(Path(opt.weights).name)
    labels = model.names

    # Checks
    gs = int(max(model.stride))  # grid size (max stride)
    opt.img_size = [check_img_size(x, gs) for x in opt.img_size]  # verify img_size are gs-multiples
    assert not (opt.device.lower() == 'cpu' and opt.half), '--half only compatible with GPU export, i.e. use --device 0'

    # Input
    img = torch.zeros(opt.batch_size, 3, *opt.img_size).to(device)  # image size(1,3,320,192) iDetection

    # Update model
    if opt.half:
        img, model = img.half(), model.half()  # to FP16
    if opt.train:
        model.train()  # training mode (no grid construction in Detect layer)
    for k, m in model.named_modules():
        m._non_persistent_buffers_set = set()  # pytorch 1.6.0 compatibility
        if isinstance(m, models.common.Conv):  # assign export-friendly activations
            if isinstance(m.act, nn.Hardswish):
                m.act = Hardswish()
            elif isinstance(m.act, nn.SiLU):
                m.act = SiLU()
        elif isinstance(m, models.yolo.Detect):
            m.inplace = opt.inplace
            m.onnx_dynamic = opt.dynamic
            # m.forward = m.forward_export  # assign forward (optional)

    for _ in range(2):
        y = model(img)  # dry runs
    print(f"\n{colorstr('PyTorch:')} starting from {opt.weights} ({file_size(opt.weights):.1f} MB)")

    # TorchScript export -----------------------------------------------------------------------------------------------
    if 'torchscript' in opt.include or 'coreml' in opt.include:
        prefix = colorstr('TorchScript:')
        try:
            print(f'\n{prefix} starting export with torch {torch.__version__}...')
            # f = opt.weights.replace('.pt', '.torchscript.pt')  # filename
            f = save_dir / Path(model_filename.replace('.pt', '.torchscript.pt'))
            ts = torch.jit.trace(model, img, strict=False)
            (optimize_for_mobile(ts) if opt.optimize else ts).save(f)
            print(f'{prefix} export success, saved as {f} ({file_size(f):.1f} MB)')
        except Exception as e:
            print(f'{prefix} export failure: {e}')

    # ONNX export ------------------------------------------------------------------------------------------------------
    if 'onnx' in opt.include:
        prefix = colorstr('ONNX:')
        try:
            import onnx

            print(f'{prefix} starting export with onnx {onnx.__version__}...')
            # f = opt.weights.replace('.pt', '.onnx')  # filename
            f = save_dir / Path(model_filename.replace('.pt', '.onnx'))
            torch.onnx.export(model, img, f, verbose=False, opset_version=opt.opset_version, input_names=['images'],
                              training=torch.onnx.TrainingMode.TRAINING if opt.train else torch.onnx.TrainingMode.EVAL,
                              do_constant_folding=not opt.train,
                              dynamic_axes={'images': {0: 'batch', 2: 'height', 3: 'width'},  # size(1,3,640,640)
                                            'output': {0: 'batch', 2: 'y', 3: 'x'}} if opt.dynamic else None)

            # Checks
            model_onnx = onnx.load(f)  # load onnx model
            onnx.checker.check_model(model_onnx)  # check onnx model
            # print(onnx.helper.printable_graph(model_onnx.graph))  # print

            # Simplify
            if opt.simplify:
                try:
                    check_requirements(['onnx-simplifier'])
                    import onnxsim

                    print(f'{prefix} simplifying with onnx-simplifier {onnxsim.__version__}...')
                    model_onnx, check = onnxsim.simplify(
                        model_onnx,
                        dynamic_input_shape=opt.dynamic,
                        input_shapes={'images': list(img.shape)} if opt.dynamic else None)
                    assert check, 'assert check failed'
                    onnx.save(model_onnx, f)
                except Exception as e:
                    print(f'{prefix} simplifier failure: {e}')
            print(f'{prefix} export success, saved as {f} ({file_size(f):.1f} MB)')
        except Exception as e:
            print(f'{prefix} export failure: {e}')

    # CoreML export ----------------------------------------------------------------------------------------------------
    if 'coreml' in opt.include:
        prefix = colorstr('CoreML:')
        try:
            import coremltools as ct

            print(f'{prefix} starting export with coremltools {ct.__version__}...')
            assert opt.train, 'CoreML exports should be placed in model.train() mode with `python export.py --train`'
            model = ct.convert(ts, inputs=[ct.ImageType('image', shape=img.shape, scale=1 / 255.0, bias=[0, 0, 0])])
            # f = opt.weights.replace('.pt', '.mlmodel')  # filename
            f = save_dir / Path(model_filename.replace('.pt', '.mlmodel'))
            model.save(f)
            print(f'{prefix} export success, saved as {f} ({file_size(f):.1f} MB)')
        except Exception as e:
            print(f'{prefix} export failure: {e}')

    # Finish
    print(f'\nExport complete ({time.time() - t:.2f}s). Visualize with https://github.com/lutzroeder/netron.')
