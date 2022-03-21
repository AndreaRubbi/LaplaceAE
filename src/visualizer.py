import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from matplotlib.patches import Ellipse
import black


def plot_latent_space(
    path,
    z,
    labels=None,
    xg_mesh=None,
    yg_mesh=None,
    sigma_vector=None,
    n_points_axis=None,
):
    plt.figure()
    if labels is not None:
        for yi in np.unique(labels):
            idx = labels == yi
            plt.plot(z[idx, 0], z[idx, 1], "x", ms=5.0, alpha=1.0)
    else:
        plt.plot(z[:, 0], z[:, 1], "x", ms=5.0, alpha=1.0)

    if sigma_vector is not None:
        precision_grid = np.reshape(sigma_vector, (n_points_axis, n_points_axis))
        plt.contourf(xg_mesh, yg_mesh, precision_grid, cmap="viridis_r")
        plt.colorbar()

    plt.savefig(f"../figures/{path}/ae_contour.png")
    plt.close()
    plt.cla()


def plot_mnist_reconstructions(path, x, x_rec_mu, x_rec_sigma=None, pre_fix=""):

    for i in range(min(len(x), 10)):
        nplots = 3 if x_rec_sigma is not None else 2

        plt.figure()
        plt.subplot(1, nplots, 1)
        plt.imshow(x[i].reshape(28, 28))
        plt.axis("off")

        plt.subplot(1, nplots, 2)
        plt.imshow(x_rec_mu[i].reshape(28, 28))
        plt.axis("off")

        if x_rec_sigma is not None:
            plt.subplot(1, nplots, 3)
            plt.imshow(x_rec_sigma[i].reshape(28, 28))
            plt.axis("off")

        plt.tight_layout()
        plt.savefig(f"../figures/{path}/{pre_fix}recon_{i}.png")
        plt.close()
        plt.cla()


def plot_latent_space_ood(
    path, z_mu, z_sigma, labels, ood_z_mu, ood_z_sigma, ood_labels
):

    max_ = np.max([np.max(z_sigma), np.max(ood_z_sigma)])
    min_ = np.min([np.min(z_sigma), np.min(ood_z_sigma)])

    # normalize sigma
    z_sigma = ((z_sigma - min_) / (max_ - min_)) * 1
    ood_z_sigma = ((ood_z_sigma - min_) / (max_ - min_)) * 1

    fig, ax = plt.subplots(1, 1, figsize=(9, 9))
    for i, (z_mu_i, z_sigma_i) in enumerate(zip(z_mu, z_sigma)):

        ax.scatter(z_mu_i[0], z_mu_i[1], color="b")
        ellipse = Ellipse(
            (z_mu_i[0], z_mu_i[1]),
            width=z_sigma_i[0],
            height=z_sigma_i[1],
            fill=False,
            edgecolor="blue",
        )
        ax.add_patch(ellipse)

        if i > 500:
            ax.scatter(z_mu_i[0], z_mu_i[1], color="b", label="ID")
            break

    for i, (z_mu_i, z_sigma_i) in enumerate(zip(ood_z_mu, ood_z_sigma)):

        ax.scatter(z_mu_i[0], z_mu_i[1], color="r")
        ellipse = Ellipse(
            (z_mu_i[0], z_mu_i[1]),
            width=z_sigma_i[0],
            height=z_sigma_i[1],
            fill=False,
            edgecolor="red",
        )
        ax.add_patch(ellipse)

        if i > 500:
            ax.scatter(z_mu_i[0], z_mu_i[1], color="r", label="OOD")
            break

    ax.legend()
    fig.savefig(f"../figures/{path}/ood_latent_space.png")


def plot_ood_distributions(path, z_sigma, ood_z_sigma, x_rec_sigma, ood_x_rec_sigma):

    if z_sigma is not None:
        z_sigma = np.sum(z_sigma, axis=1)
        ood_z_sigma = np.sum(ood_z_sigma, axis=1)
        z = pd.DataFrame(
            np.concatenate([z_sigma[:, None], ood_z_sigma[:, None]], axis=1),
            columns=["id", "ood"],
        )

        fig, ax = plt.subplots(1, 1, figsize=(9, 9))
        for col in ["id", "ood"]:
            sns.kdeplot(z[col], shade=True, label=col)
        plt.legend()
        fig.savefig(f"../figures/{path}/ood_z_sigma_distribution.png")
        plt.cla()
        plt.close()

    if x_rec_sigma is not None:
        x_rec_sigma = np.sum(x_rec_sigma, axis=1)
        ood_x_rec_sigma = np.sum(ood_x_rec_sigma, axis=1)
        x_rec = pd.DataFrame(
            np.concatenate([x_rec_sigma[:, None], ood_x_rec_sigma[:, None]], axis=1),
            columns=["id", "ood"],
        )

        fig, ax = plt.subplots(1, 1, figsize=(9, 9))
        for col in ["id", "ood"]:
            sns.kdeplot(x_rec[col], shade=True, label=col)
        plt.legend()
        fig.savefig(f"../figures/{path}/ood_x_rec_sigma_distribution.png")
        plt.cla()
        plt.close()
