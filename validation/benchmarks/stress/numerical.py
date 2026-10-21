"""Seeded bounded numerical stress; analytical oracles, no patient data."""
import json
import time
import numpy as np
from openrad.validation.physics_rules import PhysicsValidationEngine, PhysicsValidationError
from openrad.tools.gamma_tool import evaluate_gamma_index
from openrad.tools.radiobio_tool import calculate_tcp_ntcp
from validation.paths import new_run_directory


def main():
    out=new_run_directory('numerical-stress');out.mkdir(parents=True)
    rng=np.random.default_rng(20261021);start=time.monotonic();count=0
    for i in range(1000):
        values=rng.uniform(0,100,size=(2,3,4));valid=i%5==0
        if not valid:values[0,0,0]=[-1e-12,-1,float('nan'),float('inf')][i%5-1]
        try:
            PhysicsValidationEngine.validate_dose_grid(values,raise_on_fail=True)
            assert valid
        except PhysicsValidationError:assert not valid
        count+=1
    for i in range(200):
        dose=float(rng.uniform(.1,200))
        for model,parameters,key in [('LKB',{'TD50':dose,'m':.2,'n':1},'NTCP'),('Poisson_LQ',{'TCD50':dose,'gamma50':2},'TCP')]:
            result=calculate_tcp_ntcp({'dose_bins_Gy':[dose,dose+1],'volume_percent':[100,0]},model,parameters,dvh_type='differential')
            assert abs(result[key]-.5)<1e-10
            count+=1
    ref=out/'reference.npy';ev=out/'evaluated.npy'
    np.save(ref,np.ones((2,3,4)))
    for i in range(50):
        offset=float(rng.uniform(0,.09));np.save(ev,np.full((2,3,4),1+offset))
        result=evaluate_gamma_index(str(ref),str(ev),reference_spacing_mm=[1,2,3],evaluated_spacing_mm=[1,2,3])
        assert result['passing_rate']==(100 if offset<=.03 else 0)
        count+=1
    result={'seed':20261021,'assertions_passed':count,'dose_integrity_cases':1000,'radiobiology_endpoint_oracles':400,
        'gamma_uniform_field_oracles':50,'seconds':round(time.monotonic()-start,2),'clinical_release':False}
    (out/'assessment.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));print(out)

if __name__=='__main__':main()
