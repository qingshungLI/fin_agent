"""Optional single-device sparse ridge acceleration; same centered ridge objective."""
from contextlib import contextmanager
from pathlib import Path
import os
import numpy as np
from engine.config import ROOT


@contextmanager
def gpu_lease():
    import fcntl
    directory=ROOT/"artifacts"
    directory.mkdir(parents=True,exist_ok=True)
    with (directory/".gpu-ridge.lock").open("a+b") as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle,fcntl.LOCK_UN)


def _predict(train, target, test, alpha):
    import cupy as cp
    from cupyx.scipy.sparse import csr_matrix
    if cp.cuda.runtime.getDeviceCount()!=1:
        raise RuntimeError("CUDA ridge requires exactly one visible GPU")
    x=csr_matrix(train.astype(np.float64,copy=False))
    z=csr_matrix(test.astype(np.float64,copy=False))
    y=cp.asarray(target,dtype=cp.float64)
    n=x.shape[0]
    mean=cp.asarray(x.mean(axis=0)).reshape(-1)
    ymean=y.mean(axis=0)
    gram=(x.T@x).toarray()-n*cp.outer(mean,mean)
    gram=(gram+gram.T)*.5
    gram+=alpha*cp.eye(gram.shape[0],dtype=cp.float64)
    rhs=x.T@y-n*mean[:,None]*ymean[None,:]
    coefficients=cp.linalg.solve(gram,rhs)
    prediction=z@coefficients+(ymean-mean@coefficients)
    if not bool(cp.isfinite(prediction).all()):
        raise ArithmeticError("Non-finite CUDA ridge prediction")
    print(f"CUDA ridge: device=0 pid={os.getpid()} train_rows={n} columns={x.shape[1]}",flush=True)
    return cp.asnumpy(prediction)


def ridge_predict(train,target,test,alpha=1.):
    if alpha<=0:
        raise ValueError("Ridge regularization must be positive")
    with gpu_lease():
        import cupy as cp
        try:
            return _predict(train,target,test,alpha)
        finally:
            cp.cuda.get_current_stream().synchronize()
            cp.get_default_memory_pool().free_all_blocks()
