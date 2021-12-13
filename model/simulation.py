import json
import os
import sys
from . import RiskManager
from . import Shared
from . import utils
from . import Model, History
from .filter import SmoothingFilter
import copy
import time

class Simulation(Shared):
    count = 1
    def __init__(self, name) -> None:
        super().__init__()
        self.model           = Model()
        self.sim_history     = History()
        self.risk_manager    = RiskManager()
        self.name            = name    
        self.history_folder  = None
        self.inputs_folder   = None
        self.results_folder  = None
        self.metric_result_f = None
        self.sales_folder    = None

    def flushLogs(self):
        for p in self.products:
            log_f: str = os.path.join(self.history_folder, f"log_{p}.log")
            if os.path.exists(log_f):
                open(log_f.format(p), 'w').close()
    
    def log_state(self, k, dpm, rpm, cppv, cproduct_supply, cproduct_supply_out, cpdemand, creception, cpdemande_ref, creception_ref, prev_cpsupplly):      
        n = self.real_horizon          
        nchars = 16 + 7 * n
        format_row = "{:>16}" + "{:>7}" * n
        original_stdout = sys.stdout # Save a reference to the original standard output
        product_dept = self.sumOverAffiliate(self.model.cdc_dept)
        
        for p in self.products:
            log_f: str = os.path.join(self.history_folder, f"log_{p}.log")
            with open(log_f.format(p), 'a') as fp:
                sys.stdout = fp
                print("*" * nchars)
                print("Week :", k, ", Product: ", p, ", Cumulated Plans", "\n")
                print("Initial stock: ", self.model.cdc.initial_stock[p])
                print(format_row.format("week", *[f"W{t}" for t in range(k, k + n)]))
                print("-" * nchars)
                print(format_row.format("sales", *cppv[p][:n]))
                print(format_row.format("demand", *cpdemand[p][:n]))
                print(format_row.format("prev x", *prev_cpsupplly[p][:n]))
                # print(format_row.format("demand ref", *cpdemande_ref[p][k:k+n]))
                print("-" * nchars)
                # print(format_row.format("capacity", *list(utils.accumu(capacity[p]))[:n]))
                # print(format_row.format("bp", *self.model.cdc.bp[p][:n]))
                print(format_row.format("reception", *creception[p][:n]))
                # print(format_row.format("reception ref", *creception_ref[p][k:k+n]))
                print(format_row.format("dept", *product_dept[p][:n]))
                print("-" * nchars)
                print(format_row.format("A demand ref", *dpm[p]["a"][:n]))
                print(format_row.format("B demand ref", *dpm[p]["b"][:n]))
                print(format_row.format("X in", *cproduct_supply[p][:n]))
                print(format_row.format("X out", *cproduct_supply_out[p][:n]))
                print(format_row.format("C reception ref", *rpm[p]["c"][:n]))
                print(format_row.format("D reception ref", *rpm[p]["d"][:n]))
                print("=" * nchars)
                print(format_row.format("NL4 in", *[round(_, 2) for _ in self.risk_manager.getL4Necessity(rpm[p], dpm[p], cproduct_supply[p][:n])[:]]))
                print(format_row.format("NL4 out", *[round(_, 2) for _ in self.risk_manager.getL4Necessity(rpm[p], dpm[p], cproduct_supply_out[p][:n])[:]]))
        sys.stdout = original_stdout

    def generateHistory(self, start_week: int, end_week: int, smoothing_filter: SmoothingFilter=None):
        nweeks = end_week - start_week + 1
        self.flushLogs()

        # Init plans
        cppv = self.getEmptyProductQ(value=0)
        creception = self.getEmptyProductQ(value=0)
        cpdemand = self.getEmptyProductQ(value=0)
        creception_ref = self.getEmptyProductQ(value=0, size=self.horizon + nweeks)
        cdemand_ref = self.getEmptyAffQ(value=0, size=self.horizon + nweeks)
        cproduct_supply = self.getEmptyProductQ(value=0)
        prev_cpsupplly = self.getEmptyProductQ(value=0)
        
        stock_ini = {a: {p: 0 for p in self.itAffProducts(a)} for a in self.itAffiliates()}
        stock_ini["cdc"] = {p: 4000 for p in self.products}
        cdemand_ini = {}
        
        for a in self.itAffiliates():
            r0 = self.getAffPvRange(a)
            d0 = self.getAffPvRange(a)
            
            crecep_ini_ = utils.genRandCQ(self.horizon, r0)
            crecep_ini = {p: utils.genRandCQFromUCM(self.risk_manager.r_model[p], crecep_ini_, 0) for p in self.itAffProducts(a)}       
            recep_ini = {p: utils.diff(crecep_ini[p]) for p in self.itAffProducts(a)}
            
            cdemand_ini_ = utils.genRandCQ(self.horizon, d0)
            cdemand_ini[a] = {p: utils.genRandCQFromUCM(self.risk_manager.d_model[a][p], cdemand_ini_, 0) for p in self.itAffProducts(a)}  
                    
        input = {
            "prev_production": recep_ini,
            "prev_supply": self.model.getCDCPrevSupply(self.sales_history[0]),
            "initial_stock": stock_ini,
            "week": 0,
        }
        
        ppv = self.sumOverAffiliate(self.sales_history[0])
        for p in self.products:
            for a in self.itProductAff(p):
                cdemand_ref[a][p][:self.horizon] = cdemand_ini[a][p]
            creception_ref[p][:self.horizon] = crecep_ini[p]
        
        # start main loop
        for w in range(start_week, end_week + 1):
            k = w - start_week
            next_input_f = os.path.join(self.inputs_folder, f"input_S{k+1}.json")
            # snapshot_f = os.path.join(self.history_folder, f"snapshot_S{k}.json")

            self.model.loadWeekInput(input_dict=input)
            self.model.runWeek(self.sales_history[k])
            
            # get model cdc outputs
            reception = self.model.cdc_reception
            demand = self.model.cdc_demand
            pdemand = self.model.cdc_product_demand
            ppv = self.model.getProductSalesForcast()            
            supply = self.model.cdc_supply
            product_supply = self.model.cdc_product_supply
            stock_ini = self.model.cdc.initial_stock
            prev_supply = self.model.prev_supply
            prev_psupply = self.sumOverAffiliate(prev_supply)
            
            # accumulate plans
            cpr = cproduct_supply[p][0]
            prev_cpsupplly = {p: list(utils.accumu(prev_psupply[p], prev_cpsupplly[p][0])) for p in self.products}
            cproduct_supply = {p: list(utils.accumu(product_supply[p], cpr)) for p in self.products}
            cpdemand = {p: list(utils.accumu(pdemand[p], cpdemand[p][0])) for p in self.products}
            creception = {p: list(utils.accumu(reception[p], creception[p][0])) for p in self.products}
            cppv = {p: list(utils.accumu(ppv[p], cppv[p][0])) for p in self.products}
            for p in self.products:
                for a in self.itProductAff(p):
                    cdemand_ref[a][p][k+self.horizon] = cdemand_ref[a][p][k+self.horizon-1] + demand[a][p][self.horizon-1] 
                creception_ref[p][k+self.horizon] = creception_ref[p][k+self.horizon-1] + reception[p][self.horizon-1]

            # calculate distributions
            dpm, rpm = self.risk_manager.getDitributions(cdemand_ref, creception_ref, stock_ini, k)

            # Create data snapshot
            snapshot = self.model.getSnapShot()
            snapshot["cproduct_supply"] = cproduct_supply
            snapshot["demand"] = demand
            snapshot["reception"] = reception
            snapshot["supply"] = supply

            # gather metrics
            snapshot["metrics"]["in"] = self.risk_manager.getRiskMetrics(dpm, rpm, cproduct_supply)
            n = self.real_horizon

            # In case there is a filter apply it
            if smoothing_filter:
                cproduct_supply_out = {p: smoothing_filter.smooth(rpm[p], dpm[p], cproduct_supply[p][:n]) for p in self.products}
                product_supply_out = {p: utils.diff(cproduct_supply_out[p], cpr) + product_supply[p][n:] for p in self.products}
                cproduct_supply_out = {p: cproduct_supply_out[p] + list(utils.accumu(product_supply[p][n:], cproduct_supply_out[p][n-1])) for p in self.products}
                supply_out = self.dispatch(product_supply_out, demand, supply)
                print(supply_out)
                print(product_supply_out)
                self.model.setCDCSupply(supply_out, product_supply_out)
                snapshot["cproduct_supply"] = cproduct_supply_out
                snapshot["product_supply"] = product_supply_out
                snapshot["supply"] = supply_out
                snapshot["metrics"]["out"] = self.risk_manager.getRiskMetrics(dpm, rpm, cproduct_supply_out)
                cpdemande_ref = self.sumOverAffiliate(cdemand_ref, horizon=self.horizon + nweeks)
                
                # log simulation state 
                self.log_state(k, dpm, rpm, cppv, cproduct_supply, cproduct_supply_out, cpdemand, creception, cpdemande_ref, creception_ref, prev_cpsupplly)

            # utils.saveToFile(snapshot, snapshot_f)

            # add data to history 
            self.sim_history.fillData(snapshot)

            # generate next week inputs
            input = self.model.generateNextWeekInput(next_input_f)

    def run(self, sales_history, start_week, end_week, pa_filter=None):
        self.history_folder  = f"{self.name}/history"
        self.inputs_folder   = f"{self.name}/inputs"
        self.results_folder  = f"{self.name}/results"
        self.sales_history   = sales_history
        self.sim_history.init(start_week, end_week, pa_filter)

        if not os.path.exists(self.name):
            os.mkdir(self.name)
        if not os.path.exists(self.history_folder):
            os.mkdir(self.history_folder)
        if not os.path.exists(self.inputs_folder):
            os.mkdir(self.inputs_folder)
        st = time.perf_counter()
        
        print("Generating simu history ... ", end="")
        self.generateHistory(
            start_week,
            end_week,
            smoothing_filter=pa_filter
        )
        print("Finished in :", time.perf_counter()-st)

        # print("Exporting history to excel files ... ", end="")
        # self.sim_history.exportToExcel(
        #     prefix=Simulation.count,
        #     results_folder=self.results_folder
        # )
        # print("Finished")

        Simulation.count += 1