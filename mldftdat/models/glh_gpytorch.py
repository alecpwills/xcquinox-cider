import gpytorch
import torch
import copy
from torch import nn
from math import pi, log

class CovarianceMatrix(torch.nn.Module):
    def __init__(self, ndim, init_guess=None):
        super(CovarianceMatrix, self).__init__()
        if init_guess is None:
            self.mat = torch.Parameter(torch.identity(ndim))
        else:
            mat = torch.tensor(init_guess, dtype=torch.float64)
            self.mat = torch.cholesky(mat)

    def forward(self, x):
        return torch.dot(self.mat, x)


class LinearModel(gpytorch.models.ExactGP):
    def __init__(self, train_x, train_y, likelihood):
        super(LinearModel, self).__init__(train_x, train_y, likelihood)
        self.mean_module = gpytorch.means.ConstantMean()
        self.covar_module = gpytorch.kernels.LinearKernel()

    def forward(self, x):
        mean_x = self.mean_module(x)
        covar_x = self.covar_module(x)
        return gpytorch.distributions.MultivariateNormal(mean_x, covar_x)


class CovLinearModel(gpytorch.models.ExactGP):
    def __init__(self, train_x, train_y, likelihood,
                 ndim, init_guess=None):
        super(LinearModel, self).__init__(train_x, train_y, likelihood)
        self.mean_module = gpytorch.means.ConstantMean()
        self.covar_module = gpytorch.kernels.LinearKernel()
        self.cov_mat = CovarianceMatrix()

    def forward(self, x):
        x = self.cov_mat(x)
        mean_x = self.mean_module(x)
        covar_x = self.covar_module(x)
        return gpytorch.distributions.MultivariateNormal(mean_x, covar_x)


def train(train_x, train_y, test_x, test_y, 
          fixed_noise=None, use_cov=False,
          lfbgs=False, cov_mat=None, lr=0.01):

    nfeat = train_x.shape[-1]
    train_x = torch.tensor(train_x)
    train_y = torch.tensor(train_y).squeeze()
    test_x = torch.tensor(test_x)
    test_y = torch.tensor(test_y)

    if torch.cuda.is_available():
        train_x = train_x.cuda()
        train_y = train_y.cuda()
        test_x = test_x.cuda()
        test_y = test_y.cuda()

    print(train_x.size(), train_y.size())

    if fixed_noise is None:
        likelihood = gpytorch.likelihoods.GaussianLikelihood()
    else:
        print('using fixed noise')
        likelihood = gpytorch.likelihoods.FixedNoiseGaussianLikelihood(
                torch.tensor(fixed_noise, dtype=torch.float64))

    if use_cov:
        if cov_mat is None:
            model = CovLinearModel(train_x, train_y, likelihood, nfeat)
        else:
            model = CovLinearModel(train_x, train_y, likelihood,
                                   nfeat, cov_mat=cov_mat)
    else:
        model = LinearModel(train_x, train_y, likelihood)

    model = model.double()
    if torch.cuda.is_available():
        model = model.cuda()
        likelihood = model.likelihood

    if lfbgs:
        training_iterations = 100
    else:
        training_iterations = 500

    model.train()
    likelihood.train()

    if not lfbgs:
        optimizer = torch.optim.SGD(model.parameters(), lr=lr)
    else:
        optimizer = torch.optim.LBFGS(model.parameters(),
                                      lr=lr, max_iter=200,
                                      history_size=200)
        
    print(optimizer.state_dict())

    mll = gpytorch.mlls.ExactMarginalLogLikelihood(likelihood, model)
    mll2 = gpytorch.mlls.ExactMarginalLogLikelihood(likelihood, model)

    print(model.state_dict())
    print(likelihood.state_dict())

    orig_train_y = train_y.clone()
    orig_mean = likelihood(model(train_x)).mean

    min_loss = 2.00
    for i in range(training_iterations):
        if not lfbgs:
            optimizer.zero_grad()
            output = model(train_x)
            loss = -mll(output, train_y)
            loss.backward()
            optimizer.step()
        else:
            def closure():
                optimizer.zero_grad()
                output = model(train_x)
                loss = -mll(output, train_y)
                loss.backward()
                return loss
            optimizer.step(closure)
            loss = closure()
        print('cycle', i, loss.item())
        if loss.item() < min_loss:
            print('updating state', i, loss.item(), min_loss)
            min_loss = loss.item()
            best_state = copy.deepcopy(model.state_dict())

    model.load_state_dict(best_state)

    model.eval()
    likelihood.eval()
    with torch.no_grad(), gpytorch.settings.skip_posterior_variances(state=True):#, gpytorch.settings.use_toeplitz(False):#, gpytorch.settings.fast_pred_var():
        preds = model(test_x)
    print('TEST MAE: {}'.format(torch.mean(torch.abs(preds.mean - test_y))))

    if not isinstance(model, GPRModel):
        for setting in settings:
            setting.__exit__()

    return model, min_loss
