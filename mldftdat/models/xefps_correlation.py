from mldftdat.lowmem_analyzers import RHFAnalyzer, UHFAnalyzer, CCSDAnalyzer, UCCSDAnalyzer
from mldftdat.dft.numint5 import _eval_x_0, setup_aux
from mldftdat.dft.numint6 import _eval_xc_0
from pyscf.dft.libxc import eval_xc
from mldftdat.dft.correlation import *
from mldftdat.workflow_utils import get_save_dir, SAVE_ROOT
from sklearn.linear_model import LinearRegression
from pyscf.dft.numint import NumInt
from mldftdat.density import get_exchange_descriptors2
import os
import numpy as np
import yaml
import logging

LDA_FACTOR = - 3.0 / 4.0 * (3.0 / np.pi)**(1.0/3)

DEFAULT_FUNCTIONAL = 'PBE'
DEFAULT_BASIS = 'def2-qzvppd'

CF = 0.3 * (6 * np.pi**2)**(2.0/3)

def default_desc_getter(rhou, rhod, g2u, g2o, g2d, tu, td, exu, exd):
    rhot = rhou + rhod
    g2 = g2u + 2* g2o + g2d
    exo = exu + exd

    ldaxu = 2**(1.0/3) * LDA_FACTOR * rhou**(4.0/3) - 1e-20
    ldaxd = 2**(1.0/3) * LDA_FACTOR * rhod**(4.0/3) - 1e-20
    ldaxt = ldaxu + ldaxd

    gamma = 2**(2./3) * 0.004
    gammass = 0.004
    chi = corr_model.get_chi_full_deriv(rhot + 1e-16, zeta, g2, tu + td)[0]
    chiu = corr_model.get_chi_full_deriv(rhou + 1e-16, 1, g2u, tu)[0]
    chid = corr_model.get_chi_full_deriv(rhod + 1e-16, 1, g2d, td)[0]
    x2 = corr_model.get_x2(nu+nd, g2)[0]
    x2u = corr_model.get_x2(nu, g2u)[0]
    x2d = corr_model.get_x2(nd, g2d)[0]
    amix = corr_model.get_amix(rhot, zeta, x2, chi)[0]
    chidesc = np.array(corr_model.get_chi_desc(chi)[:4])
    chidescu = np.array(corr_model.get_chi_desc(chiu)[:4])
    chidescd = np.array(corr_model.get_chi_desc(chid)[:4])
    Fx = exo / ldaxt
    Fxu = exu / ldaxu
    Fxd = exd / ldaxd
    corrterms = np.append(corr_model.get_separate_xef_terms(Fx),
                          chidesc, axis=0)
    extermsu = np.append(corr_model.get_separate_sl_terms(x2u, chiu, gammass)[0],
                         corr_model.get_separate_xefa_terms(Fxu, chiu)[0], axis=0)
    extermsd = np.append(corr_model.get_separate_sl_terms(x2d, chid, gammass)[0],
                         corr_model.get_separate_xefa_terms(Fxd, chid)[0], axis=0)

    cmscale = 17.0 / 3
    cmix = cmscale * (1 - chi) / (cmscale - chi)
    #cmix_terms = np.array([cmix * (1-cmix), cmix**2 * (1-cmix),
    #                       cmix * (1-cmix)**2, cmix**2 * (1-cmix)**2])
    cmix_terms0 = np.array([chi**2-chi, chi**3-chi, chi**4-chi**2, chi**5-chi**3,
                           chi**6-chi**4, chi**7-chi**5, chi**8-chi**6])
    cmix_terms = np.array([chi, chi**2, chi**3-chi, chi**4-chi**2, chi**5-chi**3,
                           chi**6-chi**4, chi**7-chi**5, chi**8-chi**6])
    cmix_termsu = np.array([chiu, chiu**2, chiu**3-chiu, chiu**4-chiu**2, chiu**5-chiu**3,
                            chiu**6-chiu**4, chiu**7-chiu**5, chiu**8-chiu**6])
    cmix_termsd = np.array([chid, chid**2, chid**3-chid, chid**4-chid**2, chid**5-chid**3,
                            chid**6-chid**4, chid**7-chid**5, chid**8-chid**6])
    Ecscan = np.dot(co * cmix + cx * (1-cmix), weights)
    Eterms = np.dot(cmix_terms0 * (cx-co), weights)
    Eterms2 = np.dot(cmix_terms * cx, weights)
    Eterms2[0] = np.dot(co * amix * (Fx-1), weights)
    Eterms2[1] = np.dot(cx * (Fx-1), weights)
    Eterms3 = np.append(np.dot(corrterms[1:5] * cx, weights),
                        np.dot(corrterms[1:5] * (1-chi**2) * (cx-co), weights))
    #Eterms3[-1] = np.dot((Fx-1) * cx, weights)
    #Eterms3[-2] = np.dot((Fx-1) * (co * cmix + cx * (1-cmix)), weights)
    Fterms = np.dot(extermsu * ldaxu * amix, weights)
    Fterms += np.dot(extermsd * ldaxd * amix, weights)
    Fterms2 = np.dot(cmix_termsu * ldaxu * amix, weights)
    Fterms2 += np.dot(cmix_termsd * ldaxd * amix, weights)
    Fterms3 = np.dot(cmix_termsu * (Fx-1) * ldaxu * amix, weights)
    Fterms3 += np.dot(cmix_termsd * (Fx-1) * ldaxd * amix, weights)

    return np.concatenate([Eterms, Eterms2, Eterms3, Fterms, Fterms2, Fterms3],
                          axis=0)


