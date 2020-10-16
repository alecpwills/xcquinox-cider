#!/usr/bin/env python
# Copyright 2018-2019 The PySCF Developers. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Author: Peng Bao <baopeng@iccas.ac.cn>
#         Qiming Sun <osirpt.sun@gmail.com>
# Adapted and edited by Kyle Bystrom <kylebystrom@gmail.com> for use in the
# mldftdat module.
#

from pyscf.sgx.sgx import *
from pyscf.sgx.sgx_jk import *
from pyscf.sgx.sgx_jk import _gen_jk_direct
from pyscf.sgx.sgx import _make_opt
from pyscf.dft.numint import eval_ao, eval_rho
from pyscf.dft.gen_grid import make_mask, BLKSIZE
from mldftdat.models.map_c6 import VSXCContribs
from pyscf import __config__
import pyscf.dft.numint as pyscf_numint
from pyscf.dft.numint import _scale_ao, _dot_ao_ao
from pyscf.dft.rks import prune_small_rho_grids_
np = numpy

LDA_FACTOR = - 3.0 / 4.0 * (3.0 / np.pi)**(1.0/3)

def get_veff(ks, mol=None, dm=None, dm_last=0, vhf_last=0, hermi=1):
    if mol is None: mol = ks.mol
    if dm is None: dm = ks.make_rdm1()
    t0 = (time.clock(), time.time())

    ground_state = (isinstance(dm, numpy.ndarray) and dm.ndim == 2)

    if ks.grids.coords is None:
        ks.grids.build(with_non0tab=True)
        if ks.small_rho_cutoff > 1e-20 and ground_state:
            ks.grids = prune_small_rho_grids_(ks, mol, dm, ks.grids)
        t0 = logger.timer(ks, 'setting up grids', *t0)

    if ks.nlc != '':
        if ks.nlcgrids.coords is None:
            ks.nlcgrids.build(with_non0tab=True)
            if ks.small_rho_cutoff > 1e-20 and ground_state:
                # Filter grids the first time setup grids
                ks.nlcgrids = prune_small_rho_grids_(ks, mol, dm, ks.nlcgrids)
            t0 = logger.timer(ks, 'setting up nlc grids', *t0)

    ni = ks._numint
    if hermi == 2:  # because rho = 0
        n, exc, vxc = 0, 0, 0
    else:
        max_memory = ks.max_memory - lib.current_memory()[0]
        n, exc, vxc = ni.nr_rks(mol, ks.grids, ks.xc, dm, max_memory=max_memory)
        if ks.nlc != '':
            assert('VV10' in ks.nlc.upper())
            _, enlc, vnlc = ni.nr_rks(mol, ks.nlcgrids, ks.xc+'__'+ks.nlc, dm,
                                      max_memory=max_memory)
            exc += enlc
            vxc += vnlc
        logger.debug(ks, 'nelec by numeric integration = %s', n)
        t0 = logger.timer(ks, 'vxc', *t0)

    vj, vk = ks.get_jk(mol, dm, hermi)
    vxc += vj - vk * .5
    # vk array must be tagged with these attributes,
    # vc_contrib and ec_contrib
    vxc += vk.vc_contrib
    exc += vk.ec_contrib

    if ground_state:
        exc -= numpy.einsum('ij,ji', dm, vk).real * .5 * .5

    if ground_state:
        ecoul = numpy.einsum('ij,ji', dm, vj).real * .5
    else:
        ecoul = None

    vxc = lib.tag_array(vxc, ecoul=ecoul, exc=exc, vj=vj, vk=vk)
    return vxc


