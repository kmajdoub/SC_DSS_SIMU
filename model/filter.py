from . import Shared
from . import RiskManager

class SmoothingFilter(Shared):

    def __init__(self) -> None:
        super().__init__()
        self.range = self.settings["smoothing"]["range"]
        self.optimisme = self.settings["smoothing"]["optimisme"]

    def validateOutput(self, x_in: list[int], x_out: list[int]):
        n = len(x_out)
        if n != len(x_in):
            raise Exception(f"Solution size {len(x_out)} != input size {len(x_in)}!")
        for t in range(1, n):
            if x_out[t] < x_out[t-1]:
                print(x_out)
                raise Exception(f"x_out[{t}] = {x_out[t]} < x_out[{t-1}] = {x_out[t-1]}!")
    
    def smooth(self, rpm: dict[str, list[int]], dpm: dict[str, list[int]], x_in: list[int], cpr: int=0):
        x = x_in.copy()
        start = self.range["start"]
        end = self.range["end"]
        u = self.settings["smoothing"]["optimisme"]
        for t in range(start, end):
            c, d = rpm["c"][t], rpm["d"][t] 
            a, b = dpm["a"][t], dpm["b"][t]
            l4n_min = RiskManager.getMinL4n(a, b, c, d)
            if l4n_min >= self.l4n_threshold:
                tgt = d
            else:
                x1, x2 = RiskManager.getL4nAlphaBound(self.l4n_threshold, a, b, c, d)
                tgt = round(u * x1 + (1 - u) * x2)
            x[t] = tgt
            
        for t in range(start, self.real_horizon-1):
            if t == 0:
                x[t] = max(cpr, x[t])
            else:
                x[t] = max(x[t-1], x[t])
                
        for t in range(self.real_horizon-2, start-1, -1):
            x[t] = min(x[t], x[t+1])

        self.validateOutput(x_in, x)
        return x