def get_corr_contribs(dft_dir, restricted, mlfunc,
                      desc_getter, exact=True):

    from mldftdat.models import map_c10

    corr_model = map_c10.VSXCContribs(None, None, None, None,
                                      fterm_scale=2.0)

    if restricted:
        dft_analyzer = RHFAnalyzer.load(dft_dir + '/data.hdf5')
        rhot = dft_analyzer.rho_data[0]
    else:
        dft_analyzer = UHFAnalyzer.load(dft_dir + '/data.hdf5')
        rhot = dft_analyzer.rho_data[0][0] + dft_analyzer.rho_data[1][0]

    rho_data = dft_analyzer.rho_data
    weights = dft_analyzer.grid.weights
    grid = dft_analyzer.grid
    spin = dft_analyzer.mol.spin
    mol = dft_analyzer.mol
    rdm1 = dft_analyzer.rdm1
    E_pbe = dft_analyzer.e_tot

    auxmol, ao_to_aux = setup_aux(mol, 0)
    mol.ao_to_aux = ao_to_aux
    mol.auxmol = auxmol

    if restricted:
        rho_data_u, rho_data_d = rho_data / 2, rho_data / 2
    else:
        rho_data_u, rho_data_d = rho_data[0], rho_data[1]

    rhou = rho_data_u[0] + 1e-20
    g2u = np.einsum('ir,ir->r', rho_data_u[1:4], rho_data_u[1:4])
    tu = rho_data_u[5] + 1e-20
    rhod = rho_data_d[0] + 1e-20
    g2d = np.einsum('ir,ir->r', rho_data_d[1:4], rho_data_d[1:4])
    td = rho_data_d[5] + 1e-20
    ntup = (rhou, rhod)
    gtup = (g2u, g2d)
    ttup = (tu, td)
    rhot = rhou + rhod
    g2o = np.einsum('ir,ir->r', rho_data_u[1:4], rho_data_d[1:4])
    g2 = g2u + 2 * g2o + g2d

    zeta = (rhou - rhod) / (rhot)
    ds = ((1-zeta)**(5.0/3) + (1+zeta)**(5.0/3))/2
    CU = 0.3 * (3 * np.pi**2)**(2.0/3)

    co0, vo0 = corr_model.os_baseline(rhou, rhod, g2, type=0)[:2]
    co1, vo1 = corr_model.os_baseline(rhou, rhod, g2, type=1)[:2]
    co0 *= rhot
    co1 *= rhot
    cx = co0
    co = co1

    nu, nd = rhou, rhod

    N = dft_analyzer.grid.weights.shape[0]
    if restricted:
        if exact:
            ex = dft_analyzer.fx_energy_density / (rho_data[0] + 1e-20)
        else:
            desc  = np.zeros((N, len(mlfunc.desc_list)))
            ddesc = np.zeros((N, len(mlfunc.desc_list)))
            xdesc = get_exchange_descriptors2(dft_analyzer, restricted=True)
            for i, d in enumerate(mlfunc.desc_list):
                desc[:,i], ddesc[:,i] = d.transform_descriptor(xdesc, deriv = 1)
            xef = mlfunc.get_F(desc)
            ex = LDA_FACTOR * xef * rho_data[0]**(1.0/3)
        exu = ex
        exd = ex
        exo = ex
        rhou = rho_data[0] / 2
        rhod = rho_data[0] / 2
        rhot = rho_data[0]
        Ex = np.dot(exo * rhot, weights)
    else:
        if exact:
            exu = dft_analyzer.fx_energy_density_u / (rho_data[0][0] + 1e-20)
            exd = dft_analyzer.fx_energy_density_d / (rho_data[1][0] + 1e-20)
        else:
            desc  = np.zeros((N, len(mlfunc.desc_list)))
            ddesc = np.zeros((N, len(mlfunc.desc_list)))
            xdesc_u, xdesc_d = get_exchange_descriptors2(dft_analyzer, restricted=False)
            for i, d in enumerate(mlfunc.desc_list):
                desc[:,i], ddesc[:,i] = d.transform_descriptor(xdesc_u, deriv = 1)
            xef = mlfunc.get_F(desc)
            exu = 2**(1.0/3) * LDA_FACTOR * xef * rho_data[0][0]**(1.0/3)
            for i, d in enumerate(mlfunc.desc_list):
                desc[:,i], ddesc[:,i] = d.transform_descriptor(xdesc_d, deriv = 1)
            xef = mlfunc.get_F(desc)
            exd = 2**(1.0/3) * LDA_FACTOR * xef * rho_data[1][0]**(1.0/3)
        rhou = rho_data[0][0]
        rhod = rho_data[1][0]
        rhot = rho_data[0][0] + rho_data[1][0]
        exo = (exu * rho_data[0][0] + exd * rho_data[1][0])
        Ex = np.dot(exo, weights)
        exo /= (rhot + 1e-20)

    exu = exu * rhou
    exd = exd * rhod
    exo = exo * rhot

    Excbas = dft_analyzer.e_tot - dft_analyzer.energy_tot() - dft_analyzer.fx_total

    logging.info('EX ERROR', Ex - dft_analyzer.fx_total, Ex, dft_analyzer.fx_total)
    if (np.abs(Ex - dft_analyzer.fx_total) > 1e-7):
        logging.warn('LARGE ERROR')

    desc = desc_getter(rhou, rhod, g2u, g2o, g2d, tu, td, exu, exd)

    return np.concatenate([[Ex, Excbas], desc,
                          [Ecscan, dft_analyzer.fx_total]], axis=0)


