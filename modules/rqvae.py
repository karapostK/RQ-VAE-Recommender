import torch

from torch import nn
from typing import List
from typing import NamedTuple

from data.schemas import SeqBatch
from einops import rearrange
from .encoder import MLP
from .loss import CategoricalReconstuctionLoss
from .loss import ReconstructionLoss
from .loss import RqVaeLoss
from .quantize import Quantize
from .quantize import QuantizeForwardMode


class RqVaeOutput(NamedTuple):
    embeddings: torch.Tensor
    residuals: torch.Tensor
    sem_ids: torch.Tensor


class RqVaeComputedLosses(NamedTuple):
    loss: torch.Tensor
    reconstruction_loss: torch.Tensor
    rqvae_loss: torch.Tensor


class RqVae(nn.Module):
    def __init__(
        self,
        input_dim: int,
        embed_dim: int,
        hidden_dims: List[int],
        codebook_size: int,
        codebook_kmeans_init: bool = True,
        codebook_normalize: bool = True,
        n_layers: int = 3,
        commitment_weight: float = 0.25,
        n_cat_features: int = 18,
    ) -> None:
        super().__init__()

        self.input_dim = input_dim
        self.embed_dim = embed_dim
        self.hidden_dims = hidden_dims
        self.n_layers = n_layers
        self.codebook_size = codebook_size
        self.commitment_weight = commitment_weight

        self.layers = nn.ModuleList(modules=[
            Quantize(
                embed_dim=embed_dim,
                n_embed=codebook_size,
                forward_mode=QuantizeForwardMode.ROTATION_TRICK,
                do_kmeans_init=codebook_kmeans_init,
                codebook_normalize=codebook_normalize
            ) for _ in range(n_layers)
        ])

        self.encoder = MLP(
            input_dim=input_dim,
            hidden_dims=hidden_dims,
            out_dim=embed_dim,
            normalize=codebook_normalize
        )

        self.decoder = MLP(
            input_dim=embed_dim,
            hidden_dims=hidden_dims[-1::-1],
            out_dim=input_dim
        )

        self.reconstruction_loss = (
            CategoricalReconstuctionLoss(n_cat_features) if n_cat_features != 0
            else ReconstructionLoss()
        )
        self.rqvae_loss = RqVaeLoss(self.commitment_weight)
    
    @property
    def device(self) -> torch.device:
        return next(self.encoder.parameters()).device
    
    def load_pretrained(self, path: str) -> None:
        state = torch.load(path, map_location=self.device)
        self.load_state_dict(state["model"])

    def encode(self, x: torch.Tensor) -> torch.Tensor:
        return self.encoder(x)

    def decode(self, x: torch.Tensor) -> torch.Tensor:
        return self.decoder(x)

    def get_semantic_ids(self,
                         x: torch.Tensor,
                         gumbel_t: float = 0.001) -> RqVaeOutput:
        res = self.encode(x)
        embs, residuals, sem_ids = [], [], []

        for layer in self.layers:
            residuals.append(res)
            quantized = layer(res, temperature=gumbel_t)
            emb, id = quantized.embeddings, quantized.ids
            res = res - emb.detach()
            sem_ids.append(id)
            embs.append(emb)

        return RqVaeOutput(
            embeddings=rearrange(embs, "b h d -> h d b"),
            residuals=rearrange(residuals, "b h d -> h d b"),
            sem_ids=rearrange(sem_ids, "b d -> d b")
        )

    def forward(self, batch: SeqBatch, gumbel_t: float) -> RqVaeComputedLosses:
        x = batch.x
        quantized = self.get_semantic_ids(x, gumbel_t)
        embs, residuals = quantized.embeddings, quantized.residuals
        x_hat = self.decode(embs.sum(axis=-1))

        reconstuction_loss = self.reconstruction_loss(x_hat, x)
        rqvae_loss = self.rqvae_loss(residuals, embs)
        loss = (reconstuction_loss + 3*rqvae_loss).mean()

        return RqVaeComputedLosses(
            loss=loss,
            reconstruction_loss=reconstuction_loss.mean(),
            rqvae_loss=rqvae_loss.mean()
        )