def get_gridss_with_non0tab(mol, level=1, gthrd=1e-10):
    Ktime = (time.clock(), time.time())
    grids = dft.gen_grid.Grids(mol)
    grids.level = level
    grids.build(with_non0tab=True)

    ngrids = grids.weights.size
    mask = []
    for p0, p1 in lib.prange(0, ngrids, 10000):
        ao_v = mol.eval_gto('GTOval', grids.coords[p0:p1])
        ao_v *= grids.weights[p0:p1,None]
        wao_v0 = ao_v
        mask.append(numpy.any(wao_v0>gthrd, axis=1) |
                    numpy.any(wao_v0<-gthrd, axis=1))

    mask = numpy.hstack(mask)
    grids.coords = grids.coords[mask]
    grids.weights = grids.weights[mask]
    logger.debug(mol, 'threshold for grids screening %g', gthrd)
    logger.debug(mol, 'number of grids %d', grids.weights.size)
    logger.timer_debug1(mol, "Xg screening", *Ktime)
    return grids

def sgx_fit_corr(mf, auxbasis=None, with_df=None):
    # needs to:
    # 1. Wrap in typical SGX but with get get_jkc function
    #    instead of the normal get_jk function
    # 2. Find a way to pass the correlation energy and
    #    vc by attaching it to sgx and then returning
    #    it when nr_uks is called.
    # 3. I.e. attach the sgx to the numint, then
    #    when numint is called, return the current
    #    Ec and Vc attached to sgx
    from pyscf import scf
    from pyscf import df
    from pyscf.soscf import newton_ah
    assert(isinstance(mf, scf.hf.SCF))

    if with_df is None:
        with_df = SGXCorr(mf.mol)
        with_df.max_memory = mf.max_memory
        with_df.stdout = mf.stdout
        with_df.verbose = mf.verbose
        with_df.auxbasis = auxbasis

    mf._numint.sgx = with_df
    with_df.corr_model = mf._numint.corr_model

    new_mf = sgx_fit(mf, auxbasis=auxbasis, with_df=with_df)

    cls = new_mf.__class__
    cls.get_veff = get_veff

    new_mf = cls(mf, with_df, auxbasis)

    return new_mf


def _eval_corr_uks(corr_model, rho_data, F):
    N = rho_data.shape[-1]
    print(rho_data.shape)
    rhou = rho_data[0][0]
    g2u = np.einsum('ir,ir->r', rho_data[0][1:4], rho_data[0][1:4])
    tu = rho_data[0][5]
    rhod = rho_data[1][0]
    g2d = np.einsum('ir,ir->r', rho_data[1][1:4], rho_data[1][1:4])
    td = rho_data[1][5]
    ntup = (rhou, rhod)
    gtup = (g2u, g2d)
    ttup = (tu, td)
    rhot = rhou + rhod
    g2o = np.einsum('ir,ir->r', rho_data[0][1:4], rho_data[1][1:4])

    vtot = [np.zeros((N,2)), np.zeros((N,3)), np.zeros((N,2)),
            np.zeros((N,2)), np.zeros((N,2))]
        
    exc, vxc = corr_model.xefc(rhou, rhod, g2u, g2o, g2d,
                               tu, td, F[0], F[1],
                               include_baseline=False,
                               include_aug_sl=False,
                               include_aug_nl=True)

    vtot[0][:,:] += vxc[0]
    vtot[0][:,0] += vxc[3][:,0] * -4 * F[0] / (3 * rhou)
    vtot[0][:,1] += vxc[3][:,1] * -4 * F[1] / (3 * rhod)
    vtot[1][:,:] += vxc[1]
    vtot[3][:,:] += vxc[2]
    vtot[4][:,0] += vxc[3][:,0] / (LDA_FACTOR * rhou**(4.0/3))
    vtot[4][:,1] += vxc[3][:,1] / (LDA_FACTOR * rhod**(4.0/3))

    return exc / (rhot + 1e-20), vtot

def _eval_corr_rks(corr_model, rho_data, F):
    rho_data = np.stack([rho_data, rho_data], axis=0)
    F = np.stack([F, F], axis=0)
    exc, vxc = _eval_corr_uks(corr_model, rho_data, F)[:2]
    vxc = [vxc[0][:,0], 0.5 * vxc[1][:,0] + 0.25 * vxc[1][:,1],\
           vxc[2][:,0], vxc[3][:,0], vxc[4][:,0]]
    return exc, vxc

