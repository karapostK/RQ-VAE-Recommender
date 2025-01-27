from modules.encoder import MLP
from modules.normalize import RMSNorm
from modules.transformer.attention import AttentionInput
from modules.transformer.attention import MultiHeadAttention
from typing import List
from typing import Optional
from torch import nn
from torch import Tensor


class TransformerBlock(nn.Module):
    def __init__(
        self,
        d_in: int,
        d_out: int,
        dropout: float,
        num_heads: int,
        qkv_bias: bool,
        mlp_hidden_dims: List[int] = [1024],
        do_cross_attn: bool = False
    ) -> None:
        super().__init__()
        
        self.d_in = d_in
        self.d_out = d_out
        self.dropout = dropout
        self.num_heads = num_heads
        self.qkv_bias = qkv_bias
        self.do_cross_attn = do_cross_attn

        self.attention = MultiHeadAttention(
            d_in=d_in, d_out=d_out, num_heads=num_heads, cross_attn=False, dropout=dropout, qkv_bias=qkv_bias
        )

        self.ff = MLP(
            input_dim=d_out,
            hidden_dims=mlp_hidden_dims,
            out_dim=d_out,
            normalize=False
        )

        self.attn_norm = RMSNorm(d_out)
        self.ffn_norm = RMSNorm(d_out)

        if self.do_cross_attn:
            self.cross_attention = MultiHeadAttention(
                d_in=d_out, d_out=d_out, num_heads=num_heads, cross_attn=True, dropout=dropout, qkv_bias=qkv_bias
            )
            self.cross_attn_norm = RMSNorm(d_out)
    
    def forward(
        self,
        x: AttentionInput,
        x_kv: Optional[Tensor] = None,
        padding_mask: Optional[Tensor] = None,
        attn_mask: Optional[Tensor] = None,
        jagged: Optional[bool] = False
    ) -> AttentionInput:
        attn_out = self.attn_norm(x + self.attention(x, padding_mask=padding_mask, attn_mask=attn_mask, jagged=jagged, use_cache=not self.training))
        if self.do_cross_attn:
            attn_out = self.cross_attn_norm(
                attn_out +
                self.cross_attention(
                    x_q=attn_out, x_kv=x_kv, padding_mask=padding_mask, attn_mask=attn_mask, jagged=jagged, use_cache=not self.training
                )
            )
        proj_out = self.ffn_norm(attn_out + self.ff(attn_out))
        return proj_out
    
    def reset_kv_cache(self):
        self.attention.kv_cache.reset()
        if self.do_cross_attn:
            self.cross_attention.kv_cache.reset()

    def apply_to_kv_cache(self, fn):
        self.attention.kv_cache.apply(fn)
        if self.do_cross_attn:
            self.cross_attention.kv_cache.apply(fn)


class TransformerDecoder(nn.Module):
    def __init__(
        self,
        d_in: int,
        d_out: int,
        dropout: float,
        num_heads: int,
        n_layers: int,
        do_cross_attn: bool = False
    ) -> None:
        super().__init__()

        self.do_cross_attn = do_cross_attn

        self.layers = nn.ModuleList([
            TransformerBlock(
                d_in=d_in,
                d_out=d_out,
                dropout=dropout,
                num_heads=num_heads,
                qkv_bias=False,
                do_cross_attn=self.do_cross_attn
            ) for _ in range(n_layers)
        ])

    def forward(
        self,
        x: AttentionInput,
        padding_mask: Optional[Tensor] = None,
        attn_mask: Optional[Tensor] = None,
        context: Optional[Tensor] = None,
        jagged: Optional[bool] = None
    ) -> AttentionInput:
        for layer in self.layers:
            x = layer(x=x, x_kv=context, padding_mask=padding_mask, attn_mask=attn_mask, jagged=jagged)
        return x
    
    @property
    def seq_lengths(self) -> Tensor:
        return self.layers[0].attention.kv_cache.seq_lengths
    
    def reset_kv_cache(self) -> None:
        for layer in self.layers:
            layer.reset_kv_cache()
    
    def apply_to_kv_cache(self, fn) -> None:
        for layer in self.layers:
            layer.apply_to_kv_cache(fn)