def store_corr_contribs_dataset(FNAME, ROOT, MOL_FNAME, MLFUNC,
                                ndesc, desc_getter,
                                exact=True,
                                mol_id_full=False,
                                functional=DEFAULT_FUNCTIONAL,
                                basis=DEFAULT_BASIS):

    with open(os.path.join(ROOT, MOL_FNAME), 'r') as f:
        data = yaml.load(f, Loader = yaml.Loader)
        dft_dirs = data['dft_dirs']
        is_restricted_list = data['is_restricted_list']

    SIZE = ndesc + 4
    X = np.zeros([0,SIZE])

    for dft_dir, is_restricted in zip(dft_dirs, is_restricted_list):

        logging.info('Corr contribs in', dft_dir)

        sl_contribs = get_corr_contribs(dft_dir, is_restricted,
                                        MLFUNC, desc_getter,
                                        exact=exact)
        assert (not np.isnan(sl_contribs).any())
        X = np.vstack([X, sl_contribs])

    np.save(FNAME, X)


def get_etot_contribs(dft_dir, ccsd_dir, restricted):

    if restricted:
        dft_analyzer = RHFAnalyzer.load(dft_dir + '/data.hdf5')
        ccsd_analyzer = CCSDAnalyzer.load(ccsd_dir + '/data.hdf5')
    else:
        dft_analyzer = UHFAnalyzer.load(dft_dir + '/data.hdf5')
        ccsd_analyzer = UCCSDAnalyzer.load(ccsd_dir + '/data.hdf5')

    E_pbe = dft_analyzer.e_tot
    if ccsd_analyzer.mol.nelectron < 3:
        E_ccsd = ccsd_analyzer.e_tot
    else:
        E_ccsd = ccsd_analyzer.e_tot + ccsd_analyzer.e_tri

    return np.array([E_pbe, E_ccsd])

