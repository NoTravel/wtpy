from wtpy import WtBtEngine, EngineType
from strategies.HftStraDemo import HftStraDemo, myTestHftStrat, myTestHftArbitrageStrat
from wtpy.apps import WtBtAnalyst

import os
s_dir_thisfile = os.path.dirname(os.path.realpath(__file__))
if __name__ == "__main__":
    # 创建一个运行环境，并加入策略
    engine = WtBtEngine(EngineType.ET_HFT)
    engine.init(s_dir_thisfile + '\\common\\', s_dir_thisfile + "\\configbt.json")
    engine.configBacktest(202110080859,202111121500)
    #engine.configBacktest(202110080859,202110091500)
    engine.configBTStorage(mode="csv", path=s_dir_thisfile + "\\storage\\")
    engine.commitBTConfig()

    straInfo = myTestHftArbitrageStrat(name='hft_sp_2contracts_10',
                         code1="SHFE.sp.2201",
                         code2="SHFE.sp.2202",
                         expsecs=20,
                         offset=0,
                         freq=10,
                         sizeofbet=10)

    engine.set_hft_strategy(straInfo)

    engine.run_backtest()
    
    analyst = WtBtAnalyst()
    analyst.add_strategy("hft_sp_2contracts_10", folder="./outputs_bt/hft_sp_2contracts_10/", init_capital=500000, rf=0.02, annual_trading_days=240)
    analyst.run()

    kw = input('press any key to exit\n')
    engine.release_backtest()
