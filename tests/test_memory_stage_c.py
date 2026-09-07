import numpy as np
import pandas as pd
import pytest
from engine.memory import build_design_matrix, interaction_contrasts

@pytest.mark.parametrize("missing", [[], [(0,0)], [(0,0),(1,1),(2,2)], [(0,1),(0,2),(1,0),(1,2),(2,0),(2,1)]])
def test_stage_c_uses_only_estimable_interactions(missing):
    rows=[{"family":f"M{f}", "form":str(v), "period":str(p), "structure":f"{f}-{v}-{rep}"}
          for f in range(3) for v in range(3) if (f,v) not in missing
          for rep in range(4) for p in range(4)]
    frame=pd.DataFrame(rows)
    basis,names,codes=interaction_contrasts(frame)
    cells=frame[["family","form"]].astype(str).drop_duplicates().sort_values(["family","form"])
    main=np.column_stack([np.ones(len(cells)),pd.get_dummies(cells,drop_first=True,dtype=float)])
    np.testing.assert_allclose(main.T@basis,0,atol=1e-12)
    np.testing.assert_allclose(basis.T@basis,np.eye(basis.shape[1]),atol=1e-12)
    assert len(names)==len(cells)
    assert (codes>=0).all()
    # Disconnected family/form designs remain unidentified, not padded with invented cells.
    design,_=build_design_matrix(frame,"C")
    connected=not (len(missing)==6)
    if connected: assert np.linalg.matrix_rank(design)==design.shape[1]
    else: assert np.linalg.matrix_rank(design)<design.shape[1]
    shuffled=frame.sample(frac=1,random_state=3)
    b2,n2,_=interaction_contrasts(shuffled)
    assert n2==names
    np.testing.assert_allclose(basis@basis.T,b2@b2.T,atol=1e-12)