def store_total_energies_dataset(FNAME, ROOT, MOL_FNAME,
                                 functional=DEFAULT_FUNCTIONAL,
                                 basis=DEFAULT_BASIS):

    # DFT, CCSD
    y = np.zeros([0, 2])

    with open(os.path.join(ROOT, MOL_FNAME), 'r') as f:
        data = yaml.load(f, Loader = yaml.Loader)
        dft_dirs = data['dft_dirs']
        ccsd_dirs = data['ccsd_dirs']
        is_restricted_list = data['is_restricted_list']

    for dft_dir, ccsd_dir, is_restricted in zip(dft_dirs, ccsd_dirs,
                                                is_restricted_list):
        logging.info('Storing total energies from', dft_dir, ccsd_dir)

        dft_ccsd = get_etot_contribs(dft_dir, ccsd_dir, is_restricted)

        y = np.vstack([y, dft_ccsd])

    np.save(FNAME, y)


def get_vv10_contribs(dft_dir, restricted, NLC_COEFS):

    if restricted:
        dft_analyzer = RHFAnalyzer.load(dft_dir + '/data.hdf5')
        rhot = dft_analyzer.rho_data[0]
        rdm1_nsp = dft_analyzer.rdm1
    else:
        dft_analyzer = UHFAnalyzer.load(dft_dir + '/data.hdf5')
        rhot = dft_analyzer.rho_data[0][0] + dft_analyzer.rho_data[1][0]
        rdm1_nsp = dft_analyzer.rdm1[0] + dft_analyzer.rdm1[1]

    rho_data = dft_analyzer.rho_data
    weights = dft_analyzer.grid.weights
    grid = dft_analyzer.grid
    spin = dft_analyzer.mol.spin
    mol = dft_analyzer.mol
    rdm1 = dft_analyzer.rdm1
    E_pbe = dft_analyzer.e_tot
    numint = NumInt()

    grid.level = 2
    grid.build()

    vv10_contribs = []

    for b_test, c_test in NLC_COEFS:

        _, Evv10, _ = nr_rks_vv10(numint, mol, grid, None, rdm1_nsp, b = b_test, c = c_test)

        vv10_contribs.append(Evv10)

    return np.array(vv10_contribs)

DEFAULT_NLC_COEFS = [[5.9, 0.0093], [6.0, 0.01], [6.3, 0.0089],\
                     [9.8, 0.0093], [14.0, 0.0093], [15.7, 0.0093]]

def store_vv10_contribs_dataset(FNAME, ROOT, MOL_FNAME,
                                NLC_COEFS=DEFAULT_NLC_COEFS,
                                functional=DEFAULT_FUNCTIONAL,
                                basis=DEFAULT_BASIS):
    with open(os.path.join(ROOT, MOL_FNAME), 'r') as f:
        data = yaml.load(f, Loader = yaml.Loader)
        dft_dirs = data['dft_dirs']
        is_restricted_list = data['is_restricted_list']

    X = np.zeros([0, len(NLC_COEFS)])

    for dft_dir, is_restricted in zip(dft_dirs, is_restricted_list):

        logging.info('Calculate VV10 contribs for', mol_id)

        vv10_contribs = get_vv10_contribs(dft_dir, is_restricted, NLC_COEFS)

        X = np.vstack([X, vv10_contribs])

    np.save(FNAME, X)


