import sys
import os
dirpath_base = "C:\\Users\\zhouyou\\Documents\\BaiduNetdiskWorkspace\\GitHub\\"
print(dirpath_base)
sys.path.append(os.path.join(dirpath_base, 'wtpy'))

from wtpy import WtBtEngine, EngineType
#from strategies.HftStraDemo import HftStraDemo, myTestHftStrat, myTestHftArbitrageStrat, mySimpleArbitrageStrategy
from strategies.Hft_simpleExecution import mySimpleArbitrageStrategy
from wtpy.apps import WtBtAnalyst
import pandas as pd

from datetime import datetime
import multiprocessing
import time
import threading

s_dir_thisfile = os.path.dirname(os.path.realpath(__file__))


class WtMultipleBacktest:
    '''
    方便在一次运行里面做多次回测，因为底层是单例模式，所以需要这个\n
    '''
    def __init__(self, worker_num:int = 8):
        '''
        构造函数\n

        @worker_num 工作进程个数，默认为8，可以根据CPU核心数设置
        '''
        self.worker_num = worker_num
        self.running_worker = 0
        self.mutable_params = dict()
        self.fixed_params = dict()
        self.env_params = dict()

        self.cpp_stra_module = None
        return

    def __gen_tasks__(self, counter:int,):
        '''
        生成回测任务
        '''
        int_start = 201812240859
        #再生成最终每一组的参数dict
        param_groups = list()
        int_end = 0
        for i_count in range(counter+1):
            print("redo")
            print(s_dir_thisfile + "\\tradelists_backtest\\tradelist_backtest_" + str(i_count)+".csv")
            print(int_start, int_end)
            print("done")
            
            thisGrp = dict()
            thisGrp['i_count'] = i_count
            
            
            df_tradelist = pd.read_csv(s_dir_thisfile + "\\tradelists_backtest\\tradelist_backtest_" + str(i_count)+".csv", index_col=0)
            
            thisGrp['int_start'] = int_start = int(format(datetime.strptime(df_tradelist.index[0],"%Y-%m-%d %H:%M:%S"),'%Y%m%d%H%M'))
            
            s_date = df_tradelist.loc[df_tradelist.index[-1],'tradingDate']
            thisGrp['int_end'] = int_end = int(format(datetime.strptime(s_date + ' 15:00',"%Y-%m-%d %H:%M"),'%Y%m%d%H%M'))
            print(thisGrp)
            thisGrp['contract_1'] = df_tradelist.loc[df_tradelist.index[0],'contract_1']
            thisGrp['contract_2'] = df_tradelist.loc[df_tradelist.index[0],'contract_2']
            param_groups.append(thisGrp)
            
        return param_groups
    
    def __start_task__(self, params:dict):
        '''
        启动单个回测任务\n
        这里用线程启动子进程的目的是为了可以控制总的工作进程个数\n
        可以在线程中join等待子进程结束，再更新running_worker变量\n
        如果在__execute_task__中修改running_worker，因为在不同进程中，数据并不同步\n

        @params kv形式的参数
        '''
        p = multiprocessing.Process(target=self.__execute_task__, args=(params,))
        p.start()
        p.join()
        self.running_worker -= 1
        print("工作进程%d个" % (self.running_worker))
    
    def __execute_task__(self, params:dict):
        '''
        执行单个回测任务\n

        @params kv形式的参数
        '''
        i_count = params['i_count']
        int_start = params['int_start']
        int_end = params['int_end']
        contract_1 = params['contract_1']
        contract_2 = params['contract_2']
        
        # 创建一个运行环境，并加入策略
        engine = WtBtEngine(EngineType.ET_HFT)
        engine.init(s_dir_thisfile + '\\common\\', s_dir_thisfile + "\\configbt_2.json")
        engine.configBacktest(int_start, int_end)
        engine.configBTStorage(mode="csv", path="C:/Users/zhouyou/Documents/BaiduNetdiskWorkspace/futuredata/SP/tick/")
        engine.commitBTConfig()

        s_name = 'hft_sp_2contracts_multiple_' + str(i_count)
        straInfo = mySimpleArbitrageStrategy(name=s_name,
                            code1="SHFE.sp."+contract_1[2:],
                            code2="SHFE.sp."+contract_2[2:],
                            expsecs=20,
                            offset=0,
                            file_tradelist = s_dir_thisfile + "\\tradelists_backtest\\tradelist_backtest_" + str(i_count)+".csv",
                            tradingHorizonMin= 10,
                            slotsTotal= 2,
                            slotsEachTime= 1,
                            coldSeconds= 20,
                            addtick_open= 2,
                            addtick_close= 10,
                            freq=10,
                            sizeofbet=10)

        engine.set_hft_strategy(straInfo)
        engine.run_backtest()
        engine.release_backtest()

    def go(self, counter:int, interval:float = 0.2):
            '''
            启动优化器\n
            @interval   时间间隔，单位秒
            @markerfile 标记文件名，回测完成以后分析会用到
            '''
            self.tasks = self.__gen_tasks__(counter)
            self.running_worker = 0
            total_task = len(self.tasks)
            left_task = total_task
            while True:
                if left_task == 0:
                    break

                if self.running_worker < self.worker_num:
                    params = self.tasks[total_task-left_task]
                    left_task -= 1
                    print("剩余任务%d个" % (left_task))
                    p = threading.Thread(target=self.__start_task__, args=(params,))
                    p.start()
                    self.running_worker += 1
                    print("工作进程%d个" % (self.running_worker))
                else:
                    time.sleep(interval)

            #最后，全部任务都已经启动完了，再等待所有工作进程结束
            while True:
                if self.running_worker == 0:
                    break
                else:
                    time.sleep(interval)




if __name__ == "__main__":
    
    df_tradelist_full = pd.read_csv(s_dir_thisfile + "\\test.csv", index_col=0)
    i_begin = 0 
    counter = 0
    if not os.path.isdir(s_dir_thisfile + "\\tradelists_backtest\\"):
        os.mkdir(s_dir_thisfile + "\\tradelists_backtest\\")
    for i_row in range(1,df_tradelist_full.shape[0]):
        s_index = df_tradelist_full.index[i_row]
        s_lastindex = df_tradelist_full.index[i_row-1]
        if df_tradelist_full.loc[s_index, 'contract_1'] != df_tradelist_full.loc[s_lastindex, 'contract_1'] or \
            df_tradelist_full.loc[s_index, 'contract_2'] != df_tradelist_full.loc[s_lastindex, 'contract_2']:
                print(i_row)
                df_tradelist_full.iloc[i_begin:i_row,:].to_csv(s_dir_thisfile + "\\tradelists_backtest\\tradelist_backtest_" + str(counter)+".csv")
                counter += 1
                i_begin = i_row
    df_tradelist_full.iloc[i_begin:,:].to_csv(s_dir_thisfile + "\\tradelists_backtest\\tradelist_backtest_" + str(counter)+".csv")
    
    multipleBT = WtMultipleBacktest(worker_num=8)
    multipleBT.go(counter = counter, interval=0.2)
    
    analyst = WtBtAnalyst()
    for i_count in range(counter+1):
        s_name = 'hft_sp_2contracts_multiple_' + str(i_count)
        analyst.add_strategy(s_name, folder="./outputs_bt/" +s_name +"/", init_capital=500000, rf=0.02, annual_trading_days=240)    
    analyst.run_multiple(outname='bt_backtest')
    kw = input('press any key to exit\n')
    
