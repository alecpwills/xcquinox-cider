import numpy as np
from mldftdat.xcutil.cdesc import *

def desc_set(weights, rhou, rhod, g2u, g2o, g2d, tu, td, exu, exd):
    rhot = rhou + rhod
    g2 = g2u + 2* g2o + g2d
    exo = exu + exd

    co0, vo0 = get_os_baseline(rhou, rhod, g2, type=0)[:2]
    co1, vo1 = get_os_baseline(rhou, rhod, g2, type=1)[:2]
    co0 *= rhot
    co1 *= rhot
    cx = co0
    co = co1

    nu, nd = rhou, rhod

    zeta = (rhou - rhod) / (rhot)
    ds = ((1-zeta)**(5.0/3) + (1+zeta)**(5.0/3))/2
    CU = 0.3 * (3 * np.pi**2)**(2.0/3)

    ldaxu = 2**(1.0/3) * LDA_FACTOR * rhou**(4.0/3) - 1e-20
    ldaxd = 2**(1.0/3) * LDA_FACTOR * rhod**(4.0/3) - 1e-20
    ldaxt = ldaxu + ldaxd

    gamma = 2**(2./3) * 0.004
    gammass = 0.004
    chi = get_chi_full_deriv(rhot + 1e-16, zeta, g2, tu + td)[0]
    chiu = get_chi_full_deriv(rhou + 1e-16, 1, g2u, tu)[0]
    chid = get_chi_full_deriv(rhod + 1e-16, 1, g2d, td)[0]
    x2 = get_x2(nu+nd, g2)[0]
    x2u = get_x2(nu, g2u)[0]
    x2d = get_x2(nd, g2d)[0]
    amix = get_amix_schmidt2(rhot, zeta, x2, chi)[0]
    chidesc = np.array(get_chi_desc(chi)[:4])
    chidescu = np.array(get_chi_desc(chiu)[:4])
    chidescd = np.array(get_chi_desc(chid)[:4])
    Fx = exo / ldaxt
    Fxu = exu / ldaxu
    Fxd = exd / ldaxd
    corrterms = np.append(get_separate_xef_terms(Fx, return_deriv=False),
                          chidesc, axis=0)
    extermsu = np.append(get_sl_small(x2u, chiu, gammass)[0],
                         get_xefa_small(Fxu, chiu)[0], axis=0)
    extermsd = np.append(get_sl_small(x2d, chid, gammass)[0],
                         get_xefa_small(Fxd, chid)[0], axis=0)

    cmscale = 17.0 / 3
    cmix = cmscale * (1 - chi) / (cmscale - chi)
    cmix_terms0 = np.array([chi**2-chi, chi**3-chi, chi**4-chi**2])
    Ecscan = np.dot(co * cmix + cx * (1-cmix), weights)
    Eterms = np.dot(cmix_terms0 * (cx-co), weights)
    Eterms2 = np.array([np.dot(co * amix * (Fx-1), weights),
                        np.dot(cx * amix * (Fx-1), weights)])
    Fterms = np.dot(extermsu * ldaxu * amix, weights)
    Fterms += np.dot(extermsd * ldaxd * amix, weights)

    return Ecscan, np.concatenate([Eterms, Eterms2, Fterms], axis=0)