def solve_from_stored_ae(DATA_ROOT, DESC_NAME,
                         ADESC_NAME, noise=1e-3,
                         use_vv10=False,
                         regression_method='weighted_llsr'):
    """
    regression_method options:
        weighted_lrr: weighted linear ridge regression
        weighted_lasso: weighted lasso regression
    """

    import yaml
    from collections import Counter
    from ase.data import chemical_symbols, atomic_numbers, ground_state_magnetic_moments
    from sklearn.metrics import r2_score
    from pyscf import gto

    coef_sets = []
    scores = []

    etot = np.load(os.path.join(DATA_ROOT, 'etot.npy'))
    mlx = np.load(os.path.join(DATA_ROOT, DESC_NAME))
    if use_vv10:
        vv10 = np.load(os.path.join(DATA_ROOT, 'vv10.npy'))
    with open(os.path.join(DATA_ROOT, 'mols.yaml'), 'r') as f:
        mols = yaml.load(f, Loader = yaml.Loader)['mols']

    aetot = np.load(os.path.join(DATA_ROOT, 'atom_etot.npy'))
    amlx = np.load(os.path.join(DATA_ROOT, ADESC_NAME))
    atom_vv10 = np.load(os.path.join(DATA_ROOT, 'atom_vv10.npy'))
    with open(os.path.join(DATA_ROOT, 'atom_ref.yaml'), 'r') as f:
        amols = yaml.load(f, Loader = yaml.Loader)['mols']

    logging.info("SHAPES", mlx.shape, etot.shape, amlx.shape, aetot.shape)

    valset_bools_init = np.array([mol['valset'] for mol in mols])
    valset_bools_init = np.append(valset_bools_init,
                        np.zeros(len(amols), valset_bools_init.dtype))
    mols = [gto.mole.unpack(mol) for mol in mols]
    for mol in mols:
        mol.build()
    amols = [gto.mole.unpack(mol) for mol in amols]
    for mol in amols:
        mol.build()

    Z_to_ind = {}
    Z_to_ind_bsl = {}
    ind_to_Z_ion = {}
    formulas = {}
    ecounts = []
    for i, mol in enumerate(mols):
        ecounts.append(mol.nelectron)
        if len(mol._atom) == 1:
            Z = atomic_numbers[mol._atom[0][0]]
            Z_to_ind[Z] = i
        else:
            atoms = [atomic_numbers[a[0]] for a in mol._atom]
            formulas[i] = Counter(atoms)

    for i, mol in enumerate(amols):
        Z = atomic_numbers[mol._atom[0][0]]
        if mol.spin == ground_state_magnetic_moments[Z]:
            Z_to_ind_bsl[Z] = i
        else:
            ind_to_Z_ion[i] = Z

    ecounts = np.array(ecounts)

    N = etot.shape[0]
    if use_vv10:
        num_vv10 = vv10.shape[-1]
    else:
        num_vv10 = 1

    for i in range(num_vv10):

        def get_terms(etot, mlx, vv10=None):
            if vv10 is not None:
                E_vv10 = vv10[:,i]
            E_dft = etot[:,0]
            E_ccsd = etot[:,1]
            E_x = mlx[:,0]
            E_xscan = mlx[:,1]
            E_cscan = mlx[:,-2]
            E_c = mlx[2:-2]
            diff = E_ccsd - (E_dft - E_xscan + E_x + E_cscan)
            if use_vv10:
                diff -= E_vv10

            return E_c, diff, E_ccsd, E_dft, E_xscan, E_x, E_cscan

        E_c, diff, E_ccsd, E_dft, E_xscan, E_x, E_cscan = \
            get_terms(etot, mlx)
        E_c2, diff2, E_ccsd2, E_dft2, E_xscan2, E_x2, E_cscan2 = \
            get_terms(aetot, amlx)
        E_c = np.append(E_c, E_c2, axis=0)
        diff = np.append(diff, diff2)
        E_ccsd = np.append(E_ccsd, E_ccsd2)
        E_dft = np.append(E_dft, E_dft2)
        E_xscan = np.append(E_xscan, E_xscan2)
        E_x = np.append(E_x, E_x2)
        E_cscan = np.append(E_cscan, E_cscan2)

        # E_{tot,PBE} + diff + Evv10 + dot(c, sl_contribs) = E_{tot,CCSD(T)}
        # dot(c, sl_contribs) = E_{tot,CCSD(T)} - E_{tot,PBE} - diff - Evv10
        # not an exact relationship, but should give a decent fit
        X = E_c.copy()
        y = diff.copy()
        Ecc = E_ccsd.copy()
        Edf = E_dft.copy()
        weights = []
        for i in range(len(mols)):
            if i in formulas.keys():
                #weights.append(1.0)
                weights.append(1.0 / (len(mols[i]._atom) - 1))
                formula = formulas[i]
                if formula.get(1) == 2 and formula.get(8) == 1 and len(list(formula.keys()))==2:
                    waterind = i
                    logging.info(formula, E_ccsd[i], E_dft[i])
                for Z in list(formula.keys()):
                    X[i,:] -= formula[Z] * X[Z_to_ind[Z],:]
                    y[i] -= formula[Z] * y[Z_to_ind[Z]]
                    Ecc[i] -= formula[Z] * Ecc[Z_to_ind[Z]]
                    Edf[i] -= formula[Z] * Edf[Z_to_ind[Z]]
                logging.debug(formulas[i], y[i], Ecc[i], Edf[i], E_x[i] - E_xscan[i])
            else:
                if mols[i].nelectron == 1:
                    hind = i
                if mols[i].nelectron == 8:
                    oind = i
                    logging.debug(mols[i], E_ccsd[i], E_dft[i])
                if mols[i].nelectron == 3:
                    weights.append(1e-8 / 3)
                else:
                    weights.append(1e-8 / mols[i].nelectron if mols[i].nelectron <= 10 else 0)
        for i in range(len(amols)):
            logging.info(amols[i].nelectron, Ecc[len(mols)+i], Edf[len(mols)+i])
            weights.append(8 / amols[i].nelectron)
            if i in ind_to_Z_ion.keys():
                j = len(mols) + i
                k = len(mols) + Z_to_ind_bsl[ind_to_Z_ion[i]]
                X[j,:] -= X[k,:]
                y[j] -= y[k]
                Ecc[j] -= Ecc[k]
                Edf[j] -= Edf[k]
                weights[-1] = 4

        weights = np.array(weights)
        
        logging.info(E_xscan[[hind,oind,waterind]])
        logging.info('ASSESS MEAN DIFF')
        logging.info(np.mean(np.abs(Ecc-Edf)[weights > 0]))
        logging.info(np.mean(np.abs(diff)[weights > 0]))

        inds = np.arange(len(y))
        valset_bools = valset_bools_init[weights > 0]
        X = X[weights > 0, :]
        y = y[weights > 0]
        Ecc = Ecc[weights > 0]
        Edf = Edf[weights > 0]
        inds = inds[weights > 0]
        indd = {}
        for i in range(inds.shape[0]):
            indd[inds[i]] = i
        weights = weights[weights > 0]

        logging.info(E_ccsd[waterind], E_dft[waterind])

        oind = indd[oind]
        hind = indd[hind]
        waterind = indd[waterind]

        trset_bools = np.logical_not(valset_bools)
        Xtr = X[trset_bools]
        Xts = X[valset_bools]
        ytr = y[trset_bools]
        yts = y[valset_bools]
        wtr = weights[trset_bools]
        if method == 'weighted_lrr':
            A = np.linalg.inv(np.dot(Xtr.T * wtr, Xtr) + np.diag(noise))
            B = np.dot(Xtr.T, wtr * ytr)
            coef = np.dot(A, B)
        elif method == 'weighted_lasso':
            from sklearn.linear_model import Lasso
            model = Lasso(alpha=noise, fit_intercept=False)
            model.fit(Xtr * wtr[:,np.newaxis], ytr * wtr)
            coef = model.coef_
        else:
            raise ValueError('Model choice not recognized')

        score = r2_score(yts, np.dot(Xts, coef))
        score0 = r2_score(yts, np.dot(Xts, 0 * coef))
        logging.info(Xts.shape, yts.shape)
        logging.info(score, score0)
        logging.info((Ecc)[[hind,oind,waterind]], Ecc[oind], Edf[oind],
                     Ecc[waterind], Edf[waterind])
        logging.info((y - Ecc - np.dot(X, coef))[[hind,oind,waterind]],
                     Ecc[oind], Edf[oind], Ecc[waterind], Edf[waterind])
        logging.info('SCAN ALL', np.mean(np.abs(Ecc-Edf)),
                     np.mean((Ecc-Edf)), np.std(Ecc-Edf))
        logging.info('SCAN VAL', np.mean(np.abs(Ecc-Edf)[valset_bools]),
                     np.mean((Ecc-Edf)[valset_bools]),
                     np.std((Ecc-Edf)[valset_bools]))
        logging.info('ML ALL', np.mean(np.abs(y - np.dot(X, coef))),
                     np.mean(y - np.dot(X, coef)),
                     np.std(y - np.dot(X,coef)))
        logging.info('ML VAL', np.mean(np.abs(yts - np.dot(Xts, coef))),
                     np.mean(yts - np.dot(Xts, coef)),
                     np.std(yts-np.dot(Xts,coef)))
        logging.info(np.max(np.abs(y - np.dot(X, coef))),
                     np.max(np.abs(Ecc - Edf)))
        logging.info(np.max(np.abs(yts - np.dot(Xts, coef))),
                     np.max(np.abs(Ecc - Edf)[valset_bools]))

        coef_sets.append(coef)
        scores.append(score)

    return coef_sets, scores


