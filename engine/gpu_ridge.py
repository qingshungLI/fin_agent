"""Optional single-device sparse ridge acceleration; same centered ridge objective."""
from contextlib import contextmanager
import os
import numpy as np
from engine.config import ROOT

BATCH_ROWS = 32768


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
    n, columns=train.shape
    gram=cp.zeros((columns,columns),dtype=cp.float64)
    sums=cp.zeros(columns,dtype=cp.float64)
    target_sums=cp.zeros(target.shape[1],dtype=cp.float64)
    rhs=cp.zeros((columns,target.shape[1]),dtype=cp.float64)
    # Bound sparse-product workspace; a full-market X.T @ X may otherwise
    # materialize billions of intermediate products despite its small output.
    for start in range(0,n,BATCH_ROWS):
        x=csr_matrix(train[start:start+BATCH_ROWS].astype(np.float64,copy=False))
        y=cp.asarray(target[start:start+BATCH_ROWS],dtype=cp.float64)
        gram+=(x.T@x).toarray()
        sums+=cp.asarray(x.sum(axis=0)).reshape(-1)
        target_sums+=y.sum(axis=0)
        rhs+=x.T@y
        del x,y
    mean=sums/n
    ymean=target_sums/n
    gram-=n*cp.outer(mean,mean)
    gram=(gram+gram.T)*.5
    gram+=alpha*cp.eye(columns,dtype=cp.float64)
    rhs-=n*mean[:,None]*ymean[None,:]
    coefficients=cp.linalg.solve(gram,rhs)
    intercept=ymean-mean@coefficients
    output=np.empty((test.shape[0],target.shape[1]),dtype=np.float64)
    for start in range(0,test.shape[0],BATCH_ROWS):
        z=csr_matrix(test[start:start+BATCH_ROWS].astype(np.float64,copy=False))
        prediction=z@coefficients+intercept
        if not bool(cp.isfinite(prediction).all()):
            raise ArithmeticError("Non-finite CUDA ridge prediction")
        output[start:start+BATCH_ROWS]=cp.asnumpy(prediction)
        del z,prediction
    print(f"CUDA ridge: device=0 pid={os.getpid()} train_rows={n} columns={columns}",flush=True)
    return output


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
