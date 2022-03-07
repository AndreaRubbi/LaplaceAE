from builtins import breakpoint
import os
import torch
from torch import nn
from torch.nn import functional as F
from tqdm import tqdm
import numpy as np
import matplotlib.pyplot as plt
import pytorch_lightning as pl
from pytorch_lightning.loggers import TensorBoardLogger
from pytorch_lightning.callbacks.early_stopping import EarlyStopping

from data import get_data, generate_latent_grid
from ae_models import get_encoder, get_decoder
from utils import softclip
from torch.nn.utils import parameters_to_vector, vector_to_parameters
from copy import deepcopy


def sample(parameters, posterior_scale, n_samples=100):
    n_params = len(parameters)
    samples = torch.randn(n_samples, n_params, device="cuda:0")
    samples = samples * posterior_scale.reshape(1, n_params)
    return parameters.reshape(1, n_params) + samples


def get_model(encoder, decoder):

    net = deepcopy(encoder.encoder._modules)
    decoder = decoder.decoder._modules
    max_ = max([int(i) for i in net.keys()])
    for i in decoder.keys():
        net.update({f"{max_+int(i) + 1}" : decoder[i]}) 

    return nn.Sequential(net)


def compute_hessian(x, feature_maps, net, output_size):
        
    H = []
    bs = x.shape[0]
    feature_maps = [x] + feature_maps
    tmp = torch.diag_embed(torch.ones(bs, output_size)).to(x.device)

    with torch.no_grad():
        for k in range(len(net) - 1, -1, -1):
            if isinstance(net[k], torch.nn.Linear):
                diag_elements = torch.diagonal(tmp,dim1=1,dim2=2)
                feature_map_k2 = (feature_maps[k] ** 2).unsqueeze(1)

                h_k = torch.bmm(diag_elements.unsqueeze(2), feature_map_k2).view(bs, -1)

                # has a bias
                if net[k].bias is not None:
                    h_k = torch.cat([h_k, diag_elements], dim=1)

                H = [h_k] + H

            elif isinstance(net[k], torch.nn.Tanh):
                J_tanh = torch.diag_embed(torch.ones(feature_maps[k+1].shape).to(x.device) - feature_maps[k+1]**2)
                # TODO: make more efficent by using row vectors
                tmp = torch.einsum("bnm,bnj,bjk->bmk", J_tanh, tmp, J_tanh) 

            if k == 0:                
                break

            if isinstance(net[k], torch.nn.Linear):
                tmp = torch.einsum("nm,bnj,jk->bmk", net[k].weight, tmp, net[k].weight) 

    H = torch.cat(H, dim = 1)
    
    # mean over batch size
    H = torch.mean(H, dim = 0)
                
    return H


class LitLaplaceAutoEncoder(pl.LightningModule):
    def __init__(self, dataset):
        super().__init__()

        device = "cuda:0" if torch.cuda.is_available() else "cpu"  # hola frederik :) can you fix this shit?

        latent_size = 2
        self.output_size = 784
        encoder = get_encoder(dataset, latent_size)
        decoder = get_decoder(dataset, latent_size)

        self.sigma_n =  1.0
        self.constant = 1.0/(2*self.sigma_n**2)
        
        self.net = get_model(encoder, decoder)

        self.feature_maps = []
        def fw_hook(module, input, output):
            self.feature_maps.append(output.detach())
        
        for k in range(len(self.net)):
            self.net[k].register_forward_hook(fw_hook)

        s = 1.0 
        self.h = s * torch.ones_like(parameters_to_vector(self.net.parameters())).to(device)

    def forward(self, x):
        out = self.net(x)
        return out

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(self.parameters(), lr=1e-3)
        return optimizer

    def training_step(self, train_batch, batch_idx):
        x, y = train_batch
        x = x.view(x.size(0), -1)

        # compute kl
        sigma_q = 1 / (self.h + 1e-6)
        
        mu_q = parameters_to_vector(self.net.parameters())
        k = len(mu_q)

        kl = 0.5 * (torch.log(1 / sigma_q) - k + torch.matmul(mu_q.T,mu_q) + torch.sum(sigma_q))

        mse = []
        h = []
        # TODO: how to retain gradients
        
        # draw samples from the nn (sample nn)
        samples = sample(mu_q, sigma_q, n_samples=2)
        for net_sample in samples:

            # replace the network parameters with the sampled parameters
            vector_to_parameters(net_sample, self.net.parameters())

            self.feature_maps = []

            # predict with the sampled weights
            x_rec = self.net(x.to(self._device))

            # compute mse for sample net
            mse_s = F.mse_loss(x_rec, x)

            # compute hessian for sample net
            h_s = compute_hessian(x, self.feature_maps, self.net, self.output_size)

            # append results
            mse.append(mse_s)
            h.append(h_s)
        
        # pablo do trust me...
        h = torch.stack(h) if len(h) > 1 else h
        self.h = self.constant * h.mean(dim=0) + 1

        # reset the network parameters with the mean parameter (MAP estimate parameters)
        vector_to_parameters(mu_q, self.net.parameters())

        mse = torch.stack(mse) if len(mse) > 1 else mse
        loss = self.constant * mse.mean() + kl.mean()
        self.log('train_loss', loss)

        return loss

    def validation_step(self, val_batch, batch_idx):
        x, y = val_batch
        x = x.view(x.size(0), -1)

        x_rec = self.net(x)
        loss = F.mse_loss(x_rec, x)

        self.log('val_loss', loss)