def store_mols_in_order(FNAME, ROOT, MOL_IDS, IS_RESTRICTED_LIST,
                        VAL_SET=None, mol_id_full=False,
                        functional=DEFAULT_FUNCTIONAL):
    from pyscf import gto
    import yaml

    dft_dirs = []
    ccsd_dirs = []
    mol_dicts = []

    for mol_id, is_restricted in zip(MOL_IDS, IS_RESTRICTED_LIST):

        if mol_id_full:
            dft_dir = mol_id[0]
            ccsd_dir = mol_id[1]
        else:
            if is_restricted:
                dft_dir = get_save_dir(ROOT, 'RKS', DEFAULT_BASIS, mol_id,
                                       functional=functional)
                ccsd_dir = get_save_dir(ROOT, 'CCSD', DEFAULT_BASIS, mol_id)
            else:
                dft_dir = get_save_dir(ROOT, 'UKS', DEFAULT_BASIS, mol_id,
                                       functional=functional)
                ccsd_dir = get_save_dir(ROOT, 'UCCSD', DEFAULT_BASIS, mol_id)
        if is_restricted:
            dft_analyzer = RHFAnalyzer.load(dft_dir + '/data.hdf5')
        else:
            dft_analyzer = UHFAnalyzer.load(dft_dir + '/data.hdf5')

        mol_dicts.append(gto.mole.pack(pbe_analyzer.mol))
        dft_dirs.append(dft_dir)
        ccsd_dirs.append(ccsd_dir)
        if VAL_SET is not None:
            mol_dicts[-1].update({'valset': mol_id in VAL_SET})

    all_data = {
        'mols': mol_dicts,
        'dft_dirs': dft_dirs,
        'ccsd_dirs': ccsd_dirs,
        'is_restricted_list': IS_RESTRICTED_LIST
    }

    with open(FNAME, 'w') as f:
        yaml.dump(all_data, f)