def desc_set2(weights, rhou, rhod, g2u, g2o, g2d, tu, td, exu, exd):
    rhot = rhou + rhod
    g2 = g2u + 2* g2o + g2d
    exo = exu + exd

    co0, vo0 = get_os_baseline(rhou, rhod, g2, type=0)[:2]
    co1, vo1 = get_os_baseline(rhou, rhod, g2, type=1)[:2]
    co0 *= rhot
    co1 *= rhot
    cx = co0
    co = co1

    nu, nd = rhou, rhod

    zeta = (rhou - rhod) / (rhot)
    ds = ((1-zeta)**(5.0/3) + (1+zeta)**(5.0/3))/2
    CU = 0.3 * (3 * np.pi**2)**(2.0/3)

    ldaxu = 2**(1.0/3) * LDA_FACTOR * rhou**(4.0/3) - 1e-20
    ldaxd = 2**(1.0/3) * LDA_FACTOR * rhod**(4.0/3) - 1e-20
    ldaxt = ldaxu + ldaxd

    gamma = 2**(2./3) * 0.004
    gammass = 0.004
    chi = get_chi_full_deriv(rhot + 1e-16, zeta, g2, tu + td)[0]
    chiu = get_chi_full_deriv(rhou + 1e-16, 1, g2u, tu)[0]
    chid = get_chi_full_deriv(rhod + 1e-16, 1, g2d, td)[0]
    x2 = get_x2(nu+nd, g2)[0]
    x2u = get_x2(nu, g2u)[0]
    x2d = get_x2(nd, g2d)[0]
    amix = get_amix_schmidt2(rhot, zeta, x2, chi)[0]
    amixz = get_amix_schmidt2(rhot, zeta, x2, chi, mixer='n')[0]
    chidesc = np.array(get_chi_desc(chi)[:4])
    chidescu = np.array(get_chi_desc(chiu)[:4])
    chidescd = np.array(get_chi_desc(chid)[:4])
    Fx = exo / ldaxt
    Fxu = exu / ldaxu
    Fxd = exd / ldaxd
    corrterms = np.append(get_separate_xef_terms(Fx, return_deriv=False),
                          chidesc, axis=0)
    extermsu = np.append(get_sl_small(x2u, chiu, gammass)[0],
                         get_xefa_small(Fxu, chiu)[0], axis=0)
    extermsd = np.append(get_sl_small(x2d, chid, gammass)[0],
                         get_xefa_small(Fxd, chid)[0], axis=0)

    Fexp = np.exp(-2*(Fx-1)**2) * (Fx-1)
    Fexpu = np.exp(-2*(Fxu-1)**2) * (Fxu-1)
    Fexpd = np.exp(-2*(Fxd-1)**2) * (Fxu-1)
    cmscale = 17.0 / 3
    cmix = cmscale * (1 - chi) / (cmscale - chi)
    cmix_terms0 = np.array([chi**2-chi, chi**3-chi, chi**4-chi**2])
    Ecscan = np.dot(co * cmix + cx * (1-cmix), weights)
    Eterms = np.dot(cmix_terms0 * (cx-co), weights)
    Eterms2 = np.array([np.dot(co * amix * (Fx-1), weights),
                        np.dot(cx * amix * (Fx-1), weights)])
    Eterms3 = np.array([np.dot(co * (1-chi**2) * Fexp, weights),
                        np.dot(cx * Fexp, weights)])
    Eterms4 = np.array([np.dot(amix**2 * ldaxu * Fexpu, weights),
                        np.dot(amixz * ldaxu * Fexpu, weights),
                        np.dot(amixz**2 * ldaxu * Fexpu, weights)])
    Eterms4 += np.array([np.dot(amix**2 * ldaxd * Fexpd, weights),
                         np.dot(amixz * ldaxd * Fexpd, weights),
                         np.dot(amixz**2 * ldaxd * Fexpd, weights)])
    Fterms = np.dot(extermsu * ldaxu * amix, weights)
    Fterms += np.dot(extermsd * ldaxd * amix, weights)

    return Ecscan, np.concatenate([Eterms, Eterms2, Eterms3,
                                   Eterms4, Fterms], axis=0)