from pyscf.dft.numint import _rks_gga_wv0, _uks_gga_wv0

def _contract_corr_rks(vmat, mol, exc, vxc, weight, ao, rho, mask):

    ngrid = weight.size
    shls_slice = (0, mol.nbas)
    ao_loc = mol.ao_loc_nr()
    aow = np.ndarray(ao[0].shape, order='F')
    vrho, vsigma, vlap, vtau = vxc[:4]
    den = rho[0]*weight
    excsum = np.dot(den, exc)

    wv = _rks_gga_wv0(rho, vxc, weight)
    aow = _scale_ao(ao[:4], wv)
    vmat += _dot_ao_ao(mol, ao[0], aow, mask, shls_slice, ao_loc)

    wv = (0.5 * 0.5 * weight * vtau).reshape(-1,1)
    vmat += _dot_ao_ao(mol, ao[1], wv*ao[1], mask, shls_slice, ao_loc)
    vmat += _dot_ao_ao(mol, ao[2], wv*ao[2], mask, shls_slice, ao_loc)
    vmat += _dot_ao_ao(mol, ao[3], wv*ao[3], mask, shls_slice, ao_loc)

    vmat = vmat + vmat.T

    return excsum, vmat

def _contract_corr_uks(vmat, mol, exc, vxc, weight, ao, rho, mask):

    ngrid = weight.size
    shls_slice = (0, mol.nbas)
    ao_loc = mol.nao_loc_nr()
    aow = np.ndarray(ao[0].shape, order='F')
    rho_a = rho[0]
    rho_b = rho[1]
    vrho, vsigma, vlpal, vtau = vxc[:4]
    den = rho_a[0]*weight
    excsum = np.dot(den, exc)
    den = rho_b[0]*weight
    excsum += np.dot(den, exc)

    wva, wvb = _uks_gga_wv0((rho_a,rho_b), vxc, weight)
    #:aow = np.einsum('npi,np->pi', ao[:4], wva, out=aow)
    aow = _scale_ao(ao[:4], wva, out=aow)
    vmat[0] += _dot_ao_ao(mol, ao[0], aow, mask, shls_slice, ao_loc)
    #:aow = np.einsum('npi,np->pi', ao[:4], wvb, out=aow)
    aow = _scale_ao(ao[:4], wvb, out=aow)
    vmat[1] += _dot_ao_ao(mol, ao[0], aow, mask, shls_slice, ao_loc)

    wv = (.25 * weight * vtau[:,0]).reshape(-1,1)
    vmat[0] += _dot_ao_ao(mol, ao[1], wv*ao[1], mask, shls_slice, ao_loc)
    vmat[0] += _dot_ao_ao(mol, ao[2], wv*ao[2], mask, shls_slice, ao_loc)
    vmat[0] += _dot_ao_ao(mol, ao[3], wv*ao[3], mask, shls_slice, ao_loc)
    vmat[1] += _dot_ao_ao(mol, ao[1], wv*ao[1], mask, shls_slice, ao_loc)
    vmat[1] += _dot_ao_ao(mol, ao[2], wv*ao[2], mask, shls_slice, ao_loc)
    vmat[1] += _dot_ao_ao(mol, ao[3], wv*ao[3], mask, shls_slice, ao_loc)

    vmat[0] = vmat[0] + vmat[0].T
    vmat[1] = vmat[1] + vmat[1].T

    return excsum, vmat


