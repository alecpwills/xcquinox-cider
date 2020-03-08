#from mldftdat.gp import DFTGP
from mldftdat.data import get_unique_coord_indexes_spherical
from mldftdat.density import get_exchange_descriptors
from mldftdat.lowmem_analyzers import RHFAnalyzer
from mldftdat.workflow_utils import get_save_dir
from setup_fireworks import SAVE_ROOT
from sklearn.model_selection import train_test_split
import numpy as np 
import os
import time

CALC_TYPE = 'RKS'
FUNCTIONAL = 'LDA_VWN'
MOL_IDS = ['atoms/{}-0'.format(s) for s in ['2-He', '10-Ne', '18-Ar', '36-Kr']]
BASIS = 'cc-pcvtz'

all_descriptor_data = None
all_values = []

for MOL_ID in MOL_IDS:
    print('Working on {}'.format(MOL_ID))
    data_dir = get_save_dir(SAVE_ROOT, CALC_TYPE, BASIS, MOL_ID, FUNCTIONAL)
    start = time.monotonic()
    analyzer = RHFAnalyzer.load(data_dir + '/data.hdf5')
    end = time.monotonic()
    print('analyzer load time', end - start)
    start = time.monotonic()
    indexes = get_unique_coord_indexes_spherical(analyzer.grid.coords)
    end = time.monotonic()
    print('index scanning time', end - start)
    start = time.monotonic()
    descriptor_data = get_exchange_descriptors(analyzer.rho_data,
                                               analyzer.tau_data,
                                               analyzer.grid.coords,
                                               analyzer.grid.weights,
                                               restricted = True)
    end = time.monotonic()
    print('get descriptor time', end - start)
    values = analyzer.get_fx_energy_density()[indexes]
    print(np.min(values))
    descriptor_data = descriptor_data[:,indexes]
    print(np.max(descriptor_data[0]))
    print(values.shape, descriptor_data.shape)
    if all_descriptor_data is None:
        all_descriptor_data = descriptor_data
    else:
        all_descriptor_data = np.append(all_descriptor_data, descriptor_data,
                                        axis = 1)
    all_values = np.append(all_values, values)

print(all_descriptor_data.shape, all_values.shape)
save_dir = os.path.join(SAVE_ROOT, 'DATASETS')
desc_file = os.path.join(save_dir, 'noblex2_rho_data.npz')
fx_file = os.path.join(save_dir, 'noblex2_fx.npz')
np.savetxt(desc_file, all_descriptor_data)
np.savetxt(fx_file, all_values)
#gp = DFTGP(descriptor_data, values, 1e-3)
