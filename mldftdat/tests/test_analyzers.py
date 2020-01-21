from pyscf import scf, gto
from nose import SkipTest
from nose.tools import nottest
from nose.plugins.skip import Skip
from numpy.testing import assert_almost_equal, assert_equal

from mldftdat.pyscf_utils import get_hf_coul_ex_total, get_hf_coul_ex_total_unrestricted,\
                                run_scf, run_cc, integrate_on_grid, get_ccsd_ee_total,\
                                transform_basis_2e, transform_basis_1e
from mldftdat.analyzers import RHFAnalyzer, UHFAnalyzer, CCSDAnalyzer, UCCSDAnalyzer
import numpy as np

class TestRHFAnalyzer():

    @classmethod
    def setup_class(cls):
        cls.mol = gto.Mole(atom='H 0 0 0; F 0 0 1.1', basis = '631g')
        cls.mol.build()
        cls.rhf = run_scf(cls.mol, 'RHF')
        cls.analyzer = RHFAnalyzer(cls.rhf)
        cls.ha_tot_ref, cls.fx_tot_ref = get_hf_coul_ex_total(cls.mol, cls.rhf)

    def test_post_process(self):
        # This is tested in the rest of the module
        assert_almost_equal(self.ha_tot_ref + self.fx_tot_ref, self.mol.energy_elec()[1])

    def test_get_ha_energy_density(self):
        ha_density = self.analyzer.get_ha_energy_density()
        ha_tot = integrate_on_grid(ha_density, self.analyzer.grid.weights)
        assert_almost_equal(ha_tot, self.ha_tot_ref, 5)

    def test_get_fx_energy_density(self):
        fx_density = self.analyzer.get_fx_energy_density()
        fx_tot = integrate_on_grid(fx_density, self.analyzer.grid.weights)
        assert_almost_equal(fx_tot, self.fx_tot_ref, 5)

    def test_get_ee_energy_density(self):
        ee_density = self.analyzer.get_ee_energy_density()
        ee_tot = integrate_on_grid(ee_density, self.analyzer.grid.weights)
        assert_almost_equal(ee_tot, self.mol.energy_elec()[1], 5)

    def test__get_rdm2(self):
        # Tested by next test
        pass

    def test__get_ee_energy_density_slow(self):
        ee_density = self.analyzer._get_ee_energy_density_slow()
        ee_tot = integrate_on_grid(ee_density, self.analyzer.grid.weights)
        assert_almost_equal(ee_tot, self.mol.energy_elec()[1], 5)


class TestUHFAnalyzer():

    @classmethod
    def setup_class(cls):
        cls.mol = gto.Mole(atom='N 0 0 0; O 0 0 1.15', basis = '631g', spin = 1)
        cls.mol.build()
        cls.uhf = run_scf(cls.mol, 'UHF')
        cls.analyzer = UHFAnalyzer(cls.uhf)
        cls.ha_tot_ref, cls.fx_tot_ref = get_hf_coul_ex_total_unrestricted(cls.mol, cls.uhf)

    def test_post_process(self):
        # This is tested in the rest of the module
        assert_almost_equal(self.ha_tot_ref + self.fx_tot_ref, self.mol.energy_elec()[1])

    def test_get_ha_energy_density(self):
        ha_density = self.analyzer.get_ha_energy_density()
        ha_tot = integrate_on_grid(ha_density, self.analyzer.grid.weights)
        assert_almost_equal(ha_tot, self.ha_tot_ref, 5)

    def test_get_fx_energy_density(self):
        fx_density = self.analyzer.get_fx_energy_density()
        fx_tot = integrate_on_grid(fx_density, self.analyzer.grid.weights)
        assert_almost_equal(fx_tot, self.fx_tot_ref, 5)

    def test_get_ee_energy_density(self):
        ee_density = self.analyzer.get_ee_energy_density()
        ee_tot = integrate_on_grid(ee_density, self.analyzer.grid.weights)
        assert_almost_equal(ee_tot, self.mol.energy_elec()[1], 5)

    def test__get_rdm2(self):
        # Tested by next test
        pass

    def test__get_ee_energy_density_slow(self):
        ee_density = self.analyzer._get_ee_energy_density_slow()
        ee_tot = integrate_on_grid(ee_density, self.analyzer.grid.weights)
        assert_almost_equal(ee_tot, self.mol.energy_elec()[1], 5)


class TestCCSDAnalyzer():

    @classmethod
    def setup_class(cls):
        cls.mol = gto.Mole(atom='He 0 0 0', basis = 'cc-pvdz')
        cls.mol.build()
        cls.hf = run_scf(cls.mol, 'RHF')
        cls.cc = run_cc(cls.hf)
        cls.analyzer = CCSDAnalyzer(cls.cc)
        cls.ee_tot_ref = get_ccsd_ee_total(cls.mol, cls.cc, cls.hf)

    def test_post_process(self):
        pass

    def test_get_ha_energy_density(self):
        eri = self.mol.intor('int2e')
        eri = transform_basis_2e(eri, self.hf.mo_coeff)
        rdm1 = self.cc.make_rdm1()
        ha_tot_ref = np.sum(np.sum(eri * rdm1, axis=(2,3)) * rdm1) / 2
        ha_density = self.analyzer.get_ha_energy_density()
        ha_tot = integrate_on_grid(ha_density, self.analyzer.grid.weights)
        assert_almost_equal(ha_tot, ha_tot_ref, 5)

    def test_get_ee_energy_density(self):
        ee_density = self.analyzer.get_ee_energy_density()
        ee_tot = integrate_on_grid(ee_density, self.analyzer.grid.weights)
        assert_almost_equal(ee_tot, self.ee_tot_ref)
        # ee repulsion should be similar to HF case
        # Note this case may not pass for all systems, but hsould pass for He and Li
        assert_almost_equal(ee_tot, self.hf.energy_elec()[1], 1)


class TestUCCSDAnalyzer():

    @classmethod
    def setup_class(cls):
        cls.mol = gto.Mole(atom='Li 0 0 0', basis = 'cc-pvdz', spin=1)
        cls.mol.build()
        cls.hf = run_scf(cls.mol, 'UHF')
        cls.cc = run_cc(cls.hf)
        cls.analyzer = UCCSDAnalyzer(cls.cc)
        cls.ee_tot_ref = get_ccsd_ee_total(cls.mol, cls.cc, cls.hf)

    def test_post_process(self):
        pass

    def test_get_ha_energy_density(self):
        eri = self.mol.intor('int2e')
        rdm1 = self.cc.make_rdm1()
        rdm1 = transform_basis_1e(rdm1, np.transpose(self.hf.mo_coeff, axes=(0,2,1)))
        rdm1 = np.sum(rdm1, axis=0)
        ha_tot_ref = np.sum(np.sum(eri * rdm1, axis=(2,3)) * rdm1) / 2
        ha_density = self.analyzer.get_ha_energy_density()
        ha_tot = integrate_on_grid(ha_density, self.analyzer.grid.weights)
        assert_almost_equal(ha_tot, ha_tot_ref)

    def test_get_ee_energy_density(self):
        ee_density = self.analyzer.get_ee_energy_density()
        ee_tot = integrate_on_grid(ee_density, self.analyzer.grid.weights)
        assert_almost_equal(ee_tot, self.ee_tot_ref)
        # ee repulsion should be similar to HF case
        # Note this case may not pass for all systems, but hsould pass for He and Li
        assert_almost_equal(ee_tot, self.hf.energy_elec()[1], 1)