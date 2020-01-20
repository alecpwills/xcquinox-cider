from pyscf import scf, dft, gto, ao2mo, df, lib, fci, cc
from pyscf.dft.numint import eval_ao, eval_rho
from pyscf.dft.gen_grid import Grids
from pyscf.pbc.tools.pyscf_ase import atoms_from_ase
import numpy as np

SCF_TYPES = {
    'RHF': scf.hf.RHF,
    'UHF': scf.uhf.UHF,
    'RKS': dft.RKS,
    'UKS': dft.UKS
}

def mol_from_ase(atoms, basis):
    """
    Get a pyscf gto.Mole object from an ase Atoms object (atoms).
    Assign it the atomic basis set (basis).
    Return the Mole object.
    """
    mol = gto.Mole()
    mol.atom = atoms_from_ase(atoms)
    mol.basis = basis
    mol.build()
    return mol

def run_scf(mol, calc_type):
    """
    Run an SCF calculation on a gto.Mole object (Mole)
    of a given calc_type in SCF_TYPES. Return the calc object.
    """
    if not calc_type in SCF_TYPES:
        raise ValueError('Calculation type must be in {}'.format(list(SCF_TYPES.keys())))
    calc = SCF_TYPES[calc_type](mol)
    calc.kernel()
    return calc

def run_cc(hf):
    """
    Run and return a restricted CCSD calculation on mol,
    with HF molecular orbital coefficients in the RHF object hf.
    """
    print(type(hf))
    if type(hf) == SCF_TYPES['RHF']:
        calc_cls = cc.CCSD
    elif type(hf) == SCF_TYPES['UHF']:
        calc_cls = cc.UCCSD
    else:
        raise NotImplementedError('HF type {} not supported'.format(type(hf)) +\
            '\nSupported Types: {}'.format(SCF_TYPES['RHF'], SCF_TYPES['UHF']))
    calc = calc_cls(hf)
    calc.kernel()
    return calc

def get_cc_rdms(calc, mo_coeff=None):
    """
    Get RDMs of a coupled cluster object calc.
    If mo_coeff is None (default), the RDMs
    are returned in the MO basis set (this is pyscf default).
    If mo_coeff if given, the RDMs are converted to the atomic
    orbital (AO) basis set.
    """
    rdm1 = calc.make_rdm1()
    rdm2 = calc.make_rdm2()
    print(rdm2[0].shape, len(rdm2))
    if mo_coeff is not None:
        if len(mo_coeff.shape) == 2:
            axes = (1,0)
        else:
            axes = (0,2,1)
        mo_coeff_trans = np.transpose(mo_coeff, axes=axes)
        rdm1 = np.matmul(mo_coeff, np.matmul(rdm1, mo_coeff_trans))
        if len(mo_coeff.shape) == 2:
            rdm2 = ao2mo.incore.full(rdm2, mo_coeff_trans)
        else:
            shape = mo_coeff.shape
            new_shape = (shape[0], shape[0], shape[1], shape[1], shape[2], shape[2])
            rdm2 = np.zeros(new_shape)
            for i in range(2):
                for j in range(2):
                    rdm2[i,j,:,:,:,:] = ao2mo.incore.general(rdm2[i,j,:,:,:,:], 
                        [mo_coeff_trans[i], mo_coeff_trans[i],\
                        mo_coeff_trans[j], mo_coeff_trans[j]])
    return rdm1, rdm2

def get_grid(mol):
    """
    Get the real-space grid of a molecule for numerical integration.
    """
    grid = Grids(mol)
    grid.kernel()
    return grid

def get_ha_total(rdm1, eeint):
    return np.sum(np.sum(eeint * rdm1, axis=(2,3)) * rdm1)

def get_hf_coul_ex_total(mol, hf):
    rdm1 = hf.make_rdm1()
    jmat, kmat = scf.hf.get_jk(mol, rdm1)
    return np.sum(jmat * rdm1) / 2, np.sum(kmat * rdm1) / 2

def get_ccsd_ee_total(mol, cccalc, hfcalc):
    rdm2 = cccalc.make_rdm2()
    eeint = mol.intor('int2e', aosym='s1')
    eeint = ao2mo.incore.full(eeint, hfcalc.mo_coeff)
    return np.sum(eeint * rdm2) / 2

integrate_on_grid = np.dot

def make_rdm2_from_rdm1(rdm1, restricted = True):
    """
    For an RHF calculation, return the 2-RDM from
    a given 1-RDM. Given D2(ijkl)=<psi| i+ k+ l j |psi>,
    and D(ij)=<psi| i+ j |psi>, then
    D2(ijkl) = D(ij) * D(kl) - 0.5 * D(lj) * D(ki)
    """
    factor = 0.5 if restricted else 1.0
    rdm1copy = rdm1.copy()
    part1 = np.einsum('ij,kl->ijkl', rdm1, rdm1copy)
    part2 = np.einsum('lj,ki->ijkl', rdm1, rdm1copy)
    return part1 - factor * part2

def get_vele_mat(mol, points):
    auxmol = gto.fakemol_for_charges(points)
    return df.incore.aux_e2(mol, auxmol)

def get_ha_energy_density(mol, rdm1, vele_mat, ao_vals):
    """
    Get the classical Hartree energy density on a real-space grid,
    for a given molecular structure with basis set (mol),
    for a given 1-electron reduced density matrix (rdm1).
    Returns the Hartree energy density.
    """
    if len(rdm1.shape) == 2:
        Vele = np.einsum('ijp,ij->p', vele_mat, rdm1)
    else:
        Vele = np.einsum('ijp,sij->p', vele_mat, rdm1)
    rho = eval_rho(mol, ao_vals, rdm1)
    return 0.5 * Vele * rho

def get_fx_energy_density(mol, rdm1, vele_mat, ao_vals, restricted = True):
    """
    Get the Hartree Fock exchange energy density on a real-space grid,
    for a given molecular structure with basis set (mol),
    for a given atomic orbital (AO) 1-electron reduced density matrix (rdm1).
    Returns the exchange energy density, which is negative.
    """
    if len(rdm1.shape) == 2:
        Vele = 0.5 * np.einsum('jip,ij->p', vele_mat, rdm1)
    else:
        Vele = np.einsum('jip,sij->sp', vele_mat, rdm1)
    rho = eval_rho(mol, ao_vals, rdm1)
    return -0.5 * Vele * rho

def get_ee_energy_density(mol, rdm2, vele_mat, ao_vals):
    """
    Get the electron-electron repulsion energy density for a system and basis set (mol),
    for a given molecular structure with basis set (mol).
    Returns the electron-electron repulsion energy.
    """
    #mu,nu,lambda,sigma->i,j,k,l; r->p
    vele_mat = np.ascontiguousarray(np.transpose(vele_mat, axes=(2,0,1)))
    Vele_tmp = np.einsum('ijkl,pkl->pij', rdm2, vele_mat)
    tmp = np.einsum('pij,pj->pi', Vele_tmp, ao_vals)
    Vele = np.einsum('pi,pi->p', tmp, ao_vals)
    return 0.5 * Vele