def desc_set3(weights, rhou, rhod, g2u, g2o, g2d, tu, td, exu, exd):
    rhot = rhou + rhod
    g2 = g2u + 2* g2o + g2d
    exo = exu + exd

    co0, vo0 = get_os_baseline(rhou, rhod, g2, type=0)[:2]
    co1, vo1 = get_os_baseline(rhou, rhod, g2, type=1)[:2]
    co0 *= rhot
    co1 *= rhot
    cx = co0
    co = co1

    nu, nd = rhou, rhod

    zeta = (rhou - rhod) / (rhot)
    ds = ((1-zeta)**(5.0/3) + (1+zeta)**(5.0/3))/2
    CU = 0.3 * (3 * np.pi**2)**(2.0/3)

    ldaxu = 2**(1.0/3) * LDA_FACTOR * rhou**(4.0/3) - 1e-20
    ldaxd = 2**(1.0/3) * LDA_FACTOR * rhod**(4.0/3) - 1e-20
    ldaxt = ldaxu + ldaxd

    gamma = 2**(2./3) * 0.004
    gammass = 0.004
    gt = gamma * g2 / (1 + gamma * g2)
    gtu = gammass * g2u / (1 + gammass * g2u)
    gtd = gammass * g2d / (1 + gammass * g2d)
    chi = get_chi_full_deriv(rhot + 1e-16, zeta, g2, tu + td)[0]
    chiu = get_chi_full_deriv(rhou + 1e-16, 1, g2u, tu)[0]
    chid = get_chi_full_deriv(rhod + 1e-16, 1, g2d, td)[0]
    x2 = get_x2(nu+nd, g2)[0]
    x2u = get_x2(nu, g2u)[0]
    x2d = get_x2(nd, g2d)[0]
    amix = get_amix_schmidt2(rhot, zeta, x2, chi)[0]
    amixz = get_amix_schmidt2(rhot, zeta, x2, chi, mixer='n')[0]
    chidesc = np.array(get_chi_desc(chi)[:4])
    chidescu = np.array(get_chi_desc(chiu)[:4])
    chidescd = np.array(get_chi_desc(chid)[:4])
    Fx = exo / ldaxt
    Fxu = exu / ldaxu
    Fxd = exd / ldaxd
    corrterms = np.append(get_separate_xef_terms(Fx, return_deriv=False),
                          chidesc, axis=0)
    extermsu = np.append(get_sl_small(x2u, chiu, gammass)[0],
                         get_xefa_small(Fxu, chiu)[0], axis=0)
    extermsd = np.append(get_sl_small(x2d, chid, gammass)[0],
                         get_xefa_small(Fxd, chid)[0], axis=0)

    Fexp = np.exp(-2*(Fx-1)**2) * (Fx-1)
    Fexpu = np.exp(-2*(Fxu-1)**2) * (Fxu-1)
    Fexpd = np.exp(-2*(Fxd-1)**2) * (Fxu-1)
    cmscale = 17.0 / 3
    cmix = cmscale * (1 - chi) / (cmscale - chi)
    cmix_terms0 = np.array([chi**2-chi, chi**3-chi, chi**4-chi**2])
    Ecscan = np.dot(co * cmix + cx * (1-cmix), weights)
    Eterms = np.dot(cmix_terms0 * (cx-co), weights)
    Eterms2 = np.array([np.dot(co * amix * (Fx-1), weights),
                        np.dot(cx * amix * (Fx-1), weights)])
    Eterms3 = np.array([np.dot(co * (1-chi**2) * Fexp, weights),
                        np.dot(cx * Fexp, weights)])
    Eterms4 = np.array([np.dot(amix**2 * ldaxu * Fexpu, weights),
                        np.dot(amixz * ldaxu * Fexpu, weights),
                        np.dot(amixz**2 * ldaxu * Fexpu, weights)])
    Eterms4 += np.array([np.dot(amix**2 * ldaxd * Fexpd, weights),
                         np.dot(amixz * ldaxd * Fexpd, weights),
                         np.dot(amixz**2 * ldaxd * Fexpd, weights)])
    Eterms5 = np.array([np.dot(co * amix * gt, weights),
                        np.dot(cx * amix * gt, weights)])
    Eterms6 = np.array([np.dot(amix**2 * ldaxu * gtu, weights),
                        np.dot(amixz * ldaxu * gtu, weights),
                        np.dot(amixz**2 * ldaxu * gtu, weights)])
    Eterms6 += np.array([np.dot(amix**2 * ldaxd * gtd, weights),
                         np.dot(amixz * ldaxd * gtd, weights),
                         np.dot(amixz**2 * ldaxd * gtd, weights)])
    Fterms = np.dot(extermsu * ldaxu * amix, weights)
    Fterms += np.dot(extermsd * ldaxd * amix, weights)

    return Ecscan, np.concatenate([Eterms, Eterms2, Eterms3,
                                   Eterms4, Eterms5, Eterms6,
                                   Fterms], axis=0)