def get_jkc(sgx, dm, hermi=1, with_j=True, with_k=True,
            direct_scf_tol=1e-13):
    """
    WARNING: Assumes dm.shape=(1,nao,nao) if restricted
    and dm.shape=(2,nao,nao) for unrestricted for correlation
    to be calculated correctly.
    """
    t0 = time.clock(), time.time()
    mol = sgx.mol
    nao = mol.nao_nr()
    grids = sgx.grids
    non0tab = grids.non0tab
    if non0tab is None:
        raise ValueError('Grids object must have non0tab!')
    gthrd = sgx.grids_thrd

    dms = numpy.asarray(dm)
    dm_shape = dms.shape
    nao = dm_shape[-1]
    dms = dms.reshape(-1,nao,nao)
    nset = dms.shape[0]

    if sgx.debug:
        batch_nuc = _gen_batch_nuc(mol)
    else:
        batch_jk = _gen_jk_direct(mol, 's2', with_j, with_k, direct_scf_tol,
                                  sgx._opt)

    sn = numpy.zeros((nao,nao))
    ngrids = grids.coords.shape[0]
    max_memory = sgx.max_memory - lib.current_memory()[0]
    sblk = sgx.blockdim
    blksize = min(ngrids, max(4, int(min(sblk, max_memory*1e6/8/nao**2))))
    for i0, i1 in lib.prange(0, ngrids, blksize):
        coords = grids.coords[i0:i1]
        ao = mol.eval_gto('GTOval', coords)
        wao = ao * grids.weights[i0:i1,None]
        sn += lib.dot(ao.T, wao)

    ovlp = mol.intor_symmetric('int1e_ovlp')
    proj = scipy.linalg.solve(sn, ovlp)
    proj_dm = lib.einsum('ki,xij->xkj', proj, dms)

    t1 = logger.timer_debug1(mol, "sgX initialziation", *t0)
    vj = numpy.zeros_like(dms)
    vk = numpy.zeros_like(dms)
    vc = numpy.zeros_like(dms)
    if nset == 1:
        contract_corr = _contract_corr_rks
        eval_corr = _eval_corr_rks
    elif nset == 2:
        contract_corr = _contract_corr_uks
        eval_corr = _eval_corr_uks
    else:
        raise ValueError('Can only call sgx correlation model with nset=1,2')
    FXtmp = numpy.zeros(ngrids)
    Ec = 0
    tnuc = 0, 0
    for i0, i1 in lib.prange(0, ngrids, blksize):
        non0 = non0tab[i0//BLKSIZE:]
        coords = grids.coords[i0:i1]
        ao = mol.eval_gto('GTOval', coords)
        wao = ao * grids.weights[i0:i1,None]
        weights = grids.weights[i0:i1]

        fg = lib.einsum('gi,xij->xgj', wao, proj_dm)
        mask = numpy.zeros(i1-i0, dtype=bool)
        for i in range(nset):
            mask |= numpy.any(fg[i]>gthrd, axis=1)
            mask |= numpy.any(fg[i]<-gthrd, axis=1)
        if not numpy.all(mask):
            ao = ao[mask]
            fg = fg[:,mask]
            coords = coords[mask]
            weights = weights[mask]

        if with_j:
            rhog = numpy.einsum('xgu,gu->xg', fg, ao)
        else:
            rhog = None
        rhogs = numpy.einsum('xgu,gu->g', fg, ao)
        ex = numpy.zeros(rhogs.shape)
        FX = numpy.zeros(rhogs.shape)
        ao_data = eval_ao(mol, coords, deriv=2, non0tab=non0)
        # should make mask for rho_data in the future.
        rho_data = eval_rho(mol, ao_data, dm, non0tab=non0, xctype='MGGA')

        if sgx.debug:
            tnuc = tnuc[0] - time.clock(), tnuc[1] - time.time()
            gbn = batch_nuc(mol, coords)
            tnuc = tnuc[0] + time.clock(), tnuc[1] + time.time()
            if with_j:
                jpart = numpy.einsum('guv,xg->xuv', gbn, rhog)
            if with_k:
                gv = lib.einsum('gtv,xgt->xgv', gbn, fg)
            gbn = None
        else:
            tnuc = tnuc[0] - time.clock(), tnuc[1] - time.time()
            jpart, gv = batch_jk(mol, coords, rhog, fg)
            tnuc = tnuc[0] + time.clock(), tnuc[1] + time.time()

        if with_j:
            vj += jpart
        if with_k:
            for i in range(nset):
                vk[i] += lib.einsum('gu,gv->uv', ao, gv[i])
                print(ex.shape, fg.shape, gv[i].shape, weights.shape)
                ex += lib.einsum('gu,gu->g', fg[i]/weights[:,None], gv[i]/weights[:,None])
            FX = ex / (LDA_FACTOR * rhogs**(4.0/3))
            # vctmp = (vrho, vsigma, vlapl, vtau, vxdens)
            ec, vctmp = eval_corr(sgx.corr_model, rho_data, FX)
            Ec += numpy.dot(ec * rhogs, weights)
            contract_corr(vc, mol, ec, vctmp[:-1], weights,
                          ao_data, rho_data, non0)
            if nset == 1:
                vc[i] += lib.einsum('gu,gv->uv', ao, gv[0] * vctmp[-1][:,None])
            else:
                for i in range(nset):
                    vc[i] += lib.einsum('gu,gv->uv', ao, gv[i] * vctmp[-1][:,i,None])

        jpart = gv = None

    t2 = logger.timer_debug1(mol, "sgX J/K builder", *t1)
    tdot = t2[0] - t1[0] - tnuc[0] , t2[1] - t1[1] - tnuc[1]
    logger.debug1(sgx, '(CPU, wall) time for integrals (%.2f, %.2f); '
                  'for tensor contraction (%.2f, %.2f)',
                  tnuc[0], tnuc[1], tdot[0], tdot[1])

    for i in range(nset):
        lib.hermi_triu(vj[i], inplace=True)
    if with_k and hermi == 1:
        vk = (vk + vk.transpose(0,2,1))*.5
    logger.timer(mol, "vj and vk", *t0)

    vk = vk.reshape(dm_shape)
    vk = lib.tag_array(vk, vc_contrib=vc.reshape(dm_shape), ec_contrib=Ec)

    return vj.reshape(dm_shape), vk


class SGXCorr(SGX):

    def __init__(self, mol, auxbasis=None):
        super(SGXCorr, self).__init__(mol, auxbasis)
        self.grids_level_i = 1
        self.grids_level_f = 2

    def build(self, level=None):
        if level is None:
            level = self.grids_level_f

        self.grids = get_gridss_with_non0tab(self.mol, level, self.grids_thrd)
        self._opt = _make_opt(self.mol)

        # TODO no rsh currently

        return self

    def get_jk(self, dm, hermi=1, with_j=True, with_k=True,
               direct_scf_tol=getattr(__config__, 'scf_hf_SCF_direct_scf_tol', 1e-13),
               omega=None):
        # omega not used
        if with_j and self.dfj:
            vj = df_jk.get_j(self, dm, hermi, direct_scf_tol)
            if with_k:
                vk = get_jkc(self, dm, hermi, False, with_k, direct_scf_tol)[1]
            else:
                vk = None
        else:
            vj, vk = get_jkc(self, dm, hermi, with_j, with_k, direct_scf_tol)
        return vj, vk


class HFCNumInt(pyscf_numint.NumInt):

    def __init__(self, css, cos, cx, cm, ca,
                 dss, dos, dx, dm, da, vv10_coeff = None):
        super(HFCNumInt, self).__init__()
        from mldftdat.models import map_c6
        self.corr_model = map_c6.VSXCContribs(
                                css, cos, cx, cm, ca,
                                dss, dos, dx, dm, da)

        if vv10_coeff is None:
            self.vv10 = False
        else:
            self.vv10 = True
            self.vv10_b, self.vv10_c = vv10_coeff

    def nr_rks(self, mol, grids, xc_code, dms, relativity=0, hermi=0,
               max_memory=2000, verbose=None):
        nelec, excsum, vmat = super(HFCNumInt, self).nr_rks(
                                mol, grids, xc_code, dms,
                                relativity, hermi,
                                max_memory, verbose)
        return nelec, excsum, vmat

    def nr_uks(self, mol, grids, xc_code, dms, relativity=0, hermi=0,
               max_memory=2000, verbose=None):
        nelec, excsum, vmat = super(HFCNumInt, self).nr_uks(
                                mol, grids, xc_code, dms,
                                relativity, hermi,
                                max_memory, verbose)
        return nelec, excsum, vmat

    def eval_xc(self, xc_code, rho, spin=0, relativity=0, deriv=1, omega=None,
                verbose=None):
        rho_data = rho
        N = rho_data.shape[1]
        rhou = rho_data[0][0]
        g2u = np.einsum('ir,ir->r', rho_data[0][1:4], rho_data[0][1:4])
        tu = rho_data[0][5]
        rhod = rho_data[1][0]
        g2d = np.einsum('ir,ir->r', rho_data[1][1:4], rho_data[1][1:4])
        td = rho_data[1][5]
        ntup = (rhou, rhod)
        gtup = (g2u, g2d)
        ttup = (tu, td)
        rhot = rhou + rhod
        g2o = np.einsum('ir,ir->r', rho_data[0][1:4], rho_data[1][1:4])

        vtot = [np.zeros((N,2)), np.zeros((N,3)), np.zeros((N,2)),
                np.zeros((N,2))]
            
        exc, vxc = self.corr_model.xefc(rhou, rhod, g2u, g2o, g2d,
                                   tu, td, None, None,
                                   include_baseline=True,
                                   include_aug_sl=True,
                                   include_aug_nl=False)

        vtot[0][:,:] += vxc[0]
        vtot[1][:,:] += vxc[1]
        vtot[3][:,:] += vxc[2]

        return exc / (rhot + 1e-20), vtot, None, None

DEFAULT_COS = [-0.02481797,  0.00303413,  0.00054502,  0.00054913]
DEFAULT_CX = [-0.03483633, -0.00522109, -0.00299816, -0.0022187 ]
DEFAULT_CA = [-0.60154365, -0.06004444, -0.04293853, -0.03146755]
DEFAULT_DOS = [-0.00041445, -0.01881556,  0.03186469,  0.00100642, -0.00333434,
          0.00472453]
DEFAULT_DX = [ 0.00094936,  0.09238444, -0.21472824, -0.00118991,  0.0023009 ,
         -0.00096118]
DEFAULT_DA = [ 7.92248007e-03, -2.11963128e-03,  2.72918353e-02,  4.57295468e-05,
         -1.00450001e-05, -3.47808331e-04]
DEFAULT_CM = None
DEFAULT_DM = None
DEFAULT_CSS = None
DEFAULT_DSS = None

def setup_rks_calc(mol, css=DEFAULT_CSS, cos=DEFAULT_COS,
                   cx=DEFAULT_CX, cm=DEFAULT_CM, ca=DEFAULT_CA,
                   dss=DEFAULT_DSS, dos=DEFAULT_DOS, dx=DEFAULT_DX,
                   dm=DEFAULT_DM, da=DEFAULT_DA,
                   vv10_coeff = None):
    rks = dft.RKS(mol)
    rks.xc = None
    rks._numint = HFCNumInt(css, cos, cx, cm, ca,
                           dss, dos, dx, dm, da,
                           vv10_coeff)
    return sgx_fit_corr(rks)

def setup_uks_calc(mol, css=DEFAULT_CSS, cos=DEFAULT_COS,
                   cx=DEFAULT_CX, cm=DEFAULT_CM, ca=DEFAULT_CA,
                   dss=DEFAULT_DSS, dos=DEFAULT_DOS, dx=DEFAULT_DX,
                   dm=DEFAULT_DM, da=DEFAULT_DA,
                   vv10_coeff = None):
    uks = dft.UKS(mol)
    uks.xc = None
    uks._numint = HFCNumInt(css, cos, cx, cm, ca,
                           dss, dos, dx, dm, da,
                           vv10_coeff)
    return sgx_fit_corr(uks)