def test_lae(dataset, batch_size=1):

    # initialize_model
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    path = f"{dataset}/lae"

    latent_size = 2
    encoder = get_encoder(dataset, latent_size).eval().to(device)
    encoder.load_state_dict(torch.load(f"../weights/{path}/encoder.pth"))

    mu_decoder = get_decoder(dataset, latent_size).eval().to(device)
    mu_decoder.load_state_dict(torch.load(f"../weights/{path}/mu_decoder.pth"))

    train_loader, val_loader = get_data(dataset, batch_size)

    # forward eval
    x, z, x_rec_mu, x_rec_sigma, labels = [], [], [], [], []
    for i, (xi, yi) in tqdm(enumerate(val_loader)):
        xi = xi.view(xi.size(0), -1).to(device)
        with torch.inference_mode():
            zi = encoder(xi)
            x_reci = mu_decoder(zi)

            x += [xi.cpu()]
            z += [zi.cpu()]
            x_rec_mu += [x_reci.cpu()]
            labels += [yi]

        # only show the first 50 points
        # if i > 50:
        #    break
    
    x = torch.cat(x, dim=0).numpy()
    labels = torch.cat(labels, dim=0).numpy()
    z = torch.cat(z, dim=0).numpy()
    x_rec_mu = torch.cat(x_rec_mu, dim=0).numpy()
    if use_var_decoder:
        x_rec_sigma = torch.cat(x_rec_sigma, dim=0).numpy()

    if use_var_decoder:
        # Grid for probability map
        n_points_axis = 50
        xg_mesh, yg_mesh, z_grid_loader = generate_latent_grid(
            z[:, 0].min(),
            z[:, 0].max(),
            z[:, 1].min(),
            z[:, 1].max(),
            n_points_axis
        )
        
        all_f_mu, all_f_sigma = [], []
        for z_grid in tqdm(z_grid_loader):
            
            z_grid = z_grid[0].to(device)

            with torch.inference_mode():
                mu_rec_grid = mu_decoder(z_grid)
                log_sigma_rec_grid = softclip(var_decoder(z_grid), min=-6)

            sigma_rec_grid = torch.exp(log_sigma_rec_grid)

            all_f_mu += [mu_rec_grid.cpu()]
            all_f_sigma += [sigma_rec_grid.cpu()]

        f_mu = torch.cat(all_f_mu, dim=0)
        f_sigma = torch.cat(all_f_sigma, dim=0)

        # get diagonal elements
        sigma_vector = f_sigma.mean(axis=1)

    # create figures
    if not os.path.isdir(f"../figures/{path}"): os.makedirs(f"../figures/{path}")

    plt.figure()
    if dataset == "mnist":
        for yi in np.unique(labels):
            idx = labels == yi
            plt.plot(z[idx, 0], z[idx, 1], 'x', ms=5.0, alpha=1.0)
    else:
        plt.plot(z[:, 0], z[:, 1], 'x', ms=5.0, alpha=1.0)

    if use_var_decoder:
        precision_grid = np.reshape(sigma_vector, (n_points_axis, n_points_axis))
        plt.contourf(xg_mesh, yg_mesh, precision_grid, cmap='viridis_r')
        plt.colorbar()

    plt.savefig(f"../figures/{path}/ae_contour.png")
    plt.close(); plt.cla()

    if dataset == "mnist":
        for i in range(min(len(z), 10)):
            nplots = 3 if use_var_decoder else 2

            plt.figure()
            plt.subplot(1,nplots,1)
            plt.imshow(x[i].reshape(28,28))

            plt.subplot(1,nplots,2)
            plt.imshow(x_rec_mu[i].reshape(28,28))

            if use_var_decoder:
                plt.subplot(1,nplots,3)
                plt.imshow(x_rec_sigma[i].reshape(28,28))

            plt.savefig(f"../figures/{path}/ae_recon_{i}.png")
            plt.close(); plt.cla()


def train_lae(dataset = "mnist"):

    # data
    train_loader, val_loader = get_data(dataset, batch_size=32)

    # model
    model = LitLaplaceAutoEncoder(dataset)

    # default logger used by trainer
    logger = TensorBoardLogger(save_dir="../", version=1, name="lightning_logs")

    # early stopping
    callbacks = [EarlyStopping(monitor="val_loss")]

    # training
    n_device = torch.cuda.device_count()

    trainer = pl.Trainer(gpus=n_device, num_nodes=1, logger=logger, callbacks=callbacks)
    trainer.fit(model, train_loader, val_loader)
    
    # save weights
    path = f"{dataset}/lae_elbo"
    if not os.path.isdir(f"../weights/{path}"): os.makedirs(f"../weights/{path}")
    torch.save(model.net.state_dict(), f"../weights/{path}/net.pth")


if __name__ == "__main__":

    dataset = "mnist"
    train = True

    # train or load auto encoder
    if train:
        train_lae(dataset)

    test_lae(dataset)

    