def desc_set1_cider(weights, rhou, rhod, g2u, g2o, g2d, tu, td, exu, exd):
    rhot = rhou + rhod
    g2 = g2u + 2* g2o + g2d
    exo = exu + exd

    co0, vo0 = get_os_baseline(rhou, rhod, g2, type=0)[:2]
    co1, vo1 = get_os_baseline(rhou, rhod, g2, type=1)[:2]
    co0 *= rhot
    co1 *= rhot
    cx = co0
    co = co1

    nu, nd = rhou, rhod

    zeta = (rhou - rhod) / (rhot)
    ds = ((1-zeta)**(5.0/3) + (1+zeta)**(5.0/3))/2
    CU = 0.3 * (3 * np.pi**2)**(2.0/3)

    ldaxu = 2**(1.0/3) * LDA_FACTOR * rhou**(4.0/3) - 1e-20
    ldaxd = 2**(1.0/3) * LDA_FACTOR * rhod**(4.0/3) - 1e-20
    ldaxt = ldaxu + ldaxd

    gamma = 2**(2./3) * 0.004
    gammass = 0.004
    gtu = gammass * g2u / (1 + gammass * g2u)
    gtd = gammass * g2d / (1 + gammass * g2d)
    chi = get_chi_full_deriv(rhot + 1e-16, zeta, g2, tu + td)[0]
    chiu = get_chi_full_deriv(rhou + 1e-16, 1, g2u, tu)[0]
    chid = get_chi_full_deriv(rhod + 1e-16, 1, g2d, td)[0]
    x2 = get_x2(nu+nd, g2)[0]
    x2u = get_x2(nu, g2u)[0]
    x2d = get_x2(nd, g2d)[0]
    amix = get_amix_schmidt2(rhot, zeta, x2, chi)[0]
    chidesc = np.array(get_chi_desc(chi)[:4])
    chidescu = np.array(get_chi_desc(chiu)[:4])
    chidescd = np.array(get_chi_desc(chid)[:4])
    Fx = exo / ldaxt
    Fxu = exu / ldaxu
    Fxd = exd / ldaxd
    corrterms = np.append(get_separate_xef_terms(Fx, return_deriv=False),
                          chidesc, axis=0)
    extermsu = np.append(get_sl_small(x2u, chiu, gammass)[0],
                         get_xefa_small(Fxu, chiu)[0], axis=0)
    extermsd = np.append(get_sl_small(x2d, chid, gammass)[0],
                         get_xefa_small(Fxd, chid)[0], axis=0)

    cmscale = 17.0 / 3
    cmix = cmscale * (1 - chi) / (cmscale - chi)
    cmix_terms0 = np.array([chi**2-chi, chi**3-chi, chi**4-chi**2])
    Ecscan = np.dot(co * cmix + cx * (1-cmix), weights)
    Eterms = np.dot(cmix_terms0 * (cx-co), weights)
    Eterms2 = np.array([np.dot(co * amix * (Fx-1), weights),
                        np.dot(cx * amix * (Fx-1), weights)])
    Fterms = np.dot(extermsu * ldaxu * amix, weights)
    Fterms += np.dot(extermsd * ldaxd * amix, weights)
    Xterms1 = np.dot([ldaxu * (Fxu-1), ldaxd * (Fxd-1)], weights)
    Xterms2 = np.dot([ldaxu * gtu, ldaxd * gtd], weights)

    return Ecscan, np.concatenate([Eterms, Eterms2, Fterms,
                                   Xterms1, Xterms2], axis=0)