import torch
import torch.nn as nn
import numpy as np

A = torch.tensor(0.704) # maybe replace with sqrt(6/5)?
B = 2 * np.pi / 9 * np.sqrt(6.0/5)
FXP0 = 27 / 50 * 10 / 81
FXI = 1.0 / 3 * (4*np.pi**2 / 3)**(1.0/3)
#MU = 10/81
MU = 0.21
C1 = 1.0 / 3 * (4*np.pi**2 / 3)**(1.0/3)
C2 = 1 - C1
C3 = 0.19697 * np.sqrt(0.704)
C4 = (C3**2 - 0.09834 * MU) / C3**3

def asinh(x):
    return torch.log(x+(x**2+1)**0.5)

def edmgga_from_q(Q):
    x = A * Q + torch.sqrt(1 + (A*Q)**2)
    FX = C1 + (C2 * x) / (1 + C3 * torch.sqrt(x) * asinh(C4 * (x-1)))
    return FX

class PolyAnsatz(nn.Module):

    def __init__(self, ndesc, func = edmgga_from_q, quadratic = False,
                 init_weight = None, init_bias = 1.0):
        super(PolyAnsatz, self).__init__()
        self.func = edmgga_from_q
        if quadratic:
            ndesc = ndesc + ndesc * (ndesc + 1) // 2
        self.linear = nn.Linear(ndesc, 1, bias = True)
        self.quadratic = quadratic
        with torch.no_grad():
            print(self.linear.weight.size())
            print(self.linear.bias.size())
            weight = np.zeros(ndesc)
            if init_weight is not None:
                init_weight = np.array(init_weight)
                size = init_weight.shape[0]
                weight[:size] = init_weight
            self.linear.weight = nn.Parameter(torch.tensor([weight],
                                                dtype=torch.float64))
            self.linear.bias = nn.Parameter(torch.tensor([init_bias], dtype=torch.float64))
            print(self.linear.weight.size())
            print(self.linear.bias.size())

    def forward(self, x):
        if self.quadratic:
            x2 = torch.ger(x, x)
            tind = x2.triu().nonzero().transpose()
            x = torch.cat([x, x2[tind[0], tind[1]]], dim=1)
        x = self.linear(x)
        return torch.squeeze(self.func(x), dim=1)

def get_traing_obj(model, lr = 0.01):
    criterion = nn.MSELoss()
    optimizer = torch.optim.SGD(model.parameters(), lr = lr)
    return criterion, optimizer

def train(x, y_true, criterion, optimizer, model):
    model.train()
    x = torch.tensor(x)
    y_true = torch.tensor(y_true)
    optimizer.zero_grad()
    y_pred = model(x)
    loss = criterion(y_pred, y_true)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(), 0.5)
    optimizer.step()
    #print('Current Train Loss', loss.item())
    return loss.item()

def validate(x, y_true, criterion, model):
    model.eval()
    x = torch.tensor(x)
    y_true = torch.tensor(y_true)
    y_pred = model(x)
    loss = criterion(y_pred, y_true)
    print('Current Train Loss', loss.item())
    return loss.item()

def save_nn(model, fname):
    torch.save(model.state_dict(), fname)

def load_nn(fname, ndesc, func = edmgga_from_q, quadratic = False):
    model = PolyAnsatz(ndesc, func, quadratic)
    model.load_state_dict(torch.load(fname))
    model.eval()
    return model
