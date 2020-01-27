from fireworks import FiretaskBase, FWAction
from fireworks.utilities.fw_utilities import explicit_serialize
from fireworks.utilities.fw_serializers import recursive_dict
from ase import Atoms
from mldftdat.pyscf_utils import *
import json
import datetime
from datetime import date
from mldftdat.analyzers import RHFAnalyzer, UHFAnalyzer, CCSDAnalyzer, UCCSDAnalyzer, RKSAnalyzer, UKSAnalyzer
import os, psutil, multiprocessing, time

from pyscf import gto, scf, dft, cc, fci


def safe_mem_cap_mb():
    return int(psutil.virtual_memory().available // 4e6)

def time_func(func, *args):
    start_time = time.monotonic()
    res = func(*args)
    finish_time = time.monotonic()
    return res, finish_time - start_time


@explicit_serialize
class SCFCalc(FiretaskBase):

    required_params = ['struct', 'basis', 'calc_type']
    optional_params = ['spin', 'charge', 'max_conv_tol', 'functional']

    DEFAULT_MAX_CONV_TOL = 1e-7

    def run_task(self, fw_spec):
        atoms = Atoms.fromdict(self['struct'])
        kwargs = {}
        if self.get('spin') is not None:
            kwargs['spin'] = self['spin']
        if self.get('charge') is not None:
            kwargs['charge'] = self['charge']
        max_conv_tol = self.get('max_conv_tol') or self.DEFAULT_MAX_CONV_TOL
        mol = mol_from_ase(atoms, self['basis'], **kwargs)
        calc_type = self['calc_type']

        start_time = time.monotonic()
        calc = run_scf(mol, calc_type, self.get('functional'))
        stop_time = time.monotonic()

        max_iter = 50 # extra safety catch
        iter_step = 0
        while not calc.converged and calc.conv_tol < max_conv_tol\
                and iter_step < max_iter:
            iter_step += 1
            print ("Did not converge SCF, increasing conv_tol.")
            calc.conv_tol *= 10

            start_time = time.monotonic()
            calc.kernel()
            stop_time = time.monotonic()

        assert calc.converged, "SCF calculation did not converge!"
        update_spec={
            'calc'      : calc,
            'calc_type' : calc_type,
            'conv_tol'  : calc.conv_tol,
            'cpu_count' : multiprocessing.cpu_count(),
            'mol'       : mol,
            'struct'    : atoms,
            'wall_time' : stop_time - start_time
        }
        if 'KS' in calc_type:
            functional = self.get('functional')
            if functional is None:
                update_spec['functional'] = 'LDA_VWN'
            else:
                functional = functional.replace(',', '_')
                functional = functional.replace(' ', '_')
                functional = functional.upper()
                update_spec['functional'] = functional

        return FWAction(update_spec = update_spec)


# old name so that Fireworks can be rerun
@explicit_serialize
class HFCalc(SCFCalc):
    pass

        
@explicit_serialize
class CCSDCalc(FiretaskBase):

    optional_params = ['max_conv_tol']

    DEFAULT_MAX_CONV_TOL = 1e-5

    def run_task(self, fw_spec):
        mol = fw_spec['mol']
        hfcalc = fw_spec['calc']

        start_time = time.monotonic()
        calc = run_cc(hfcalc)
        stop_time = time.monotonic()

        max_iter = 50 # extra safety catch
        iter_step = 0
        max_conv_tol = self.get('max_conv_tol') or self.DEFAULT_MAX_CONV_TOL
        while not calc.converged and calc.conv_tol < max_conv_tol\
                and iter_step < max_iter:
            iter_step += 1
            print ("Did not converge CCSD, increasing conv_tol.")
            calc.conv_tol *= 10

            start_time = time.monotonic()
            calc.kernel()
            stop_time = time.monotonic()

        assert calc.converged, "CCSD calculation did not converge!"
        calc_type = 'CCSD' if type(calc) == cc.ccsd.CCSD else 'UCCSD'
        return FWAction(update_spec={
                'calc'      : calc,
                'calc_type' : calc_type,
                'conv_tol'  : calc.conv_tol,
                'cpu_count' : multiprocessing.cpu_count(),
                'hfcalc'    : hfcalc,
                'wall_time' : stop_time - start_time
            })


@explicit_serialize
class TrainingDataCollector(FiretaskBase):

    required_params = ['save_root_dir', 'mol_id']
    optional_params = ['no_overwrite']
    implemented_calcs = ['RHF', 'UHF', 'RKS', 'UKS', 'CCSD', 'UCCSD']

    def run_task(self, fw_spec):

        calc = fw_spec['calc']
        assert calc.converged, "This training data is not converged!"
        calc_type = fw_spec['calc_type']
        mol = fw_spec['mol']
        struct = fw_spec['struct']
        mol_dat = {
            'calc_type'  : calc_type,
            'charge'     : mol.charge,
            'conv_tol'   : calc.conv_tol,
            'cpu_count'  : fw_spec['cpu_count'],
            'e_tot'      : calc.e_tot,
            'functional' : fw_spec.get('functional')
            'max_cycle'  : calc.max_cycle,
            'nelectron'  : mol.nelectron,
            'spin'       : mol.spin,
            'struct'     : struct.todict(),
            'task_run'   : str(datetime.datetime.now()),
            'wall_time'  : fw_spec['wall_time']
        }

        if type(calc) == scf.hf.RHF:
            Analyzer = RHFAnalyzer
        elif type(calc) == dft.rks.RKS:
            Analyzer = RKSAnalyzer
        elif type(calc) == scf.uhf.UHF:
            Analyzer = UHFAnalyzer
        elif type(calc) == dft.uks.UKS:
            Analyzer = UKSAnalyzer
        elif type(calc) == cc.ccsd.CCSD:
            Analyzer = CCSDAnalyzer
        elif type(calc) == cc.uccsd.UCCSD:
            Analyzer = UCCSDAnalyzer
        else:
            raise NotImplementedError(
                'Training data collection not supported for {}'.format(type(calc)))

        if self.get('no_overwrite'):
            exist_ok = False
        else:
            exist_ok = True
        if fw_spec.get('functional') is not None:
            calc_type = calc_type + '/' + fw_spec['functional']
        save_dir = os.path.join(self['save_root_dir'], calc_type,
                                mol.basis, self['mol_id'])
        os.makedirs(save_dir, exist_ok=exist_ok)

        info_file = os.path.join(save_dir, 'run_info.json')
        f = open(info_file, 'w')
        json.dump(recursive_dict(mol_dat), f, indent=4, sort_keys=True)
        f.close()

        analyzer = Analyzer(calc, max_mem=safe_mem_cap_mb())
        analyzer.perform_full_analysis()
        analyzer.dump(os.path.join(save_dir, 'data.hdf5'))

        return FWAction(stored_data={'save_dir': save_dir})
