import torch

from torch.utils.data import Dataset
from .ml1m import RawMovieLens1M
from .schemas import SeqBatch

PROCESSED_MOVIE_LENS_SUFFIX = "/processed/data.pt"


class MovieLensMovieData(Dataset):
    def __init__(
        self,
        root: str,
        *args,
        **kwargs
    ) -> None:

        raw_movie_lens = RawMovieLens1M(root=root, *args, **kwargs)
        raw_movie_lens.process()

        data = torch.load(root + PROCESSED_MOVIE_LENS_SUFFIX)
        self.movie_data = data[0]["movie"]["x"]

    def __len__(self):
        return self.movie_data.shape[0]

    def __getitem__(self, idx):
        return self.movie_data[idx, :]


class MovieLensSeqData(Dataset):
    def __init__(
            self,
            root: str,
            *args,
            **kwargs
    ) -> None:

        raw_movie_lens = RawMovieLens1M(root=root, *args, **kwargs)
        raw_movie_lens.process()
  
        data = torch.load(root + PROCESSED_MOVIE_LENS_SUFFIX)
        self.sequence_data = data[0][("user", "rated", "movie")]["history"]
        self.movie_data = data[0]["movie"]["x"]

    def __len__(self):
        return self.sequence_data.shape[0]
  
    def __getitem__(self, idx):
        user_ids = self.sequence_data[idx, 0]
        movie_ids = self.sequence_data[idx, 1:] - 1
        assert movie_ids >= -1, "Invalid movie id found"
        return SeqBatch(
            user_ids=user_ids,
            ids=movie_ids,
            x=self.movie_data[movie_ids, :],
            seq_mask=(movie_ids >= 0)
        )


if __name__ == "__main__":
    dataset = MovieLensSeqData("dataset/ml-1m")
