from functools import lru_cache
from typing import Optional, TypedDict, TypeVar

from pachyderm_sdk import Client
from pachyderm_sdk.api import pfs
from torch.utils.data import MapDataPipe, functional_datapipe
from torch.utils.data.datapipes.utils.common import StreamWrapper

T_co = TypeVar('T_co', covariant=True)


class PfsData(TypedDict):
    info: pfs.FileInfo
    file: StreamWrapper


class PfsFileDataPipe(MapDataPipe[PfsData]):
    """MapDataPipe implementation for accessing files stored in PFS.

    This indexes the files of a pfs.Commit at initialization and then
      downloads and serves them at time of access (__getitem__).

    If a previous_commit is specified, then this class accesses all _new_
      files added between previous_commit and commit.
    """

    def __init__(
        self,
        client: Client,
        commit: pfs.Commit,
        path="/",
        previous_commit: Optional[pfs.Commit] = None
    ):
        self.client = client
        self.root_file = pfs.File(commit=commit, path=path)
        self.previous_commit = previous_commit

        # Collect a list of all files that will be "piped".
        # Notes:
        #   * This may cause memory issues when indexing >1,000,000 files.
        #   * The memory efficiency of this could be improved by only storing the
        #     URI string of the file, at the cost of requiring an additional
        #     InspectFile call to re-retrieve the FileInfo object at time of access.
        #   * We could take this to the extreme and use pagination to have make the
        #     memory footprint negligible, at the cost of (on average) many network
        #     calls at time of access and making the implementation of this class
        #     significantly more complicated.
        self._file_infos = []
        if previous_commit is not None:
            previous_root_file = pfs.File(commit=self.previous_commit, path=path)
            for diff in client.pfs.diff_file(
                    new_file=self.root_file, old_file=previous_root_file
            ):
                if diff.new_file.file_type == pfs.FileType.FILE:
                    self._file_infos.append(diff.new_file)
        else:
            for info in client.pfs.walk_file(file=self.root_file):
                if info.file_type == pfs.FileType.FILE:
                    self._file_infos.append(info)

        # If this DataPipe is loaded using a DataLoader with `num_workers` > 0, then
        #   the __getitem__ calls will occur within a multiprocessing worker. This is
        #   problematic since gRPC clients do not interact well with multiprocessing.
        # The workaround is:
        #   1. The following environment variables _must_ be set if `num_workers` > 0:
        #        - GRPC_ENABLE_FORK_SUPPORT=true
        #        - GRPC_POLL_STRATEGY=poll
        #   2. The client must be recreated within the worker process, since gRPC will
        #      close the grpc.Channel when `fork()` is called.
        #      ref: github.com/grpc/grpc/blob/master/doc/fork_support.md
        self.worker_client: Optional[Client] = None

    def __getitem__(self, idx) -> PfsData:
        if self.worker_client is None:
            self.worker_client = Client.from_pachd_address(
                pachd_address=self.client.address,
                auth_token=self.client.auth_token,
            )

        info = self._file_infos[idx]
        file = self.worker_client.pfs.pfs_file(file=info.file)
        return PfsData(info=info, file=StreamWrapper(file))

    def __len__(self):
        return len(self._file_infos)


@functional_datapipe(name="with_cache")
class CacheDataPipe(MapDataPipe[T_co]):

    def __init__(self, source: MapDataPipe[T_co], cache_size: Optional[int] = None):
        self._source = source

        @lru_cache(cache_size)
        def __cached_getitem__(idx):
            return source[idx]
        self.__cached_getitem__ = __cached_getitem__

    def __getitem__(self, idx) -> T_co:
        return self.__cached_getitem__(idx)

    def __len__(self):
        return len(self._source)
