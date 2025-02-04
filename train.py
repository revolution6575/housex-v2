from config import *
from dataset import MainstageDataset, create_splits
from model import MainstageModel
from torch.utils.data import DataLoader, random_split
import torch
import lightning as L
from lightning.pytorch.loggers import WandbLogger
from easydict import EasyDict as edict
from copy import deepcopy
from argparse import ArgumentParser
from lightning.pytorch.callbacks import ModelCheckpoint
import os
import json

torch_rng = torch.Generator().manual_seed(42)
torch.set_float32_matmul_precision('high')

if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('--extractor_name', type=str, default='resnet18')
    parser.add_argument('--transformer_num_layers', type=int, default=1)
    parser.add_argument('--loss_weight', type=str, default=None)
    parser.add_argument('--learning_rate', type=float, default=1e-4)
    parser.add_argument('--d_model', type=int, default=768)
    parser.add_argument('--n_head', type=int, default=3)
    parser.add_argument('--project', type=str, default='Mainstage-v2-dataset')
    parser.add_argument('--ckpt_dir', type=str, default='/home/xinyu.li/checkpoints')
    parser.add_argument('--comment', type=str, default='')
    parser.add_argument('--use_chroma', default=False, action='store_true')
    parser.add_argument('--mode', type=str, default='full')
    parser.add_argument('--gpu_id', type=int, default=-1)
    parser.add_argument('--debug', default=False, action='store_true')
    
    args = parser.parse_args()
    os.makedirs(args.ckpt_dir, exist_ok=True)
    
    model_config = edict({
        'extractor_name': args.extractor_name,
        'transformer_num_layers': args.transformer_num_layers,
        'loss_weight': args.loss_weight,
        'learning_rate': args.learning_rate,
        'd_model': args.d_model,
        'n_head': args.n_head,
    })
    
    model = MainstageModel(model_config)
    wb_config = deepcopy(model_config)
    wb_config.loss_weight = 'weighted' if wb_config is not None else None
    wb_config['comment'] = args.comment
    wb_config['batch_size'] = 4
    wb_config['mode'] = args.mode
    wb_config['use_chroma'] = args.use_chroma
    
    
    train_set = torch.load(f'/home/xinyu.li/train_set_{args.mode}_{args.use_chroma}.pth')
    val_set = torch.load(f'/home/xinyu.li/test_set_{args.mode}_{args.use_chroma}.pth')
    if args.debug:
        train_set = train_set[:20]
        val_set = val_set[:10]
    
    ### train_set, val_set = random_split(dataset, [0.8, 0.2], generator=torch_rng)
    
    class_cnt = sum([y for _, y in train_set])
    for genre, score in zip(ALL_GENRES, class_cnt.numpy().tolist()):
        print(genre, score)
    lw = 1 / class_cnt
    lw /= lw.sum()
    lw = torch.tensor(lw, dtype=torch.float32)

    train_loader = DataLoader(train_set, batch_size=wb_config['batch_size'], shuffle=True, generator=torch_rng)
    val_loader = DataLoader(val_set, batch_size=wb_config['batch_size'], shuffle=False, generator=torch_rng)
    
    wandb_logger = WandbLogger(
        project=args.project,
        config=wb_config,
        save_dir='/home/xinyu.li/'
    )
    
    checkpoint_callback = ModelCheckpoint(
        monitor='val_acc',    # The metric to monitor (validation accuracy in this case)
        mode='max',                # Save the checkpoint with the maximum accuracy
        save_top_k=1,              # Save only the best checkpoint
        dirpath=args.ckpt_dir,    # Directory where the checkpoints will be saved
        filename=f'{args.extractor_name}-{args.transformer_num_layers}-{args.n_head}' # Filename for the best checkpoint
    )
    
    trainer = L.Trainer(
        callbacks=[checkpoint_callback],
        max_epochs=1,
        logger=wandb_logger,
        log_every_n_steps=1,
        val_check_interval=0.25,
        devices=[args.gpu_id,],
        accelerator="gpu"
        # enable_checkpointing=False,
    )
    trainer.fit(model=model, train_dataloaders=train_loader, val_dataloaders=val_loader)
    
    # model = MainstageModel.__init__(model_config).load_from_checkpoint(checkpoint_callback.best_model_path)
    model = MainstageModel.load_from_checkpoint(checkpoint_callback.best_model_path, model_config=model_config)
    print("Best ckpt reloaded.")
    model.eval()
    with open(os.path.join(args.ckpt_dir, f'{args.extractor_name}-{args.transformer_num_layers}-{args.n_head}-{args.mode}-{str(args.use_chroma)}.json'), 'w') as f:
        ret = {}
        ret['train_res'] = model.train_metric_results
        ret['val_res'] = model.val_metric_results
        json.dump(ret, f)
        
        print('Results saved to', f.name)
